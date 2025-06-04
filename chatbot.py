import os
from typing import Dict, Any
from bson import ObjectId
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from langchain_qdrant import QdrantVectorStore
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.runnables import RunnableLambda
from dotenv import load_dotenv


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
QDRANT_URL = os.getenv("QDRANT_URL")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

sessions: Dict[str, Dict[str, Any]] = {}


class ChatBot:
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-04-17", google_api_key=GEMINI_API_KEY)
        self.embedding = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

        self.chain = RunnableWithMessageHistory(
            RunnableLambda(lambda inputs: self.llm.invoke(inputs["input"])),
            get_session_history=self._get_history_for_session,
            input_messages_key="input",
            history_messages_key="history"
        )
    
    def _get_history_for_session(self, session_id: str) -> BaseChatMessageHistory:
        if session_id not in sessions:
            sessions[session_id] = {"history": ChatMessageHistory()}
        return sessions[session_id]["history"]

    def create_session(self, session_id: str, course_id: str) -> str:
        try:
            mongo_client = MongoClient(MONGO_URI)
            mongo_db = mongo_client[MONGO_DB_NAME]
            courses_collection = mongo_db['courses']
            
            if not ObjectId.is_valid(course_id):
                return None
            
            course_data = courses_collection.find_one(
                {'_id': ObjectId(course_id)},
                {'_id': 0, 'creator_username': 1, 'title': 1}
            )

            if course_data is None:
                return None
            
            sessions[session_id] = {
                "user": course_data['creator_username'],
                "course": course_data['title'],
                "history": ChatMessageHistory()
            }
            return session_id
        except Exception as e:
            print('Error: cannot retrieve quiz attempt from database.', e)
        finally:
            mongo_client.close()
    
    def _retrieve_context(self, query: str, user: str, course: str) -> str:
        try:
            mongo_client = MongoClient(MONGO_URI)
            mongo_db = mongo_client[MONGO_DB_NAME]
            chunks_collection = mongo_db['chunks']

            client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
            vector_store = QdrantVectorStore(
                client=client,
                collection_name=COLLECTION_NAME,
                embedding=self.embedding
            )
            qdrant_filter = Filter(
                must=[
                    FieldCondition(key="metadata.user", match=MatchValue(value=user)),
                    FieldCondition(key="metadata.course", match=MatchValue(value=course))
                ]
            )
            results = vector_store.similarity_search_with_score(query, filter=qdrant_filter, k=5)
            
            context = []
            for doc, _ in results:
                record = chunks_collection.find_one({"_id": doc.metadata['id']})
                if record:
                    context.append(record['chunk'])
            return "\n\n".join(context)
        except Exception as e:
            print(f"Error retrieving context: {e}")
            return ""
        finally:
            client.close()
            mongo_client.close()
    
    def process_message(self, session_id: str, message: str) -> str:
        user = sessions.get(session_id, {}).get("user", None)
        course = sessions.get(session_id, {}).get("course", None)

        if user is None or course is None:
            return None

        context = self._retrieve_context(message, user, course)

        prompt = (
            f"Context for this conversation:\n{context}\n\n"
            f"User: {message}\n"
            f"Assistant:"
        )

        response = self.chain.invoke(
            {"input": prompt},
            config={"configurable": {"session_id": session_id}}
        )

        return response.content

    def close_session(self, session_id: str) -> None:
        if session_id in sessions:
            del sessions[session_id]


if __name__ == "__main__":
    bot = ChatBot()
    
    session_id = "123456"
    bot.create_session(session_id, user="Beksultan", course="Attention")
    
    queries = [
        "Hi",
        "What is a transformer?"
    ]
    
    for query in queries:
        print(f"User: {query}")
        response = bot.process_message(session_id, query)
        print(f"Assistant: {response}\n")
    
    bot.close_session(session_id)
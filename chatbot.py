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
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import HumanMessage
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

        history = sessions[session_id]["history"]
        messages = history.messages.copy()

        messages.append(HumanMessage(content=message))

        context = self._retrieve_context(message, user, course)
        if context:
            context_msg = f"Context for this conversation:\n{context}\n\n"
            messages.insert(0, HumanMessage(content=context_msg))

        response = self.llm.invoke(messages)

        history.add_user_message(message)
        history.add_ai_message(response.content)

        return response.content

    
    def get_memory_history(self, session_id: str) -> dict:
        history = sessions.get(session_id, {}).get("history", None)
        if history is None:
            return {'Human': [], 'AI': []}

        human_messages = []
        ai_messages = []

        for msg in history.messages:
            if msg.type == "human":
                human_messages.append(msg.content)
            elif msg.type == "ai":
                ai_messages.append(msg.content)

        return {'Human': human_messages, 'AI': ai_messages}

    def close_session(self, session_id: str) -> None:
        if session_id in sessions:
            del sessions[session_id]


if __name__ == "__main__":
    bot = ChatBot()
    
    session_id = "123456"
    course_id = "6829e8d84685438e1e3daaf0"
    bot.create_session(session_id, course_id)
    
    queries = [
        "Hi",
        "What is a transformer?",
        "What is a meaning of life?"
    ]
    
    for query in queries:
        response = bot.process_message(session_id, query)
    
    print(bot.get_memory_history(session_id))
    bot.close_session(session_id)
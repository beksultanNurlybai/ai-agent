import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from pymongo import MongoClient


load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
QDRANT_URL = os.getenv('QDRANT_URL')
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY')
COLLECTION_NAME = os.getenv('COLLECTION_NAME')


def delete_course(user: str, course: str):
    try:
        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        qdrant_filter = Filter(
            must=[
                FieldCondition(key="metadata.user", match=MatchValue(value=user)),
                FieldCondition(key="metadata.course", match=MatchValue(value=course))
            ]
        )
        client.delete(collection_name=COLLECTION_NAME, points_selector=qdrant_filter)
    except Exception as e:
        print('Error: cannot delete chunks in a vector database:', e)
    finally:
        client.close()
    
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client['edtech']

        course_collection = mongo_db['courses']
        course_collection.delete_one({'user': user, 'course': course})

        chunks_collection = mongo_db['chunks']
        chunks_collection.delete_many({'user': user, 'course': course})
    except Exception as e:
        print('Error: cannot delete course data and chunks in a database:', e)
    finally:
        mongo_client.close()
    
    print('Course "' + course + '" is deleted.')


if __name__ == '__main__':
    user = 'Beksultan'
    course = 'Transformers and RAG'
    delete_course(user, course)
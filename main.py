import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient

from generate_course import generate_course
from delete_course import delete_course


load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME')

app = FastAPI(title="RAG Course API")

class CourseRequest(BaseModel):
    title: str
    creator_username: str


@app.post("/generate-course")
async def generate_course_endpoint(request: CourseRequest):
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]
        course_collection = mongo_db['courses']

        record = course_collection.find_one({
            'title': request.title,
            'creator_username': request.creator_username
        })
        files_paths = ['uploaded_files/' + file['stored_filename'] for file in record['files']]

        generate_course(request.creator_username, request.title, files_paths)
        return {"message": f'Course "{request.title}" has been successfully generated.'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete-course")
async def delete_course_endpoint(request: CourseRequest):
    try:
        delete_course(request.creator_username, request.title)
        return {"message": f'Course "{request.title}" has been successfully deleted.'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

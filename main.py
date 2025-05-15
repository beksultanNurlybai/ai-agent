from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import generate_course
import delete_course

app = FastAPI(title="RAG Course API")

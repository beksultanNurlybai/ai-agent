import os
from typing import List
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Form, File, UploadFile

from generate_course import generate_course
from delete_course import delete_course as del_course


UPLOAD_FOLDER = "uploaded_files"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = FastAPI(title="RAG Course API")

@app.post("/generate")
async def create_course(
    title: str = Form(...),
    owner: str = Form(...),
    files: List[UploadFile] = File(...)
):
    files_paths = []
    try:
        for file in files:
            ext = file.filename.split(".")[-1]
            if ext != 'pdf':
                return HTTPException(status_code=415, detail='Files\' extention must be pdf.')
            
            unique_id = str(uuid4())[:8]
            safe_title = title.replace(" ", "_")
            new_filename = f"{safe_title}_{unique_id}.{ext}"
            file_path = os.path.join(UPLOAD_FOLDER, new_filename)

            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            
            files_paths.append(file_path)
    except Exception as e:
        HTTPException(status_code=500, detail=str(e))
    
    if len(files_paths) == 0:
        HTTPException(status_code=400, detail='PDF files are not uploaded.')
    
    try:
        generate_course(owner, title, files_paths)
    except Exception as e:
        HTTPException(status_code=500, detail=str(e))
    finally:
        for file_path in files_paths:
            if os.path.exists(file_path):
                os.remove(file_path)

    return {"message": f'Course "{title}" has been successfully generated.'}


@app.delete("/delete")
async def delete_course(
    title: str = Form(...),
    owner: str = Form(...)
):
    try:
        del_course(owner, title)
        return {"message": f'Course "{title}" has been successfully deleted.'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

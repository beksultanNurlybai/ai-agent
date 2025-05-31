import os
from dotenv import load_dotenv
from typing import List, Tuple
from google import genai
from langchain.prompts import ChatPromptTemplate
from pymongo import MongoClient

load_dotenv()


MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

MODEL_NAME = "gemini-2.5-flash-preview-04-17"

def get_model_response(content: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=content
    )
    return response.text


def generate_questions(user: str, course: str, module: int, user_questions: List[Tuple[int]]):
    prompt_template = (
        "You are an intelligent assistant tasked with generating a personalized quiz to help reduce a user's knowledge gaps.\n"
        "Based on the list of questions the user answered incorrectly, select **exactly 10 related questions** from the provided database.\n"
        "Constraints:\n"
        "- Choose only questions that are conceptually or thematically related to the incorrectly answered ones.\n"
        "- Select exactly 10 questions.\n"
        "- Return only their **question numbers**, separated by commas (no additional explanation).\n"
        "Format example:\n"
        "1, 3, 5, 6, 7, 14, 16, 18, 19, 20\n\n"
        "* User's incorrectly answered questions: *\n{incorrecty_answered_questions}\n"
        "* Available questions in the database: *\n{questions}"
    )
    questions = []
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]
        course_collection = mongo_db['courses']
        
        questions = course_collection.find_one(
            {'title': course, 'creator_username': user, 'modules.number': module},
            {'modules.$': 1, '_id': 0}
        )['modules'][0]['questions']
    except Exception as e:
        print('Error: cannot c')
    finally:
        mongo_client.close()
    
    incorrecty_answered_questions = [(question[0], questions[question[0]]) for question in user_questions if question[1] == 0]
    
    incorrecty_answered_questions_text = ''
    for question in incorrecty_answered_questions:
        question_text = str(question[0]+1) + '. ' + question[1]['question'] + '\n'
        option_text = '\n'.join(key + ') ' + value for key, value in question[1]['options'].items())
        incorrecty_answered_questions_text += question_text + option_text + '\n\n'
    
    questions_text = ''
    for i, question in enumerate(questions, 1):
        question_text = str(i) + '. ' + question['question'] + '\n'
        option_text = '\n'.join(key + ') ' + value for key, value in question['options'].items())
        questions_text += question_text + option_text + '\n\n'
    
    prompt = ChatPromptTemplate.from_template(prompt_template).format(
        incorrecty_answered_questions=incorrecty_answered_questions_text,
        questions=questions_text,
    )
    response = get_model_response(prompt)
    print(response)


if __name__ == '__main__':
    user = 'Beksultan'
    course = 'Transformers and RAG'
    module = 1
    user_questions = [(1, 1), (3, 0), (4, 1), (14, 1), (9, 0)]
    generate_questions(user, course, module, user_questions)


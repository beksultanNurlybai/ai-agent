import os
from dotenv import load_dotenv
from bson import ObjectId
from typing import List, Dict
from google import genai
from langchain.prompts import ChatPromptTemplate
from pymongo import MongoClient
from random import randint

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


def save_quiz_attempt(question_ids: List[int], quiz_attempt: Dict) -> str:
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]
        quiz_attempts_collection = mongo_db['quiz_attempts']

        answers = [{'question_index': question_id} for question_id in question_ids]
        result = quiz_attempts_collection.insert_one({
            'course_id': quiz_attempt['course_id'],
            'user_id': quiz_attempt['user_id'],
            # 'attempt_number': quiz_attempt['attempt_number'] + 1,
            'is_completed': False,
            'answers': answers
        })
        return result.inserted_id
    except Exception as e:
        print('Error: cannot insert quiz attempt in a database:', e)
    finally:
        mongo_client.close()


def generate_module_quiz(attempt_id: str):
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
    questions_db = []
    quiz_attempt = {}
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]

        quiz_attempts_collection = mongo_db['quiz_attempts']
        
        if not ObjectId.is_valid(attempt_id):
            return None
        
        quiz_attempt = quiz_attempts_collection.find_one({'_id': ObjectId(attempt_id)})

        if quiz_attempt is None:
            return None
        
        courses_collection = mongo_db['courses']
        questions_db = courses_collection.find_one(
            {'_id': ObjectId(quiz_attempt['course_id']), 'modules.number': quiz_attempt['module_number']},
            {'modules.$': 1, '_id': 0}
        )['modules'][0]['questions']
    except Exception as e:
        print('Error: cannot retrieve quiz attempt from database.', e)
    finally:
        mongo_client.close()

    incorrecty_answered_question_ids = [question['question_index'] for question in quiz_attempt['answers'] if not question['is_correct']]

    if len(incorrecty_answered_question_ids) == 0:
        result = []
        while len(result) < 10:
            question_id = randint(0, 19)
            if question_id not in result:
                result.append(question_id)
        return save_quiz_attempt(result, quiz_attempt)

    
    incorrecty_answered_questions_text = ''
    for question_id in incorrecty_answered_question_ids:
        question_text = str(question_id+1) + '. ' + questions_db[question_id]['question'] + '\n'
        option_text = '\n'.join(key + ') ' + value for key, value in questions_db[question_id]['options'].items())
        incorrecty_answered_questions_text += question_text + option_text + '\n\n'
    
    question_db_text = ''
    for i, question in enumerate(questions_db, 1):
        question_text = str(i) + '. ' + question['question'] + '\n'
        option_text = '\n'.join(key + ') ' + value for key, value in question['options'].items())
        question_db_text += question_text + option_text + '\n\n'
    
    prompt = ChatPromptTemplate.from_template(prompt_template).format(
        incorrecty_answered_questions=incorrecty_answered_questions_text,
        questions=question_db_text,
    )
    response = get_model_response(prompt)
    result = response.split(', ')
    result = [int(num) for num in result]
    return save_quiz_attempt(result, quiz_attempt)


if __name__ == '__main__':
    print(generate_module_quiz('683f680afa42b1137c5ab28e'))


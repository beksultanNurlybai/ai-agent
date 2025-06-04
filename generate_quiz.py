import os
from dotenv import load_dotenv
from bson import ObjectId
from typing import List, Dict
from google import genai
from langchain.prompts import ChatPromptTemplate
from pymongo import MongoClient
from random import randint

from generate_course import parse_questions

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


def save_quiz(question_ids: List[int], quiz_attempt: Dict) -> str:
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]
        quizzes_collection = mongo_db['quizzes']

        quizzes_collection.delete_one({'course_id': quiz_attempt['course_id'], 'user_id': quiz_attempt['user_id']})

        result = quizzes_collection.insert_one({
            'course_id': quiz_attempt['course_id'],
            'user_id': quiz_attempt['user_id'],
            'questions': question_ids
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
        result = sorted(result)
        return save_quiz(result, quiz_attempt)

    
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
    return save_quiz(result, quiz_attempt)


def round_preserving_sum(arr: List[float]) -> List[int]:
    floor_arr = [int(x) for x in arr]
    diff = round(sum(arr)) - sum(floor_arr)
    
    frac_parts = sorted(
        [(i, arr[i] - floor_arr[i]) for i in range(len(arr))],
        key=lambda x: -x[1]
    )
    
    for i in range(diff):
        idx = frac_parts[i][0]
        floor_arr[idx] += 1

    return floor_arr

def generate_final_quiz(course_id: str, user_id: str):
    result = []
    course = None
    attempts = None
    mistake_questions: List[List[int]] = []
    module_question_lens: List[int] = []
    question_len = 30
    
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]

        courses_collection = mongo_db['courses']
        course = courses_collection.find_one({'_id': ObjectId(course_id)})
        
        quiz_attempts_collection = mongo_db['quiz_attempts']
        mistake_scores = []
        for i in range(len(course['modules'])):
            attempts = list(quiz_attempts_collection.find({'course_id': course_id, 'user_id': user_id, 'module_number': i+1}))
            if attempts == []:
                return None
            
            mistake_module_questions = []
            mistake_score = 0
            for attempt in attempts:
                for answer in attempt['answers']:
                    if not answer['is_correct']:
                        mistake_score += 1
                        if answer['question_index'] not in mistake_module_questions:
                            mistake_module_questions.append(answer['question_index'])
            
            mistake_questions.append(mistake_module_questions)
            mistake_scores.append(mistake_score / len(attempts))
        
        mistake_scores_sum = sum(mistake_scores)
        temp = mistake_scores_sum / len(mistake_scores)
        for i in range(len(mistake_scores)):
            mistake_scores[i] += temp
        
        module_question_lens += round_preserving_sum([mistake_score * question_len / (mistake_scores_sum * 2) for mistake_score in mistake_scores])
    except Exception as e:
        print('Error: cannot retrieve questions from database.', e)
    finally:
        mongo_client.close()

    prompt_template1 = (
        "You are an intelligent assistant tasked with generating a personalized multiple-choice questions (MCQs) to help reduce a user's knowledge gaps.\n"
        "Based on the list of questions the user answered incorrectly, generate **exactly {question_num} related questions** by using context.\n"
        "* Constraints: *\n"
        "- Generate exactly {question_num} MCQs based on the module content.\n"
        "- Generated questions have to be conceptually or thematically related to the incorrectly answered ones.\n"
        "- Do not copy the questions from questions database.\n"
        "- Each question should have four options labeled a), b), c), and d).\n"
        "- Only one option should be correct.\n"
        "- Provide the correct answer after each question.\n"
        "- Questions can be paraphrased or have similarities.\n\n"
        "* Format: *\n"
        "1. [Question text]\n"
        "a) [Option A]\n"
        "b) [Option B]\n"
        "c) [Option C]\n"
        "d) [Option D]\n"
        "Answer: [a/b/c/d]\n\n"
        "2. [Question text]\n"
        "a) [Option A]\n"
        "b) [Option B]\n"
        "c) [Option C]\n"
        "d) [Option D]\n"
        "Answer: [a/b/c/d]\n\n"
        "* Module Content: *\n{context}\n\n"
        "* User's incorrectly answered questions: *\n{incorrecty_answered_questions}\n"
        "* Available questions in the database: *\n{questions}"
    )
    prompt_template2 = (
        "You are an intelligent assistant tasked with generating a personalized multiple-choice questions (MCQs) to help reduce a user's knowledge gaps.\n"
        "Based on the context, generate **exactly {question_num} related questions** by using context.\n"
        "* Constraints: *\n"
        "- Generate exactly {question_num} MCQs based on the module content.\n"
        "- Do not copy the questions from questions database.\n"
        "- Each question should have four options labeled a), b), c), and d).\n"
        "- Only one option should be correct.\n"
        "- Provide the correct answer after each question.\n"
        "- Questions can be paraphrased or have similarities.\n\n"
        "* Format: *\n"
        "1. [Question text]\n"
        "a) [Option A]\n"
        "b) [Option B]\n"
        "c) [Option C]\n"
        "d) [Option D]\n"
        "Answer: [a/b/c/d]\n\n"
        "2. [Question text]\n"
        "a) [Option A]\n"
        "b) [Option B]\n"
        "c) [Option C]\n"
        "d) [Option D]\n"
        "Answer: [a/b/c/d]\n\n"
        "* Module Content: *\n{context}\n\n"
        "* Available questions in the database: *\n{questions}"
    )

    for i, module in enumerate(course['modules']):
        prompt = ''
        question_db_text = ''
        for j, question in enumerate(module['questions'], 1):
            question_text = str(j) + '. ' + question['question'] + '\n'
            option_text = '\n'.join(key + ') ' + value for key, value in question['options'].items())
            question_db_text += question_text + option_text + '\n\n'

        if mistake_questions[i] == []:
            prompt = ChatPromptTemplate.from_template(prompt_template2).format(
                question_num=module_question_lens[i],
                context=module['content'],
                questions=question_db_text
            )
        else:
            incorrecty_answered_questions_text = ''
            for question_id in mistake_questions[i]:
                question_text = str(question_id+1) + '. ' + module['questions'][question_id]['question'] + '\n'
                option_text = '\n'.join(key + ') ' + value for key, value in module['questions'][question_id]['options'].items())
                incorrecty_answered_questions_text += question_text + option_text + '\n\n'
            
            prompt = ChatPromptTemplate.from_template(prompt_template1).format(
                question_num=module_question_lens[i],
                context=module['content'],
                incorrecty_answered_questions=incorrecty_answered_questions_text,
                questions=question_db_text
            )
        
        response = get_model_response(prompt)
        result += parse_questions(response)
    
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]

        final_quizzes_collection = mongo_db['final_quizzes']
        insert_result = final_quizzes_collection.insert_one({
            'course_id': course_id,
            'user_id': user_id,
            'questions': result
        })
        return insert_result.inserted_id
    except Exception as e:
        print('Error: cannot insert final quiz into database.', e)
    finally:
        mongo_client.close()


if __name__ == '__main__':
    generate_final_quiz('6829e8d84685438e1e3daaf0', 'AzimZen')
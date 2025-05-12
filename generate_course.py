import os
import glob
import re
from uuid import uuid4
from dotenv import load_dotenv
from typing import List, Dict, Tuple
from google import genai
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.schema.document import Document
from langchain.prompts import ChatPromptTemplate
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from unstructured.partition.pdf import partition_pdf
from pymongo import MongoClient
import tiktoken

from utils import save_summary, save_toc_and_course_content


load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME')
QDRANT_URL = os.getenv('QDRANT_URL')
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY')
COLLECTION_NAME = os.getenv('COLLECTION_NAME')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

MODEL_NAME = "gemini-2.5-flash-preview-04-17"
SMALL_MODEL_NAME = "gemini-2.0-flash-lite"
CONTEXT_WINDOW_THRESHOLD = 100_000

client = genai.Client(api_key=GEMINI_API_KEY)

def get_small_model_response(content: str) -> str:
    response = client.models.generate_content(
        model=SMALL_MODEL_NAME,
        contents=content
    )
    return response.text

def get_model_response(content: str) -> str:
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=content
    )
    return response.text

def get_embedding_function():
    return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")


def store_course(modules: List[Dict]):
    if not modules:
        print("No modules were parsed. Skipping DB insertion.")
        return []
    
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]
        course_collection = mongo_db['courses']
        course_collection.insert_one({
            'user': user,
            'course': course,
            'modules': modules,
        })
    except Exception as e:
        print('Error: cannot insert course data in a database:', e)
    finally:
        mongo_client.close()


def parse_questions(question_text: str) -> List[Dict]:
    pattern = re.compile(
        r"""
        ^\d+\.\s*(?P<question>.+?)\s*
        a\)\s*(?P<a>.+?)\s*
        b\)\s*(?P<b>.+?)\s*
        c\)\s*(?P<c>.+?)\s*
        d\)\s*(?P<d>.+?)\s*
        Answer:\s*(?P<answer>[a-dA-D])\s*
        """,
        re.MULTILINE | re.VERBOSE
    )

    questions = []
    for match in pattern.finditer(question_text):
        question = match.group('question').strip()
        options = {
            'a': match.group('a').strip(),
            'b': match.group('b').strip(),
            'c': match.group('c').strip(),
            'd': match.group('d').strip()
        }
        answer = match.group('answer').lower()
        questions.append({
            'question': question,
            'options': options,
            'answer': answer
        })
    return questions

def generate_questions(course_content: List[Dict]) -> List[Dict]:
    prompt_text = (
        "You are an AI assistant tasked with generating multiple-choice questions (MCQs) "
        "to assess understanding of the provided module content.\n\n"
        "Instructions:\n"
        "- Generate about 20 MCQs based on the module content.\n"
        "- Each question should have four options labeled a), b), c), and d).\n"
        "- Only one option should be correct.\n"
        "- Provide the correct answer after each question.\n"
        "- Questions can be paraphrased or have similarities.\n\n"
        "Format:\n"
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
        "Module Content:\n"
    )
    for module in course_content:
        response = get_small_model_response(prompt_text + module['content'])
        questions = parse_questions(response)
        module['questions'] = questions
    
    return course_content


def generate_course_content(toc: List[Dict], user: str, course: str, k: int = 10) -> List[Dict]:
    prompt_template = """
    **Task:** Generate a well-structured and easy-to-understand submodule for a learning course.

    **Instructions:**
    - Use the context below only as supporting material. Do **not** copy content verbatim—use it to **explain and teach** the topic in your own words.
    - Follow a clear pedagogical structure: start by introducing the topic, then explain core concepts, and finally move to more advanced or applied ideas.
    - Ensure that this module content **fits logically within the entire course structure**. Refer to the Table of Contents below to avoid unnecessary repetition or overlap with other modules.
    - The writing should be **educational, clear, and concise**. Avoid filler content or overly complex phrasing.
    - Do **not** add the title of the module
    - Use **Markdown formatting** only:
        - Use `##`, `###`, etc. for headings and subheadings.
        - Use bullet points **only when they improve clarity** (e.g., listing key steps or definitions).
        - Prefer structured paragraphs and subheadings over long lists.
        - Use **LaTeX-style math** (e.g., `$E = mc^2$`) instead of HTML tags like `<sub>` or `<sup>`.
    - You may add generally accepted factual information that enhances understanding (e.g., standard definitions, widely known facts, key formulas).
    - Do **not** include any introductory remarks like "Here is the content" or repeat the summary/context.

    **Course Table of Contents (with module summaries):**
    {toc}

    **Current Module Summary:**  
    {summary}

    **Reference Context (from uploaded materials):**
    {context}

    **Now write the submodule content in Markdown:**
    """
    try:
        mongo_client = MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]
        chunks_collection = mongo_db['chunks']

        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        vector_db = QdrantVectorStore(client=client, collection_name=COLLECTION_NAME, embedding=get_embedding_function())
        filter = Filter(
            must=[
                FieldCondition(key="metadata.user", match=MatchValue(value=user)),
                FieldCondition(key="metadata.course", match=MatchValue(value=course))
            ]
        )
        toc_text = ''
        for module in toc:
            toc_text += f"{module['number']}. {module['title']}\nSummary: {module['summary']}\n\n"

        for module in toc:
            results = vector_db.similarity_search_with_score(module['summary'], filter=filter, k=k)
            context = ''
            for doc, _ in results:
                record = chunks_collection.find_one({"_id": doc.metadata['id']})
                if record:
                    context += '\n\n---\n\n' + record['chunk']

            prompt = ChatPromptTemplate.from_template(prompt_template).format(
                toc=toc_text,
                summary=module['summary'],
                context=context
            )
            response = get_model_response(prompt)
            module['content'] = response
    except Exception as e:
        print("Error: cannot retrieve chunks related to a query in databases:", e)
    finally:
        client.close()
        mongo_client.close()

    return toc


def parse_module_summaries(text: str) -> List[Dict]:
    modules = []
    lines = text.splitlines()
    module_pattern = re.compile(r"\*\*Module\s+(\d+):\s*(.*?)\*\*")
    
    current_module = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        module_match = module_pattern.match(line)
        if module_match:
            if current_module:
                modules.append(current_module)
            current_module = {
                'number': int(module_match.group(1)),
                'title': module_match.group(2).strip(),
                'summary': ''
            }
        elif current_module and line.lower().startswith('summary:'):
            summary_text = line[len('summary:'):].strip()
            current_module['summary'] = summary_text

    if current_module:
        modules.append(current_module)

    return modules

def get_summary(chunks_summaries: List[str]) -> str:
    prompt_text = """
    You are an assistant tasked with summarizing text.
    Give a concise summary of the text.

    Respond only with the summary, no additionnal comment.
    Do not start your message by saying "Here is a summary" or anything like that.
    Just give the summary as it is.

    Text chunk:\n"""
    encoding = tiktoken.get_encoding('cl100k_base')
    
    def recursive_summary(summaries: List[str]) -> str:
        token_num = 0
        for summary in summaries:
            token_num += len(encoding.encode(summary))
        
        if token_num < CONTEXT_WINDOW_THRESHOLD:
            return '\n'.join(summaries)
        
        new_summaries = [get_small_model_response(prompt_text + ''.join(summaries[i-4: i])) for i in range(4, len(summaries), 4)]
        return recursive_summary(new_summaries)
    
    return recursive_summary(chunks_summaries)

def generate_toc(chunks_summaries: List[str], module_num: int) -> List[Dict]:
    prompt_template = (
        "You are an expert instructional designer tasked with crafting a high‑level course outline. "
        "Using the consolidated summary below—which captures the essential concepts from several source documents, "
        "create modules. For each module, output **only**:\n\n"
        "**Module X: [Module Title]**\n"
        "Summary: [An 80-120-word paragraph in clear, active voice that includes:]\n"
        "  • A one-sentence overview of the module's theme\n"
        "  • 1-2 bullet-style learning objectives\n"
        "  • 1-2 keywords or topics for retrieval-based querying\n\n"
        "Constraints:\n"
        "- Exactly {min_module}-{max_module} modules.\n"
        "- No submodules, introductory remarks, or closing statements.\n"
        "- Do not use lists or extra formatting inside the summary except the two bullet points for objectives.\n\n"
        "Example:\n"
        "**Module 1: Introduction to Blockchain**\n"
        "Summary: This module introduces the core principles of blockchain technology and its historical evolution. "
        "Learning Objectives:\n"
        "  • Understand the definition and purpose of a blockchain\n"
        "  • Describe how decentralization enhances security\n"
        "Keywords: consensus mechanisms, distributed ledger\n\n"
        "Summary:\n{summary}"
    )
    summary = get_summary(chunks_summaries)
    prompt = ChatPromptTemplate.from_template(prompt_template).format(
                min_module=int(module_num*0.7),
                max_module=module_num,
                summary=summary
            )
    response = get_model_response(prompt)
    return parse_module_summaries(response)


def store_chunks(chunks: List[str], chunks_summaries: List[str], user: str, course: str):
    ids = []
    
    try:
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client[MONGO_DB_NAME]
        chunks_collection = db['chunks']
        
        for chunk in chunks:
            id = str(uuid4())
            chunks_collection.insert_one({
                "_id": id,
                "user": user,
                "course": course,
                "chunk": chunk
            })
            ids.append(id)
    except Exception as e:
        print('Error: cannot insert chunks into "chunks_actual_texts" collection:', e)
    finally:
        mongo_client.close()
    
    try:
        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        db = QdrantVectorStore(client=client, collection_name=COLLECTION_NAME, embedding=get_embedding_function())

        qdrant_filter = Filter(
            must=[
                FieldCondition(key="metadata.user", match=MatchValue(value=user)),
                FieldCondition(key="metadata.course", match=MatchValue(value=course))
            ]
        )
        count_result = client.count(collection_name=COLLECTION_NAME, count_filter=qdrant_filter)
        if count_result.count > 0:
            print(f"Course with the name '{course}' already exists.")
            exit()

        docs = []
        for i in range(len(chunks_summaries)):
            docs.append(Document(
                page_content=chunks_summaries[i],
                metadata={'id': ids[i], 'user': user, 'course': course}
            ))
        db.add_documents(docs, ids=ids)
    except Exception as e:
        print('Error: cannot insert chunks\' embeddings into a database:', e)
    finally:
        client.close()


def summarize(chunks: List[str]) -> List[str]:
    prompt_text = """
    You are an assistant tasked with summarizing text.
    Give a concise summary of the text.

    Respond only with the summary, no additionnal comment.
    Do not start your message by saying "Here is a summary" or anything like that.
    Just give the summary as it is.

    Text chunk:\n"""
    chunks_summaries = [get_small_model_response(prompt_text + text) for text in chunks]
    return chunks_summaries


def parse_files(dir_path: str) -> Tuple[List[str], int]:
    file_paths = glob.glob(os.path.join(dir_path, '*.pdf')) + glob.glob(os.path.join(dir_path, '*.PDF'))
    if len(file_paths) == 0:
        print('there is no files.')
        return [], 0
    
    chunks = []
    for file_path in file_paths:
        chunks += partition_pdf(
            filename=file_path,
            infer_table_structure=True,
            strategy='hi_res',
            languages=['eng', 'rus', 'kaz'],
            chunking_strategy='by_title',
            max_characters=10000,
            combine_text_under_n_chars=2000,
            new_after_n_chars=6000)
    
    encoding = tiktoken.get_encoding('cl100k_base')
    token_num = 0
    texts = []
    for chunk in chunks:
        text = ''
        for element in chunk.metadata.orig_elements:
            if 'Image' in str(type(element)):
                continue
            elif 'Table' in str(type(element)):
                text += element.metadata.text_as_html + '\n'
            else:
                text += element.text + '\n'
        token_num += len(encoding.encode(text))
        texts.append(text)
    
    module_num = int((token_num / 1000)**0.5) + 2
    if module_num > 30:
        module_num = 30
    return texts, module_num


def generate_course(user: str, course: str, dir_path: str):
    print("Files are being processed...")
    chunks, module_num = parse_files(dir_path)
    print("Files are loaded.")

    chunks_summaries = summarize(chunks)
    print("Summary is generated.")
    # save_summary(chunks_summaries)

    store_chunks(chunks, chunks_summaries, user, course)
    print("Documents saved in a vector database.")

    toc = generate_toc(chunks_summaries, module_num)
    print("Table of contents is generated.")

    course_content = generate_course_content(toc, user, course)
    print("Content of the course is generated.")
    # save_toc_and_course_content(course_content)

    course_content = generate_questions(course_content)
    print("Questions of the course are generated.")
    store_course(course_content)


if __name__ == '__main__':
    user = 'Beksultan'
    course = 'Attention'
    dir_path = 'resource'
    generate_course(user, course, dir_path)

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from google import genai
from google.genai import types
import pymongo
import os
from dotenv import load_dotenv

load_dotenv()

_client: genai.Client | None = None

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ['google_api_key'])
    return _client

def connect_to_mongodb(url):
    try:
        mongo_client = MongoClient(url, serverSelectionTimeoutms = 5000)
        return mongo_client
    except ServerSelectionTimeoutError:
        print("Lỗi kết nối: Không tìm thấy server MongoDB.")
        print("Vui lòng kiểm tra: MongoDB server có đang chạy không?")
        return None
    except ConnectionFailure as e:
        print(f"Lỗi kết nối: Không thể kết nối đến MongoDB. Chi tiết: {e}")
        return None
    except Exception as e:
        print(f"Đã xảy ra lỗi không mong muốn: {e}")
        return None


from .prompts import create_rag_prompt, create_chat_history_prompt

def get_embedding(text: str) -> list[float]:
    result = _get_client().models.embed_content(
        model="gemini-embedding-exp-03-07",
        contents=text,
        config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY")
    )
    return result.embeddings[0].values


def find_similar_documents(query_vector: list[float], limit: int = 3, candidates: int = 10) -> list[dict]:
    """
    Thực hiện Vector Search để tìm các document liên quan.
    """
    mongo_url = os.environ['MONGODB_ATLAS_URI_2']
    if not mongo_url:
        print("MONGO_URI not set in environment variables")
    mongo_client = connect_to_mongodb(mongo_url)
    collection = mongo_client['local-bot2']['it_support']
    pipeline = [
        {
            "$vectorSearch": {
                "index": "embedding_search",
                "path": "embedding",
                "queryVector": query_vector,
                "limit": limit,
                "numCandidates": candidates
            }
        },
        {
            "$project": {
                'title': 1,
                'problem_descriptions': 1,
                'solution' : 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]
    try:
        return list(collection.aggregate(pipeline))
    except pymongo.errors.OperationFailure as e:
        print(f"Lỗi khi thực hiện tìm kiếm: {e}")
        return []
    
def format_documents(documents: list[dict], separator: str = '\n\n') -> str:

    formatted_docs = []
    for doc in documents:
        title = doc.get('title', 'No title')
        problems = ', '.join(doc.get('problem_descriptions', []))
        solution = doc.get('solution', 'No solution')
        score = doc.get('score', 0.0)
        doc_str = f"Title: {title}\nProblems: {problems}\nSolution: {solution}\nScore: {score}"
        formatted_docs.append(doc_str)

    return separator.join(formatted_docs)

def initialize_model(temperature=0.2, top_p=0.95, max_output_tokens=1024):
    """
    Returns a config dict used for generate_content calls.
    Kept for backward compatibility — callers use _generate(prompt, cfg).
    """
    return types.GenerateContentConfig(
        temperature=temperature,
        top_p=top_p,
        max_output_tokens=max_output_tokens,
        safety_settings=[
            types.SafetySetting(category='HARM_CATEGORY_HARASSMENT',        threshold='BLOCK_MEDIUM_AND_ABOVE'),
            types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH',       threshold='BLOCK_MEDIUM_AND_ABOVE'),
            types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_MEDIUM_AND_ABOVE'),
            types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_ONLY_HIGH'),
        ]
    )

_default_config = initialize_model()

def _generate(prompt: str, config: types.GenerateContentConfig | None = None) -> str:
    """Helper that calls the new SDK and returns response text."""
    return _get_client().models.generate_content(
        model='gemini-2.0-flash',
        contents=prompt,
        config=config or _default_config
    ).text

def condense_question(chat_history):
    
    if not chat_history:
        return ""

    history_string = "\n".join([f"{role}: {text}" for role, text in chat_history])
    prompt = create_chat_history_prompt(history_string=history_string)
    
    try:
        return _generate(prompt)
    except Exception:
        return ""

def get_answer_with_rag(user_question, chat_history):
    
    history_string = condense_question(chat_history)
    context_docs = find_similar_documents(get_embedding(user_question))
    context_string = format_documents(context_docs)
    rag_prompt = create_rag_prompt(
        history_string=history_string,
        context_string=context_string,
        user_question=user_question
    )

    try:
        return _generate(rag_prompt)
    except Exception as e:
        return (f"Lỗi khi cố gắng đưa ra câu trả lời: {e}")
import os
import logging
import re
from typing import List, Dict, Any
from langchain.agents import tool
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from .db import (
    find_similar_documents_hybrid_search, 
    find_similar_documents_vector_search,
    get_embedding
)
from google import genai
from google.genai import types
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

logger = logging.getLogger(__name__)

_safety_settings = [
    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT',        threshold='BLOCK_MEDIUM_AND_ABOVE'),
    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH',       threshold='BLOCK_MEDIUM_AND_ABOVE'),
    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_MEDIUM_AND_ABOVE'),
    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_ONLY_HIGH'),
]

_generation_config = types.GenerateContentConfig(
    temperature=0.1,
    top_p=0.95,
    safety_settings=_safety_settings,
)

_genai_client: genai.Client | None = None

def _get_model_client() -> genai.Client:
    """Returns a lazily initialised google-genai Client."""
    global _genai_client
    if _genai_client is None:
        api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('google_api_key')
        _genai_client = genai.Client(api_key=api_key)
    return _genai_client


def safe_log_info(message: str):
    """
    Safely log info messages with Unicode characters.
    Falls back to ASCII representation if encoding fails.
    """
    try:
        logger.info(message)
    except UnicodeEncodeError:
        # Fallback: Replace non-ASCII characters with ASCII equivalents
        safe_message = message.encode('ascii', 'replace').decode('ascii')
        logger.info(f"[UNICODE_SAFE] {safe_message}")

def safe_log_warning(message: str):
    """
    Safely log warning messages with Unicode characters.
    Falls back to ASCII representation if encoding fails.
    """
    try:
        logger.warning(message)
    except UnicodeEncodeError:
        # Fallback: Replace non-ASCII characters with ASCII equivalents
        safe_message = message.encode('ascii', 'replace').decode('ascii')
        logger.warning(f"[UNICODE_SAFE] {safe_message}")

def safe_log_error(message: str, exc_info=None):
    """
    Safely log error messages with Unicode characters.
    Falls back to ASCII representation if encoding fails.
    """
    try:
        logger.error(message, exc_info=exc_info)
    except UnicodeEncodeError:
        # Fallback: Replace non-ASCII characters with ASCII equivalents
        safe_message = message.encode('ascii', 'replace').decode('ascii')
        logger.error(f"[UNICODE_SAFE] {safe_message}", exc_info=exc_info)


@tool
def summarize_conversation(messages: List[str], user_preferences: Dict[str, Any] = None) -> str:
    """
    Tóm tắt cuộc hội thoại sử dụng Gemini API.
    
    Args:
        messages: Danh sách tin nhắn trong cuộc hội thoại
        user_preferences: Thông tin preferences của user (optional)
        
    Returns:
        Summary của cuộc hội thoại
    """
    safe_log_info("--- Running Tool: summarize_conversation ---")
    
    try:
        if not messages or len(messages) == 0:
            return "Không có tin nhắn để tóm tắt"
        
        # Simple conversation text
        conversation_text = "\n".join(messages[-15:])  
        
        # Simple prompt
        prompt = f"""Hãy tóm tắt cuộc hội thoại sau trong 3-4 câu ngắn gọn:\n\n{conversation_text}
            Giữ lại những ý chính và các thông tin quan trọng.
            giữ lại những kiến thức source của người dùng (ví dụ: tên tài khoản, tên tài khoản của người dùng đã tải lên, ...)
            Lưu trữ thông tin cá nhân của người dùng (nếu có) (ví dụ: Tên, tuổi, giới tính, email, số điện thoại, địa chỉ, ...)
            Để tóm tắt cuộc hội thoại, hãy ngắn gọn và dễ hiểu.
        """
        
        # Call Gemini API using sync
        response = _get_model_client().models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=_generation_config
        )
        summary = response.text.strip()
        
        safe_log_info(f"Generated summary: {summary[:100]}...")
        return summary
        
    except Exception as e:
        safe_log_error(f"Error in summarize_conversation: {e}")
        return "Cuộc hội thoại về các chủ đề công nghệ" 

@tool
def find_documents_parallel(search_query: str, uploader_username: str) -> Dict[str, List[dict]]:
    """
    Tìm kiếm tài liệu từ cả user và admin song song để tối ưu tốc độ với shared embedding
    """
    safe_log_info("--- Running Tool: find_documents_parallel ---")
    safe_log_info(f"Searching documents in parallel for query: '{search_query}' and uploader: '{uploader_username}'")
    
    # Generate embedding once for both searches
    start_time = time.time()
    query_vector = get_embedding(search_query)
    if not query_vector:
        logger.error("Failed to generate embedding for parallel document search")
        return {
            "user_documents": [],
            "admin_documents": []
        }
    
    embedding_time = time.time() - start_time
    safe_log_info(f"Embedding generated in {embedding_time:.3f}s")
    
    def get_user_documents():
        """Retrieve user documents using pre-generated embedding."""
        try:
            documents = find_similar_documents_hybrid_search(query_vector, search_query, uploader_username)
            safe_log_info(f"Found {len(documents)} user documents")
            return documents
        except Exception as e:
            safe_log_error(f"Error in user document search: {e}", exc_info=True)
            return []
    
    def get_admin_documents():
        """Retrieve admin documents using pre-generated embedding."""
        try:
            documents = find_similar_documents_vector_search(query_vector)
            safe_log_info(f"Found {len(documents)} admin documents")
            return documents
        except Exception as e:
            safe_log_error(f"Error in admin document search: {e}", exc_info=True)
            return []
    
    try:
        search_start = time.time()
        
        # Run both searches in parallel with shared embedding
        with ThreadPoolExecutor(max_workers=2) as executor:
            user_future = executor.submit(get_user_documents)
            admin_future = executor.submit(get_admin_documents)
            
            user_docs = []
            admin_docs = []
            
            # Collect results as they complete
            for future in as_completed([user_future, admin_future]):
                try:
                    if future == user_future:
                        user_docs = future.result()
                    elif future == admin_future:
                        admin_docs = future.result()
                except Exception as e:
                    safe_log_error(f"Error in parallel document retrieval: {e}")
        
        search_time = time.time() - search_start
        total_time = time.time() - start_time
        safe_log_info(f"Parallel document retrieval completed in {search_time:.3f}s (total: {total_time:.3f}s)")
        
        return {
            "user_documents": user_docs,
            "admin_documents": admin_docs
        }
        
    except Exception as e:
        safe_log_error(f"Error in find_documents_parallel: {e}", exc_info=True)
        return {
            "user_documents": [],
            "admin_documents": []
        }

@tool
def find_document_from_user(search_query: str, uploader_username: str) -> list[dict]:
    """
    Tìm kiếm tài liệu từ người dùng
    """
    safe_log_info("--- Running Tool: find_document_from_user ---")
    safe_log_info(f"Searching user documents for query: '{search_query}' and uploader: '{uploader_username}'")
    
    try:
        query_vector = get_embedding(search_query)
        if not query_vector:
            logger.error("Failed to generate embedding for search query")
            return []
            
        documents = find_similar_documents_hybrid_search(query_vector, search_query, uploader_username)
        safe_log_info(f"Found {len(documents)} user documents")
        
        return documents
    except Exception as e:
        safe_log_error(f"Error in find_document_from_user: {e}", exc_info=True)
        return []
    
@tool
def find_document_from_admin(search_query: str, uploader_username: str) -> list[dict]:
    """
    Tìm kiếm tài liệu từ admin
    """
    safe_log_info("--- Running Tool: find_document_from_admin ---")
    safe_log_info(f"Searching admin documents for query: '{search_query}' (uploader_username parameter ignored for admin search)")
    
    try:
        query_vector = get_embedding(search_query)
        if not query_vector:
            logger.error("Failed to generate embedding for search query")
            return []
            
        documents = find_similar_documents_vector_search(query_vector)
        safe_log_info(f"Found {len(documents)} admin documents")
        
        return documents
    except Exception as e:
        safe_log_error(f"Error in find_document_from_admin: {e}", exc_info=True)
        return []  
      
@tool
def rerank_documents(user_question: str, documents: list[dict]) -> list[dict]:
    """
    Rerank documents based on relevance to user question using Gemini API.
    """
    if not documents:
        return []

    docs_for_prompt = []
    for doc in documents:
        doc['_id'] = str(doc['_id'])
        docs_for_prompt.append({
            "id": doc['_id'],
            "content": doc.get('content', '')
        })

    prompt = f"""
    ### VAI TRÒ VÀ NHIỆM VỤ CHUYÊN SÂU ###
    Bạn là một hệ thống Phân loại và Xếp hạng Mức độ Liên quan (Relevance Classification and Ranking System) cực kỳ chính xác.
    Nhiệm vụ của bạn KHÔNG PHẢI là trả lời câu hỏi. Nhiệm vụ của bạn là ĐÁNH GIÁ và CHẤM ĐIỂM từng tài liệu dựa trên mức độ chúng giúp trả lời câu hỏi được cung cấp.

    ### QUY TRÌNH SUY LUẬN (CHO MỖI TÀI LIỆU) ###
    1.  Đọc kỹ và hiểu sâu [CÂU HỎI CỦA NGƯỜI DÙNG].
    2.  Đọc kỹ nội dung của tài liệu đang xét.
    3.  Tự đặt câu hỏi: "Tài liệu này có chứa thông tin trực tiếp và đầy đủ để trả lời câu hỏi không? Hay nó chỉ cung cấp thông tin nền tảng? Hay nó gần như không liên quan?".
    4.  Dựa trên câu trả lời, chọn một điểm số từ [BẢNG CHẤM ĐIỂM] dưới đây.

    ### BẢNG CHẤM ĐIỂM CHI TIẾT (SCORING RUBRIC) ###
    - **1.0 (Rất cao):** Tài liệu chứa câu trả lời trực tiếp, đầy đủ và rõ ràng cho câu hỏi.
    - **0.7 (Cao):** Tài liệu không trả lời thẳng nhưng chứa thông tin cốt lõi, gần như không thể thiếu để suy ra câu trả lời.
    - **0.4 (Trung bình):** Tài liệu có liên quan, đề cập đến các chủ đề hoặc từ khóa trong câu hỏi nhưng không đi vào chi tiết hoặc không trả lời trực tiếp.
    - **0.1 (Thấp):** Tài liệu có vẻ liên quan ở bề mặt (ví dụ: chung chủ đề) nhưng thực chất không hữu ích để trả lời câu hỏi.
    - **0.0 (Không liên quan):** Tài liệu nói về một chủ đề hoàn toàn khác.

    ### QUY TẮC ĐỊNH DẠNG ĐẦU RA (OUTPUT FORMAT RULES) ###
    - Kết quả BẮT BUỘC phải là một chuỗi JSON duy nhất, là một danh sách các object.
    - Mỗi object BẮT BUỘC phải có hai key: "id" (dạng chuỗi, lấy từ input), và "new_score" (dạng số thực).
    - TUYỆT ĐỐI KHÔNG thêm bất kỳ văn bản, ghi chú, hay lời giải thích nào khác. Chỉ trả về chuỗi JSON.

    ### VÍ DỤ MẪU (FEW-SHOT EXAMPLE) ###
    [VÍ DỤ ĐẦU VÀO]
    CÂU HỎI:
    Làm thế nào để tạo môi trường ảo trong Python?

    DANH SÁCH TÀI LIỆU:
    [
      {{
        "id": "doc1",
        "uploader_username": "user1",
        "content": "Để tạo môi trường ảo, hãy dùng lệnh `python -m venv myenv`."
      }},
      {{
        "id": "doc2",
        "uploader_username": "user2",
        "content": "Python là một ngôn ngữ lập trình phổ biến."
      }}
    ]
    [VÍ DỤ KẾT QUẢ JSON]
    [
      {{
        "id": "doc1",
        "uploader_username": "user1",
        "new_score": 1.0
      }},
      {{
        "id": "doc2",
        "uploader_username": "user2",
        "new_score": 0.1
      }}
    ]

    ---
    [BẮT ĐẦU DỮ LIỆU THỰC TẾ]

    ### DỮ LIỆU ĐẦU VÀO ###
    [CÂU HỎI]
    {user_question}

    [DANH SÁCH TÀI LIỆU]
    {json.dumps(docs_for_prompt, ensure_ascii=False, indent=2)}

    ### KẾT QUẢ JSON ###
    """

    try:
        response = _get_model_client().models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=_generation_config
        )
        cleaned_response_text = response.text.strip().replace("```json", "").replace("```", "")
        rerank_results = json.loads(cleaned_response_text)

        scores_map = {item['id']: item['new_score'] for item in rerank_results}
        for doc in documents:
            doc['new_score'] = scores_map.get(doc['_id'], 0)

        reranked_documents = sorted(documents, key=lambda x: x['new_score'], reverse=True)

        return reranked_documents

    except Exception as e:
        safe_log_error(f"Error in rerank_documents: {e}")
        return documents

@tool
def classify_query_type(user_query: str) -> Dict[str, Any]:
    """
    Phân loại câu hỏi của người dùng để xác định xem có cần truy vấn kiến thức hay không.
    Classifies user query to determine if knowledge retrieval is needed.
    
    Args:
        user_query: Câu hỏi của người dùng / User's question
        
    Returns:
        Dict with:
        - needs_retrieval (bool): True if query needs knowledge retrieval
        - query_type (str): Type of query (greeting, farewell, general_chat, knowledge_query)
        - confidence (float): Confidence score of classification
    """
    safe_log_info("--- Running Tool: classify_query_type ---")
    safe_log_info(f"Classifying query: '{user_query}'")

    try:
        # Normalize query for better matching
        normalized_query = user_query.lower().strip()
        
        # Enhanced patterns for better matching
        greeting_patterns = [
            r'^\s*(xin\s+chào|chào\s+bạn|chào|xin\s+chao|chao)\s*[!.]*\s*$',
            r'^\s*(hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening)\s*[!.]*\s*$',
            r'^\s*(chào\s+buổi\s+sáng|chào\s+buổi\s+chiều|chào\s+buổi\s+tối)\s*[!.]*\s*$',
            r'^\s*(hế\s*lô|hể\s*lô|hêlô|helo)\s*[!.]*\s*$',
            r'^\s*(alo|a\s*lo|alô)\s*[!.]*\s*$'
        ]
        
        farewell_patterns = [
            r'^\s*(tạm\s+biệt|tam\s+biet|goodbye|bye|see\s+you|hẹn\s+gặp\s+lại)\s*[!.]*\s*$',
            r'^\s*(chào\s+tạm\s+biệt|gặp\s+lại\s+sau|bye\s+bye)\s*[!.]*\s*$',
            r'^\s*(cảm\s+ơn\s+và\s+tạm\s+biệt|thanks\s+and\s+bye)\s*[!.]*\s*$'
        ]
        
        general_chat_patterns = [
            r'^\s*(bạn\s+khỏe\s+không|how\s+are\s+you|what\'s\s+up|whats\s+up)\s*[?!.]*\s*$',
            r'^\s*(bạn\s+tên\s+gì|tên\s+của\s+bạn|what\'s\s+your\s+name|whats\s+your\s+name)\s*[?!.]*\s*$',
            r'^\s*(cảm\s+ơn|thank\s+you|thanks|thank)\s*[!.]*\s*$',
            r'^\s*(ok|okay|oke|được\s+rồi|tốt)\s*[!.]*\s*$'
        ]

        # Check for greetings first (highest priority)
        for pattern in greeting_patterns:
            if re.search(pattern, normalized_query):
                safe_log_info(f"Query '{user_query}' classified as GREETING with high confidence")
                return {
                    "needs_retrieval": False,
                    "query_type": "greeting",
                    "confidence": 0.95
                }

        # Check for farewells
        for pattern in farewell_patterns:
            if re.search(pattern, normalized_query):
                safe_log_info(f"Query '{user_query}' classified as FAREWELL with high confidence")
                return {
                    "needs_retrieval": False,
                    "query_type": "farewell",
                    "confidence": 0.95
                }

        # Check for general chat
        for pattern in general_chat_patterns:
            if re.search(pattern, normalized_query):
                safe_log_info(f"Query '{user_query}' classified as GENERAL_CHAT with high confidence")
                return {
                    "needs_retrieval": False,
                    "query_type": "general_chat",
                    "confidence": 0.90
                }

        # Additional simple checks for very short queries
        if len(normalized_query) <= 3:
            common_short_greetings = ['hi', 'hey', 'yo', 'chào', 'xin chào']
            if normalized_query in common_short_greetings:
                safe_log_info(f"Query '{user_query}' classified as SHORT GREETING")
                return {
                    "needs_retrieval": False,
                    "query_type": "greeting",
                    "confidence": 0.90
                }

        # For more complex classification, use Gemini API
        safe_log_info(f"Using Gemini API for complex classification of: '{user_query}'")
        
        prompt = f"""
        Phân tích câu hỏi sau và xác định xem có cần truy vấn kiến thức để trả lời không:

        Câu hỏi: "{user_query}"

        Hãy phân loại thành một trong các dạng sau:
        1. **greeting** - Câu chào hỏi đơn giản (xin chào, hi, hello, chào bạn, v.v.)
        2. **farewell** - Câu tạm biệt (tạm biệt, bye, goodbye, v.v.)
        3. **general_chat** - Trò chuyện chung (hỏi thăm sức khỏe, cảm ơn, v.v.)
        4. **knowledge_query** - Câu hỏi cần kiến thức cụ thể

        QUY TẮC QUAN TRỌNG:
        - Nếu là câu chào hỏi đơn giản → needs_retrieval = false
        - Nếu là câu tạm biệt → needs_retrieval = false  
        - Nếu là trò chuyện chung → needs_retrieval = false
        - Chỉ khi nào thực sự cần thông tin cụ thể → needs_retrieval = true

        Trả về kết quả dưới dạng JSON chính xác:
        {{
            "needs_retrieval": boolean,
            "query_type": string,
            "confidence": float
        }}
        """

        response = _get_model_client().models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=_generation_config
        )
        result_text = response.text.strip()
        
        # Clean up response text
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        
        try:
            result = json.loads(result_text)
            safe_log_info(f"Gemini API classification result: {result}")
            
            # Validation
            if not isinstance(result.get('needs_retrieval'), bool):
                raise ValueError("needs_retrieval must be boolean")
            if result.get('query_type') not in ['greeting', 'farewell', 'general_chat', 'knowledge_query']:
                raise ValueError("Invalid query_type")
            if not isinstance(result.get('confidence'), (int, float)):
                raise ValueError("confidence must be numeric")
                
            return result
            
        except (json.JSONDecodeError, ValueError) as e:
            safe_log_error(f"Failed to parse Gemini API response: {e}. Raw response: {result_text}")
            # Fall back to knowledge query
            return {
                "needs_retrieval": True,
                "query_type": "knowledge_query",
                "confidence": 0.5
            }

    except Exception as e:
        safe_log_error(f"Error in classify_query_type: {e}")
        # Default to knowledge query if classification fails
        return {
            "needs_retrieval": True,
            "query_type": "knowledge_query",
            "confidence": 0.5
        }

@tool
def direct_response(user_query: str, query_type: str = "general_chat") -> str:
    """
    Trả lời trực tiếp câu hỏi của người dùng mà không cần truy vấn kiến thức.
    Directly respond to user queries without knowledge retrieval.
    
    Args:
        user_query: Câu hỏi của người dùng
        query_type: Loại câu hỏi (greeting, farewell, general_chat)
    """
    safe_log_info("--- Running Tool: direct_response ---")
    safe_log_info(f"Direct response to query type: '{query_type}' for query: '{user_query}'")
    
    try:
        # Provide quick responses for common patterns without API call
        if query_type == "greeting":
            import random
            greetings = [
                "Xin chào! Tôi là WoxionChat AI, rất vui được gặp bạn! 👋\nHi! I'm WoxionChat AI, nice to meet you! 👋",
                "Chào bạn! Tôi sẵn sàng hỗ trợ bạn hôm nay! 😊\nHello! I'm ready to help you today! 😊",
                "Xin chào! Tôi là trợ lý AI WoxionChat. Bạn cần tôi hỗ trợ gì không? 🤖\nHi! I'm WoxionChat AI assistant. How can I help you? 🤖",
                "Chào bạn! Rất vui được trò chuyện với bạn! 🌟\nHello! Great to chat with you! 🌟"
            ]
            return random.choice(greetings)
        
        elif query_type == "farewell":
            import random
            farewells = [
                "Tạm biệt! Hẹn gặp lại bạn lần sau! 👋\nGoodbye! See you next time! 👋",
                "Chào tạm biệt! Chúc bạn một ngày tốt lành! 😊\nFarewell! Have a great day! 😊",
                "Hẹn gặp lại! Luôn sẵn sàng hỗ trợ bạn! 🤗\nSee you later! Always ready to help! 🤗",
                "Tạm biệt! Cảm ơn bạn đã trò chuyện! 💫\nGoodbye! Thanks for chatting! 💫"
            ]
            return random.choice(farewells)
        
        elif query_type == "general_chat":
            # Handle common general chat patterns
            normalized_query = user_query.lower().strip()
            
            if "cảm ơn" in normalized_query or "thank" in normalized_query:
                return "Không có gì! Tôi rất vui được giúp đỡ bạn! 😊\nYou're welcome! I'm happy to help! 😊"
            
            if "khỏe" in normalized_query or "how are you" in normalized_query:
                return "Tôi rất khỏe và sẵn sàng hỗ trợ bạn! Còn bạn thì sao? 😊\nI'm doing great and ready to help! How about you? 😊"
            
            if "tên" in normalized_query or "name" in normalized_query:
                return "Tôi là WoxionChat AI, trợ lý thông minh của bạn! 🤖\nI'm WoxionChat AI, your intelligent assistant! 🤖"
                
            if "ok" in normalized_query or "okay" in normalized_query or "được rồi" in normalized_query:
                return "Tốt! Tôi sẵn sàng hỗ trợ bạn tiếp! 👍\nGreat! I'm ready to help you further! 👍"
        
        # For more complex responses, use Gemini API
        safe_log_info(f"Using Gemini API for direct response to query type: '{query_type}'")
        
        prompt = f"""
        Bạn là WoxionChat AI, một trợ lý thông minh, thân thiện và chuyên nghiệp.
        Hãy trả lời câu hỏi của người dùng một cách tự nhiên và phù hợp.

        Loại câu hỏi: {query_type}
        Câu hỏi/Tin nhắn: "{user_query}"

        QUY TẮC TRẢI NGHIỆM:
        1. Trả lời ngắn gọn, tự nhiên như một người bạn thân thiện
        2. Phù hợp với loại câu hỏi (chào hỏi, tạm biệt, trò chuyện)
        3. Luôn giữ thái độ tích cực, chuyên nghiệp
        4. Sử dụng emoji phù hợp để tạo cảm giác thân thiện
        5. Trả lời bằng cả tiếng Việt và tiếng Anh (Vietnamese first, English second)
        6. KHÔNG đưa ra câu trả lời dạng JSON hoặc code
        7. KHÔNG hỏi thông tin cá nhân hoặc yêu cầu đăng nhập
        8. Tập trung vào việc tạo ra một cuộc trò chuyện tự nhiên

        PHONG CÁCH:
        - Nếu greeting: Chào đón nhiệt tình, giới thiệu bản thân
        - Nếu farewell: Tạm biệt ấm áp, mời quay lại
        - Nếu general_chat: Trả lời thân thiện, tự nhiên

        Hãy trả lời một cách tự nhiên nhất có thể!
        """

        response = _get_model_client().models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=_generation_config
        )
        result = response.text.strip()
        
        # Clean up response
        result = result.replace("```", "").replace("json", "").strip()
        safe_log_info(f"Generated direct response: {result[:100]}...")
        
        return result

    except Exception as e:
        safe_log_error(f"Error in direct_response: {e}")
        # Fallback responses
        if query_type == "greeting":
            return "Xin chào! Tôi là WoxionChat AI, rất vui được gặp bạn! 👋\nHi! I'm WoxionChat AI, nice to meet you! 👋"
        elif query_type == "farewell":
            return "Tạm biệt! Hẹn gặp lại bạn nhé! 👋\nGoodbye! See you again! 👋"
        else:
            return "Rất vui được trò chuyện với bạn! Tôi có thể giúp gì cho bạn không? 😊\nIt's nice chatting with you! How can I help you? 😊"

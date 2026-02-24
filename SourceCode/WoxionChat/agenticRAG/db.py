import os
import logging
import pymongo
from google import genai
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import hashlib
from functools import lru_cache

# Configure logging
logger = logging.getLogger(__name__)

# Simple in-memory cache for embeddings
_embedding_cache = {}
_cache_lock = threading.Lock()

# Lazy genai client
_genai_client: genai.Client | None = None

def _get_genai_client() -> genai.Client:
    """Returns a lazily initialised google-genai Client."""
    global _genai_client
    if _genai_client is None:
        api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('google_api_key')
        _genai_client = genai.Client(api_key=api_key)
    return _genai_client

def safe_log_info(message: str):
    """Safely log info messages with Unicode characters."""
    try:
        logger.info(message)
    except UnicodeEncodeError:
        safe_message = message.encode('ascii', 'replace').decode('ascii')
        logger.info(f"[UNICODE_SAFE] {safe_message}")

def safe_log_warning(message: str):
    """Safely log warning messages with Unicode characters."""
    try:
        logger.warning(message)
    except UnicodeEncodeError:
        safe_message = message.encode('ascii', 'replace').decode('ascii')
        logger.warning(f"[UNICODE_SAFE] {safe_message}")

def safe_log_error(message: str, exc_info=None):
    """Safely log error messages with Unicode characters."""
    try:
        logger.error(message, exc_info=exc_info)
    except UnicodeEncodeError:
        safe_message = message.encode('ascii', 'replace').decode('ascii')
        logger.error(f"[UNICODE_SAFE] {safe_message}", exc_info=exc_info)

db_client = None

def init_db(app):
    """Initialize database connection."""
    global db_client
    mongo_url = app.config.get("MONGO_CONNECTION_STRING")
    if not mongo_url:
        raise ValueError("MONGO_CONNECTION_STRING not found in Flask config")
    
    try:
        client = pymongo.MongoClient(
            mongo_url,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            retryWrites=True,
            retryReads=True
        )
        client.admin.command('ping')
        db_client = client.get_database('local-bot')
        safe_log_info("Connected to MongoDB and database 'local-bot' is selected.")
    except Exception as e:
        safe_log_error(f"Failed to connect to MongoDB: {e}")
        raise

def get_db():
    """Returns the database client instance."""
    if db_client is None:
        raise RuntimeError("Database is not initialized. Call init_db() first.")
    return db_client

def get_embedding(text, model='models/gemini-embedding-exp-03-07'):
    """Get embeddings for text using Google's generative AI with caching."""
    # Create cache key
    cache_key = hashlib.md5(f"{text}:{model}".encode()).hexdigest()
    
    # Check cache first
    with _cache_lock:
        if cache_key in _embedding_cache:
            safe_log_info(f"Cache hit for embedding: {text[:50]}...")
            return _embedding_cache[cache_key]
    
    try:
        start_time = time.time()
        result = _get_genai_client().models.embed_content(model=model, contents=text)
        embedding = result.embeddings[0].values
        
        # Cache the result
        with _cache_lock:
            _embedding_cache[cache_key] = embedding
            # Keep cache size reasonable (max 100 items)
            if len(_embedding_cache) > 100:
                # Remove oldest entries
                keys_to_remove = list(_embedding_cache.keys())[:20]
                for key in keys_to_remove:
                    del _embedding_cache[key]
        
        embedding_time = time.time() - start_time
        safe_log_info(f"Generated embedding in {embedding_time:.3f}s for: {text[:50]}...")
        return embedding
    except Exception as e:
        safe_log_error(f"Error getting embedding: {e}", exc_info=True)
        return None

def get_embedding_batch(texts, model='models/gemini-embedding-exp-03-07'):
    """Get embeddings for multiple texts efficiently."""
    results = []
    uncached_texts = []
    uncached_indices = []
    
    # Check cache for all texts
    with _cache_lock:
        for i, text in enumerate(texts):
            cache_key = hashlib.md5(f"{text}:{model}".encode()).hexdigest()
            if cache_key in _embedding_cache:
                results.append(_embedding_cache[cache_key])
            else:
                results.append(None)
                uncached_texts.append(text)
                uncached_indices.append(i)
    
    # Generate embeddings for uncached texts
    if uncached_texts:
        try:
            start_time = time.time()
            
            # Process uncached texts in parallel
            def get_single_embedding(text):
                return get_embedding(text, model)
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_index = {
                    executor.submit(get_single_embedding, text): idx 
                    for idx, text in zip(uncached_indices, uncached_texts)
                }
                
                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        embedding = future.result()
                        results[idx] = embedding
                    except Exception as e:
                        safe_log_error(f"Error getting embedding for text {idx}: {e}")
                        results[idx] = None
            
            batch_time = time.time() - start_time
            safe_log_info(f"Generated {len(uncached_texts)} embeddings in {batch_time:.3f}s")
            
        except Exception as e:
            safe_log_error(f"Error in batch embedding generation: {e}")
    
    return results

def find_similar_documents_hybrid_search(
    query_vector: list[float],
    search_query: str,
    uploader_username: str,
    limit: int = 10,
    candidates: int = 20,
    vector_search_index: str = "vector_search_on_users",
    atlas_search_index: str = "text_search_on_users" 
) -> list[dict]:
    """
    Hybrid search combining vector and text search with parallel execution.
    """
    db = get_db()
    collection = db['user_documents_chunking']
    
    all_results = []
    
    def perform_vector_search():
        """Perform vector search in parallel."""
        try:
            vector_pipeline = [
                {
                    "$vectorSearch": {
                        "index": vector_search_index,
                        "path": "embedding",
                        "queryVector": query_vector,
                        "limit": limit,
                        "numCandidates": candidates,
                        "filter": {
                            "uploader_username": {"$eq": uploader_username}
                        }
                    }
                },
                {
                    "$project": {
                        '_id': 1,
                        'content': 1,
                        'uploader_username': 1,
                        "vector_score": {"$meta": "vectorSearchScore"}
                    }
                }
            ]
            
            vector_results = list(collection.aggregate(vector_pipeline))
            safe_log_info(f"Vector search returned {len(vector_results)} results")
            for doc in vector_results:
                doc['search_type'] = 'vector'
                doc['combined_score'] = doc.get('vector_score', 0) * 0.7  # Weight vector score
            return vector_results
        except Exception as e:
            safe_log_warning(f"Vector search failed: {e}")
            return []
    
    def perform_text_search():
        """Perform text search in parallel."""
        if not search_query or not search_query.strip():
            return []
        
        try:
            text_pipeline = [
                {
                    "$search": {
                        "index": atlas_search_index,
                        "compound": {
                            "must": [
                                {
                                    "text": {
                                        "query": search_query,
                                        "path": "content"
                                    }
                                },
                                {
                                    "text": {
                                        "query": uploader_username,
                                        "path": "uploader_username"
                                    }
                                }
                            ]
                        }
                    }
                },
                {
                    "$project": {
                        '_id': 1,
                        'content': 1,
                        'uploader_username': 1,
                        "text_score": {"$meta": "searchScore"}
                    }
                }
            ]
            
            text_results = list(collection.aggregate(text_pipeline))
            safe_log_info(f"Text search returned {len(text_results)} results")
            for doc in text_results:
                doc['search_type'] = 'text'
                doc['combined_score'] = doc.get('text_score', 0) * 0.3  # Weight text score
            return text_results
        except Exception as e:
            safe_log_warning(f"Text search failed: {e}")
            return []
    
    try:
        # Run both searches in parallel
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=2) as executor:
            vector_future = executor.submit(perform_vector_search)
            text_future = executor.submit(perform_text_search)
            
            # Collect results as they complete
            for future in as_completed([vector_future, text_future]):
                try:
                    results = future.result()
                    all_results.extend(results)
                except Exception as e:
                    safe_log_error(f"Error in parallel search: {e}")
        
        search_time = time.time() - start_time
        safe_log_info(f"Parallel search completed in {search_time:.3f}s")
        
        # 3. Merge và deduplicate results
        seen_ids = set()
        merged_results = []
        
        for doc in all_results:
            doc_id = str(doc['_id'])
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                # Clean up the document for final result
                final_doc = {
                    '_id': doc['_id'],
                    'content': doc.get('content', ''),
                    'uploader_username': doc.get('uploader_username', ''),
                    'score': doc.get('combined_score', 0)
                }
                merged_results.append(final_doc)
            else:
                # If document already exists, boost its score
                for existing_doc in merged_results:
                    if str(existing_doc['_id']) == doc_id:
                        existing_doc['score'] += doc.get('combined_score', 0) * 0.5
                        break
        
        # Sort by combined score
        merged_results.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        # Return top results
        final_results = merged_results[:limit]
        safe_log_info(f"Hybrid search final results: {len(final_results)} documents")
        
        return final_results
        
    except Exception as e:
        safe_log_error(f"Error in hybrid search: {e}", exc_info=True)
        
        # Fallback: Simple text search without vector
        try:
            fallback_results = list(collection.find(
                {
                    "uploader_username": uploader_username,
                    "$text": {"$search": search_query}
                }
            ).limit(limit))
            
            safe_log_info(f"Fallback search returned {len(fallback_results)} results")
            
            # Format fallback results
            formatted_results = []
            for doc in fallback_results:
                formatted_results.append({
                    '_id': doc['_id'],
                    'content': doc.get('content', ''),
                    'uploader_username': doc.get('uploader_username', ''),
                    'score': 0.5  # Default score for fallback
                })
            
            return formatted_results
            
        except Exception as fallback_error:
            safe_log_error(f"Fallback search also failed: {fallback_error}")
            return []

def find_similar_documents_vector_search(
    query_vector: list[float],
    limit: int = 10,
    candidates: int = 10,
    vector_search_index: str = "vector_search_admin"
) -> list[dict]:
    """
    Vector search for admin documents.
    """
    db = get_db()
    collection = db['admin_documents_chunking']

    pipeline = [
        {
            "$vectorSearch": {
                "index": vector_search_index,
                "path": "embedding",
                "queryVector": query_vector,
                "limit": limit,
                "numCandidates": candidates
            }
        },
        {
            "$project": {
                '_id': 1,
                'content': 1,
                'uploader_username': 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]

    try:
        results = list(collection.aggregate(pipeline))
        safe_log_info(f"Admin vector search returned {len(results)} results")
        return results
        
    except Exception as e:
        safe_log_error(f"Vector search failed: {e}")
        
        # Fallback: Simple content search
        try:
            safe_log_info("Attempting fallback search...")
            fallback_results = list(collection.find({}).limit(limit))
            
            safe_log_info(f"Fallback search returned {len(fallback_results)} results")
            
            # Format results to match expected structure
            formatted_results = []
            for doc in fallback_results:
                formatted_results.append({
                    '_id': doc['_id'],
                    'content': doc.get('content', ''),
                    'uploader_username': doc.get('uploader_username', ''),
                    'score': 0.5  # Default score for fallback
                })
            
            return formatted_results
            
        except Exception as fallback_error:
            safe_log_error(f"Fallback search also failed: {fallback_error}")
            return []
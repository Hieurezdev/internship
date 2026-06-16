import os
import sys
import re
import logging
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional
import numpy as np
import openai

# Setup path injection for ACE
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)  # WoxionChat folder
WORKSPACE_ROOT = os.path.dirname(PARENT_DIR)  # SourceCode folder
ACE_PATH = os.path.join(WORKSPACE_ROOT, 'ace')

if ACE_PATH not in sys.path:
    sys.path.append(ACE_PATH)
    # Also inject the nested 'ace' directory which contains core modules
    sys.path.append(os.path.join(ACE_PATH, 'ace'))

logger = logging.getLogger(__name__)

# Try importing ACE
try:
    from ace import ACE
    from ace.core.playbook_retriever import PlaybookRetriever
    from ace.core import Generator, Reflector, Curator
    from ace.core.failure_memory import FailureMemoryBank
    ACE_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import ACE from paths: {ACE_PATH}. Error: {e}")
    ACE_AVAILABLE = False

DEFAULT_PLAYBOOK_CONTENT = """## STRATEGIES & INSIGHTS
[rag-00001] helpful=0 harmful=0 :: When answering user queries, always refer to the provided document context and cite the source file names clearly if possible.
[rag-00002] helpful=0 harmful=0 :: If the retrieved document context is empty or does not contain any relevant information to answer the user's question, politely state that you cannot find the answer in the database, rather than hallucinating or making up details.
[rag-00003] helpful=0 harmful=0 :: Maintain a professional, polite, and helpful tone, answering in the same language as the user's query (defaulting to Vietnamese).
[rag-00004] helpful=0 harmful=0 :: Do not ask the user for their user ID, username, or other authentication details, as they are already identified.
[rag-00005] helpful=0 harmful=0 :: When the query is classified as a general chat or greeting (needs_retrieval=False), respond directly and friendly using general knowledge without searching the database.
[rag-00006] helpful=0 harmful=0 :: Format your response beautifully using clean markdown, headings, and bullet points where appropriate for readability.

## FORMULAS & CALCULATIONS

## CODE SNIPPETS & TEMPLATES

## COMMON MISTAKES TO AVOID
[err-00001] helpful=0 harmful=0 :: Avoid repeating the user ID or other internal metadata in the final response to the user.

## PROBLEM-SOLVING HEURISTICS

## CONTEXT CLUES & INDICATORS

## OTHERS"""

# Cache for user-specific retrievers, playbook hashes, and failure memories
_retrievers: Dict[str, PlaybookRetriever] = {}
_playbook_hashes: Dict[str, str] = {}
_failure_memories: Dict[str, FailureMemoryBank] = {}


def get_user_playbook_collection():
    """Retrieve the PyMongo collection for user-specific ACE playbooks."""
    from .db import get_db
    db = get_db()
    return db['ace_playbooks']


def get_user_failure_memories_collection():
    """Retrieve the PyMongo collection for user-specific FailureMemory cases."""
    from .db import get_db
    db = get_db()
    return db['ace_failure_memories']


def load_playbook(user_id: str, return_status: bool = False):
    """Load the ACE playbook for a specific user from MongoDB. Returns default if not found."""
    user_id = user_id or "default_user"
    was_created = False
    
    try:
        collection = get_user_playbook_collection()
        doc = collection.find_one({"user_id": user_id})
        
        if doc:
            logger.info(f"Loaded ACE playbook from MongoDB for user: {user_id}")
            playbook_str = doc.get("playbook_text", DEFAULT_PLAYBOOK_CONTENT).strip()
        else:
            # If not found, insert default playbook for this user
            logger.info(f"ACE playbook not found in MongoDB for user: {user_id}. Creating default.")
            collection.update_one(
                {"user_id": user_id},
                {"$set": {
                    "user_id": user_id,
                    "playbook_text": DEFAULT_PLAYBOOK_CONTENT.strip(),
                    "updated_at": datetime.utcnow()
                }},
                upsert=True
            )
            playbook_str = DEFAULT_PLAYBOOK_CONTENT.strip()
            was_created = True
    except Exception as e:
        logger.error(f"Error loading playbook from MongoDB for user {user_id}: {e}", exc_info=True)
        playbook_str = DEFAULT_PLAYBOOK_CONTENT.strip()
        was_created = False

    if return_status:
        return playbook_str, was_created
    return playbook_str


def save_playbook(user_id: str, playbook_str: str) -> bool:
    """Save the playbook text to MongoDB for a specific user and clear its cached retriever."""
    user_id = user_id or "default_user"
    playbook_str = playbook_str.strip()
    
    try:
        collection = get_user_playbook_collection()
        collection.update_one(
            {"user_id": user_id},
            {"$set": {
                "playbook_text": playbook_str,
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )
        logger.info(f"Successfully saved ACE playbook to MongoDB for user: {user_id}")
        
        # Update or clear cached retriever for this user
        if user_id in _retrievers:
            try:
                _retrievers[user_id].update_index(playbook_str)
                _playbook_hashes[user_id] = hashlib.md5(playbook_str.encode('utf-8')).hexdigest()
                logger.info(f"PlaybookRetriever (RAE) index rebuilt for user: {user_id}")
            except Exception as e:
                logger.error(f"Failed to rebuild PlaybookRetriever index for user {user_id}: {e}")
                _retrievers.pop(user_id, None)
                _playbook_hashes.pop(user_id, None)
                
        return True
    except Exception as e:
        logger.error(f"Error saving playbook to MongoDB for user {user_id}: {e}", exc_info=True)
        return False


def get_ace_retriever(user_id: str, top_k: int = 5) -> Optional[PlaybookRetriever]:
    """Get or initialize the user-specific PlaybookRetriever (RAE) from cache or MongoDB."""
    if not ACE_AVAILABLE:
        return None

    user_id = user_id or "default_user"
    playbook_str = load_playbook(user_id)
    current_hash = hashlib.md5(playbook_str.encode('utf-8')).hexdigest()

    # Rebuild index if retriever doesn't exist or playbook text changed
    if user_id not in _retrievers or _playbook_hashes.get(user_id) != current_hash:
        try:
            logger.info(f"Initializing/Updating ACE PlaybookRetriever (RAE) for user: {user_id}")
            retriever = PlaybookRetriever(
                embedding_model_name='BAAI/bge-m3',
                embedding_dim=1024,
                top_k=top_k
            )
            retriever.update_index(playbook_str)
            
            _retrievers[user_id] = retriever
            _playbook_hashes[user_id] = current_hash
        except Exception as e:
            logger.error(f"Failed to initialize ACE PlaybookRetriever for user {user_id}: {e}", exc_info=True)
            return None

    return _retrievers[user_id]


def get_ace_context(query: str, user_id: str, top_k: int = 10) -> str:
    """
    Retrieve Top-K most relevant bullets from the user-specific playbook.
    Falls back to the full user playbook if RAE fails or is unavailable.
    """
    user_id = user_id or "default_user"
    playbook_str = load_playbook(user_id)
    
    if not ACE_AVAILABLE:
        return playbook_str

    try:
        retriever = get_ace_retriever(user_id, top_k=top_k)
        if retriever is not None:
            retrieved = retriever.retrieve(query, top_k=top_k)
            return retrieved
    except Exception as e:
        logger.error(f"Error in RAE retrieval for user {user_id}: {e}")

    return playbook_str


def load_failure_memory(user_id: str, retriever: Optional[PlaybookRetriever] = None) -> FailureMemoryBank:
    """Load the FailureMemoryBank for a specific user from MongoDB, reusing the retriever's encoder."""
    user_id = user_id or "default_user"
    
    # Return from cache if already loaded
    if user_id in _failure_memories:
        return _failure_memories[user_id]
        
    memory_bank = FailureMemoryBank(
        encoder=retriever.encode if retriever else None,
        top_k=3
    )
    
    try:
        collection = get_user_failure_memories_collection()
        cursor = collection.find({"user_id": user_id})
        
        entries = []
        for doc in cursor:
            if 'embedding' in doc and doc['embedding']:
                entry = {
                    'question': doc['question'],
                    'predicted_answer': doc['predicted_answer'],
                    'ground_truth': doc['ground_truth'],
                    'error_identification': doc.get('error_identification', ''),
                    'root_cause': doc.get('root_cause', ''),
                    'key_insight': doc.get('key_insight', ''),
                    '_emb': np.array(doc['embedding'], dtype=np.float32)
                }
                entries.append(entry)
                
        if entries:
            memory_bank._entries = entries
            memory_bank._rebuild_index()
            logger.info(f"Loaded {len(entries)} failure memory cases from MongoDB for user: {user_id}")
    except Exception as e:
        logger.error(f"Error loading failure memory from MongoDB for user {user_id}: {e}", exc_info=True)
        
    _failure_memories[user_id] = memory_bank
    return memory_bank


def get_openai_compatible_gemini_client() -> openai.OpenAI:
    """Initialize OpenAI client configured to hit Gemini API."""
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("google_api_key")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in environment variables.")
    return openai.OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )


def reflect_and_curate_feedback(
    user_id: str,
    query: str,
    context: str,
    response: str,
    rating: str,  # 'thumbs_up' or 'thumbs_down'
    correct_answer: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze user feedback, reflect using Reflector (with FailureMemoryBank lookup), and curate the user-specific playbook.
    """
    if not ACE_AVAILABLE:
        return {"success": False, "message": "ACE framework is not available"}

    user_id = user_id or "default_user"

    try:
        # 1. Initialize client & models
        client = get_openai_compatible_gemini_client()
        model_name = "gemini-2.5-flash"

        reflector = Reflector(client, "openai", model_name)
        curator = Curator(client, "openai", model_name)

        # Load current user playbook
        playbook_str = load_playbook(user_id)

        # Get the bullets that were retrieved for this query
        retriever = get_ace_retriever(user_id)
        bullets_used_str = ""
        if retriever:
            bullets_used_str = retriever.retrieve(query)
        else:
            bullets_used_str = playbook_str

        # 2. Determine environment feedback
        is_correct = (rating == "thumbs_up")
        if is_correct:
            environment_feedback = "The user rated this answer as correct/helpful."
        else:
            environment_feedback = "The user rated this answer as incorrect/unhelpful."
            if correct_answer:
                environment_feedback += f" The user suggested a better answer: {correct_answer}"

        # Load user-specific FailureMemoryBank (Analogical Reflection)
        memory_bank = load_failure_memory(user_id, retriever)

        # 3. Reflector step
        logger.info(f"--- Running ACE Reflector on feedback for user: {user_id} ---")
        reflection, bullet_tags, call_info = reflector.reflect(
            question=query,
            reasoning_trace=response,
            predicted_answer=response,
            ground_truth=correct_answer,
            environment_feedback=environment_feedback,
            bullets_used=bullets_used_str,
            use_ground_truth=bool(correct_answer),
            use_json_mode=False,
            failure_memory=memory_bank  # Enabled FailureMemoryBank!
        )
        logger.info(f"Reflector tags generated: {bullet_tags}")

        # Update bullet helpful/harmful counts based on user feedback & reflector tags
        from playbook_utils import update_bullet_counts, get_playbook_stats
        if bullet_tags:
            playbook_str = update_bullet_counts(playbook_str, bullet_tags)

        # Save failure memory if thumbs down (incorrect answer) to enrich analogical reflection next time
        if rating == "thumbs_down":
            try:
                # Distill insights
                error_id = ""
                root_cause = ""
                insight = ""
                
                try:
                    parsed = json.loads(reflection)
                    error_id = parsed.get("error_identification", "")
                    root_cause = parsed.get("root_cause_analysis", "") or parsed.get("root_cause", "")
                    insight = parsed.get("key_insight", "")
                except (json.JSONDecodeError, TypeError):
                    # Extract sections using regex
                    if "error identification" in reflection.lower() or "key insight" in reflection.lower():
                        error_match = re.search(r'(?:Error Identification|Error|Sai sót):\s*(.*?)(?=\n\n|\n[A-Z]|$)', reflection, re.DOTALL | re.IGNORECASE)
                        root_match = re.search(r'(?:Root Cause|Cause|Nguyên nhân):\s*(.*?)(?=\n\n|\n[A-Z]|$)', reflection, re.DOTALL | re.IGNORECASE)
                        insight_match = re.search(r'(?:Key Insight|Insight|Bài học|Kinh nghiệm):\s*(.*?)(?=\n\n|\n[A-Z]|$)', reflection, re.DOTALL | re.IGNORECASE)
                        
                        error_id = error_match.group(1).strip() if error_match else ""
                        root_cause = root_match.group(1).strip() if root_match else ""
                        insight = insight_match.group(1).strip() if insight_match else ""
                    
                    # Fallback: if all empty, store full reflection as error_identification
                    if not error_id and not root_cause and not insight:
                        error_id = reflection.strip()
                        
                # Encode the question using retriever
                emb = retriever.encode([query])[0] if retriever else None
                
                if emb is not None:
                    # Save to MongoDB
                    collection = get_user_failure_memories_collection()
                    collection.insert_one({
                        "user_id": user_id,
                        "question": query,
                        "predicted_answer": response,
                        "ground_truth": correct_answer or "",
                        "error_identification": error_id,
                        "root_cause": root_cause,
                        "key_insight": insight,
                        "embedding": emb.tolist(),
                        "created_at": datetime.utcnow()
                    })
                    
                    # Also append in-memory cache
                    entry = {
                        'question': query,
                        'predicted_answer': response,
                        'ground_truth': correct_answer or '',
                        'error_identification': error_id,
                        'root_cause': root_cause,
                        'key_insight': insight,
                        '_emb': emb
                    }
                    memory_bank._entries.append(entry)
                    memory_bank._rebuild_index()
                    logger.info(f"Added failure memory case to MongoDB and cache for user: {user_id}")
            except Exception as ex:
                logger.error(f"Failed to save failure memory for user {user_id}: {ex}", exc_info=True)

        # 4. Curator step
        logger.info(f"--- Running ACE Curator on feedback for user: {user_id} ---")
        
        # Calculate next global ID by finding max suffix in current bullets
        bullet_pattern = re.compile(r'\[[a-z]+-(\d+)\]')
        ids = [int(m) for m in bullet_pattern.findall(playbook_str)]
        next_global_id = max(ids) + 1 if ids else 1
        
        # Get playbook stats
        stats = get_playbook_stats(playbook_str)

        updated_playbook, next_global_id, operations, curator_call_info = curator.curate(
            current_playbook=playbook_str,
            recent_reflection=reflection,
            question_context=query,
            current_step=1,
            total_samples=1,
            token_budget=80000,
            playbook_stats=stats,
            use_ground_truth=bool(correct_answer),
            use_json_mode=False,
            call_id="curate_feedback",
            next_global_id=next_global_id
        )

        # 5. Save the updated user playbook to MongoDB
        save_success = save_playbook(user_id, updated_playbook)

        return {
            "success": save_success,
            "reflection": reflection,
            "bullet_tags": bullet_tags,
            "playbook": updated_playbook
        }

    except Exception as e:
        logger.error(f"Error in reflect_and_curate_feedback for user {user_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during reflection/curation: {str(e)}"}


def parse_playbook_to_json(playbook_str: str) -> List[Dict[str, Any]]:
    """Parse the playbook text file into structured JSON format for display."""
    bullets = []
    current_section = "OTHERS"

    # Pattern matches: [slug-00001] helpful=X harmful=Y :: content
    bullet_pattern = re.compile(r'\[([^\]]+)\]\s*helpful=(\d+)\s*harmful=(\d+)\s*::\s*(.*)')
    section_pattern = re.compile(r'^##?\s*(.*)')

    for line in playbook_str.split('\n'):
        line = line.strip()
        if not line:
            continue

        section_match = section_pattern.match(line)
        if section_match:
            current_section = section_match.group(1).strip()
            continue

        bullet_match = bullet_pattern.match(line)
        if bullet_match:
            bullet_id, helpful, harmful, content = bullet_match.groups()
            bullets.append({
                "id": bullet_id,
                "section": current_section,
                "helpful": int(helpful),
                "harmful": int(harmful),
                "content": content.strip()
            })

    return bullets

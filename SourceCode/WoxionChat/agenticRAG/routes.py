import os
import time
import logging
import hashlib
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from .agent import AgentState
from .memory import MemoryManager
from .db import get_embedding, find_similar_documents_hybrid_search, find_similar_documents_vector_search

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Pydantic request / response models ──────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = None

class SearchRequest(BaseModel):
    user_id: Optional[str] = None
    query: str = ""
    limit: int = 10
    search_type: str = "hybrid"  # "hybrid" | "vector"

class AdminSearchRequest(BaseModel):
    user_id: Optional[str] = None
    query: str
    limit: int = 10

class PreferencesRequest(BaseModel):
    pass  # arbitrary JSON; handled via Request body

class PerformanceTestRequest(BaseModel):
    search_query: str = "test performance query"
    user_id: str = "test_user"

class DebugToolsRequest(BaseModel):
    search_query: str = "test query"
    user_id: str = "test_user"


# ── Helpers ──────────────────────────────────────────────────────────────────

def generate_user_id(request: Request) -> str:
    user_agent = request.headers.get("user-agent", "")
    ip_address = request.client.host if request.client else "unknown"
    identifier_string = f"{ip_address}:{user_agent}"
    user_id = hashlib.md5(identifier_string.encode()).hexdigest()[:16]
    return f"user_{user_id}"


def _get_agent_graph():
    """Import lazily to avoid circular imports at module load time."""
    from . import get_agent_graph
    return get_agent_graph()


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/health")
def health_check():
    health_status = {"status": "ok", "message": "API is running"}
    try:
        memory_manager = MemoryManager.from_app_config()
        health_status["redis"] = memory_manager.health_check()
    except Exception as e:
        health_status["redis"] = {"status": "unhealthy", "error": str(e)}
        health_status["status"] = "degraded"
    return health_status


@router.post("/chat")
def chat(body: ChatRequest, request: Request):
    request_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    start_time = time.time()

    try:
        query = body.message
        if not query or not query.strip():
            raise HTTPException(status_code=400, detail="Empty query not allowed")

        user_id = body.user_id or generate_user_id(request)
        logger.info(f"Request {request_id}: Processing query for user {user_id}: '{query[:100]}...'")

        graph = _get_agent_graph()
        if graph is None:
            raise HTTPException(status_code=503, detail="Agent graph not initialised yet")

        graph_start_time = time.time()

        initial_state: AgentState = {
            "input": query,
            "messages": [HumanMessage(content=query)],
            "context": None,
            "user_id": user_id,
            "message_count": 0,
            "summarize_text": None,
            "need_summarize": False,
            "agent_output_message": None,
            "memory_manager": None,
            "short_term_memory": None,
            "user_preferences": None,
            "conversation_summaries": None,
        }

        config = {"recursion_limit": 30}
        final_state = None
        try:
            final_state = graph.invoke(initial_state, config=config)
        except Exception as graph_error:
            logger.error(f"Request {request_id}: Error invoking LangGraph: {graph_error}", exc_info=True)
            error_msg = f"Lỗi thực thi agent: {type(graph_error).__name__}. Xem log (ID: {request_id})."
            return JSONResponse(
                status_code=500,
                content={
                    "request_id": request_id,
                    "user_id": user_id,
                    "error": error_msg,
                    "success": False,
                    "timing": {"total_seconds": round(time.time() - start_time, 3)},
                },
            )

        graph_time = time.time() - graph_start_time
        logger.info(f"Request {request_id}: LangGraph processing took {graph_time:.3f}s")

        response_content = (
            f"Lỗi: Không thể xử lý yêu cầu, không tìm thấy phản hồi cuối cùng (ID: {request_id})."
        )
        final_ai_message = None
        if final_state and final_state.get("messages"):
            messages = final_state["messages"]
            last_message = messages[-1]
            if isinstance(last_message, ToolMessage) and "Validation successful" in last_message.content:
                if len(messages) > 1:
                    final_ai_message = messages[-2]
            elif isinstance(last_message, AIMessage) and not last_message.tool_calls:
                final_ai_message = last_message

            if isinstance(final_ai_message, AIMessage):
                response_content = final_ai_message.content
        else:
            logger.error(f"Request {request_id}: Final state is missing or has no messages. State: {final_state}")

        total_time = time.time() - start_time

        memory_stats = {}
        if final_state and final_state.get("memory_manager"):
            try:
                memory_stats = {
                    "short_term_messages": len(final_state.get("short_term_memory", [])),
                    "user_preferences_loaded": bool(final_state.get("user_preferences")),
                    "conversation_summaries": len(final_state.get("conversation_summaries", [])),
                }
            except Exception as e:
                logger.warning(f"Error collecting memory stats: {e}")

        return {
            "request_id": request_id,
            "user_id": user_id,
            "response": response_content,
            "success": final_ai_message is not None,
            "memory_stats": memory_stats,
            "timing": {
                "total_seconds": round(total_time, 3),
                "graph_processing_seconds": round(graph_time, 3),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"Request {request_id}: Unexpected error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "request_id": request_id,
                "error": f"An internal server error occurred: {type(e).__name__}. Check logs (ID: {request_id}).",
                "success": False,
                "timing": {"total_seconds": round(total_time, 3)},
            },
        )


@router.get("/memory/{user_id}")
def get_user_memory(user_id: str):
    try:
        memory_manager = MemoryManager.from_app_config()
        short_term_messages = memory_manager.load_short_term_memory(user_id)
        summaries = memory_manager.get_conversation_summaries(user_id, limit=10)
        preferences = memory_manager.get_user_preferences(user_id)
        memory_types = memory_manager.get_all_long_term_memory_types(user_id)

        return {
            "user_id": user_id,
            "short_term_memory": {
                "message_count": len(short_term_messages),
                "messages": [
                    {
                        "type": msg.__class__.__name__,
                        "content": msg.content[:100] + "..." if len(msg.content) > 100 else msg.content,
                    }
                    for msg in short_term_messages
                ],
            },
            "conversation_summaries": summaries,
            "user_preferences": preferences,
            "long_term_memory_types": memory_types,
            "success": True,
        }
    except Exception as e:
        logger.error(f"Error retrieving memory for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve memory: {str(e)}")


@router.delete("/memory/{user_id}")
def clear_user_memory(user_id: str, type: str = "all"):
    try:
        memory_manager = MemoryManager.from_app_config()
        if type == "all":
            memory_manager.clear_short_term_memory(user_id)
            for mem_type in memory_manager.get_all_long_term_memory_types(user_id):
                memory_manager.delete_long_term_memory(user_id, mem_type)
            return {"message": f"All memory cleared for user {user_id}", "success": True}
        elif type == "short_term":
            success = memory_manager.clear_short_term_memory(user_id)
            return {"message": f"Short-term memory cleared for user {user_id}", "success": success}
        else:
            success = memory_manager.delete_long_term_memory(user_id, type)
            return {"message": f"Memory type '{type}' cleared for user {user_id}", "success": success}
    except Exception as e:
        logger.error(f"Error clearing memory for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear memory: {str(e)}")


@router.post("/preferences/{user_id}")
async def save_user_preferences(user_id: str, request: Request):
    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail="No preferences data provided")
        memory_manager = MemoryManager.from_app_config()
        success = memory_manager.save_user_preferences(user_id, data)
        return {"message": f"Preferences saved for user {user_id}", "success": success}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving preferences for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save preferences: {str(e)}")


@router.post("/search/user-documents")
def search_user_documents(body: SearchRequest, request: Request):
    try:
        user_id = body.user_id or generate_user_id(request)
        search_query = body.query
        limit = body.limit
        search_type = body.search_type

        logger.info(f"Searching documents for user_id: {user_id}, query: '{search_query}'")

        results = []
        if search_type == "hybrid" and search_query:
            query_embedding = get_embedding(search_query)
            if query_embedding:
                results = find_similar_documents_hybrid_search(
                    query_vector=query_embedding,
                    search_query=search_query,
                    uploader_username=user_id,
                    limit=limit,
                )
        elif search_type == "vector" and search_query:
            query_embedding = get_embedding(search_query)
            if query_embedding:
                results = find_similar_documents_vector_search(
                    query_vector=query_embedding,
                    limit=limit,
                )
        else:
            from .db import get_db
            db = get_db()
            collection = db["user_documents_chunking"]
            results = list(
                collection.find(
                    {"uploader_username": user_id},
                    {"_id": 1, "content": 1, "uploader_username": 1},
                ).limit(limit)
            )

        return {
            "user_id": user_id,
            "search_query": search_query,
            "search_type": search_type,
            "results_count": len(results),
            "results": results,
            "success": True,
        }
    except Exception as e:
        logger.error(f"Error searching user documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to search documents: {str(e)}")


@router.post("/search/admin-documents")
def search_admin_documents(body: AdminSearchRequest, request: Request):
    try:
        user_id = body.user_id or generate_user_id(request)
        search_query = body.query
        limit = body.limit

        logger.info(f"Searching admin documents for user_id: {user_id}, query: '{search_query}'")

        query_embedding = get_embedding(search_query)
        if not query_embedding:
            raise HTTPException(status_code=500, detail="Failed to generate embedding for query")

        results = find_similar_documents_vector_search(query_vector=query_embedding, limit=limit)

        return {
            "user_id": user_id,
            "search_query": search_query,
            "results_count": len(results),
            "results": results,
            "success": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching admin documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to search admin documents: {str(e)}")


@router.post("/test/performance")
def test_performance(body: PerformanceTestRequest):
    try:
        from .tools import find_document_from_user, find_document_from_admin, find_documents_parallel

        search_query = body.search_query
        user_id = body.user_id
        results = {"query": search_query, "user_id": user_id, "timestamp": time.time()}

        # Sequential
        try:
            seq_start = time.time()
            user_start = time.time()
            user_docs = find_document_from_user.invoke({"search_query": search_query, "uploader_username": user_id})
            user_time = time.time() - user_start
            adm_start = time.time()
            admin_docs = find_document_from_admin.invoke({"search_query": search_query, "uploader_username": user_id})
            adm_time = time.time() - adm_start
            results["sequential"] = {
                "user_docs_count": len(user_docs),
                "admin_docs_count": len(admin_docs),
                "user_docs_time": round(user_time, 3),
                "admin_docs_time": round(adm_time, 3),
                "total_time": round(time.time() - seq_start, 3),
                "success": True,
            }
        except Exception as e:
            results["sequential"] = {"error": str(e), "success": False}

        # Parallel
        try:
            par_start = time.time()
            parallel_docs = find_documents_parallel.invoke({"search_query": search_query, "uploader_username": user_id})
            results["parallel"] = {
                "user_docs_count": len(parallel_docs.get("user_documents", [])),
                "admin_docs_count": len(parallel_docs.get("admin_documents", [])),
                "total_time": round(time.time() - par_start, 3),
                "success": True,
            }
        except Exception as e:
            results["parallel"] = {"error": str(e), "success": False}

        if results.get("sequential", {}).get("success") and results.get("parallel", {}).get("success"):
            s = results["sequential"]["total_time"]
            p = results["parallel"]["total_time"]
            improvement = ((s - p) / s) * 100 if s else 0
            results["comparison"] = {
                "improvement_percent": round(improvement, 1),
                "speedup_factor": round(s / p, 2) if p else 0,
                "time_saved_seconds": round(s - p, 3),
                "recommendation": "Parallel execution is faster" if improvement > 0 else "Sequential is faster",
            }

        return {"performance_test": results, "success": True}

    except Exception as e:
        logger.error(f"Error in performance test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debug/tools")
def debug_tools(body: DebugToolsRequest):
    try:
        from .tools import find_document_from_user, find_document_from_admin
        from .db import get_embedding

        search_query = body.search_query
        user_id = body.user_id
        results = {}

        try:
            embedding = get_embedding(search_query)
            results["embedding"] = {"success": True, "length": len(embedding) if embedding else 0}
        except Exception as e:
            results["embedding"] = {"error": str(e)}

        try:
            user_docs = find_document_from_user.invoke({"search_query": search_query, "uploader_username": user_id})
            results["user_documents"] = {"success": True, "count": len(user_docs), "documents": user_docs[:2]}
        except Exception as e:
            results["user_documents"] = {"error": str(e)}

        try:
            admin_docs = find_document_from_admin.invoke({"search_query": search_query, "uploader_username": user_id})
            results["admin_documents"] = {"success": True, "count": len(admin_docs), "documents": admin_docs[:2]}
        except Exception as e:
            results["admin_documents"] = {"error": str(e)}

        return {"query": search_query, "user_id": user_id, "results": results, "success": True}

    except Exception as e:
        logger.error(f"Error in debug_tools: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
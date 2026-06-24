import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings, load_environment
from .db import init_db
from .agent import create_agent_graph
from .models import ModelRegistry
from .routes import router
from .tools import (
    summarize_conversation,
    find_document_from_user,
    find_document_from_admin,
    find_documents_parallel,
    rerank_documents,
    direct_response,
    classify_query_type,
)
from langchain_openai import ChatOpenAI

# Module-level state shared across requests
_agent_graph = None


def get_agent_graph():  
    """Return the compiled LangGraph agent (set during startup lifespan)."""
    return _agent_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise all resources on startup; clean up on shutdown."""
    global _agent_graph

    load_environment()
    settings = get_settings()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)



    # ── MongoDB ──────────────────────────────────────────────────────────────
    class _FakeApp:
        """Minimal shim so init_db keeps its current signature."""
        config = {
            "MONGO_CONNECTION_STRING": __import__("os").environ.get("MONGO_CONNECTION_STRING"),
        }

    try:
        init_db(_FakeApp())
        logger.info("MongoDB initialised.")
    except Exception as e:
        logger.error(f"Database initialisation failed: {e}")
        raise

    # ── LangChain LLMs + ModelRegistry + Agent graph ─────────────────────────────────
    try:
        # 1. LLM Proxy (Qwen)—used for RAG answering and tool-calls
        gemini_llm = ChatOpenAI(
            model=settings.PROXY_MODEL,
            base_url=settings.PROXY_BASE_URL,
            api_key=settings.PROXY_API_KEY,
            temperature=0.3,
            max_tokens=None,
            timeout=180,
            max_retries=2,
        )
        logger.info(f"Proxy LLM initialised: {settings.PROXY_MODEL} @ {settings.PROXY_BASE_URL}")

        # 2. Local/self-hosted model via OpenAI-compatible endpoint
        local_llm = ChatOpenAI(
            model=settings.LOCAL_LLM_MODEL,
            base_url=settings.LOCAL_LLM_BASE_URL,
            api_key=settings.LOCAL_LLM_API_KEY,
            temperature=0.3,
            max_tokens=None,
            timeout=120,
            max_retries=2,
        )
        logger.info(f"Local LLM initialised: {settings.LOCAL_LLM_MODEL} @ {settings.LOCAL_LLM_BASE_URL}")

        model_registry = ModelRegistry(gemini=gemini_llm, local=local_llm)

        tools = [
            summarize_conversation,
            find_document_from_user,
            find_document_from_admin,
            find_documents_parallel,
            rerank_documents,
            direct_response,
            classify_query_type,
        ]
        # Chạy ở chế độ SINGLE-MODEL (chỉ dùng Proxy LLM) để demo theo yêu cầu
        _agent_graph = create_agent_graph(gemini_llm, tools)
        logger.info("LangGraph agent compiled (single-model: proxy).")
    except Exception as e:
        logger.error(f"Agent graph creation failed: {e}")
        raise

    yield  # ── Application runs ────────────────────────────────────────────

    # Cleanup (if needed)
    logger.info("Shutting down agenticRAG.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="WoxionChat agenticRAG",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()
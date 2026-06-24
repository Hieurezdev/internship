import os
from dotenv import load_dotenv
from functools import lru_cache
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    """Application settings — reads from environment variables."""
    GOOGLE_API_KEY: str = ""
    GOOGLE_CSE_ID: str = ""

    # Self-hosted / local LLM (OpenAI-compatible API)
    LOCAL_LLM_BASE_URL: str = "http://localhost:8080/v1"   # e.g. vLLM, Ollama, LM Studio
    LOCAL_LLM_MODEL: str = "local-model"                   # model name on the server
    LOCAL_LLM_API_KEY: str = "not-needed"                  # placeholder if server requires a key

    # LLM Proxy Configuration
    PROXY_API_KEY: str = "458d41f783134eb3715cc8f371af8351"
    PROXY_BASE_URL: str = "http://171.226.10.154:8080/v1"
    PROXY_MODEL: str = "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_DECODE_RESPONSES: bool = True

    # Memory TTLs
    SHORT_TERM_MEMORY_TTL: int = 3600       # 1 hour
    LONG_TERM_MEMORY_TTL: int = 2592000     # 30 days
    MAX_SHORT_TERM_MESSAGES: int = 20

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_environment():
    """Kept for backward compatibility."""
    load_dotenv()
"""
ModelRegistry — holds all LLM instances used by agenticRAG.

Available models
----------------
* gemini  : LLM Proxy (Qwen/Qwen3.5-35B-A3B-GPTQ-Int4) configured via ChatOpenAI
* local   : Any self-hosted model exposed through an OpenAI-compatible
            completion endpoint (vLLM, Ollama, LM Studio, etc.)
            Loaded via langchain_openai.ChatOpenAI with a custom base_url.
"""

from __future__ import annotations
from dataclasses import dataclass
from langchain_core.language_models import BaseChatModel


@dataclass
class ModelRegistry:
    """Container for all active LLM instances."""

    # Primary — LLM Proxy (tool-calling, RAG answering, historically named gemini for compatibility)
    gemini: BaseChatModel

    # Secondary — self-hosted OpenAI-compatible model (direct responses, chat)
    local: BaseChatModel
    
    def get(self, name: str) -> BaseChatModel:
        """Retrieve a model by name ('gemini' | 'local')."""
        if name == "gemini":
            return self.gemini
        if name == "local":
            return self.local
        raise KeyError(f"Unknown model name: '{name}'. Use 'gemini' or 'local'.")

import os
import asyncio
import re
from threading import Lock
import numpy as np
from typing import List, Dict, Any

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_client: genai.Client | None = None

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_OUTPUT_DIMENSIONALITY = 768
BGE_FALLBACK_MODEL = "BAAI/bge-m3"

_bge_model: Any | None = None
_bge_model_lock = Lock()


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get('google_api_key') or os.environ.get('GOOGLE_API_KEY')
        _client = genai.Client(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _prepare_embedding_text(text: str, task: str) -> str:
    text = text.strip()
    return f"task: {task} | query: {text}"


def _is_usage_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        token in message
        for token in (
            "resource exhausted",
            "quota",
            "rate limit",
            "usage limit",
            "too many requests",
            "429",
            "insufficient quota",
            "exceeded",
        )
    )


def _get_bge_model() -> Any:
    global _bge_model
    if _bge_model is None:
        with _bge_model_lock:
            if _bge_model is None:
                try:
                    from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]
                except ImportError as exc:
                    raise RuntimeError(
                        "Fallback BGE-M3 yêu cầu cài đặt package 'sentence-transformers'."
                    ) from exc

                _bge_model = SentenceTransformer(BGE_FALLBACK_MODEL)
    return _bge_model


async def _get_bge_embedding(text: str, task: str) -> list[float]:
    prepared_text = _prepare_embedding_text(text, task)

    def _encode() -> list[float]:
        embedding = _get_bge_model().encode(
            prepared_text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        # BGE-M3 outputs 1024 dimensions. Slice to match EMBEDDING_OUTPUT_DIMENSIONALITY (768)
        # to align shapes with Google AI embeddings and database schemas.
        return embedding[:EMBEDDING_OUTPUT_DIMENSIONALITY].tolist()

    try:
        return await asyncio.to_thread(_encode)
    except Exception as exc:
        raise Exception(f"Lỗi khi gọi BGE-M3 Embedding fallback: {exc}") from exc


async def get_embedding(
    text: str,
    task: str = "sentence similarity",
    model: str = EMBEDDING_MODEL,
) -> list[float]:
    try:
        prepared_text = _prepare_embedding_text(text, task)
        result = await asyncio.to_thread(
            _get_client().models.embed_content,
            model=model,
            contents=prepared_text,
            config=types.EmbedContentConfig(
                output_dimensionality=EMBEDDING_OUTPUT_DIMENSIONALITY,
            ),
        )
        return result.embeddings[0].values
    except Exception as e:
        if _is_usage_limit_error(e):
            return await _get_bge_embedding(text, task)
        raise Exception(f"Lỗi khi gọi Google AI Embedding API: {e}")


async def get_embeddings_batch(
    texts: List[str],
    task: str = "sentence similarity",
    model: str = EMBEDDING_MODEL,
    batch_size: int = 50
) -> List[List[float]]:
    """
    Get embeddings for a list of texts in batches to avoid 429 rate limit.
    Includes retry logic with exponential backoff and BGE-M3 fallback.
    """
    if not texts:
        return []

    client = _get_client()
    embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        prepared_batch = [_prepare_embedding_text(t, task) for t in batch]
        
        # Retry with exponential backoff if quota limit hit
        max_retries = 5
        base_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                result = await asyncio.to_thread(
                    client.models.embed_content,
                    model=model,
                    contents=prepared_batch,
                    config=types.EmbedContentConfig(
                        output_dimensionality=EMBEDDING_OUTPUT_DIMENSIONALITY,
                    ),
                )
                
                for emb in result.embeddings:
                    embeddings.append(emb.values)
                    
                break
            except Exception as e:
                if _is_usage_limit_error(e) and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                else:
                    # Try BGE fallback as a last resort
                    try:
                        fallback_embeddings = []
                        for t in batch:
                            emb = await _get_bge_embedding(t, task)
                            fallback_embeddings.append(emb)
                        embeddings.extend(fallback_embeddings)
                        break
                    except Exception as fallback_exc:
                        raise Exception(f"Lỗi khi gọi API Embedding (đã thử fallback BGE-M3): {e} | Fallback error: {fallback_exc}")
                        
    return embeddings


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Semantic chunker — same logic as SemanticChunker(breakpoint_threshold_type="percentile")
# ---------------------------------------------------------------------------

async def _semantic_chunk(
    sentences: list[str],
    breakpoint_percentile: float = 95.0,
) -> list[str]:
    """
    Split a flat list of sentences into semantically coherent chunks using
    the same percentile-based breakpoint logic as LangChain's SemanticChunker.

    1. Embed every sentence in batches.
    2. Compute cosine distance between consecutive sentence embeddings.
    3. Split wherever the distance exceeds the given percentile threshold.
    """
    if not sentences:
        return []

    # Embed all sentences using the batch function
    embeddings = await get_embeddings_batch(sentences, task="sentence similarity")

    # Consecutive cosine distances (higher distance → bigger semantic shift)
    distances: list[float] = []
    for i in range(len(embeddings) - 1):
        sim = _cosine_similarity(embeddings[i], embeddings[i + 1])
        distances.append(1.0 - sim)  # cosine distance

    if not distances:
        return [" ".join(sentences)]

    threshold = float(np.percentile(distances, breakpoint_percentile))

    # Build chunks
    chunks: list[str] = []
    current: list[str] = [sentences[0]]
    for i, dist in enumerate(distances):
        if dist >= threshold:
            chunks.append(" ".join(current))
            current = [sentences[i + 1]]
        else:
            current.append(sentences[i + 1])
    chunks.append(" ".join(current))

    return chunks


def _split_into_sentences(text: str) -> list[str]:
    """Lightweight sentence splitter for Vietnamese + English text."""
    # Split on ., ?, ! followed by whitespace or end-of-string
    raw = re.split(r'(?<=[.?!])\s+', text)
    return [s.strip() for s in raw if s.strip()]


# ---------------------------------------------------------------------------
# Markdown cleaning
# ---------------------------------------------------------------------------

def clean_markdown_text(markdown_text: str) -> str:
    """Dọn dẹp văn bản markdown thô."""
    PATTERNS_TO_REMOVE = [
        r"!\[img-\d+\.jpeg\]\(img-\d+\.jpeg\)",
        r"^##\s*(?:Trang|Page)?\s+\d+\s*(?:/\s*\d+)?\s*$",
        r"^\d+(?:\.\d+)*\s+.+?\s+\.{3,}\s+\d+$",
        r"^\|.+",
    ]
    COMBINED_PATTERNS = re.compile("|".join(PATTERNS_TO_REMOVE), re.MULTILINE | re.IGNORECASE)
    NEWLINE_CLEANUP_PATTERN = re.compile(r'\n{3,}')
    cleaned_text = COMBINED_PATTERNS.sub('', markdown_text)
    cleaned_text = NEWLINE_CLEANUP_PATTERN.sub('\n\n', cleaned_text)
    return cleaned_text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def create_chunks_from_markdown(
    markdown_text: str,
    source_file: str,
    breakpoint_percentile: float = 95.0,
) -> List[Dict[str, Any]]:

    cleaned_text = clean_markdown_text(markdown_text)
    if not cleaned_text:
        return []

    try:
        sentences = _split_into_sentences(cleaned_text)
        chunks_content_list = await _semantic_chunk(
            sentences,
            breakpoint_percentile=breakpoint_percentile,
        )

        # Embed each final chunk in batch
        embeddings_results = await get_embeddings_batch(chunks_content_list, task="clustering")

        processed_chunks = []
        for chunk_content, chunk_embedding in zip(chunks_content_list, embeddings_results):
            processed_chunks.append({
                "source_file": source_file,
                "content": chunk_content,
                "embedding": chunk_embedding,
            })

        return processed_chunks

    except Exception as e:
        raise Exception(f"Lỗi khi xử lý chunking cho tài liệu {source_file}: {e}")
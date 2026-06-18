import os
import asyncio
import re
from threading import Lock
from typing import List, Dict, Any
import numpy as np
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_OUTPUT_DIMENSIONALITY = 1024

_bge_model: Any | None = None
_bge_model_lock = Lock()


def _get_bge_model() -> Any:
    global _bge_model
    if _bge_model is None:
        with _bge_model_lock:
            if _bge_model is None:
                try:
                    from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]
                except ImportError as exc:
                    raise RuntimeError(
                        "BGE-M3 yêu cầu cài đặt package 'sentence-transformers'."
                    ) from exc
                import torch
                # Utilize MPS on macOS for faster encoding if available
                device = "mps" if torch.backends.mps.is_available() else "cpu"
                _bge_model = SentenceTransformer(EMBEDDING_MODEL, device=device)
    return _bge_model


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _prepare_embedding_text(text: str, task: str) -> str:
    text = text.strip()
    return f"task: {task} | query: {text}"


async def get_embedding(
    text: str,
    task: str = "sentence similarity",
    model: str = EMBEDDING_MODEL,
) -> list[float]:
    prepared_text = _prepare_embedding_text(text, task)

    def _encode() -> list[float]:
        embedding = _get_bge_model().encode(
            prepared_text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embedding.tolist()

    try:
        return await asyncio.to_thread(_encode)
    except Exception as exc:
        raise Exception(f"Lỗi khi gọi BGE-M3 Embedding: {exc}") from exc


async def get_embeddings_batch(
    texts: List[str],
    task: str = "sentence similarity",
    model: str = EMBEDDING_MODEL,
    batch_size: int = 50
) -> List[List[float]]:
    """
    Get embeddings for a list of texts in batches using local BGE-M3 model.
    """
    if not texts:
        return []

    embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        prepared_batch = [_prepare_embedding_text(t, task) for t in batch]
        
        def _encode_batch() -> List[List[float]]:
            emb = _get_bge_model().encode(
                prepared_batch,
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=len(prepared_batch)
            )
            return emb.tolist()
            
        try:
            batch_emb = await asyncio.to_thread(_encode_batch)
            embeddings.extend(batch_emb)
        except Exception as exc:
            raise Exception(f"Lỗi khi gọi BGE-M3 Embedding Batch: {exc}") from exc
            
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
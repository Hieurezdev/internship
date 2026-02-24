import os
import asyncio
import re
import numpy as np
from typing import List, Dict, Any

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get('google_api_key') or os.environ.get('GOOGLE_API_KEY')
        _client = genai.Client(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

async def get_embedding(
    text: str,
    model: str = 'models/gemini-embedding-exp-03-07',
) -> list[float]:
    try:
        result = await asyncio.to_thread(
            _get_client().models.embed_content,
            model=model,
            contents=text,
            config=types.EmbedContentConfig(task_type='SEMANTIC_SIMILARITY'),
        )
        return result.embeddings[0].values
    except Exception as e:
        raise Exception(f"Lỗi khi gọi Google AI Embedding API: {e}")


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

    1. Embed every sentence.
    2. Compute cosine distance between consecutive sentence embeddings.
    3. Split wherever the distance exceeds the given percentile threshold.
    """
    if not sentences:
        return []

    # Embed all sentences concurrently
    embedding_tasks = [get_embedding(s) for s in sentences]
    embeddings = await asyncio.gather(*embedding_tasks)

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

        # Embed each final chunk concurrently
        embedding_tasks = [get_embedding(chunk) for chunk in chunks_content_list]
        embeddings_results = await asyncio.gather(*embedding_tasks)

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
"""Local RAG pipeline: embed, chunk, ingest, semantic search, document CRUD.

Embeddings come from Gemini (gemini-embedding-001). Chunk vectors are stored
as float32 BLOBs in SQLite and searched by brute-force cosine similarity in
NumPy — simple, dependency-light, and fast enough for a single business's
knowledge base. Swap in sqlite-vec / pgvector if the corpus grows very large.
"""
import io
import logging
import threading
import time

import numpy as np
from google import genai
from google.genai import types

from config import EMBEDDING_DIM, EMBEDDING_MODEL, GEMINI_API_KEY
from db import get_conn, write_lock

log = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)

# Chunking parameters (characters).
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 150

# Gemini embed_content accepts batches; keep them modest to stay under limits.
_EMBED_BATCH = 100

# Cached vector matrix for search. Invalidated on any ingest/delete.
_cache_lock = threading.Lock()
_cache: dict | None = None  # {"ids", "matrix", "texts", "sources"}


# ── Embedding ────────────────────────────────────────────────────────────────

def _embed(texts: list[str], task_type: str) -> np.ndarray:
    """Embed a list of texts; returns an (n, EMBEDDING_DIM) L2-normalized matrix."""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i : i + _EMBED_BATCH]
        resp = _client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=batch,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
        vectors.extend(e.values for e in resp.embeddings)

    arr = np.asarray(vectors, dtype=np.float32)
    # gemini-embedding-001 only returns pre-normalized vectors at 3072 dims;
    # at other output dimensions we must normalize ourselves.
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def embed_query(query: str) -> np.ndarray:
    return _embed([query], task_type="RETRIEVAL_QUERY")[0]


# ── Document parsing ─────────────────────────────────────────────────────────

def extract_text(filename: str, content_type: str, data: bytes) -> str:
    """Extract plain text from an uploaded file based on extension/content type."""
    name = filename.lower()
    if name.endswith(".pdf") or content_type == "application/pdf":
        return _extract_pdf(data)
    if name.endswith(".docx") or "wordprocessingml" in content_type:
        return _extract_docx(data)
    # txt / md / csv / anything else decodable
    return data.decode("utf-8", errors="ignore")


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks on paragraph/sentence boundaries."""
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= _CHUNK_SIZE:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current:
            chunks.append(current)
        if len(para) <= _CHUNK_SIZE:
            current = para
        else:
            # Paragraph itself too long — hard-split it.
            chunks.extend(_split_long(para))
            current = ""
    if current:
        chunks.append(current)

    return _add_overlap(chunks)


def _split_long(para: str) -> list[str]:
    out = []
    for i in range(0, len(para), _CHUNK_SIZE):
        out.append(para[i : i + _CHUNK_SIZE])
    return out


def _add_overlap(chunks: list[str]) -> list[str]:
    if _CHUNK_OVERLAP <= 0 or len(chunks) < 2:
        return chunks
    overlapped = [chunks[0]]
    for prev, cur in zip(chunks, chunks[1:]):
        tail = prev[-_CHUNK_OVERLAP:]
        overlapped.append(f"{tail} {cur}")
    return overlapped


# ── Ingest ───────────────────────────────────────────────────────────────────

def ingest(filename: str, content_type: str, data: bytes) -> dict:
    """Parse, chunk, embed, and store an uploaded document. Returns a summary."""
    text = extract_text(filename, content_type, data)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("No extractable text found in the file.")

    matrix = _embed(chunks, task_type="RETRIEVAL_DOCUMENT")
    conn = get_conn()
    with write_lock:
        cur = conn.execute(
            "INSERT INTO documents (filename, content_type, size_bytes, num_chunks, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (filename, content_type, len(data), len(chunks), time.time()),
        )
        doc_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO chunks (document_id, chunk_index, text, embedding) VALUES (?, ?, ?, ?)",
            [
                (doc_id, i, chunk, matrix[i].astype(np.float32).tobytes())
                for i, chunk in enumerate(chunks)
            ],
        )
        conn.commit()

    _invalidate_cache()
    log.info("Ingested %s: %d chunks (doc_id=%s)", filename, len(chunks), doc_id)
    return {"document_id": doc_id, "filename": filename, "num_chunks": len(chunks)}


# ── Search ───────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    global _cache
    with _cache_lock:
        if _cache is not None:
            return _cache
        rows = get_conn().execute(
            "SELECT c.id, c.text, c.embedding, d.filename "
            "FROM chunks c JOIN documents d ON d.id = c.document_id"
        ).fetchall()
        if rows:
            matrix = np.vstack(
                [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]
            )
        else:
            matrix = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        _cache = {
            "ids": [r["id"] for r in rows],
            "matrix": matrix,
            "texts": [r["text"] for r in rows],
            "sources": [r["filename"] for r in rows],
        }
        return _cache


def _invalidate_cache():
    global _cache
    with _cache_lock:
        _cache = None


def search(query: str, k: int = 5, min_score: float = 0.25) -> list[dict]:
    """Return up to k chunks most similar to the query, above min_score."""
    cache = _load_cache()
    if cache["matrix"].shape[0] == 0:
        return []

    q = embed_query(query)
    scores = cache["matrix"] @ q  # cosine (vectors are normalized)
    top = np.argsort(scores)[::-1][:k]
    results = []
    for idx in top:
        score = float(scores[idx])
        if score < min_score:
            continue
        results.append(
            {
                "text": cache["texts"][idx],
                "source": cache["sources"][idx],
                "score": score,
            }
        )
    return results


def search_as_context(query: str, k: int = 5) -> str:
    """Search and format results as a context string for the model."""
    hits = search(query, k=k)
    if not hits:
        return "No relevant information found in the knowledge base."
    blocks = [f"[Source: {h['source']}]\n{h['text']}" for h in hits]
    return "\n\n---\n\n".join(blocks)


# ── Document management ──────────────────────────────────────────────────────

def list_documents() -> list[dict]:
    rows = get_conn().execute(
        "SELECT id, filename, content_type, size_bytes, num_chunks, uploaded_at "
        "FROM documents ORDER BY uploaded_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_document(doc_id: int) -> bool:
    conn = get_conn()
    with write_lock:
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
    _invalidate_cache()
    return cur.rowcount > 0

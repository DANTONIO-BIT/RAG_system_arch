"""
RAG retrieval layer.

Three query modes:
  query_public   → searches "public" collection only (safe to forward to cloud)
  query_private  → searches "private" collection only (never leaves local)
  query_full     → searches both, merges results by relevance score

Every result carries _source metadata so the caller knows its provenance.
"""
from __future__ import annotations

import logging
import yaml
from pathlib import Path

import chromadb

logger = logging.getLogger(__name__)

AGENT_ROOT  = Path(__file__).parent.parent.parent
CONFIG_PATH = AGENT_ROOT / "config.yaml"
_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def _get_client() -> chromadb.PersistentClient:
    cfg = _load_config()
    persist_path = AGENT_ROOT / cfg["chroma"]["persist_directory"]
    persist_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_path))


def _query_collection(collection_name: str, text: str, n_results: int) -> list[dict]:
    """Query a single ChromaDB collection. Returns [] if collection is empty."""
    from embeddings import generate_embedding

    client = _get_client()
    try:
        col = client.get_collection(collection_name)
    except Exception:
        logger.debug("Collection '%s' does not exist yet — skipping.", collection_name)
        return []

    count = col.count()
    if count == 0:
        return []

    n = min(n_results, count)
    embedding = generate_embedding(text)

    results = col.query(
        query_embeddings=[embedding],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )

    hits: list[dict] = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "text": doc,
            "metadata": meta,
            "distance": dist,
            "score": max(0.0, round(1.0 - dist, 4)),
            "_source": meta.get("_source", collection_name),
        })
    return hits


def query_public(text: str, n_results: int = 5) -> list[dict]:
    """
    Query the public collection only.
    Results are safe to include as context in cloud LLM calls.
    """
    return _query_collection("public", text, n_results)


def query_private(text: str, n_results: int = 5) -> list[dict]:
    """
    Query the private collection only.
    Results must NEVER be forwarded to external services without explicit user confirmation.
    """
    return _query_collection("private", text, n_results)


def query_full(text: str, n_results: int = 5) -> list[dict]:
    """
    Query both collections and merge by score (best first).
    Each result includes _source: "public" | "private".
    """
    pub  = query_public(text, n_results)
    priv = query_private(text, n_results)
    merged = sorted(pub + priv, key=lambda r: r["score"], reverse=True)
    return merged[:n_results]


def compute_confidence(results: list[dict]) -> float:
    """
    Rank-weighted confidence score from 0 to 1.
    Top result has weight 1.0, second 0.5, third 0.33, etc.
    Returns 0.0 if no results.
    """
    if not results:
        return 0.0
    weights = [1 / (i + 1) for i in range(len(results))]
    scores  = [r["score"] for r in results]
    return round(
        sum(w * s for w, s in zip(weights, scores)) / sum(weights),
        4,
    )


def format_context(results: list[dict]) -> str:
    """Format retrieved chunks as a numbered, prompt-ready context block."""
    if not results:
        return "[No relevant context found in knowledge base.]"

    lines = ["=== Retrieved Context ===\n"]
    for i, r in enumerate(results, 1):
        meta  = r.get("metadata", {})
        fname = meta.get("filename", "unknown")
        src   = r.get("_source", "?")
        score = r.get("score", 0.0)
        cidx  = meta.get("chunk_index", "?")
        proj  = meta.get("project_id", "")
        proj_tag = f" · project: {proj}" if proj and proj not in ("shared", "untagged") else ""
        lines.append(f"[{i}] {fname}  (source: {src}{proj_tag}, chunk #{cidx}, score: {score:.3f})")
        lines.append(r["text"])
        lines.append("")

    return "\n".join(lines)

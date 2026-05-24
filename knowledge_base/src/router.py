"""
LLM routing layer.

Confidence thresholds (from config.yaml) determine where a query goes:
  High  (>= confidence_high) → RAG context only, no LLM
  Mid   (between thresholds) → local LLM + RAG context
  Low   (<  confidence_low)  → cloud LLM (public context only)

Private context NEVER travels to cloud without explicit user confirmation.
"""
from __future__ import annotations

import json
import logging
import os
import re
import yaml
from datetime import datetime
from pathlib import Path

import httpx

from .query import query_full, compute_confidence, format_context

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


class PrivacyError(Exception):
    """Raised when private data would be sent to an external service without confirmation."""


def route(query: str, confirmed_cloud: bool = False, silent: bool = False) -> dict:
    """
    Full pipeline: retrieve → score → route → respond.

    Returns:
        {
          "response": str,
          "confidence": float,
          "llm_used": "rag_only" | "local" | "cloud",
          "context_sources": list[str],
          "wiki_written": str | None
        }
    """
    cfg        = _load_config()
    thresholds = cfg["routing"]
    wiki_cfg   = cfg["wiki"]

    results    = query_full(query, n_results=5)
    confidence = compute_confidence(results)
    context_sources = list({r["_source"] for r in results})
    has_private     = "private" in context_sources

    logger.info(
        "Query confidence=%.3f | sources=%s | hits=%d",
        confidence, context_sources, len(results),
    )

    wiki_written: str | None = None

    if confidence >= thresholds["confidence_high"]:
        response = format_context(results)
        llm_used = "rag_only"

    elif confidence >= thresholds["confidence_low"]:
        response = _call_local_llm(query, results, silent=silent)
        llm_used = "local"

    else:
        public_results = [r for r in results if r["_source"] == "public"]

        if has_private and not confirmed_cloud:
            raise PrivacyError(
                "Private context found in results. Call route(query, confirmed_cloud=True) "
                "after obtaining explicit user confirmation, or use query_public() "
                "to restrict to public knowledge only."
            )

        context_for_cloud = (
            public_results if (has_private and not confirmed_cloud) else results
        )
        response = _call_cloud_llm(query, context_for_cloud)
        llm_used = "cloud"

    if confidence >= wiki_cfg["quality_threshold"] and llm_used in ("local", "cloud"):
        wiki_written = _write_wiki_node(query, response, results, confidence)

    return {
        "response":        response,
        "confidence":      confidence,
        "llm_used":        llm_used,
        "context_sources": context_sources,
        "wiki_written":    wiki_written,
    }


def _build_prompt(query: str, context: list[dict]) -> str:
    context_block = format_context(context)
    return (
        "You are a scientific research assistant. Answer questions precisely, "
        "cite sources when available, and flag uncertainty clearly.\n\n"
        f"Context from knowledge base:\n{context_block}\n\n"
        f"Question: {query}\n\n"
        "Provide a concise, accurate answer based on the context. "
        "If the context is insufficient, say so explicitly."
    )


def _call_local_llm(prompt: str, context: list[dict], silent: bool = False) -> str:
    cfg       = _load_config()
    local_cfg = cfg["llm"]["local"]
    url       = f"{local_cfg['base_url']}/api/generate"

    payload = {
        "model":  local_cfg["model"],
        "prompt": _build_prompt(prompt, context),
        "stream": True,
        "options": {
            "temperature": local_cfg.get("temperature", 0.2),
            "num_predict": local_cfg.get("num_predict", 4096),
        },
    }

    tokens: list[str] = []
    thinking_shown = False
    try:
        with httpx.stream(
            "POST", url, json=payload,
            timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
        ) as resp:
            resp.raise_for_status()
            if not silent:
                print()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError:
                    continue
                if not silent and not thinking_shown and chunk.get("thinking"):
                    print("[thinking…]", flush=True)
                    thinking_shown = True
                token = chunk.get("response", "")
                if token:
                    if not silent:
                        print(token, end="", flush=True)
                    tokens.append(token)
                if chunk.get("done", False):
                    break
            if not silent:
                print()
    except httpx.ConnectError:
        raise RuntimeError(
            f"Ollama no disponible en {local_cfg['base_url']}. "
            f"Ejecuta: ollama serve && ollama run {local_cfg['model']}"
        )

    return "".join(tokens).strip()


def _call_cloud_llm(prompt: str, context: list[dict]) -> str:
    """Call cloud LLM via OpenRouter. Raises PrivacyError if private chunks sneak in."""
    if any(r.get("_source") == "private" for r in context):
        raise PrivacyError(
            "Private context must not reach cloud LLM without explicit confirmation."
        )

    cfg       = _load_config()
    cloud_cfg = cfg["llm"]["cloud"]
    api_key   = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY not set in environment.")

    try:
        resp = httpx.post(
            f"{cloud_cfg['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       cloud_cfg["model"],
                "messages":    [{"role": "user", "content": _build_prompt(prompt, context)}],
                "max_tokens":  2048,
                "temperature": cloud_cfg.get("temperature", 0.3),
            },
            timeout=90.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Cloud error {e.response.status_code}: {e.response.text[:300]}")


def _write_wiki_node(
    query: str,
    response: str,
    context: list[dict],
    confidence: float,
) -> str | None:
    """Write a structured wiki node to wiki/auto/. Returns path or None."""
    cfg      = _load_config()
    wiki_dir = AGENT_ROOT / cfg["wiki"]["output_dir"]
    wiki_dir.mkdir(parents=True, exist_ok=True)

    max_len   = cfg["wiki"].get("max_node_length", 2000)
    truncated = response[:max_len] + ("…" if len(response) > max_len else "")

    slug_words = re.sub(r"[^\w\s]", "", query.lower()).split()[:6]
    slug       = "_".join(slug_words) or "untitled"
    dest       = wiki_dir / f"{slug}.md"

    sources     = list({r["metadata"].get("filename", "?") for r in context})
    has_private = any(r.get("_source") == "private" for r in context)
    source_tag  = "private+public" if has_private else "public"
    timestamp   = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    dest.write_text(
        f"# {query}\n\n"
        f"_Auto-generated · {timestamp} · confidence: {confidence:.3f} · source: {source_tag}_\n\n"
        f"## Summary\n\n{truncated}\n\n"
        f"## Sources\n\n"
        + "\n".join(f"- {s}" for s in sorted(sources))
        + "\n",
        encoding="utf-8",
    )
    logger.info("Wiki node written: %s", dest)
    return str(dest)


# Legacy helpers for get_collection_for_topic — used by run_ingest
def get_collection_for_topic(topic: str) -> str:
    """Kept for backward compatibility. All new ingests route by path."""
    return "public"


def all_collections() -> list[str]:
    return ["public", "private"]

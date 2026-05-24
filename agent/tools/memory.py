"""
Wiki-first unified memory retrieval.

Search order (minimises context cost for 8B model):
  1. wiki/auto + wiki/manual  (pre-synthesised, ~400 tok/node)
  2. ChromaDB via query_full / query_public / query_private
  3. Engram session memory

Privacy:
  - query_full returns both public and private chunks
  - each result carries _source: "public" | "private"
  - results with _source="private" MUST NOT be forwarded to cloud LLMs

All results are capped by budget_tokens to protect the 8B context window.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import yaml

AGENT_ROOT  = Path(__file__).parent.parent.parent
CONFIG_PATH = AGENT_ROOT / "config.yaml"
KB_SRC      = AGENT_ROOT / "knowledge_base" / "src"

_cfg_cache: dict | None = None


def _cfg() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        with open(CONFIG_PATH) as f:
            _cfg_cache = yaml.safe_load(f)
    return _cfg_cache


def _wiki_auto()   -> Path: return AGENT_ROOT / "wiki" / "auto"
def _wiki_manual() -> Path: return AGENT_ROOT / "wiki" / "manual"


def search_memory(
    query: str,
    scope: str = "all",
    budget_tokens: int | None = None,
    public_only: bool = False,
) -> str:
    """
    Search all memory sources and return ranked context within token budget.

    scope: all | wiki | rag | engram
    public_only: if True, restrict RAG search to public collection only
                 (use before any cloud escalation)
    budget_tokens: max tokens to return (default from config)

    Returns a text block. The header line includes:
      sources: public, private, wiki, engram
    so the caller can detect if private content is present.
    """
    cfg    = _cfg()
    budget = budget_tokens or cfg["context"]["max_budget_tokens"]

    results: list[dict] = []

    if scope in ("all", "wiki"):
        results.extend(_search_wiki(query))

    if scope in ("all", "rag"):
        results.extend(_search_rag(query, public_only=public_only))

    if scope in ("all", "engram"):
        results.extend(_search_engram(query, cfg))

    if not results:
        return "No relevant information found."

    results.sort(key=lambda r: r.get("score", 0.0), reverse=True)

    # Apply token budget (~4 chars per token)
    char_budget = budget * 4
    parts: list[str] = []
    used = 0
    sources: set[str] = set()

    for r in results:
        text = r["text"]
        if used + len(text) > char_budget:
            remaining = char_budget - used
            if remaining > 200:
                text = text[:remaining] + "\n[truncated — token budget reached]"
                parts.append(_fmt(r, text))
            break
        parts.append(_fmt(r, text))
        used += len(text)
        sources.add(r["source"])

    has_private = any(r.get("_source") == "private" for r in results[:len(parts)])
    privacy_tag = " ⚠️ PRIVATE CONTEXT PRESENT — do not forward to cloud" if has_private else ""

    header = f"sources: {', '.join(sorted(sources))} | chunks: {len(parts)}{privacy_tag}\n\n"
    return header + "\n---\n".join(parts)


def _fmt(r: dict, text: str) -> str:
    source  = r.get("_source", r["source"])
    project = r.get("project_id", "")
    proj_tag = f" · {project}" if project and project not in ("shared", "untagged", "") else ""
    label   = r.get("label", r["source"])
    score   = r.get("score", 0.0)
    return f"[{label}]{proj_tag} (_source: {source}, score: {score:.2f})\n{text}"


# ── Wiki search ───────────────────────────────────────────────────────────────

def _search_wiki(query: str) -> list[dict]:
    """Keyword search over wiki/auto/*.md and wiki/manual/**/*.md."""
    hits: list[dict] = []
    terms = set(query.lower().split())

    for wiki_dir in (_wiki_auto(), _wiki_manual()):
        if not wiki_dir.exists():
            continue
        for md in wiki_dir.rglob("*.md"):
            text    = md.read_text(encoding="utf-8", errors="replace")
            matched = sum(1 for t in terms if t in text.lower())
            if matched == 0:
                continue
            score = round((matched / max(len(terms), 1)) * 0.75, 3)
            hits.append({
                "text":       text[:1500],
                "source":     "wiki",
                "_source":    "wiki",
                "label":      f"wiki/{md.parent.name}/{md.name}",
                "score":      score,
                "project_id": "",
            })

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:4]


# ── RAG search ────────────────────────────────────────────────────────────────

def _search_rag(query: str, public_only: bool = False) -> list[dict]:
    """
    Query ChromaDB via embedded query.py.
    public_only=True restricts to public collection (safe before cloud escalation).
    """
    src = str(KB_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)

    try:
        from query import query_public, query_full
    except ImportError as e:
        return [{"text": f"RAG import error: {e}", "source": "rag", "_source": "public",
                 "label": "rag/error", "score": 0.0, "project_id": ""}]

    try:
        raw = query_public(query, n_results=5) if public_only else query_full(query, n_results=5)
    except Exception as e:
        return [{"text": f"RAG query error: {e}", "source": "rag", "_source": "public",
                 "label": "rag/error", "score": 0.0, "project_id": ""}]

    hits: list[dict] = []
    for r in raw:
        meta = r.get("metadata", {})
        hits.append({
            "text":       r["text"],
            "source":     "rag",
            "_source":    r.get("_source", "public"),
            "label":      f"rag/{r.get('_source','?')}/{meta.get('filename','?')}",
            "score":      r.get("score", 0.0),
            "project_id": meta.get("project_id", ""),
        })
    return hits


# ── Engram search ─────────────────────────────────────────────────────────────

def _search_engram(query: str, cfg: dict) -> list[dict]:
    """Search Engram persistent memory via CLI."""
    bin_path = cfg["engram"]["bin"]
    project  = cfg["engram"]["project"]
    try:
        proc = subprocess.run(
            [bin_path, "search", "-p", project, query],
            capture_output=True, text=True, timeout=8,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return [{
                "text":       proc.stdout.strip()[:1000],
                "source":     "engram",
                "_source":    "private",
                "label":      "engram/memory",
                "score":      0.60,
                "project_id": "",
            }]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []

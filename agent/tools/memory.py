"""
Wiki-first unified memory retrieval.

Search order (minimizes context cost for 8B model):
  1. wiki/auto + wiki/manual  (pre-synthesized, ~400 tok/node)
  2. ChromaDB via existing knowledge_base router + vector_store
  3. Engram session memory

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
KB_CHROMA   = AGENT_ROOT / "knowledge_base" / "data" / "chroma_db"
_cfg_cache: dict | None = None


def _cfg() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        with open(CONFIG_PATH) as f:
            _cfg_cache = yaml.safe_load(f)
    return _cfg_cache


def _wiki_auto()  -> Path: return AGENT_ROOT / "wiki" / "auto"
def _wiki_manual() -> Path: return AGENT_ROOT / "wiki" / "manual"


def search_memory(query: str, scope: str = "all", budget_tokens: int | None = None) -> str:
    """
    Search all memory sources and return ranked context within token budget.

    scope: all | wiki | rag | engram
    budget_tokens: max tokens to return (default from config). Caps output to
                   protect the 8B context window.
    """
    cfg = _cfg()
    budget = budget_tokens or cfg["context"]["max_budget_tokens"]

    results: list[dict] = []

    if scope in ("all", "wiki"):
        results.extend(_search_wiki(query, cfg))

    if scope in ("all", "rag"):
        results.extend(_search_rag(query, cfg))

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

    header = f"sources: {', '.join(sorted(sources))} | chunks: {len(parts)}\n\n"
    return header + "\n---\n".join(parts)


def _fmt(r: dict, text: str) -> str:
    return f"[{r.get('label', r['source'])}] (score: {r.get('score', 0.0):.2f})\n{text}"


# ── Wiki search ───────────────────────────────────────────────────────────────

def _search_wiki(query: str, cfg: dict) -> list[dict]:
    """Keyword search over wiki/auto/*.md and wiki/manual/*.md."""
    hits: list[dict] = []
    terms = set(query.lower().split())

    for wiki_dir in (_wiki_auto(), _wiki_manual()):
        if not wiki_dir.exists():
            continue
        for md in wiki_dir.glob("*.md"):
            text = md.read_text(encoding="utf-8", errors="replace")
            matched = sum(1 for t in terms if t in text.lower())
            if matched == 0:
                continue
            score = round((matched / max(len(terms), 1)) * 0.75, 3)
            hits.append({
                "text": text[:1500],
                "source": "wiki",
                "label": f"wiki/{md.parent.name}/{md.name}",
                "score": score,
            })

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:4]


# ── RAG search ────────────────────────────────────────────────────────────────

def _search_rag(query: str, cfg: dict) -> list[dict]:
    """Route query to the right ChromaDB collections via embedded knowledge_base."""
    src = str(KB_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)

    try:
        from router import route_query
        from vector_store import get_vector_store
    except ImportError as e:
        return [{"text": f"RAG import error: {e}", "source": "rag", "label": "rag/error", "score": 0.0}]

    chroma_db = str(KB_CHROMA)
    collections = route_query(query)
    hits: list[dict] = []

    for coll in collections:
        try:
            vs = get_vector_store(collection_name=coll, persist_dir=chroma_db)
            if vs.collection.count() == 0:
                continue
            res = vs.query(query, n_results=3)
            docs = (res.get("documents") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            for i, doc in enumerate(docs):
                dist = dists[i] if i < len(dists) else 0.5
                score = max(0.0, round(1.0 - dist, 3))
                meta = metas[i] if i < len(metas) else {}
                hits.append({
                    "text": doc,
                    "source": "rag",
                    "label": f"rag/{coll}/{meta.get('filename', '?')}",
                    "score": score,
                })
        except Exception as e:
            hits.append({
                "text": f"Collection {coll} error: {e}",
                "source": "rag",
                "label": f"rag/{coll}/error",
                "score": 0.0,
            })

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:5]


# ── Engram search ─────────────────────────────────────────────────────────────

def _search_engram(query: str, cfg: dict) -> list[dict]:
    """Search Engram persistent memory via CLI."""
    bin_path = cfg["engram"]["bin"]
    project = cfg["engram"]["project"]
    try:
        proc = subprocess.run(
            [bin_path, "search", "-p", project, query],
            capture_output=True, text=True, timeout=8,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return [{
                "text": proc.stdout.strip()[:1000],
                "source": "engram",
                "label": "engram/memory",
                "score": 0.60,
            }]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []

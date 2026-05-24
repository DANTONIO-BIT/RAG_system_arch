"""
Session Context Builder — pre-loads wiki nodes into the system prompt.

An 8B model with 4K usable context cannot afford a RAG call on every turn.
This module injects pre-synthesized wiki knowledge *before* the first turn,
so the model starts sessions with domain baseline — no tool call required.

Usage:
    system_prompt = build_system_prompt(topic_hint="transformacion digital")
"""
from __future__ import annotations

from pathlib import Path
import yaml

AGENT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = AGENT_ROOT / "config.yaml"
PROMPT_PATH = AGENT_ROOT / "agent" / "prompts" / "system.md"
_cfg_cache: dict | None = None


def _cfg() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        with open(CONFIG_PATH) as f:
            _cfg_cache = yaml.safe_load(f)
    return _cfg_cache


def build_system_prompt(topic_hint: str = "") -> str:
    """
    Return a system prompt with relevant wiki nodes pre-injected.

    topic_hint: free-text clue about the session topic.
                If empty, picks the most recently modified nodes.
    """
    base_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    nodes = _select_wiki_nodes(topic_hint)

    if not nodes:
        return base_prompt

    context_block = "\n\n## Pre-loaded knowledge (session context)\n\n"
    for node_text, label in nodes:
        context_block += f"### {label}\n{node_text}\n\n"

    return base_prompt + context_block


def _select_wiki_nodes(hint: str) -> list[tuple[str, str]]:
    """Select top-N wiki nodes relevant to hint (or most-recent if no hint)."""
    cfg = _cfg()
    n = cfg["wiki"]["session_preload_nodes"]
    terms = set(hint.lower().split()) if hint.strip() else set()

    candidates: list[tuple[float, Path]] = []

    for wiki_dir in (AGENT_ROOT / "wiki" / "auto", AGENT_ROOT / "wiki" / "manual"):
        if not wiki_dir.exists():
            continue
        for md in wiki_dir.rglob("*.md"):
            if terms:
                text = md.read_text(encoding="utf-8", errors="replace").lower()
                score = sum(1 for t in terms if t in text) / max(len(terms), 1)
            else:
                score = md.stat().st_mtime  # most-recent fallback
            candidates.append((score, md))

    candidates.sort(key=lambda x: x[0], reverse=True)
    selected = candidates[:n]

    results: list[tuple[str, str]] = []
    for _, md in selected:
        text = md.read_text(encoding="utf-8", errors="replace")
        label = f"{md.parent.name}/{md.name}"
        results.append((text[:800], label))

    return results

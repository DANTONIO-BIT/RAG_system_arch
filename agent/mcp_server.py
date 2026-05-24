#!/usr/bin/env python3
"""
Research Agent — MCP Server

Exposes RAG + wiki + Engram as native MCP tools.
Registered globally in ~/.claude/settings.json so Claude Code picks it up
from ANY working directory — not just this project folder.

Tools:
  search_memory   — wiki-first knowledge retrieval
  save_insight    — persist synthesis to wiki + Engram
  save_feedback   — persist evaluator feedback
  agent_status    — knowledge base stats
  ingest_files    — add files to the knowledge base

Do NOT run interactively — stdout is reserved for JSON-RPC.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(AGENT_ROOT))
sys.path.insert(0, str(AGENT_ROOT / "agent"))

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "Research Agent",
    instructions=(
        "You have access to a local research knowledge base with topics: "
        "TRANSF.DIGITAL, Nexus_IA_Big_Data_turism, Emprendimiento, Agente_inmobiliario, web_development. "
        "\n\nWORKFLOW:\n"
        "1. Always check search_memory (scope='wiki') FIRST — pre-synthesized nodes are cheapest.\n"
        "2. If wiki misses, use search_memory (scope='rag') for raw document chunks.\n"
        "3. After a high-confidence synthesis, call save_insight to persist it.\n"
        "4. For evaluator feedback: call save_feedback immediately.\n"
        "5. Cloud (call_cloud) is last resort — public context only, confirmed=False first.\n"
        "\nAlways cite source labels from retrieved results."
    ),
)


@mcp.tool()
def search_memory(query: str, scope: str = "all", budget_tokens: int = 3000) -> str:
    """
    Search the research knowledge base (wiki-first, then ChromaDB, then Engram).

    Args:
        query:         Natural-language search query.
        scope:         "all" | "wiki" | "rag" | "engram". Start with "wiki" to save tokens.
        budget_tokens: Max tokens to return (default 3000, lower for follow-up turns).
    """
    try:
        from tools.memory import search_memory as _search
        return _search(query=query, scope=scope, budget_tokens=budget_tokens)
    except Exception as e:
        return f"search_memory error: {e}"


@mcp.tool()
def save_insight(title: str, content: str, tags: str = "") -> str:
    """
    Persist a synthesis or finding to wiki/auto/ + Engram.
    Call after producing any answer with confidence ≥ 0.80.

    Args:
        title:   Short descriptive title (5-10 words).
        content: Insight content (markdown OK).
        tags:    Comma-separated topic labels.
    """
    try:
        from tools.insight import save_insight as _save
        return _save(title=title, content=content, tags=tags)
    except Exception as e:
        return f"save_insight error: {e}"


@mcp.tool()
def save_feedback(topic: str, unit: str, note: str, content: str) -> str:
    """
    Persist evaluator feedback for a topic/unit to wiki/manual/feedback/ + Engram.

    Args:
        topic:   Topic key (e.g. TRANSF.DIGITAL, Nexus_IA_Big_Data_turism).
        unit:    Unit number or label (e.g. "4", "final").
        note:    Grade/label (e.g. "notable", "sobresaliente").
        content: Raw feedback text from the evaluator.
    """
    try:
        from tools.feedback import save_feedback as _save
        return _save(topic=topic, unit=unit, note=note, content=content)
    except Exception as e:
        return f"save_feedback error: {e}"


@mcp.tool()
def call_cloud(prompt: str, confirmed: bool = False) -> str:
    """
    Escalate to cloud LLM (OpenRouter). Last resort — public context only.

    Two-step gate: confirmed=False shows a preview and asks for user confirmation.
    Only call with confirmed=True after the user explicitly approves.

    Args:
        prompt:    Complete prompt (public context only — NEVER private notes).
        confirmed: False = preview + ask. True = execute.
    """
    try:
        from tools.cloud import call_cloud as _call
        return _call(prompt=prompt, confirmed=confirmed)
    except Exception as e:
        return f"call_cloud error: {e}"


@mcp.tool()
def agent_status() -> str:
    """
    Return current knowledge base stats: ChromaDB collections, wiki nodes, Ollama models.
    """
    try:
        from harness import _status_summary
        return _status_summary()
    except Exception as e:
        return f"status error: {e}"


@mcp.tool()
def ingest_files(path: str) -> str:
    """
    Ingest a file or directory into the knowledge base (public collection).

    Supported: pdf, docx, txt, md, csv, xlsx, fasta, vcf, bed, wig, tsv, gtf.
    Raw NGS (.fastq, .bam, .cram) are rejected automatically.

    Args:
        path: Absolute path to file or directory.
    """
    sys.path.insert(0, str(AGENT_ROOT / "infra" / "ingest"))
    try:
        from run_ingest import ingest_path
        return ingest_path(path)
    except Exception as e:
        return f"ingest error: {e}"


if __name__ == "__main__":
    mcp.run()

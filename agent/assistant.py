#!/usr/bin/env python3
"""
Research Agent CLI — entry point for terminal and Cowork sessions.

Usage:
  python3 assistant.py "query"                   single question
  python3 assistant.py --interactive             REPL session
  python3 assistant.py --interactive --topic "tema"  REPL with pre-loaded context
  python3 assistant.py --status                  knowledge base stats
  python3 assistant.py --ingest path/to/file     ingest a single file
  python3 assistant.py --ingest path/to/dir/     ingest a directory
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(AGENT_ROOT))
sys.path.insert(0, str(AGENT_ROOT / "agent"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research Agent — local RAG + wiki + Engram + qwen3:8b",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", help="Single question")
    parser.add_argument("--interactive", "-i", action="store_true", help="REPL session")
    parser.add_argument("--topic",       "-t", default="", help="Topic hint for context pre-loading")
    parser.add_argument("--status",      "-s", action="store_true", help="Show knowledge base status")
    parser.add_argument("--ingest",      metavar="PATH", help="Ingest file or directory")
    parser.add_argument("--collection",  metavar="COLL", help="Force query against specific collection")
    parser.add_argument("--context-only", action="store_true", help="Return RAG context without LLM synthesis")
    args = parser.parse_args()

    if args.status:
        from harness import _status_summary
        print(_status_summary())
        return 0

    if args.ingest:
        return _run_ingest(args.ingest)

    from context_builder import build_system_prompt
    system_prompt = build_system_prompt(args.topic)

    if args.interactive:
        from harness import run_interactive
        run_interactive(system_prompt)
        return 0

    if args.query:
        if args.context_only:
            from tools.memory import search_memory
            print(search_memory(args.query))
            return 0
        from harness import run_once
        try:
            response, meta = run_once(args.query, system_prompt, [])
        except RuntimeError as e:
            print(f"[error] {e}", file=sys.stderr)
            return 1
        if meta.get("tools_called"):
            names = " + ".join(t["tool"] for t in meta["tools_called"])
            print(f"\n  tools: {names}")
        return 0

    parser.print_help()
    return 0


def _run_ingest(path_str: str) -> int:
    sys.path.insert(0, str(AGENT_ROOT / "infra" / "ingest"))
    try:
        from run_ingest import ingest_path
        result = ingest_path(path_str)
        print(result)
        return 0
    except Exception as e:
        print(f"Ingest error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

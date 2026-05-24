"""
ReAct harness — native tool-calling loop via Ollama /api/chat.

Pattern: generate → tool_call? → execute + inject → loop : stream text → done.
Max 8 iterations per turn to prevent infinite loops.

Tools available to the model:
  search_memory  — wiki-first knowledge retrieval
  save_insight   — persist synthesis to wiki + Engram
  save_feedback  — persist evaluator feedback
  call_cloud     — gated cloud escalation (public context only)
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import httpx
import yaml

AGENT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(AGENT_ROOT / "agent"))

from tools.memory import search_memory
from tools.insight import save_insight
from tools.cloud import call_cloud
from tools.feedback import save_feedback

logger = logging.getLogger(__name__)

CONFIG_PATH = AGENT_ROOT / "config.yaml"
_cfg_cache: dict | None = None


def _cfg() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        with open(CONFIG_PATH) as f:
            _cfg_cache = yaml.safe_load(f)
    return _cfg_cache


TOOL_REGISTRY = {
    "search_memory": search_memory,
    "save_insight":  save_insight,
    "save_feedback": save_feedback,
    "call_cloud":    call_cloud,
}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Search the research knowledge base. "
                "Searches wiki nodes first (pre-synthesized, low token cost), "
                "then ChromaDB raw chunks, then Engram session memory. "
                "Call when pre-loaded context is insufficient."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search query"},
                    "scope": {
                        "type": "string",
                        "enum": ["all", "wiki", "rag", "engram"],
                        "description": "Source to search. Default: all. Use 'wiki' first to save tokens.",
                    },
                    "budget_tokens": {
                        "type": "integer",
                        "description": "Max tokens to return. Default: 3000. Lower for follow-up turns.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_insight",
            "description": (
                "Persist a notable synthesis to long-term memory (wiki node + Engram). "
                "Call after producing an answer with confidence ≥ 0.80."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title":   {"type": "string", "description": "Short title (5-10 words)"},
                    "content": {"type": "string", "description": "Insight content (markdown OK)"},
                    "tags":    {"type": "string", "description": "Comma-separated topic tags"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_feedback",
            "description": "Persist evaluator feedback for a topic/unit to wiki and Engram.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic":   {"type": "string", "description": "Topic key, e.g. TRANSF.DIGITAL"},
                    "unit":    {"type": "string", "description": "Unit number or label"},
                    "note":    {"type": "string", "description": "Grade/label, e.g. notable"},
                    "content": {"type": "string", "description": "Raw feedback text"},
                },
                "required": ["topic", "unit", "note", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_cloud",
            "description": (
                "Escalate to cloud LLM (OpenRouter). Use ONLY when local knowledge clearly fails. "
                "NEVER include private notes. Two-step: first confirmed=False (preview), "
                "then confirmed=True after user approves."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt":    {"type": "string", "description": "Complete prompt (public context only)"},
                    "confirmed": {"type": "boolean", "description": "False=preview, True=execute"},
                },
                "required": ["prompt"],
            },
        },
    },
]


def _stream_call(messages: list[dict], cfg: dict) -> tuple[str, list]:
    """
    Streaming /api/chat call. Prints text tokens live as they arrive.
    Returns (accumulated_text, tool_calls).
    Empty tool_calls means the model produced a final answer.
    """
    local = cfg["llm"]["local"]
    url = f"{local['base_url']}/api/chat"

    payload = {
        "model": local["model"],
        "messages": messages,
        "tools": TOOL_SCHEMAS,
        "stream": True,
        "options": {
            "temperature": local.get("temperature", 0.2),
            "num_predict": local.get("num_predict", 4096),
        },
    }

    text_parts: list[str] = []
    final_tool_calls: list = []
    thinking_shown = False

    try:
        with httpx.stream(
            "POST", url, json=payload,
            timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if not raw:
                    continue
                chunk = json.loads(raw)
                msg = chunk.get("message", {})

                if not thinking_shown and msg.get("thinking"):
                    print("[thinking...]", flush=True)
                    thinking_shown = True

                token = msg.get("content", "")
                if token:
                    print(token, end="", flush=True)
                    text_parts.append(token)
                if chunk.get("done"):
                    final_tool_calls = msg.get("tool_calls") or []
                    break
    except httpx.ConnectError:
        raise RuntimeError(
            f"Ollama is not running. Start with: ollama serve\n"
            f"Then: ollama pull {local['model']}"
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama HTTP {e.response.status_code}: {e.response.text[:200]}")

    return "".join(text_parts), final_tool_calls


def run_once(query: str, system_prompt: str, history: list[dict]) -> tuple[str, dict]:
    """
    Run a single user turn through the ReAct loop.
    Returns (response_text, metadata).
    """
    cfg = _cfg()
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": query})

    tools_called: list[dict] = []

    for iteration in range(8):
        text, tool_calls = _stream_call(messages, cfg)

        if not tool_calls:
            if text:
                print()
            return text, {"tools_called": tools_called, "iterations": iteration + 1}

        messages.append({
            "role": "assistant",
            "content": text,
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = tc["function"]["arguments"]
            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except json.JSONDecodeError:
                    fn_args = {}

            print(f"\n  [{fn_name}] ", end="", flush=True)
            tool_fn = TOOL_REGISTRY.get(fn_name)
            if tool_fn:
                try:
                    result = tool_fn(**fn_args)
                    print("✓", flush=True)
                except Exception as exc:
                    result = f"Tool error: {exc}"
                    logger.warning("Tool %s failed: %s", fn_name, exc)
                    print(f"✗  {exc}", flush=True)
            else:
                result = f"Unknown tool: {fn_name}"
                print("✗  unknown", flush=True)

            tools_called.append({"tool": fn_name, "args": fn_args})
            messages.append({"role": "tool", "content": str(result)})

    return text, {"tools_called": tools_called, "iterations": 8, "warning": "max_iterations"}


def run_interactive(system_prompt: str) -> None:
    """Multi-turn REPL with ReAct tool-calling. Maintains conversation history."""
    cfg = _cfg()
    model = cfg["llm"]["local"]["model"]
    print(f"Research Agent  |  {model}  |  tools: search_memory · save_insight · save_feedback · call_cloud")
    print("Commands: exit · status · /topic <hint>\n")

    history: list[dict] = []

    try:
        import readline  # noqa: F401 — enables arrow keys
    except ImportError:
        pass

    while True:
        try:
            query = input("\n? ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            print("Exiting.")
            break
        if query.lower() == "status":
            print(_status_summary())
            continue
        if query.lower().startswith("/topic "):
            # Rebuild system prompt with new topic hint
            hint = query[7:].strip()
            from context_builder import build_system_prompt
            system_prompt = build_system_prompt(hint)
            print(f"  Context rebuilt for topic: {hint}")
            continue

        print()
        try:
            response, meta = run_once(query, system_prompt, history)
        except RuntimeError as e:
            print(f"\n[error] {e}")
            continue

        if meta.get("tools_called"):
            names = " + ".join(t["tool"] for t in meta["tools_called"])
            print(f"\n  tools: {names}")
        if meta.get("warning"):
            print(f"\n  warning: {meta['warning']}")

        history.append({"role": "user",      "content": query})
        history.append({"role": "assistant", "content": response})


def _status_summary() -> str:
    cfg = _cfg()
    lines = ["\nKnowledge Base:"]
    try:
        import chromadb
        chroma_path = str(AGENT_ROOT / "knowledge_base" / "data" / "chroma_db")
        client = chromadb.PersistentClient(path=chroma_path)
        for col in client.list_collections():
            lines.append(f"  {col.name:<28} {col.count():>6} chunks")
    except Exception as e:
        lines.append(f"  ChromaDB error: {e}")

    for label, wiki_dir in (("wiki/auto", AGENT_ROOT / "wiki" / "auto"),
                              ("wiki/manual", AGENT_ROOT / "wiki" / "manual")):
        count = len(list(wiki_dir.rglob("*.md"))) if wiki_dir.exists() else 0
        lines.append(f"  {label:<28} {count:>6} nodes")

    return "\n".join(lines)

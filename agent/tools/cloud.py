"""
Gated cloud LLM escalation via OpenRouter.

Privacy rules:
  - Private context NEVER leaves local without explicit confirmation.
  - Two-step confirmation gate prevents accidental cloud sends.
  - If context_has_private=True and confirmed=False → hard block.
"""
from __future__ import annotations

import os
from pathlib import Path
import httpx
import yaml

AGENT_ROOT  = Path(__file__).parent.parent.parent
CONFIG_PATH = AGENT_ROOT / "config.yaml"
_cfg_cache: dict | None = None


def _cfg() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        with open(CONFIG_PATH) as f:
            _cfg_cache = yaml.safe_load(f)
    return _cfg_cache


def call_cloud(
    prompt: str,
    confirmed: bool = False,
    context_has_private: bool = False,
) -> str:
    """
    Send prompt to cloud LLM (OpenRouter). NEVER include private notes.

    Three-stage gate:
      1. context_has_private=True + confirmed=False
             → PRIVACY BLOCK: explain the risk, ask for explicit confirmation
      2. confirmed=False (no private context)
             → show preview + ask for standard confirmation
      3. confirmed=True
             → execute (only after user has confirmed)

    The caller should pass context_has_private=True whenever search_memory
    returned results tagged with ⚠️ PRIVATE CONTEXT PRESENT.
    """
    cfg   = _cfg()
    model = cfg["llm"]["cloud"]["model"]

    # Stage 1 — hard privacy block
    if context_has_private and not confirmed:
        preview = prompt[:400] + ("…" if len(prompt) > 400 else "")
        return (
            "⚠️  PRIVACY GATE — private context detected\n\n"
            "Your last search_memory call returned chunks tagged _source: private.\n"
            "Sending private research notes to a cloud LLM violates data sovereignty.\n\n"
            f"Model: {model}\n"
            f"Prompt preview:\n{preview}\n\n"
            "To proceed with PUBLIC CONTEXT ONLY:\n"
            "  1. Call search_memory(query, public_only=True) to get a clean context\n"
            "  2. Build a new prompt from that context\n"
            "  3. Call call_cloud(prompt, confirmed=True)\n\n"
            "To proceed including private context (e.g. for local-only synthesis):\n"
            "  This is not allowed via cloud. Use the local LLM instead."
        )

    # Stage 2 — standard confirmation preview
    if not confirmed:
        preview = prompt[:600] + ("…" if len(prompt) > 600 else "")
        return (
            f"[CLOUD GATE — confirmation required]\n"
            f"Model: {model}\n"
            f"Preview (public context only):\n\n{preview}\n\n"
            f"Call call_cloud(prompt, confirmed=True) to execute."
        )

    # Stage 3 — execute
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "Error: OPENROUTER_API_KEY not set in environment."

    base_url = cfg["llm"]["cloud"]["base_url"]
    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       model,
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  2048,
                "temperature": cfg["llm"]["cloud"].get("temperature", 0.3),
            },
            timeout=90.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        return f"Cloud error {e.response.status_code}: {e.response.text[:300]}"
    except httpx.TimeoutException:
        return "Cloud call timed out (90s). Try a shorter prompt."
    except Exception as e:
        return f"Cloud call failed: {e}"

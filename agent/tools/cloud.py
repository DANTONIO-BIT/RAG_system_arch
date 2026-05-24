"""
Gated cloud LLM escalation via OpenRouter.
Privacy rule: private content NEVER leaves local. Only public context permitted.
Two-step confirmation gate prevents accidental cloud sends.
"""
from __future__ import annotations

import os
from pathlib import Path
import httpx
import yaml

AGENT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = AGENT_ROOT / "config.yaml"
_cfg_cache: dict | None = None


def _cfg() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        with open(CONFIG_PATH) as f:
            _cfg_cache = yaml.safe_load(f)
    return _cfg_cache


def call_cloud(prompt: str, confirmed: bool = False) -> str:
    """
    Send prompt to cloud LLM (OpenRouter). NEVER include private notes.

    Two-step gate:
      Step 1  confirmed=False → preview + ask for confirmation
      Step 2  confirmed=True  → execute (only after user says yes)
    """
    cfg = _cfg()
    model = cfg["llm"]["cloud"]["model"]
    base_url = cfg["llm"]["cloud"]["base_url"]

    if not confirmed:
        preview = prompt[:600] + ("…" if len(prompt) > 600 else "")
        return (
            f"[CLOUD GATE — confirmation required]\n"
            f"Model: {model}\n"
            f"Preview (public context only):\n\n{preview}\n\n"
            f"Reply 'yes, proceed' to confirm, then call call_cloud with confirmed=True."
        )

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "Error: OPENROUTER_API_KEY not set in environment."

    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048,
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

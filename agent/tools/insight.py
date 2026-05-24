"""
Persist synthesized knowledge: wiki node (.md) + Engram.
Called by the model after generating a high-confidence answer worth remembering.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
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


def _wiki_auto_dir() -> Path:
    return AGENT_ROOT / "wiki" / "auto"


def save_insight(title: str, content: str, tags: str = "") -> str:
    """
    Write a wiki node to wiki/auto/ and save to Engram.
    tags: optional comma-separated labels (topic, domain, etc.)
    Returns a confirmation string.
    """
    saved: list[str] = []

    wiki_path = _write_wiki(title, content, tags)
    if wiki_path:
        saved.append(f"wiki/auto/{Path(wiki_path).name}")

    if _save_engram(title, content):
        saved.append("engram")

    return "Saved to: " + ", ".join(saved) if saved else "Save failed — check logs."


def _write_wiki(title: str, content: str, tags: str) -> str | None:
    auto_dir = _wiki_auto_dir()
    auto_dir.mkdir(parents=True, exist_ok=True)

    slug_words = re.sub(r"[^\w\s]", "", title.lower()).split()[:6]
    slug = "_".join(slug_words) or "untitled"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tag_line = f"\n**tags:** {tags}" if tags.strip() else ""
    dest = auto_dir / f"{slug}.md"

    dest.write_text(
        f"# {title}\n\n_Auto-saved · {ts}_{tag_line}\n\n{content}\n",
        encoding="utf-8",
    )
    return str(dest)


def _save_engram(title: str, content: str) -> bool:
    cfg = _cfg()
    bin_path = cfg["engram"]["bin"]
    project = cfg["engram"]["project"]
    try:
        proc = subprocess.run(
            [bin_path, "save", "-t", title, "-p", project, content],
            capture_output=True, text=True, timeout=8,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

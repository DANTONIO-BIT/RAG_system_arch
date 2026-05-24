"""
Save evaluator feedback — preserves the Digital Lab feedback workflow.
Writes structured feedback locally + saves to Engram under research-agent project.
"""
from __future__ import annotations

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


def _wiki_manual_dir() -> Path:
    return AGENT_ROOT / "wiki" / "manual"


def save_feedback(topic: str, unit: str, note: str, content: str) -> str:
    """
    Persist evaluator feedback for a topic/unit to wiki/manual/ and Engram.

    topic:   e.g. "TRANSF.DIGITAL", "Nexus_IA_Big_Data_turism"
    unit:    e.g. "4", "U2", "final"
    note:    grade/label, e.g. "notable", "sobresaliente", "aprobado"
    content: raw feedback text from the evaluator
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"[feedback] {topic} U{unit} {note} {ts}"

    # Write to wiki/manual/feedback/
    manual_dir = _wiki_manual_dir() / "feedback"
    manual_dir.mkdir(parents=True, exist_ok=True)
    slug = f"fb_{topic.replace('.', '_').lower()}_u{unit}_{ts}.md"
    dest = manual_dir / slug
    dest.write_text(
        f"# Feedback: {topic} — Unidad {unit}\n\n"
        f"**Nota:** {note}  \n**Fecha:** {ts}\n\n"
        f"---\n\n{content}\n",
        encoding="utf-8",
    )

    # Save to Engram
    cfg = _cfg()
    bin_path = cfg["engram"]["bin"]
    project = cfg["engram"]["project"]
    engram_ok = False
    try:
        proc = subprocess.run(
            [bin_path, "save", "-t", title, "-p", project, content],
            capture_output=True, text=True, timeout=8,
        )
        engram_ok = proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    saved = [f"wiki/manual/feedback/{slug}"]
    if engram_ok:
        saved.append("engram")
    return "Feedback saved to: " + ", ".join(saved)

#!/usr/bin/env python3
"""
Watchdog — auto-ingest on file drop.

Monitors all configured directories simultaneously:
  data/public/    → files go to "public" collection
  data/private/   → files go to "private" collection
  data/ngs/       → files go to "public" collection
  projects/*/     → routed by subfolder (inbox/ → public, private/ → private)

Run as a background process (managed by LaunchAgent / Task Scheduler).
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import yaml

AGENT_ROOT  = Path(__file__).parent.parent.parent
CONFIG_PATH = AGENT_ROOT / "config.yaml"
sys.path.insert(0, str(AGENT_ROOT / "infra" / "ingest"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _cfg() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _on_file(path: Path) -> None:
    from run_ingest import ingest_file
    logger.info("New file: %s", path.name)
    result = ingest_file(path, move_to_indexed=True)
    logger.info(result)


def _build_watch_dirs() -> list[Path]:
    """Collect all directories that should be watched."""
    dirs: list[Path] = []

    cfg       = _cfg()
    watch_cfg = cfg.get("data", {}).get("watch_dirs", {})

    for key in ("public", "private", "ngs"):
        rel = watch_cfg.get(key)
        if rel:
            d = AGENT_ROOT / rel
            d.mkdir(parents=True, exist_ok=True)
            dirs.append(d)

    # Watch all project inbox/ and private/ dirs
    projects_root = AGENT_ROOT / "projects"
    if projects_root.exists():
        for project_dir in projects_root.iterdir():
            if not project_dir.is_dir() or project_dir.name.startswith("_"):
                continue
            for sub in ("inbox", "private"):
                d = project_dir / sub
                d.mkdir(parents=True, exist_ok=True)
                dirs.append(d)

    return dirs


def watch() -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        raise ImportError("watchdog required: pip install watchdog")

    cfg       = _cfg()
    supported = (
        set(cfg["data"]["supported_extensions"]["standard"])
        | set(cfg["data"]["supported_extensions"]["omics"])
    )

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            p = Path(event.src_path)
            if p.suffix.lower() not in supported:
                return
            time.sleep(0.5)
            _on_file(p)

        def on_moved(self, event):
            # Handle drag-and-drop (creates as temp, then renames)
            if event.is_directory:
                return
            p = Path(event.dest_path)
            if p.suffix.lower() not in supported:
                return
            time.sleep(0.5)
            _on_file(p)

    watch_dirs = _build_watch_dirs()
    observer   = Observer()
    for d in watch_dirs:
        observer.schedule(Handler(), str(d), recursive=True)
        logger.info("Watching: %s", d)

    observer.start()
    logger.info("Watcher active — drop files to auto-ingest. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("Watcher stopped.")
    observer.join()


if __name__ == "__main__":
    watch()

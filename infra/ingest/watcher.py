#!/usr/bin/env python3
"""
Watchdog for data/public/inbox/ — auto-ingest on file drop.
Run once as a background process; Ctrl+C to stop.

Usage:
  python3 infra/ingest/watcher.py
  python3 infra/ingest/watcher.py --path /custom/watch/dir
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import yaml

AGENT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = AGENT_ROOT / "config.yaml"
sys.path.insert(0, str(AGENT_ROOT / "infra" / "ingest"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _cfg() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _on_file(path: Path) -> None:
    from run_ingest import ingest_file
    logger.info(f"New file detected: {path.name}")
    result = ingest_file(path)
    logger.info(result)


def watch(watch_dir: Path) -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileCreatedEvent
    except ImportError:
        raise ImportError("watchdog required: pip install watchdog")

    cfg = _cfg()
    supported = (
        set(cfg["data"]["supported_extensions"]["standard"]) |
        set(cfg["data"]["supported_extensions"]["omics"])
    )

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            p = Path(event.src_path)
            if p.suffix.lower() not in supported:
                return
            time.sleep(0.5)  # wait for write to finish
            _on_file(p)

    observer = Observer()
    observer.schedule(Handler(), str(watch_dir), recursive=False)
    observer.start()
    logger.info(f"Watching {watch_dir} — drop files to auto-ingest. Ctrl+C to stop.")

    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("Watcher stopped.")
    observer.join()


def main() -> int:
    parser = argparse.ArgumentParser(description="Research Agent — file watcher")
    parser.add_argument("--path", help="Directory to watch (default: data/public/inbox/)")
    args = parser.parse_args()

    watch_dir = Path(args.path) if args.path else (AGENT_ROOT / "data" / "public" / "inbox")
    watch_dir.mkdir(parents=True, exist_ok=True)
    watch(watch_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

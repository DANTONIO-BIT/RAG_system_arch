#!/usr/bin/env python3
"""
Batch ingest CLI for research-agent.

Parses files → chunks → embeds → stores in the embedded ChromaDB.

Usage:
  python3 run_ingest.py path/to/file_or_dir [--topic TRANSF.DIGITAL]
  python3 run_ingest.py --inbox           # process data/public/inbox/
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import sys
from pathlib import Path

import yaml

AGENT_ROOT  = Path(__file__).parent.parent.parent
CONFIG_PATH = AGENT_ROOT / "config.yaml"
KB_SRC      = AGENT_ROOT / "knowledge_base" / "src"
KB_CHROMA   = AGENT_ROOT / "knowledge_base" / "data" / "chroma_db"

sys.path.insert(0, str(AGENT_ROOT / "infra" / "ingest"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


def _cfg() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _ensure_rag_imports():
    src = str(KB_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def _chunk_text(text: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


def _detect_topic(filename: str) -> str:
    """Match filename against topic keywords to auto-detect topic."""
    _ensure_rag_imports()
    try:
        from processor import TOPIC_MAP
        fname_lower = filename.lower()
        for topic, meta in TOPIC_MAP.items():
            keywords = meta.get("keywords", [])
            if any(kw.lower() in fname_lower for kw in keywords):
                return topic
    except Exception:
        pass
    return "general"


def ingest_file(path: Path, topic: str | None = None, move_to_indexed: bool = True) -> str:
    """
    Parse, chunk, embed and store one file into ChromaDB.
    Returns a result summary string.
    """
    _ensure_rag_imports()

    from parsers import parse_file
    from embeddings import generate_embeddings
    from vector_store import get_vector_store
    from router import get_collection_for_topic

    # Reject raw NGS
    try:
        text = parse_file(path)
    except ValueError as e:
        return f"REJECTED  {path.name}: {e}"
    except Exception as e:
        return f"ERROR     {path.name}: {e}"

    if not text or not text.strip():
        return f"EMPTY     {path.name}: no extractable text"

    detected_topic = topic or _detect_topic(path.name)
    collection = get_collection_for_topic(detected_topic)

    doc_hash = hashlib.md5(path.read_bytes()).hexdigest()
    vs = get_vector_store(collection_name=collection, persist_dir=str(KB_CHROMA))

    if vs.check_document_exists(doc_hash):
        return f"SKIP      {path.name}: already indexed in {collection}"

    chunks = _chunk_text(text)
    embeddings = generate_embeddings(chunks)

    doc_result = {
        "chunks": chunks,
        "embeddings": embeddings,
        "metadata": {
            "filename": path.name,
            "filepath": str(path),
            "hash": doc_hash,
            "topic": detected_topic,
            "category": detected_topic,
            "chunk_count": len(chunks),
            "char_count": len(text),
            "file_type": path.suffix.lower(),
            "size": path.stat().st_size,
        },
    }

    n = vs.add_documents([doc_result])

    # Move to indexed/
    if move_to_indexed:
        indexed_dir = AGENT_ROOT / "data" / "public" / "indexed"
        indexed_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(path), indexed_dir / path.name)
        except Exception:
            pass  # Leave in place if move fails

    return f"OK        {path.name} → {collection} ({n} chunks)"


def ingest_path(path_str: str, topic: str | None = None, move_to_indexed: bool = True) -> str:
    """Ingest a file or directory. Returns multi-line status."""
    cfg = _cfg()
    target = Path(path_str)
    if not target.is_absolute():
        target = AGENT_ROOT / path_str
    if not target.exists():
        return f"ERROR: path not found: {target}"

    supported = set(cfg["data"]["supported_extensions"]["standard"]) | \
                set(cfg["data"]["supported_extensions"]["omics"])

    if target.is_file():
        return ingest_file(target, topic=topic, move_to_indexed=move_to_indexed)

    files = [f for f in target.rglob("*") if f.is_file() and f.suffix.lower() in supported]
    if not files:
        return f"No supported files found in {target}"

    lines = [f"Ingesting {len(files)} files from {target.name}/\n"]
    for f in files:
        lines.append(ingest_file(f, topic=topic, move_to_indexed=move_to_indexed))

    ok  = sum(1 for l in lines if l.startswith("OK"))
    skp = sum(1 for l in lines if l.startswith("SKIP"))
    err = sum(1 for l in lines if l.startswith(("ERROR", "REJECTED", "EMPTY")))
    lines.append(f"\nDone: {ok} ingested, {skp} skipped, {err} errors.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Research Agent — batch ingest")
    parser.add_argument("path", nargs="?", help="File or directory to ingest")
    parser.add_argument("--inbox", action="store_true", help="Process data/public/inbox/")
    parser.add_argument("--topic", help="Force topic key (e.g. TRANSF.DIGITAL)")
    parser.add_argument("--no-move", action="store_true",
                        help="Do not move files to indexed/ after ingestion (use during rebuild)")
    args = parser.parse_args()

    move = not args.no_move

    if args.inbox:
        inbox = str(AGENT_ROOT / "data" / "public" / "inbox")
        print(ingest_path(inbox, topic=args.topic, move_to_indexed=move))
        return 0

    if args.path:
        target = Path(args.path)
        if not target.is_absolute():
            target = AGENT_ROOT / args.path
        if target.is_file():
            print(ingest_file(target, topic=args.topic, move_to_indexed=move))
        else:
            print(ingest_path(str(target), topic=args.topic, move_to_indexed=move))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

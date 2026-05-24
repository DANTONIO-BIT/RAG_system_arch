#!/usr/bin/env python3
"""
Ingest pipeline: file → parse → chunk → embed → ChromaDB.

Collection routing is determined by source path:
  data/public/**           → collection "public"
  data/private/**          → collection "private"
  data/ngs/**              → collection "public"   (processed outputs only)
  projects/{name}/inbox/** → collection "public"
  projects/{name}/private/** → collection "private"
  knowledge_base/input/**  → collection "public"   (rebuild source)

After successful ingest, files from inbox/ are moved to indexed/.

Usage:
  python3 run_ingest.py path/to/file [--topic TOPIC]
  python3 run_ingest.py --inbox           # process data/public/papers/inbox/
  python3 run_ingest.py --rebuild         # re-ingest knowledge_base/input/
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
sys.path.insert(0, str(KB_SRC))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Raw NGS files that must never be ingested
_RAW_NGS_EXTENSIONS = {".fastq", ".bam", ".cram"}

# FASTA size guards
_FASTA_MAX_SEQUENCES = 500
_FASTA_MAX_TOTAL_LEN = 500_000

_cfg_cache: dict | None = None


def _cfg() -> dict:
    global _cfg_cache
    if _cfg_cache is None:
        with open(CONFIG_PATH) as f:
            _cfg_cache = yaml.safe_load(f)
    return _cfg_cache


def _ensure_rag_imports() -> None:
    src = str(KB_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


# ── Collection routing ────────────────────────────────────────────────────────

def _resolve_collection(path: Path) -> str:
    """
    Determine ChromaDB collection from file path.
    First match wins:
      projects/{name}/private/**  → "private"
      projects/{name}/**          → "public"
      data/private/**             → "private"
      data/public/**              → "public"
      data/ngs/**                 → "public"
      knowledge_base/input/**     → "public"   (rebuild case)
      anything else               → "public"   (safe default)
    """
    parts = path.parts

    if "projects" in parts:
        idx = parts.index("projects")
        sub = parts[idx + 2:] if idx + 2 < len(parts) else ()
        if sub and sub[0] == "private":
            return "private"
        return "public"

    if "data" in parts:
        idx = parts.index("data")
        if idx + 1 < len(parts) and parts[idx + 1] == "private":
            return "private"
        return "public"

    return "public"


def _extract_project_id(path: Path) -> str:
    """
    Derive a project_id from the file path for per-project filtering.
      projects/{name}/**   → {name}
      data/ngs/**          → "ngs"
      data/private/**      → "private_global"
      data/public/shared/** → "shared"
      knowledge_base/input/{topic}/** → topic folder name
    """
    parts = path.parts

    if "projects" in parts:
        idx = parts.index("projects")
        if idx + 1 < len(parts):
            return parts[idx + 1]

    if "input" in parts:
        idx = parts.index("input")
        if idx + 1 < len(parts):
            return parts[idx + 1]  # topic subfolder: TRANSF.DIGITAL, Nexus_IA…

    if "data" in parts:
        idx = parts.index("data")
        sub = parts[idx + 1] if idx + 1 < len(parts) else ""
        if sub == "ngs":
            return "ngs"
        if sub == "private":
            return "private_global"
        if sub == "public" and idx + 2 < len(parts):
            return parts[idx + 2]  # papers, references, shared…

    return "untagged"


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str) -> list[str]:
    cfg     = _cfg()
    size    = cfg["chunking"]["size"]
    overlap = cfg["chunking"]["overlap"]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end   = start + size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


# ── Metadata ──────────────────────────────────────────────────────────────────

def _build_metadata(path: Path, collection: str, chunk_index: int, topic: str | None) -> dict:
    return {
        "source_path": str(path),
        "filename":    path.name,
        "collection":  collection,
        "chunk_index": chunk_index,
        "file_type":   path.suffix.lower().lstrip("."),
        "_source":     collection,                   # "public" | "private"
        "project_id":  _extract_project_id(path),
        "topic":       topic or _extract_project_id(path),
    }


# ── Core ingest ───────────────────────────────────────────────────────────────

def ingest_file(path: Path, topic: str | None = None, move_to_indexed: bool = True) -> str:
    """
    Parse → chunk → embed → store one file into ChromaDB.
    Returns a one-line status string.
    """
    suffix = path.suffix.lower()

    # Block raw NGS
    if suffix in _RAW_NGS_EXTENSIONS or path.name.endswith(".fastq.gz"):
        return f"REJECTED  {path.name}: raw NGS file — generate QC summary first"

    _ensure_rag_imports()
    from parsers import parse_file
    from embeddings import generate_embeddings
    import chromadb

    collection = _resolve_collection(path)

    try:
        text = parse_file(path)
    except ValueError as e:
        return f"REJECTED  {path.name}: {e}"
    except Exception as e:
        return f"ERROR     {path.name}: {e}"

    if not text or not text.strip():
        return f"EMPTY     {path.name}: no extractable text"

    chunks = _chunk_text(text)
    if not chunks:
        return f"EMPTY     {path.name}: no chunks produced"

    # Idempotent chunk IDs (SHA256 of path + index)
    doc_hash = hashlib.sha256(str(path).encode()).hexdigest()[:16]
    uid_exists = False
    try:
        client = chromadb.PersistentClient(path=str(KB_CHROMA))
        col    = client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"},
        )
        # Check if first chunk already exists → skip
        test_id = hashlib.sha256(f"{path}::0".encode()).hexdigest()[:32]
        existing = col.get(ids=[test_id])
        if existing["ids"]:
            return f"SKIP      {path.name}: already indexed in '{collection}'"
    except Exception:
        pass

    try:
        embeddings = generate_embeddings(chunks)
    except Exception as e:
        return f"ERROR     {path.name}: embedding failed — {e}"

    ids:       list[str] = []
    metas:     list[dict] = []
    for i, chunk in enumerate(chunks):
        uid  = hashlib.sha256(f"{path}::{i}".encode()).hexdigest()[:32]
        meta = _build_metadata(path, collection, i, topic)
        ids.append(uid)
        metas.append(meta)

    col.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metas,
    )

    # Move to indexed/ (only for inbox files)
    if move_to_indexed and "inbox" in path.parts:
        _move_to_indexed(path)

    return f"OK        {path.name} → '{collection}' · project: {_extract_project_id(path)} · {len(chunks)} chunks"


def _move_to_indexed(source: Path) -> None:
    """Move a file from any inbox/ to its sibling indexed/ dir."""
    parts = list(source.parts)
    if "inbox" not in parts:
        return
    parts[parts.index("inbox")] = "indexed"
    dest = Path(*parts)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(source), str(dest))
    except Exception as e:
        logger.warning("Could not move %s to indexed/: %s", source.name, e)


def ingest_path(path_str: str, topic: str | None = None, move_to_indexed: bool = True) -> str:
    """Ingest a file or directory. Returns multi-line status."""
    cfg     = _cfg()
    target  = Path(path_str)
    if not target.is_absolute():
        target = AGENT_ROOT / path_str
    if not target.exists():
        return f"ERROR: path not found: {target}"

    supported = (
        set(cfg["data"]["supported_extensions"]["standard"])
        | set(cfg["data"]["supported_extensions"]["omics"])
    )

    if target.is_file():
        return ingest_file(target, topic=topic, move_to_indexed=move_to_indexed)

    files = [f for f in target.rglob("*") if f.is_file() and f.suffix.lower() in supported]
    if not files:
        return f"No supported files found in {target}"

    lines = [f"Ingesting {len(files)} files from {target.name}/\n"]
    for f in sorted(files):
        lines.append(ingest_file(f, topic=topic, move_to_indexed=move_to_indexed))

    ok  = sum(1 for l in lines if l.startswith("OK"))
    skp = sum(1 for l in lines if l.startswith("SKIP"))
    err = sum(1 for l in lines if l.startswith(("ERROR", "REJECTED", "EMPTY")))
    lines.append(f"\nDone: {ok} ingested · {skp} skipped · {err} errors")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Research Agent — batch ingest")
    parser.add_argument("path",    nargs="?", help="File or directory to ingest")
    parser.add_argument("--inbox",   action="store_true", help="Process data/public/papers/inbox/")
    parser.add_argument("--rebuild", action="store_true", help="Re-ingest all knowledge_base/input/")
    parser.add_argument("--topic",   help="Force topic/project_id label")
    parser.add_argument("--no-move", action="store_true", help="Do not move files to indexed/")
    args = parser.parse_args()

    move = not args.no_move

    if args.rebuild:
        src = str(AGENT_ROOT / "knowledge_base" / "input")
        print(ingest_path(src, topic=args.topic, move_to_indexed=False))
        return 0

    if args.inbox:
        src = str(AGENT_ROOT / "data" / "public" / "papers" / "inbox")
        print(ingest_path(src, topic=args.topic, move_to_indexed=move))
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

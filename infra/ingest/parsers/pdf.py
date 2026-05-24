"""PDF parser — uses embedded knowledge_base processor, falls back to pypdf."""
from __future__ import annotations
from pathlib import Path
import sys

AGENT_ROOT = Path(__file__).parent.parent.parent.parent
KB_SRC     = AGENT_ROOT / "knowledge_base" / "src"


def parse_pdf(path: Path) -> str:
    # Try embedded processor first (handles pymupdf + chunking logic)
    try:
        src = str(KB_SRC)
        if src not in sys.path:
            sys.path.insert(0, src)
        from processor import process_file
        result = process_file(str(path))
        if result and result.get("text"):
            return result["text"]
    except Exception:
        pass

    # Direct pypdf fallback
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
        return "\n\n".join(p for p in pages if p.strip())
    except ImportError:
        raise ImportError("pypdf required: pip install pypdf")

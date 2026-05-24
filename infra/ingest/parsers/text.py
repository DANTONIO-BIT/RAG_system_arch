"""Plain-text parsers: TXT, Markdown, CSV, TSV, JSON, HTML."""
from __future__ import annotations
from pathlib import Path


def parse_text(path: Path) -> str:
    ext = path.suffix.lower()

    if ext in (".csv", ".tsv"):
        sep = "\t" if ext == ".tsv" else ","
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[:2000])  # cap large tables

    if ext == ".json":
        import json
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            return json.dumps(data, ensure_ascii=False, indent=2)[:50000]
        except json.JSONDecodeError:
            pass

    if ext in (".html", ".htm"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            from html.parser import HTMLParser

            class _Extractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.parts: list[str] = []
                    self._skip = False
                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style"):
                        self._skip = True
                def handle_endtag(self, tag):
                    if tag in ("script", "style"):
                        self._skip = False
                def handle_data(self, data):
                    if not self._skip and data.strip():
                        self.parts.append(data.strip())

            p = _Extractor()
            p.feed(raw)
            return "\n".join(p.parts)
        except Exception:
            pass

    # TXT, MD, and fallback
    return path.read_text(encoding="utf-8", errors="replace")

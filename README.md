# Research Agent

Local-first research and study assistant. Runs entirely on your machine (Ollama + ChromaDB). MCP tools available inside Claude Code from any directory.

**Default model:** `qwen3:8b` via Ollama  
**Embedding:** `bge-m3` (1024-dim, multilingual)  
**Knowledge base:** your own PDFs, docs, and notes — never sent to the cloud

---

## Requirements

- **macOS (Apple Silicon):** Python 3.9 from CommandLineTools (`xcode-select --install`).
  `setup.py` builds the isolated `.venv` with it automatically — it is the
  interpreter proven stable with the pinned `chromadb==1.5.0`. Newer ChromaDB
  (1.5.8+) segfaults on vector queries under ARM64.
- **Windows / Linux:** Python 3.10+ is fine.
- [Ollama](https://ollama.ai) running locally with `bge-m3` and `qwen3:8b` pulled
- [Claude Code](https://claude.ai/code) CLI (for MCP registration)

> `setup.py` creates an isolated `.venv` and installs all dependencies there —
> it never touches your global/system Python, so it can't clash with other tools.

---

## First-time setup (new machine or after git clone)

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd research-agent

# 2. Copy your PDFs/docs from your backup drive into:
#    knowledge_base/input/
#    (keep the same subfolder structure: TRANSF.DIGITAL/, Nexus_IA_Big_Data_turism/, etc.)

# 3. Run setup + rebuild ChromaDB from the source files
python3 setup.py --rebuild      # macOS / Linux
python setup.py --rebuild       # Windows (or double-click setup.bat)
```

`--rebuild` re-ingests every file in `knowledge_base/input/` into a fresh ChromaDB.  
It skips files already indexed (safe to re-run). Expect ~5–20 min for a full library.

**The PDFs are NOT stored in git** — keep them on your backup drive.  
The git repo only contains code, the RAG engine, and topic config.

---

## Everyday use

Drop a file into the inbox — it's auto-ingested within seconds:

```bash
cp paper.pdf data/public/papers/inbox/
```

Or use Claude Code — MCP tools are always available:

| Tool | What it does |
|------|-------------|
| `search_memory` | Wiki-first RAG retrieval across all knowledge |
| `save_insight` | Persist a synthesis note to `wiki/auto/` |
| `save_feedback` | Save evaluator feedback |
| `call_cloud` | Escalate to OpenRouter (gated, requires confirmation) |
| `agent_status` | Health check — ChromaDB, wiki, Ollama |
| `ingest_files` | Add files to the knowledge base |

---

## Moving the folder

This repo is fully self-contained. Move it anywhere and re-run setup:

```bash
python3 setup.py   # updates config.yaml paths + re-registers MCP
```

---

## Repository structure

```
research-agent/                     ← this repo (self-contained)
  agent/                            ← MCP server, harness, tools, context builder
  infra/ingest/                     ← parsers, watcher, run_ingest
  knowledge_base/
    src/                            ← RAG engine (embeddings, query, router)
    config/topics.yaml              ← topic → collection mapping
    input/                          ← your PDFs/docs (gitignored — keep on backup drive)
    data/chroma_db/                 ← vector index (gitignored — rebuilt with --rebuild)
  data/
    public/papers/inbox/            ← drop files here for auto-ingest
    public/papers/indexed/          ← processed files (gitignored)
    public/references/              ← reference documents
    private/                        ← private notes (gitignored, never sent to cloud)
    ngs/                            ← NGS processed outputs
  projects/                         ← per-project workspaces
    _template/inbox|private|pipelines/
  wiki/auto/                        ← auto-generated knowledge nodes
  wiki/manual/                      ← your curated notes (commit these)
  config.yaml                       ← all settings
  setup.py                          ← cross-platform setup + rebuild
```

---

## Supported file formats

**Standard:** pdf, docx, pptx, xlsx, txt, md, csv, json, html  
**Omics:** fasta, vcf, bed, wig, tsv, gtf, gff  
**Rejected (generate QC summary first):** fastq, bam, cram

---

## Sharing this tool

1. Push this repo to GitHub (code only — no PDFs, no ChromaDB, no private notes)
2. Recipient clones, copies their own documents into `knowledge_base/input/`, then runs `python3 setup.py --rebuild`
3. They need Ollama with the same models: `ollama pull bge-m3 && ollama pull qwen3:8b`

Private data in `data/private/` is gitignored — it never leaves your machine.

# Research Agent

Local-first research and study assistant. Runs entirely on your machine (Ollama + ChromaDB). MCP tools available inside Claude Code from any directory.

**Default model:** `qwen3:8b` via Ollama  
**Embedding:** `bge-m3` (1024-dim, multilingual)  
**Knowledge base:** your own PDFs, docs, and notes — never sent to the cloud

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) running locally with `bge-m3` and `qwen3:8b` pulled
- [Claude Code](https://claude.ai/code) CLI (for MCP registration)

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
cp paper.pdf data/public/inbox/
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

Move `research-agent/` and `knowledge_base/` anywhere together, then re-run setup:

```bash
python3 setup.py   # updates config.yaml paths + re-registers MCP
```

---

## Repository structure

```
research-agent/          ← this repo
  agent/                 ← MCP server, harness, tools, context builder
  infra/ingest/          ← parsers, watcher, run_ingest
  wiki/auto/             ← auto-generated knowledge nodes (gitignored)
  wiki/manual/           ← your own notes (commit these if you want)
  data/public/inbox/     ← drop files here for auto-ingest
  data/private/          ← private notes (gitignored, never sent to cloud)
  config.yaml            ← all settings
  setup.py               ← cross-platform setup + rebuild

knowledge_base/          ← sibling folder (tracked separately or together)
  input/                 ← source PDFs and documents (Git LFS)
  data/chroma_db/        ← generated binary index (gitignored, rebuilt with --rebuild)
  src/                   ← RAG engine (vector store, embeddings, router)
  config/topics.yaml     ← topic → collection mapping
```

---

## Supported file formats

**Standard:** pdf, docx, pptx, xlsx, txt, md, csv, json, html  
**Omics:** fasta, vcf, bed, wig, tsv, gtf, gff  
**Rejected (generate QC summary first):** fastq, bam, cram

---

## Sharing this tool

1. Push `research-agent/` to GitHub (code only — no PDFs, no ChromaDB)
2. Recipient clones, copies their own documents into `knowledge_base/input/`, then runs `python3 setup.py --rebuild`
3. They need Ollama with the same models: `ollama pull bge-m3 && ollama pull qwen3:8b`

Private data in `data/private/` is gitignored — it never leaves your machine.

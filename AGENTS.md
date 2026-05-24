# Research Agent — AGENTS.md (OpenCode / Claude Code auto-discovery)

## What this agent does

Local-first research and study assistant. Topics: transformación digital, IA y Big Data,
emprendimiento, inmobiliario, desarrollo web — plus any new files you ingest.

Runs qwen3:8b locally. Wiki nodes pre-loaded into context at session start.
Cloud escalation (OpenRouter) only when local knowledge clearly fails.

## Three ways to use it

### 1. CLI (terminal / Cowork)
```bash
python3 agent/assistant.py "pregunta"
python3 agent/assistant.py --interactive --topic "big data turismo"
```

### 2. Claude Code (MCP — global, any directory)
The MCP server is registered globally in ~/.claude/settings.json.
Tools: search_memory · save_insight · save_feedback · call_cloud · agent_status · ingest_files

### 3. OpenCode (MCP — this project directory)
Reads opencode.json at project root. Model: ollama/qwen3:8b.

## Tool usage guidance for the model

1. **search_memory(scope="wiki")** first — pre-synthesized, cheapest.
2. **search_memory(scope="rag")** if wiki misses — raw chunks.
3. **save_insight** after every high-confidence answer (≥ 0.80).
4. **save_feedback** immediately when evaluator feedback is provided.
5. **call_cloud(confirmed=False)** last resort — show preview, wait for user yes.

## Session commands (interactive REPL)
```
/topic <hint>   rebuild context with a new topic hint
status          show ChromaDB + wiki + Ollama health
exit            quit
```

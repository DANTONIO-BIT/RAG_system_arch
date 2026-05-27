#!/usr/bin/env python3
"""
Research Agent — Cross-platform setup.

Run ONCE after cloning or moving the folder to any location.
Detects macOS / Windows / Linux automatically.

  macOS / Linux:  python3 setup.py
  Windows:        python setup.py   (or double-click setup.bat)

  After a fresh git clone (ChromaDB is empty):
    python3 setup.py --rebuild

What it does:
  1. Creates embedded knowledge_base/ structure and data/ folders
  2. Updates config.yaml (engram binary path)
  3. Installs Python dependencies (pip)
  4. Registers the MCP server globally in Claude Code
  5. Installs OS auto-start for the file watchdog:
       macOS   → LaunchAgent  (~/Library/LaunchAgents/)
       Windows → Task Scheduler (schtasks)
       Linux   → prints crontab command
  --rebuild also:
  6. Re-ingests all files from knowledge_base/input/ into a fresh ChromaDB
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import platform
import tempfile
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
AGENT_ROOT  = Path(__file__).parent.resolve()
CONFIG_PATH = AGENT_ROOT / "config.yaml"
PYTHON      = sys.executable
OS          = platform.system()      # "Darwin" | "Windows" | "Linux"
IS_WIN      = OS == "Windows"
IS_MAC      = OS == "Darwin"

VENV_DIR    = AGENT_ROOT / ".venv"

TASK_NAME   = "ResearchAgentWatcher"
LAUNCH_LABEL = "com.research-agent.watcher"

# chromadb is PINNED to 1.5.0: newer 1.5.x segfault on HNSW vector queries
# under macOS/ARM64 (Apple Silicon). See requirements.txt for details.
PACKAGES = [
    "watchdog", "pypdf", "python-docx", "openpyxl",
    "httpx", "pyyaml", "chromadb==1.5.0", "ollama", "mcp",
]


def _venv_python() -> Path:
    """Path to the interpreter inside the isolated .venv."""
    if IS_WIN:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _pick_base_python() -> str:
    """
    Choose the interpreter to build the venv with. Needs >=3.10 (mcp requires it;
    chromadb 1.5.0 runs fine on 3.10/ARM64). On macOS prefer a Homebrew
    python3.12/3.11/3.10; otherwise use the interpreter running setup.py if it is
    >=3.10, else whatever python3.1x is on PATH.
    """
    if IS_MAC:
        for name in ("python3.12", "python3.11", "python3.10"):
            found = shutil.which(name)
            if found:
                return found
    if sys.version_info >= (3, 10):
        return PYTHON
    for name in ("python3.12", "python3.11", "python3.10"):
        found = shutil.which(name)
        if found:
            return found
    return PYTHON

# ── Helpers ───────────────────────────────────────────────────────────────────

def _h(title: str) -> None:
    print(f"\n── {title} {'─' * max(0, 55 - len(title))}")


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _ypath(p: Path | str) -> str:
    """Forward-slash path string safe for YAML values on all OSes."""
    return str(p).replace("\\", "/")


# ── Step 1 — knowledge_base (now embedded) ────────────────────────────────────

def step_knowledge_base() -> Path:
    _h("1. knowledge_base (embedded)")

    kb = AGENT_ROOT / "knowledge_base"
    (kb / "data" / "chroma_db").mkdir(parents=True, exist_ok=True)
    (kb / "input").mkdir(parents=True, exist_ok=True)

    # Update engram bin path in config.yaml
    engram_bin = shutil.which("engram") or ("engram.exe" if IS_WIN else "engram")
    text = CONFIG_PATH.read_text(encoding="utf-8")
    text = re.sub(r'(bin:\s*).*', f'\\g<1>{_ypath(engram_bin)}', text)
    CONFIG_PATH.write_text(text, encoding="utf-8")

    print(f"knowledge_base embebido: {kb}")
    print(f"Pon tus PDFs en: {kb / 'input'}")
    return kb


# ── Step 1.5 — isolated venv ──────────────────────────────────────────────────

def step_venv() -> str:
    """
    Create an isolated .venv and return the path to its interpreter.

    Isolation matters: installing chromadb 1.5.0 globally would clash with other
    projects (and --break-system-packages pollutes the system Python). The venv
    keeps this tool's pinned stack independent.

    Python 3.10+ is required: the `mcp` package needs >=3.10, and chromadb 1.5.0
    is verified stable on 3.10 under Apple Silicon (the segfault was a chromadb
    1.5.8 regression, not a Python-version issue). On macOS we prefer a Homebrew
    python3.10/3.11/3.12; on Win/Linux the launching interpreter is used.
    """
    _h("1.5 Entorno virtual aislado (.venv)")

    vpy = _venv_python()
    if vpy.exists():
        print(f"venv ya existe: {VENV_DIR}")
        return str(vpy)

    base_python = _pick_base_python()

    result = _run([base_python, "-m", "venv", str(VENV_DIR)])
    if result.returncode != 0 or not vpy.exists():
        print(f"WARN: no se pudo crear venv: {result.stderr[:300]}")
        print("Continuando con el Python actual (sin aislamiento).")
        return PYTHON

    print(f"venv creado: {VENV_DIR}")
    print(f"   base: {base_python}")
    # Upgrade pip quietly inside the venv
    _run([str(vpy), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    return str(vpy)


# ── Step 2 — pip packages ─────────────────────────────────────────────────────

def step_pip(py: str) -> None:
    _h("2. Dependencias Python (en venv)")

    result = _run([py, "-m", "pip", "install", *PACKAGES, "-q"])
    if result.returncode == 0:
        print("OK — todos los paquetes instalados en el venv.")
    else:
        print(f"WARN: pip reportó errores:\n{result.stderr[:400]}")
        print("Intenta manualmente: .venv/bin/pip install -r requirements.txt")


# ── Step 3 — Claude Code MCP registration ────────────────────────────────────

def step_mcp(py: str) -> None:
    _h("3. MCP Server (Claude Code)")

    # claude CLI might be claude / claude.cmd / claude.exe
    claude = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude:
        mcp_py = AGENT_ROOT / "agent" / "mcp_server.py"
        print("AVISO: 'claude' no encontrado en PATH.")
        print("Registra manualmente después de instalar Claude Code:")
        print(f'  claude mcp add --scope user research-agent "{py}" "{mcp_py}"')
        return

    mcp_py = str(AGENT_ROOT / "agent" / "mcp_server.py")
    _run([claude, "mcp", "remove", "research-agent", "--scope", "user"])
    result = _run([claude, "mcp", "add", "--scope", "user",
                   "research-agent", py, mcp_py])
    if result.returncode == 0:
        print("research-agent registrado en Claude Code (scope: user).")
        print("Disponible desde cualquier directorio.")
    else:
        print(f"WARN: {result.stderr[:300]}")


# ── Step 4 — auto-start watchdog ─────────────────────────────────────────────

def step_autostart(py: str) -> None:
    _h("4. Watchdog — auto-arranque al login")

    # Create full data structure
    for d in [
        AGENT_ROOT / "logs",
        AGENT_ROOT / "data" / "public" / "papers" / "inbox",
        AGENT_ROOT / "data" / "public" / "papers" / "indexed",
        AGENT_ROOT / "data" / "public" / "references",
        AGENT_ROOT / "data" / "public" / "shared",
        AGENT_ROOT / "data" / "private" / "hypotheses",
        AGENT_ROOT / "data" / "private" / "notes",
        AGENT_ROOT / "data" / "private" / "synthesis",
        AGENT_ROOT / "data" / "ngs" / "reports",
        AGENT_ROOT / "data" / "ngs" / "results",
        AGENT_ROOT / "data" / "ngs" / "sequences",
        AGENT_ROOT / "projects" / "_template" / "inbox",
        AGENT_ROOT / "projects" / "_template" / "private",
        AGENT_ROOT / "projects" / "_template" / "pipelines",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    if IS_MAC:
        _autostart_launchagent(py)
    elif IS_WIN:
        _autostart_task_scheduler(py)
    else:
        watcher = AGENT_ROOT / "infra" / "ingest" / "watcher.py"
        print("Linux — agrega esto al crontab (crontab -e):")
        print(f"  @reboot {py} {watcher} >> {AGENT_ROOT}/logs/watcher.log 2>&1")


def _autostart_launchagent(py: str) -> None:
    """macOS — LaunchAgent plist."""
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist = plist_dir / f"{LAUNCH_LABEL}.plist"
    log     = AGENT_ROOT / "logs" / "watcher.log"
    watcher = AGENT_ROOT / "infra" / "ingest" / "watcher.py"

    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCH_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{py}</string>
    <string>{watcher}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>""", encoding="utf-8")

    _run(["launchctl", "unload", str(plist)])
    subprocess.run(["launchctl", "load", str(plist)])
    print(f"LaunchAgent instalado: {LAUNCH_LABEL}")
    print(f"Logs: {log}")
    print("Arranca automáticamente al iniciar sesión. KeepAlive=true (se reinicia si cae).")


def _autostart_task_scheduler(py: str) -> None:
    """Windows — Task Scheduler via schtasks + XML."""
    watcher = AGENT_ROOT / "infra" / "ingest" / "watcher.py"
    log     = AGENT_ROOT / "logs" / "watcher.log"

    # Task XML — must be UTF-16 for schtasks /xml
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Research Agent — auto-ingest watchdog</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Actions Context="Author">
    <Exec>
      <Command>{py}</Command>
      <Arguments>"{watcher}"</Arguments>
      <WorkingDirectory>{AGENT_ROOT}</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <Hidden>false</Hidden>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
</Task>"""

    # Write UTF-16 XML to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml",
                                     delete=False, encoding="utf-16") as f:
        f.write(xml)
        xml_file = f.name

    try:
        # Delete existing task silently
        _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])

        result = _run(["schtasks", "/create", "/tn", TASK_NAME,
                        "/xml", xml_file, "/f"])
        if result.returncode == 0:
            # Start immediately without waiting for next login
            _run(["schtasks", "/run", "/tn", TASK_NAME])
            print(f"Task Scheduler instalado: {TASK_NAME}")
            print(f"Logs: {log}")
            print("Arranca automáticamente al iniciar sesión.")
        else:
            print(f"WARN Task Scheduler: {result.stderr[:400]}")
            _print_windows_manual(watcher, log)
    finally:
        Path(xml_file).unlink(missing_ok=True)


def _print_windows_manual(watcher: Path, log: Path) -> None:
    print("El watchdog no pudo instalarse automáticamente.")
    print("Para iniciarlo manualmente ahora:")
    print(f'  pythonw "{watcher}"')
    print("Para auto-arranque, crea un acceso directo en:")
    print(r"  shell:startup")
    print(f'  Target: pythonw "{watcher}"')


# ── Step 5 — rebuild ChromaDB from source files ───────────────────────────────

def step_rebuild(kb: Path, py: str) -> None:
    _h("5. Rebuild ChromaDB from source files")

    input_dir = kb / "input"
    if not input_dir.exists():
        print(f"WARN: {input_dir} no existe — nada que re-ingestar.")
        return

    # Collect all supported source files
    EXTENSIONS = {
        ".pdf", ".docx", ".pptx", ".xlsx", ".xls",
        ".txt", ".md", ".csv", ".tsv", ".json", ".html",
        ".fasta", ".fa", ".vcf", ".bed", ".wig", ".gtf", ".gff",
    }
    files = [f for f in input_dir.rglob("*") if f.suffix.lower() in EXTENSIONS]
    if not files:
        print(f"No se encontraron archivos en {input_dir}")
        return

    print(f"Encontrados {len(files)} archivos para re-ingestar.")
    print("Esto puede tardar varios minutos (embedding con bge-m3)...")

    run_ingest = AGENT_ROOT / "infra" / "ingest" / "run_ingest.py"
    ok = err = 0
    for fp in sorted(files):
        result = _run([py, str(run_ingest), str(fp), "--no-move"])
        if result.returncode == 0:
            ok += 1
            print(f"  ✓ {fp.name}")
        else:
            err += 1
            short = (result.stderr or result.stdout or "")[:120].strip()
            print(f"  ✗ {fp.name}  — {short}")

    print(f"\nRebuild completado: {ok} OK, {err} errores.")
    if err:
        print("Revisa los errores arriba. Los archivos omitidos se pueden re-intentar")
        print("copiándolos al inbox: data/public/papers/inbox/")


# ── Summary ───────────────────────────────────────────────────────────────────

def _print_summary() -> None:
    log = AGENT_ROOT / "logs" / "watcher.log"
    print("\n" + "═" * 60)
    print("Setup completado.")
    print("═" * 60)
    print("\nDrop files aquí para vectorizar automáticamente:")
    print(f"  Papers públicos  →  data/public/papers/inbox/")
    print(f"  Notas privadas   →  data/private/notes/  (nunca sale del local)")
    print(f"  Resultados NGS   →  data/ngs/reports/")
    print(f"  Proyecto nuevo   →  cp -r projects/_template projects/<nombre>/")
    print(f"\nFormatos: pdf, docx, xlsx, txt, md, csv, fasta, vcf, bed, html…")
    print(f"Logs watchdog: {log}")
    print(f"\nMCP tools en Claude Code (cualquier directorio):")
    print("  search_memory · save_insight · save_feedback · call_cloud")
    print("  agent_status · ingest_files")
    if IS_WIN:
        print(f"\nDesinstalar watchdog:")
        print(f'  schtasks /delete /tn "{TASK_NAME}" /f')
    elif IS_MAC:
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"
        print(f"\nDesinstalar watchdog:")
        print(f"  launchctl unload {plist} && rm {plist}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Research Agent setup")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Re-ingest all source files into a fresh ChromaDB (use after git clone)",
    )
    args = parser.parse_args()

    print("Research Agent — Setup")
    print(f"Root: {AGENT_ROOT}")
    print(f"OS:   {OS} ({platform.machine()})")
    print(f"Python: {PYTHON} ({platform.python_version()})")

    kb = step_knowledge_base()
    py = step_venv()
    step_pip(py)
    step_mcp(py)
    step_autostart(py)

    if args.rebuild:
        step_rebuild(kb, py)

    _print_summary()


if __name__ == "__main__":
    main()

#!/bin/bash
# Research Agent — macOS/Linux setup launcher.
# Thin wrapper: toda la lógica está en setup.py (cross-platform).
set -euo pipefail
cd "$(dirname "$0")"
python3 setup.py "$@"

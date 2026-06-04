#!/usr/bin/env bash
set -euo pipefail
echo "Installing Python dependencies..."
pip install -r requirements.txt
echo
echo "Done. For the LLM judge, set your key:"
echo "  export ANTHROPIC_API_KEY=..."
echo "Next steps: see RUNBOOK.md"

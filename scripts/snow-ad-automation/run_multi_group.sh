#!/bin/bash
# Runner script for AD Group automation — Multi-Group variant
# Use this when adding ONE user to MULTIPLE AD groups in one request.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if venv exists, if not run setup
if [ ! -d ".venv" ]; then
    echo "⚠️ Virtual environment not found. Running setup..."
    ./setup.sh
fi

# Activate and run multi-group script
source .venv/bin/activate
python ad_group_multi_group.py "$@"

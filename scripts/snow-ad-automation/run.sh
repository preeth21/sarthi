#!/bin/bash
# Quick runner script for AD Group automation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if venv exists, if not run setup
if [ ! -d ".venv" ]; then
    echo "⚠️ Virtual environment not found. Running setup..."
    ./setup.sh
fi

# Activate and run
source .venv/bin/activate
python ad_group_request.py "$@"

#!/bin/bash
# Setup script for ServiceNow AD Group Automation

set -e

echo "🔧 Setting up ServiceNow AD Group Automation..."
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Found Python $PYTHON_VERSION"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
else
    echo "✅ Virtual environment already exists"
fi

# Activate and install dependencies
echo "📥 Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo ""
echo "✅ Setup complete!"
echo ""
echo "Usage:"
echo "  source .venv/bin/activate"
echo "  python ad_group_request.py --groups \"GROUP-NAME\" --users \"username\" --justification \"Reason\""
echo ""
echo "Or use the shortcut:"
echo "  ./run.sh --groups \"GROUP-NAME\" --users \"username\" --justification \"Reason\""

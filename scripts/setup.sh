#!/usr/bin/env bash
# Setup script for CV Zero Claw Agent
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== CV Zero Claw Agent Setup ==="
echo ""

# Check Python version
PYTHON=${PYTHON:-python3}
PY_VERSION=$($PYTHON --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt 3 ]] || [[ "$PY_MINOR" -lt 11 ]]; then
    echo "❌ Python 3.11+ required (found $PY_VERSION)"
    echo "   Install with: brew install python@3.12"
    exit 1
fi
echo "✅ Python $PY_VERSION"

# Create virtual environment
if [[ ! -d ".venv" ]]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv .venv
fi
source .venv/bin/activate
echo "✅ Virtual environment active"

# Install the package
echo "Installing cv-zero-claw-agent..."
pip install -e ".[dev]" --quiet

# Check for MLX (Apple Silicon)
if [[ "$(uname -m)" == "arm64" ]] && [[ "$(uname -s)" == "Darwin" ]]; then
    echo "Apple Silicon detected — installing MLX support..."
    pip install -e ".[mlx]" --quiet 2>/dev/null || echo "⚠️  MLX install failed (optional)"
fi

echo "✅ Dependencies installed"

# Setup .env
if [[ ! -f ".env" ]]; then
    cp .env.example .env
    echo "✅ Created .env from template — edit with your API keys"
else
    echo "✅ .env already exists"
fi

# Create output directories
mkdir -p output/specs output/digests papers vault

# Check ZeroClaw
if command -v zeroclaw &>/dev/null; then
    echo "✅ ZeroClaw found: $(zeroclaw --version 2>/dev/null || echo 'installed')"
else
    echo "⚠️  ZeroClaw not found. Install with: brew install zeroclaw"
fi

# Check Ollama
if command -v ollama &>/dev/null; then
    echo "✅ Ollama found"
    # Check if a vision model is available
    if ollama list 2>/dev/null | grep -qi "qwen2.5-vl\|llava"; then
        echo "✅ Vision model available"
    else
        echo "⚠️  No vision model found. Pull one with:"
        echo "   ollama pull qwen2.5-vl:7b"
    fi
else
    echo "⚠️  Ollama not found. Install from https://ollama.ai"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your configuration"
echo "  2. Pull a vision model: ollama pull qwen2.5-vl:7b"
echo "  3. Run: source .venv/bin/activate && cv-agent start"
echo ""

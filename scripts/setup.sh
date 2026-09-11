#!/usr/bin/env bash
set -euo pipefail

# Bio-Quant One-Step Setup Script
echo "Initializing Bio-Quant environment..."

if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

if [ ! -d .venv ]; then
    echo "Creating virtual environment at .venv..."
    python3 -m venv .venv
fi

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Upgrading pip and installing all dependencies..."
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt

echo "Running repository cleanliness and contract validation..."
python scripts/check_repo_cleanliness.py

echo "Bio-Quant environment setup complete."

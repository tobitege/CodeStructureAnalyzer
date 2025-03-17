#!/bin/bash

echo "==================================="
echo "Code Structure Analyzer Setup"
echo "==================================="
echo ""

# Check if Python is installed
if command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python is not installed."
    echo "Please install Python 3.10 or later from https://www.python.org/downloads/"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv .venv
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment."
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/.venv/Scripts/activate" ]; then
    source "$SCRIPT_DIR/.venv/Scripts/activate"
else
    echo "Error: Could not find activation script."
    exit 1
fi

if [ $? -ne 0 ]; then
    echo "Error: Failed to activate virtual environment."
    exit 1
fi

# Install requirements
echo "Installing requirements..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Error: Failed to install requirements."
    exit 1
fi

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cp .env.example .env
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create .env file."
        exit 1
    fi
fi

# Set up pre-commit hooks
echo "Setting up pre-commit hooks..."
pre-commit run --config ./dev_config/python/.pre-commit-config.yaml --all-files || echo "Pre-commit setup completed with warnings."

echo ""
echo "==================================="
echo "Setup completed successfully!"
echo "==================================="
echo ""
echo "To use Code Structure Analyzer:"
echo "1. Make sure LMStudio is running on localhost:1234"
echo "2. Run the tool with: python cli.py [source_dir]"
echo ""
echo "For more options, run: python cli.py --help"
echo ""

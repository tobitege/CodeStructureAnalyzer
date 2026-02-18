#!/bin/bash

echo "==================================="
echo "Code Structure Analyzer Setup"
echo "==================================="
echo ""

# Check if uv is installed
if command -v uv &> /dev/null; then
    UV_CMD="uv"
else
    echo "Error: uv is not installed."
    echo "Please install uv from https://astral.sh/uv/"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $UV_CMD venv .venv
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment."
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
if [ ! -f "$SCRIPT_DIR/.venv/bin/activate" ] && [ ! -f "$SCRIPT_DIR/.venv/Scripts/activate" ]; then
    echo "Activation script not found. Recreating virtual environment..."
    rm -rf "$SCRIPT_DIR/.venv"
    $UV_CMD venv "$SCRIPT_DIR/.venv"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to recreate virtual environment."
        exit 1
    fi
fi
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
$UV_CMD pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Error: Failed to install requirements."
    exit 1
fi

# Install the package in development mode
echo "Installing package in development mode..."
$UV_CMD pip install -e .
if [ $? -ne 0 ]; then
    echo "Error: Failed to install the package."
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
echo "2. Run the tool with: python -m csa.cli [source_dir]"
echo ""
echo "For more options, run: python -m csa.cli --help"
echo ""

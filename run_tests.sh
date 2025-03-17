#!/bin/bash

echo "==================================="
echo "Code Structure Analyzer Tests"
echo "==================================="
echo ""

# Detect the environment and activate virtual environment
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/.venv/Scripts/activate" ]; then
    source "$SCRIPT_DIR/.venv/Scripts/activate"
elif [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
elif [ -f "$SCRIPT_DIR/venv/Scripts/activate" ]; then
    source "$SCRIPT_DIR/venv/Scripts/activate"
else
    echo "Error: Could not find activation script."
    exit 1
fi

# Process command-line arguments
if [ "$1" = "--all" ]; then
    echo "Running ALL tests (including integration tests)"
    echo "Note: Integration tests require LM Studio running on localhost:1234"
    python -m pytest -v --rootdir=.
elif [ "$1" = "--integration" ]; then
    echo "Running ONLY integration tests"
    echo "Note: Integration tests require LM Studio running on localhost:1234"
    python -m pytest -v -m "integration" --rootdir=.
else
    echo "Running unit tests only (excluding integration tests)"
    echo "To run integration tests too, use: ./run_tests.sh --all"
    echo "To run only integration tests, use: ./run_tests.sh --integration"
    echo ""
    python -m pytest -v -m "not integration" --rootdir=.
fi

echo ""
echo "Tests completed."

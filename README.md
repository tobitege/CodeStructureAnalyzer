# Code Structure Analyzer (CSA)

![Code Structure Analyzer](img/csa.png)

A Python CLI application that analyzes codebases and generates structured documentation
using local LLMs and is aimed for small codebases (1000 files or less).

I've been using primarily LM Studio for the LLM provider, but Ollama is also supported.
As LLM I chose Google's gemma-3-1b-it as it's a smaller model that's still reasonably
good at code analysis and performant with my AMD 7900XT GPU.
There's lots of tweaking done to format and process the LLM's responses, but depending
on the source there may still some warnings pop up during a run, but the script
should still work and continue.

For future releases I'm contemplating to use a ChromaDB vector database to store
the codebase's metadata, so it can be queried later for specific information.

An example output file can be found [here](./trace_ai.md), which is an analysis
of the CSA project itself as of 17th March 2025. :)

## Dev Notes

This repository is experimental and was developed almost entirely using Claude 3.7 Sonnet AI.
The code structure, documentation, and implementation reflect an AI-assisted development
approach, showcasing the capabilities of modern LLMs in software engineering.

## Features

- Recursively scans source directories for code files
- Filters files by extension and excludes binary/generated folders
- Analyzes code files in chunks using local LLM's (via LMStudio or Ollama)
- Generates Markdown documentation with:
  - File structure visualization (Mermaid diagram)
  - File-by-file analysis summaries
- User-friendly CLI with:
  - Comprehensive help documentation with usage examples
  - Optional file inclusion/exclusion patterns
- LM Studio and Ollama integration:
  - Smart extraction of content from LLM responses
  - Multiple fallback mechanisms for resilient operation
- Clean markdown output
- Optional logging (csa.log)
- Supports gitignore-based file exclusion
- Custom chunk sizing for optimal LLM context utilization
- Environment variable configuration via .env files
- Cross-platform compatibility (Windows, Linux, WSL2)
- Extensive test suite with unit and integration tests
- Efficient error handling and recovery mechanisms

## Requirements

- Python 3.10 or later
- One of the following LLM providers:
  - LM Studio running locally (default, configure with LMSTUDIO_HOST)
  - Ollama running locally (configure with OLLAMA_HOST and OLLAMA_MODEL)

## Installation

### Windows

1. Clone this repository
2. Run `setup.bat` to create a virtual environment and install dependencies
3. Make sure one of the following LLM providers is running:
   - LM Studio on localhost:1234 (default)
   - Ollama on localhost:11434

### Linux/WSL2

1. Clone this repository
2. Make the shell scripts executable:

   ```bash
   chmod +x setup.sh run_tests.sh
   ```

3. Run `./setup.sh` to create a virtual environment and install dependencies
4. Make sure one of the following LLM providers is running:
   - LM Studio on localhost:1234 (default)
   - Ollama on localhost:11434

### Manual Installation

1. Clone this repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Linux/WSL2: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. In folder `csa` create `.env` file from `.env.example`

## Usage

Basic usage:

```bash
# Using the Python module directly
python -m csa.cli /path/to/source/directory

# Or if installed via pip
csa /path/to/source/directory
```

This will analyze the codebase in the specified directory and generate a `trace_ai.md` file in the current directory.

### Command-line Options

```bash
usage: python -m csa.cli [-h] [-o OUTPUT] [-c CHUNK_SIZE] [--llm-provider LLM_PROVIDER]
              [--llm-host LLM_HOST] [--lmstudio-host LMSTUDIO_HOST]
              [--ollama-host OLLAMA_HOST] [--ollama-model OLLAMA_MODEL]
              [--include INCLUDE] [--exclude EXCLUDE] [--obey-gitignore]
              [--no-dependencies] [--no-functions] [--verbose]
              [source_dir]

Code Structure Analyzer - Generate structured documentation for codebases

positional arguments:
  source_dir            Path to the source directory to analyze

optional arguments:
  -h, --help            Show this help message and examples.
  -o OUTPUT, --output OUTPUT
                        Path to the output markdown file (default: trace_ai.md)
  -c CHUNK_SIZE, --chunk-size CHUNK_SIZE
                        Number of lines to read in each chunk (default: 200)
  --folders             Recursively include files in sub-folders of the source directory.
  --llm-provider LLM_PROVIDER
                        LLM provider to use (default: lmstudio)
  --llm-host LLM_HOST   Host address for the LLM provider (default: localhost:1234)
  --lmstudio-host LMSTUDIO_HOST
                        Host address for the LM Studio provider (default: localhost:1234)
  --ollama-host OLLAMA_HOST
                        Host address for Ollama (default: localhost:11434)
  --ollama-model OLLAMA_MODEL
                        Model name for Ollama (default: qwen2.5-coder:14b)
  --include INCLUDE
  --exclude EXCLUDE
  --obey-gitignore
  --no-dependencies
  --no-functions
  --verbose, -v         Enable verbose logging
```

### Examples

```bash
# Analyze the current directory with default settings
python -m csa.cli .

# Analyze a specific directory with a custom output file
python -m csa.cli /path/to/source -o analysis.md

# Analyze with a larger chunk size (for processing more lines at once)
python -m csa.cli /path/to/source -c 200

# Analyze recursively including all sub-folders
python -m csa.cli /path/to/source --folders

# Show detailed help text with examples
python -m csa.cli --help

# Use LM Studio with a specific host
python -m csa.cli /path/to/source --llm-provider lmstudio --lmstudio-host localhost:1234

# Use Ollama as the LLM provider with specific host and model
python -m csa.cli /path/to/source --llm-provider ollama --ollama-host localhost:11434 --ollama-model qwen2.5-coder:14b

# Use the legacy --llm-host parameter (will set the appropriate provider-specific host based on llm-provider)
python -m csa.cli /path/to/source --llm-provider lmstudio --llm-host localhost:5000

# Include only specific file patterns
python -m csa.cli /path/to/source --include "*.cs,*.py"

# Exclude specific file patterns
python -m csa.cli /path/to/source --exclude "test_*.py,*.tmp"

# Obey .gitignore files in the processed folder
python -m csa.cli /path/to/source --obey-gitignore

# Disable dependencies/imports in the output
python -m csa.cli /path/to/source --no-dependencies

# Disable functions list in the output
python -m csa.cli /path/to/source --no-functions
```

## Testing

The project includes test scripts for both Windows and Linux environments:

### Windows Tests

Run tests using the batch script:

```bash
run_tests.bat             # Run unit tests only
run_tests.bat --all       # Run all tests (including integration tests)
run_tests.bat --integration  # Run only integration tests
```

### Linux/WSL2 Tests

First, ensure the shell script is executable:

```bash
chmod +x run_tests.sh
```

Then run tests:

```bash
./run_tests.sh            # Run unit tests only
./run_tests.sh --all      # Run all tests (including integration tests)
./run_tests.sh --integration  # Run only integration tests
```

Note: Integration tests require a running LLM provider. By default, they expect LM Studio running on localhost:1234, but this can be configured through environment variables.

## Development

If you're interested in contributing to CSA, follow these steps to set up your development environment:

### Setting Up Development Environment

1. Clone this repository and navigate to it
2. Create a virtual environment:

   ```bash
   python -m venv .venv
   ```

3. Activate the virtual environment:
   - Windows (Command Prompt):

     ```cmd
     .venv\Scripts\activate
     ```

   - Windows (Git Bash):

     ```bash
     source .venv/Scripts/activate
     ```

   - Linux/macOS:

     ```bash
     source .venv/bin/activate
     ```

4. Install project dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Install development dependencies including pre-commit hooks:

   ```bash
   pip install pre-commit==3.7.0
   pip install ruff mypy types-requests types-setuptools types-pyyaml types-toml
   ```

6. Set up pre-commit hooks:

   ```bash
   pre-commit run --config ./dev_config/python/.pre-commit-config.yaml --all-files
   ```

### Running Pre-commit Hooks Manually

To manually run the linting/pre-commit tools from Git Bash:

1. First, activate your virtual environment:

   ```bash
   source .venv/Scripts/activate
   ```

2. Run the full pre-commit suite:

   ```bash
   pre-commit run --config ./dev_config/python/.pre-commit-config.yaml --all-files
   ```

    This will:

    - Format your code with Ruff
    - Run linting checks
    - Check for type errors with MyPy
    - Fix common issues automatically

3. To run specific hooks individually:

   ```bash
   # Run just the ruff linter
   pre-commit run ruff --config ./dev_config/python/.pre-commit-config.yaml --all-files

   # Run just the ruff formatter
   pre-commit run ruff-format --config ./dev_config/python/.pre-commit-config.yaml --all-files

   # Run just the mypy type checker
   pre-commit run mypy --config ./dev_config/python/.pre-commit-config.yaml --all-files
   ```

4. Run the linting tools directly (without pre-commit):

   ```bash
   # Run ruff linter
   ruff check --config dev_config/python/ruff.toml .

   # Run ruff formatter
   ruff format --config dev_config/python/ruff.toml .

   # Run mypy type checker
   mypy --config-file dev_config/python/mypy.ini .
   ```

If you want to run these tools on specific files instead of the entire project, replace the `--all-files` flag with the path to the specific files, or provide the file path directly to the linting tools.

## Configuration

Configuration is handled through environment variables or a `.env` file:

- `LLM_PROVIDER`: LLM provider to use (default: "lmstudio")
- `LMSTUDIO_HOST`: Host address for the LMStudio provider (default: "localhost:1234")
- `OLLAMA_HOST`: Host address for the Ollama provider (default: "localhost:11434")
- `OLLAMA_MODEL`: Model name for Ollama (default: "qwen2.5-coder:14b")
- `CHUNK_SIZE`: Number of lines to read in each chunk (default: 200)
- `OUTPUT_FILE`: Default output file path (default: "trace_ai.md")
- `FILE_EXTENSIONS`: Comma-separated list of file extensions to analyze (default: ".cs,.py,.js,.ts,.html,.css")

## Project Structure

```txt
csa/
+-- setup.bat                # Windows setup script
+-- setup.sh                 # Linux/WSL2 setup script
+-- requirements.txt         # Dependencies
+-- pyproject.toml           # Python project configuration
+-- setup.py                 # Legacy setup file for compatibility
+-- csa/                     # Python package
|   +-- .env.example         # Example environment variables
|   +-- __init__.py          # Package initialization
|   +-- config.py            # Configuration handling
|   +-- llm.py               # LLM wrapper for different providers
|   +-- analyzer.py          # Core file analysis logic
|   +-- code_analyzer.py     # Code analysis
|   +-- cli.py               # Command-line interface (entry point)
+-- tests/                   # Test directory
+-- run_tests.bat            # Windows test script
+-- run_tests.sh             # Linux/WSL2 test script
+-- README.md                # Documentation
```

## Example Output

The generated `trace_ai.md` file will have the following structure:

```markdown
# Code Structure Analysis

Source directory: `/path/to/source/directory`
Analysis started: 2023-06-10 14:30:45

## Codebase Structure

```mermaid
graph TD
  ...
```

## Files Analyzed

```txt
<details>
<summary>path/to/file.cs</summary>

- **Lines Analyzed**: 1-150 of 150
- **Description**: This file contains a class that implements the IDisposable interface...

</details>
```

## Credits

Special credits to X user [shannonNullCode](https://x.com/shannonNullCode/status/1899257896249991314) for the initial idea and inspiration for this project.

- [LMStudio](https://lmstudio.ai/) for their LM Studio and Python SDK
- [Mermaid](https://mermaid-js.github.io/) for the diagramming library

## License

MIT License - This software is provided "as is" without warranty of any kind, express or implied, and you are free to use, modify, and distribute it under the terms of the MIT License. See the LICENSE file for the full text of the MIT License, which grants permissions to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

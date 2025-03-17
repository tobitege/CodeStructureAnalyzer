@echo off
echo ===================================
echo Code Structure Analyzer Setup
echo ===================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Error: Python is not installed or not in PATH.
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo Error: Failed to create virtual environment.
        exit /b 1
    )
)

:: Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate
if %ERRORLEVEL% NEQ 0 (
    echo Error: Failed to activate virtual environment.
    exit /b 1
)

:: Install requirements
echo Installing requirements...
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo Error: Failed to install requirements.
    exit /b 1
)

:: Install the package in development mode
echo Installing package in development mode...
pip install -e .
if %ERRORLEVEL% NEQ 0 (
    echo Error: Failed to install the package.
    exit /b 1
)

:: Create .env file if it doesn't exist
if not exist .env (
    echo Creating .env file...
    copy .env.example .env
    if %ERRORLEVEL% NEQ 0 (
        echo Error: Failed to create .env file.
        exit /b 1
    )
)

:: Set up pre-commit hooks
echo Setting up pre-commit hooks...
pre-commit run --config ./dev_config/python/.pre-commit-config.yaml --all-files || echo Pre-commit setup completed with warnings.

echo.
echo ===================================
echo Setup completed successfully!
echo ===================================
echo.
echo To use Code Structure Analyzer:
echo 1. Make sure LMStudio is running on localhost:1234
echo 2. Run the tool with: .venv\Scripts\python -m csa.cli [source_dir]
echo.
echo For more options, run: .venv\Scripts\python -m csa.cli --help
echo.

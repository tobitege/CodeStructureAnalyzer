@echo off
echo ===================================
echo Code Structure Analyzer Tests
echo ===================================
echo.

:: Activate virtual environment
call venv\Scripts\activate

:: Process command-line arguments
if /I "%1"=="--all" (
    echo Running ALL tests (including integration tests)
    echo Note: Integration tests require LM Studio running on localhost:1234
    python -m pytest -v --rootdir=.
    goto :end
) else if /I "%1"=="--integration" (
    echo Running ONLY integration tests
    echo Note: Integration tests require LM Studio running on localhost:1234
    python -m pytest -v -m "integration" --rootdir=.
    goto :end
) else (
    echo Running unit tests only (excluding integration tests)
    echo To run integration tests too, use: run_tests.bat --all
    echo To run only integration tests, use: run_tests.bat --integration
    echo.
    python -m pytest -v -m "not integration" --rootdir=.
    goto :end
)

:end
echo.
echo Tests completed.

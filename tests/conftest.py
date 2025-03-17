import shutil
import tempfile
from pathlib import Path

import pytest

from csa.code_analyzer import CodeAnalyzer, get_code_analyzer
from csa.llm import LLMProvider, get_llm_provider


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_code_file(temp_dir):
    """Create a sample Python file for testing."""
    file_path = Path(temp_dir) / 'sample.py'
    with open(file_path, 'w') as f:
        f.write("""
def hello_world():
    \"\"\"Print hello world.\"\"\"
    print("Hello, World!")

class TestClass:
    \"\"\"A test class.\"\"\"
    def __init__(self, name):
        self.name = name

    def greet(self):
        \"\"\"Greet the user.\"\"\"
        return f"Hello, {self.name}!"
""")
    return str(file_path)


@pytest.fixture
def sample_csharp_file(temp_dir):
    """Create a sample C# file for testing."""
    file_path = Path(temp_dir) / 'Sample.cs'
    with open(file_path, 'w') as f:
        f.write("""
using System;

namespace SampleApp
{
    public class Program
    {
        public static void Main(string[] args)
        {
            Console.WriteLine("Hello, World!");
        }
    }

    public class Greeter
    {
        private string _name;

        public Greeter(string name)
        {
            _name = name;
        }

        public string Greet()
        {
            return $"Hello, {_name}!";
        }
    }
}
""")
    return str(file_path)


@pytest.fixture
def llm_provider():
    """
    Get the configured LLM provider.

    If LM Studio is not running, returns a mock provider.
    """
    try:
        return get_llm_provider()
    except Exception as e:
        # If we can't connect to LM Studio, return a mock provider
        if 'LMStudioWebsocketError' in str(type(e)):
            pytest.skip('LM Studio is not running, using mock LLM provider')
            return mock_llm_provider()
        raise


@pytest.fixture
def mock_llm_provider():
    """Create a mock LLM provider for testing."""

    class MockLLMProvider(LLMProvider):
        def generate_response(self, prompt, timeout=None):
            return 'Mock response'

        def get_context_length(self) -> int:
            return 8192

    return MockLLMProvider()


@pytest.fixture
def code_analyzer():
    """
    Get a code analyzer with the configured LLM provider.

    If LM Studio is not running, returns a code analyzer with a mock provider.
    """
    try:
        return get_code_analyzer()
    except Exception as e:
        # If we can't connect to LM Studio, use a mock provider
        if 'LMStudioWebsocketError' in str(type(e)):
            pytest.skip('LM Studio is not running, using mock code analyzer')
            return mock_code_analyzer(mock_llm_provider())
        raise


@pytest.fixture
def mock_code_analyzer(mock_llm_provider):
    """Create a mock code analyzer for testing."""

    class MockCodeAnalyzer(CodeAnalyzer):
        def analyze_code_chunk(
            self,
            file_path,
            content,
            start_line,
            end_line,
            total_lines,
            structural_only=False,
            timeout=None,
        ):
            """Override to return a mock analysis with all required fields."""
            return {
                'file_path': file_path,
                'start_line': start_line,
                'end_line': end_line,
                'total_lines': total_lines,
                'description': 'Mock code analysis',
                'classes': ['MockClass'],
                'functions': ['mock_function()'],
                'dependencies': ['mock_dependency'],
            }

    return MockCodeAnalyzer(mock_llm_provider)

import os
import re
from pathlib import Path
from typing import Optional

import dotenv


class Config:
    """
    Singleton configuration class for Code Structure Analyzer.
    """

    _instance = None

    # Define supported LLM providers
    SUPPORTED_PROVIDERS = ['lmstudio', 'ollama']

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize configuration by loading environment variables."""
        # Load environment variables from .env file
        dotenv.load_dotenv()

        # LLM Provider Configuration
        llm_provider = os.getenv('LLM_PROVIDER', 'lmstudio')
        if llm_provider.lower() not in [p.lower() for p in self.SUPPORTED_PROVIDERS]:
            # Log a warning but default to a supported provider
            print(f'WARNING: Unsupported LLM provider: {llm_provider}')
            print(
                f"Defaulting to 'lmstudio'. Supported providers: {', '.join(self.SUPPORTED_PROVIDERS)}"
            )
            llm_provider = 'lmstudio'
        self.LLM_PROVIDER = llm_provider

        # LMStudio Host - this value should be set in .env file
        # Example in .env: LMSTUDIO_HOST=localhost:1234
        lmstudio_host = os.getenv('LMSTUDIO_HOST', 'localhost:1234')
        if not re.match(r'^[a-zA-Z0-9.-]+:[0-9]+$', lmstudio_host):
            # Log a warning but default to a valid host format
            print(f'WARNING: Invalid LMStudio host format: {lmstudio_host}')
            print(
                "Defaulting to 'localhost:1234'. Host should be in the format 'hostname:port'"
            )
            lmstudio_host = 'localhost:1234'
        self.LMSTUDIO_HOST = lmstudio_host

        # Ollama Host - this value should be set in .env file
        # Example in .env: OLLAMA_HOST=localhost:11434
        ollama_host = os.getenv('OLLAMA_HOST', 'localhost:11434')
        if not re.match(r'^[a-zA-Z0-9.-]+:[0-9]+$', ollama_host):
            # Log a warning but default to a valid host format
            print(f'WARNING: Invalid OLLAMA host format: {ollama_host}')
            print(
                "Defaulting to 'localhost:11434'. Host should be in the format 'hostname:port'"
            )
            ollama_host = 'localhost:11434'
        self.OLLAMA_HOST = ollama_host

        # Ollama Model Configuration - this value should be set in .env file
        # Example in .env: OLLAMA_MODEL=qwen2.5-coder:14b
        self.OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:14b')

        # Analysis Configuration
        try:
            self.CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '200'))
        except ValueError:
            print('WARNING: Invalid CHUNK_SIZE value. Defaulting to 200.')
            self.CHUNK_SIZE = 200

        self.OUTPUT_FILE = os.getenv('OUTPUT_FILE', 'trace_ai.md')

        # File Extensions to Analyze
        self.FILE_EXTENSIONS = os.getenv(
            'FILE_EXTENSIONS', '.cs,.py,.js,.ts,.html,.css'
        ).split(',')

        # Binary and Generated Folders to Exclude
        self.EXCLUDED_FOLDERS = [
            'obj',
            'debug',
            'release',
            'Properties',
            'bin',
            'node_modules',
            '.git',
            '__pycache__',
            'venv',
            '.venv',
            'env',
            '.env',
            'dist',
            'build',
        ]

        # Whether to obey .gitignore files in the processed folder
        self.OBEY_GITIGNORE = os.getenv('OBEY_GITIGNORE', 'False').lower() in (
            'true',
            'yes',
            '1',
        )

    def get_project_root(self) -> Path:
        """Return the project root directory."""
        return Path(__file__).parent

    def get_output_path(self, output_file: Optional[str] = None) -> Path:
        """Return the full path to the output file."""
        if output_file is None:
            output_file = self.OUTPUT_FILE
        return self.get_project_root() / output_file

    @classmethod
    def reload(cls):
        """Reload configuration from environment variables."""
        cls._instance = None
        # Re-initialize will happen on next access
        return Config()  # Return a fresh instance

    @property
    def LLM_HOST(self) -> str:
        """
        Returns the host for the currently selected LLM provider.
        This property exists for backward compatibility.

        Returns:
            The host address string for the current LLM provider.
        """
        if self.LLM_PROVIDER.lower() == 'lmstudio':
            return self.LMSTUDIO_HOST
        elif self.LLM_PROVIDER.lower() == 'ollama':
            return self.OLLAMA_HOST
        else:
            # Default to LMStudio host if provider is unknown
            return self.LMSTUDIO_HOST


# Create the singleton instance
config = Config()

# Store a reference to the original instance for tests
_original_instance = config


# Add a function to restore the original instance
def restore_original_instance():
    """Restore the original singleton instance."""
    Config._instance = _original_instance
    return _original_instance

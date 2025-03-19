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

    def _handle_host_format(
        self, host_value: str, host_type: str, current_provider: str, default_host: str
    ) -> str:
        """
        Helper method to handle host format validation and conversion.

        Args:
            host_value: The host value to validate
            host_type: Type of host (e.g., 'LMStudio', 'Ollama')
            current_provider: The current LLM provider
            default_host: Default host value if validation fails

        Returns:
            Validated and potentially converted host value
        """
        # Handle URL format (e.g., http://localhost:1234)
        if re.match(r'^https?://', host_value):
            url_match = re.match(r'^https?://([^/:]+)(:[0-9]+)?', host_value)
            if url_match and self.LLM_PROVIDER.lower() == current_provider.lower():
                host = url_match.group(1)
                port = (
                    url_match.group(2)[1:] if url_match.group(2) else '80'
                )  # Default to port 80
                print(
                    f'WARNING: Converting URL format to hostname:port format: {host_value} -> {host}:{port}'
                )
                host_value = f'{host}:{port}'
            # Even if we can't parse it, store the value as provided
        # Only validate the format if this is the selected provider
        elif self.LLM_PROVIDER.lower() == current_provider.lower() and not re.match(
            r'^[a-zA-Z0-9.-]+:[0-9]+$', host_value
        ):
            # Log a warning but default to a valid host format
            print(f'WARNING: Invalid {host_type} host format: {host_value}')
            print(
                f"Defaulting to '{default_host}'. Host should be in the format 'hostname:port'"
            )
            host_value = default_host

        return host_value

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
        self.LMSTUDIO_HOST = self._handle_host_format(
            lmstudio_host, 'LMStudio', 'lmstudio', 'localhost:1234'
        )

        # Ollama Host - this value should be set in .env file
        # Example in .env: OLLAMA_HOST=localhost:11434
        ollama_host = os.getenv('OLLAMA_HOST', 'localhost:11434')
        self.OLLAMA_HOST = self._handle_host_format(
            ollama_host, 'Ollama', 'ollama', 'localhost:11434'
        )

        # Ollama Model Configuration - this value should be set in .env file
        # Example in .env: OLLAMA_MODEL=qwen2.5-coder:14b
        self.OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:14b')

        # Analysis Configuration
        try:
            self.CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '200'))
        except ValueError:
            print('WARNING: Invalid CHUNK_SIZE value. Defaulting to 200.')
            self.CHUNK_SIZE = 200

        # Store output file as string - will be converted to Path when needed
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
        """
        Return the full path to the output file, handling both Windows and Linux paths.

        Args:
            output_file: Optional output file path or name. If None, uses self.OUTPUT_FILE.

        Returns:
            Path object representing the absolute path to the output file.
        """
        if output_file is None:
            output_file = self.OUTPUT_FILE

        # Handle potential Windows-style paths (like 'd:\temp') on all platforms
        if os.name == 'nt' or (
            isinstance(output_file, str) and re.match(r'^[a-zA-Z]:\\', output_file)
        ):
            # If we're on Windows or the path is a Windows-style absolute path
            try:
                output_path = Path(output_file)
                if output_path.is_absolute():
                    return output_path
            except Exception:
                # Fall back to joining with project root if there's any issue
                pass

        # Handle potential Unix-style paths (like '/mnt/d/temp') on all platforms
        if os.name != 'nt' or (
            isinstance(output_file, str) and output_file.startswith('/')
        ):
            # If we're on Unix or the path is a Unix-style absolute path
            try:
                output_path = Path(output_file)
                if output_path.is_absolute():
                    return output_path
            except Exception:
                # Fall back to joining with project root if there's any issue
                pass

        # For any other case, treat as a relative path
        # On non-Windows platforms, convert Windows-style path separators to platform-specific
        if os.name != 'nt' and isinstance(output_file, str) and '\\' in output_file:
            output_file = output_file.replace('\\', '/')

        return self.get_project_root().joinpath(output_file)

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

from pathlib import Path
from unittest.mock import patch

from csa.config import config


def test_get_project_root():
    """Test the get_project_root function."""
    root = config.get_project_root()
    assert isinstance(root, Path)
    assert root.exists()
    assert (root / 'config.py').exists()


def test_get_output_path(tmp_path, monkeypatch):
    """Test the get_output_path function."""
    monkeypatch.chdir(tmp_path)

    # Test with default output file
    default_path = config.get_output_path()
    assert isinstance(default_path, Path)
    assert default_path.name == config.OUTPUT_FILE
    assert default_path.parent == tmp_path
    default_path.write_text('test', encoding='utf-8')
    assert default_path.exists()

    # Test with custom output file
    custom_file = 'custom_output.md'
    custom_path = config.get_output_path(custom_file)
    assert isinstance(custom_path, Path)
    assert custom_path.name == custom_file
    assert custom_path.parent == tmp_path
    custom_path.write_text('test', encoding='utf-8')
    assert custom_path.exists()

    # Absolute paths should be preserved.
    absolute_output = tmp_path / 'absolute.md'
    absolute_path = config.get_output_path(str(absolute_output))
    assert absolute_path == absolute_output


def test_env_variables():
    """Test that environment variables are loaded correctly."""
    # Use dotenv to load the values directly from the .env file

    import dotenv

    # Load the environment from the .env file
    env_path = config.get_project_root() / '.env'
    if env_path.exists():
        dotenv_values = dotenv.dotenv_values(env_path)
    else:
        # If .env doesn't exist, use the .env.example file
        env_path = config.get_project_root() / '.env.example'
        dotenv_values = dotenv.dotenv_values(env_path)

    # Compare config values with values from dotenv file
    assert config.LLM_PROVIDER == dotenv_values.get('LLM_PROVIDER', 'lmstudio')

    # Test LMSTUDIO_HOST value
    assert config.LMSTUDIO_HOST == dotenv_values.get('LMSTUDIO_HOST', 'localhost:1234')

    # Test LLM_HOST property returns the correct host based on provider
    if config.LLM_PROVIDER.lower() == 'lmstudio':
        assert config.LLM_HOST == config.LMSTUDIO_HOST
    elif config.LLM_PROVIDER.lower() == 'ollama':
        assert config.LLM_HOST == config.OLLAMA_HOST

    assert config.CHUNK_SIZE == int(dotenv_values.get('CHUNK_SIZE', '200'))
    assert config.OUTPUT_FILE == dotenv_values.get('OUTPUT_FILE', 'trace_ai.md')

    # Check file extensions from dotenv
    file_extensions = dotenv_values.get(
        'FILE_EXTENSIONS', '.cs,.py,.js,.ts,.html,.css'
    ).split(',')
    for ext in file_extensions:
        assert ext in config.FILE_EXTENSIONS


def test_excluded_folders():
    """Test that excluded folders list is properly defined."""
    # Check that common binary and generated folders are excluded
    assert 'bin' in config.EXCLUDED_FOLDERS
    assert 'obj' in config.EXCLUDED_FOLDERS
    assert 'node_modules' in config.EXCLUDED_FOLDERS
    assert '__pycache__' in config.EXCLUDED_FOLDERS
    assert 'venv' in config.EXCLUDED_FOLDERS


def test_singleton_instance():
    """Test that Config is a proper singleton."""
    from csa.config import Config, config, restore_original_instance

    # Make sure we're using the original instance
    restore_original_instance()

    # Getting a new instance should return the same object
    config2 = Config()
    assert config2 is config

    # Modifying one instance affects the other
    original_chunk_size = config.CHUNK_SIZE
    try:
        config2.CHUNK_SIZE = 500
        assert config.CHUNK_SIZE == 500
    finally:
        # Reset for other tests
        config.CHUNK_SIZE = original_chunk_size


def test_invalid_llm_config():
    """Test validation of invalid LLM configuration."""
    import os

    from csa.config import Config

    original_provider = os.environ.get('LLM_PROVIDER', '')
    original_lmstudio_host = os.environ.get('LMSTUDIO_HOST', '')
    original_chunk_size = os.environ.get('CHUNK_SIZE', '')
    original_llm_host = os.environ.get('LLM_HOST', '')

    try:
        os.environ['LLM_PROVIDER'] = 'invalid_provider'
        os.environ['LMSTUDIO_HOST'] = 'localhost-missing-port'
        os.environ['CHUNK_SIZE'] = 'not_a_number'

        Config._instance = None

        with patch('builtins.print') as mock_print:
            test_config = Config()

            assert test_config.LLM_PROVIDER == 'lmstudio'
            mock_print.assert_any_call(
                'WARNING: Unsupported LLM provider: invalid_provider'
            )

            assert test_config.LMSTUDIO_HOST == 'localhost:1234'
            mock_print.assert_any_call(
                'WARNING: Invalid LMStudio host format: localhost-missing-port'
            )
            mock_print.assert_any_call(
                "Defaulting to 'localhost:1234'. Host should be in the format 'hostname:port'"
            )

            assert test_config.LLM_HOST == test_config.LMSTUDIO_HOST

            assert test_config.CHUNK_SIZE == 200
            mock_print.assert_any_call(
                'WARNING: Invalid CHUNK_SIZE value. Defaulting to 200.'
            )

    finally:
        if original_provider:
            os.environ['LLM_PROVIDER'] = original_provider
        else:
            os.environ.pop('LLM_PROVIDER', None)

        if original_lmstudio_host:
            os.environ['LMSTUDIO_HOST'] = original_lmstudio_host
        else:
            os.environ.pop('LMSTUDIO_HOST', None)

        if original_llm_host:
            os.environ['LLM_HOST'] = original_llm_host
        else:
            os.environ.pop('LLM_HOST', None)

        if original_chunk_size:
            os.environ['CHUNK_SIZE'] = original_chunk_size
        else:
            os.environ.pop('CHUNK_SIZE', None)

        from csa.config import restore_original_instance

        restore_original_instance()

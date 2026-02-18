import socket
from unittest.mock import MagicMock, patch

import pytest

from csa.cli import check_host_reachable, main, parse_args
from csa.config import config
from csa.llm import LMStudioWebsocketError, OllamaError


def test_parse_args():
    """Test command-line argument parsing."""
    with patch('sys.argv', ['cli.py', '/test/dir']):
        args = parse_args()
        assert args.source_dir == '/test/dir'
        assert args.output == config.OUTPUT_FILE
        assert args.chunk_size == config.CHUNK_SIZE
        assert args.llm_provider == config.LLM_PROVIDER
        assert args.llm_host is None
        assert args.lmstudio_host is None
        assert args.ollama_host is None


@patch('csa.cli.analyze_codebase', return_value='/tmp/output.md')
@patch('csa.cli.LMStudioProvider')
def test_main_with_source_dir_returns_zero(mock_provider_cls, mock_analyze_codebase):
    """Main flow should return 0 for successful analysis."""
    mock_provider_cls.return_value = MagicMock()

    with patch('sys.argv', ['cli.py', '/test/dir']), patch(
        'os.path.exists', return_value=True
    ):
        result = main()

    assert result == 0
    assert mock_analyze_codebase.call_count == 1


@patch('csa.cli.create_parser')
def test_main_without_source_dir(mock_create_parser):
    """Main should print help and return 1 when source_dir is missing."""
    mock_parser = MagicMock()
    mock_parser.parse_args.return_value = MagicMock(source_dir=None, help=False)
    mock_create_parser.return_value = mock_parser

    with patch('sys.argv', ['cli.py']):
        result = main()

    mock_parser.print_help.assert_called_once()
    assert result == 1


def test_main_source_dir_not_found():
    """Main should raise FileNotFoundError when source directory is missing."""
    with patch('sys.argv', ['cli.py', '/nonexistent/dir']):
        with pytest.raises(FileNotFoundError) as excinfo:
            main()
        error_msg = str(excinfo.value)
        assert any(
            path in error_msg for path in ['nonexistent/dir', 'nonexistent\\dir']
        )


@patch('os.path.exists', return_value=True)
def test_main_with_invalid_llm_provider(mock_exists):
    """Main should fail fast for unsupported provider names."""
    with patch('sys.argv', ['cli.py', '.', '--llm-provider', 'invalid_provider']):
        with patch('builtins.print') as mock_print:
            result = main()
    assert result == 1
    mock_print.assert_any_call('\nERROR: Unsupported LLM provider: invalid_provider')


@patch('socket.create_connection')
def test_check_host_reachable(mock_create_connection):
    """check_host_reachable should use per-socket timeout and no global timeout."""
    mock_socket_context = MagicMock()
    mock_create_connection.return_value = mock_socket_context

    with patch('socket.setdefaulttimeout') as mock_setdefaulttimeout:
        result = check_host_reachable('localhost', 1234)
        assert result is True
        mock_setdefaulttimeout.assert_not_called()

    mock_create_connection.side_effect = socket.error()
    result = check_host_reachable('localhost', 9999)
    assert result is False


@pytest.mark.parametrize(
    'argv, expected_lmstudio_host, expected_ollama_host',
    [
        (
            ['cli.py', '/test/dir', '--llm-provider', 'lmstudio', '--llm-host', 'legacy:5000'],
            'legacy:5000',
            None,
        ),
        (
            [
                'cli.py',
                '/test/dir',
                '--llm-provider',
                'lmstudio',
                '--llm-host',
                'legacy:5000',
                '--lmstudio-host',
                'explicit:5001',
            ],
            'explicit:5001',
            None,
        ),
        (
            ['cli.py', '/test/dir', '--llm-provider', 'ollama', '--llm-host', 'legacy:11434'],
            None,
            'legacy:11434',
        ),
        (
            [
                'cli.py',
                '/test/dir',
                '--llm-provider',
                'ollama',
                '--llm-host',
                'legacy:11434',
                '--ollama-host',
                'explicit:11435',
            ],
            None,
            'explicit:11435',
        ),
    ],
)
@patch('csa.cli.analyze_codebase', return_value='/tmp/output.md')
@patch('csa.cli.check_host_reachable', return_value=True)
@patch('os.path.exists', return_value=True)
def test_host_precedence(
    mock_exists,
    mock_reachable,
    mock_analyze_codebase,
    argv,
    expected_lmstudio_host,
    expected_ollama_host,
):
    """Provider-specific host args must override legacy --llm-host."""
    with patch('sys.argv', argv), patch('csa.cli.LMStudioProvider') as mock_lm_cls, patch(
        'csa.cli.OllamaProvider'
    ) as mock_ollama_cls:
        mock_lm_cls.return_value = MagicMock()
        mock_ollama_cls.return_value = MagicMock()
        result = main()

    assert result == 0
    if expected_lmstudio_host is not None:
        mock_lm_cls.assert_called_once_with(host=expected_lmstudio_host)
        mock_ollama_cls.assert_not_called()
    if expected_ollama_host is not None:
        mock_ollama_cls.assert_called_once_with(
            host=expected_ollama_host, model=config.OLLAMA_MODEL
        )
        mock_lm_cls.assert_not_called()


@patch('os.path.exists', return_value=True)
@patch('csa.cli.LMStudioProvider')
@patch('csa.cli.analyze_codebase', side_effect=LMStudioWebsocketError('boom'))
def test_main_handles_lmstudio_error(
    mock_analyze_codebase, mock_provider_cls, mock_exists, capsys
):
    """LM Studio errors should hit provider-specific error handling."""
    mock_provider_cls.return_value = MagicMock()

    with patch(
        'sys.argv',
        ['cli.py', '/test/dir', '--llm-provider', 'lmstudio', '--lmstudio-host', 'local:1234'],
    ):
        result = main()

    captured = capsys.readouterr()
    assert result == 1
    assert 'Unable to connect to LM Studio at local:1234' in captured.out


@patch('os.path.exists', return_value=True)
@patch('csa.cli.OllamaProvider')
@patch('csa.cli.analyze_codebase', side_effect=OllamaError('boom'))
def test_main_handles_ollama_error(
    mock_analyze_codebase, mock_provider_cls, mock_exists, capsys
):
    """Ollama errors should hit provider-specific error handling."""
    mock_provider_cls.return_value = MagicMock()

    with patch(
        'sys.argv',
        ['cli.py', '/test/dir', '--llm-provider', 'ollama', '--ollama-host', 'local:11434'],
    ):
        result = main()

    captured = capsys.readouterr()
    assert result == 1
    assert 'Unable to connect to Ollama at local:11434' in captured.out

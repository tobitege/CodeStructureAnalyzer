import argparse
import logging
import os
import re
import socket
import sys
import threading
from logging import Handler
from typing import Optional, Tuple

from csa.analyzer import analyze_codebase
from csa.config import config
from csa.llm import (
    LMStudioProvider,
    LMStudioWebsocketError,
    OllamaError,
    OllamaProvider,
)

# Configure logging
handlers: list[Handler] = [logging.StreamHandler(), logging.FileHandler('csa.log')]
# Ensure handlers only show INFO and above
for handler in handlers:
    handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=handlers,
)

# Configure websocket and HTTP loggers to emit at DEBUG level
for logger_name in ['_AsyncWebsocketThread', 'SyncLMStudioWebsocket', 'httpx']:
    logger = logging.getLogger(logger_name)
    # Prevent propagation to root logger
    logger.propagate = False
    # Set to debug level
    logger.setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

TITLE = """
###################################################
#       Code Structure Analyzer (CSA)             #
#       Generate documentation for codebases      #
###################################################
"""


def create_parser():
    """Create the command-line argument parser with custom help text."""
    epilog_text = """
Examples:
  # Analyze the current directory with default settings
  python -m csa.cli .

  # Analyze a specific directory with a custom output file
  python -m csa.cli /path/to/source -o analysis.md

  # Analyze a specific directory and store results in a ChromaDB vector database
  python -m csa.cli /path/to/source --reporter chromadb --output data/chroma

  # Analyze with a larger chunk size (for processing more lines at once)
  python -m csa.cli /path/to/source -c 200

  # Use a specific LLM host (for LM Studio)
  python -m csa.cli /path/to/source --llm-host localhost:5000

  # Use Ollama as the LLM provider with specific host and model
  python -m csa.cli /path/to/source --llm-provider ollama --ollama-host localhost:11434 --ollama-model qwen2.5-coder:14b

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
"""

    parser = argparse.ArgumentParser(
        description='Code Structure Analyzer - Generate structured documentation for codebases',
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog_text,
    )
    # Store epilog text as a regular attribute for later use
    setattr(parser, 'custom_epilog', epilog_text)
    parser.add_argument(
        '-h', '--help', action='store_true', help='Show this help message and examples.'
    )
    parser.add_argument(
        '--folders',
        action='store_true',
        help='Recursively include files in sub-folders of the source directory.',
    )

    parser.add_argument(
        'source_dir',
        nargs='?',
        default=None,
        help='Path to the source directory to analyze',
    )

    parser.add_argument(
        '-o',
        '--output',
        help=f'Path to the output markdown file or chromadb directory (default: {config.OUTPUT_FILE})',
        default=config.OUTPUT_FILE,
    )

    parser.add_argument(
        '--reporter',
        help='Reporter type to use (markdown or chromadb)',
        choices=['markdown', 'chromadb'],
        default='markdown',
    )

    parser.add_argument(
        '-c',
        '--chunk-size',
        help=f'Number of lines to read in each chunk (default: {config.CHUNK_SIZE})',
        type=int,
        default=config.CHUNK_SIZE,
    )

    parser.add_argument(
        '--llm-provider',
        help=f'LLM provider to use (default: {config.LLM_PROVIDER})',
        default=config.LLM_PROVIDER,
    )

    parser.add_argument(
        '--llm-host',
        help='Legacy host for selected provider (fallback only when provider-specific host is not explicitly set)',
        default=None,
    )

    parser.add_argument(
        '--lmstudio-host',
        help=f'Host address for the LM Studio provider (default: {config.LMSTUDIO_HOST}); overrides --llm-host',
        default=None,
    )

    parser.add_argument(
        '--ollama-host',
        help=f'Host address for Ollama (default: {config.OLLAMA_HOST}); overrides --llm-host',
        default=None,
    )

    parser.add_argument(
        '--ollama-model',
        help=f'Model name for Ollama (default: {config.OLLAMA_MODEL})',
        default=config.OLLAMA_MODEL,
    )

    parser.add_argument(
        '--include',
        help='Comma-separated list in double quotes of file patterns to include (gitignore style)',
        default=None,
    )

    parser.add_argument(
        '--exclude',
        help='Comma-separated list in double quotes of file patterns to exclude (gitignore style)',
        default=None,
    )

    parser.add_argument(
        '--obey-gitignore',
        action='store_true',
        help=f'Whether to obey .gitignore files in the processed folder (default: {config.OBEY_GITIGNORE})',
        default=config.OBEY_GITIGNORE,
    )

    parser.add_argument(
        '--no-dependencies',
        action='store_true',
        help='Disable output of dependencies/imports in the analysis',
        default=False,
    )

    parser.add_argument(
        '--no-functions',
        action='store_true',
        help='Disable output of functions list in the analysis',
        default=False,
    )

    parser.add_argument(
        '--verbose', '-v', action='store_true', help='Enable verbose logging'
    )

    return parser


def parse_args():
    """Parse command-line arguments."""
    parser = create_parser()
    args = parser.parse_args()

    if args.help:
        parser.print_help()
        print(parser.custom_epilog)
        sys.exit(0)

    # If source_dir is None but we have other args, print a friendly message about arg order
    if args.source_dir is None and len(sys.argv) > 1:
        print(
            "\nNOTE: When using flags with cli.py, make sure to specify the source directory last or use '.' for current directory"
        )
        print('Example: python cli.py --no-dependencies -o output.md .\n')

    return args


def check_dependencies():
    """Check for required dependencies and show warnings."""
    try:
        import pathspec  # noqa: F401

        return True
    except ImportError:
        print('WARNING: pathspec is not installed. Please install it using:')
        print('pip install pathspec>=0.12.1')
        print('Gitignore-style pattern matching will be limited without it.')
        return False


def check_host_reachable(host, port, timeout=1):
    """
    Check if a host:port is reachable.

    Args:
        host: Hostname or IP address
        port: Port number
        timeout: Connection timeout in seconds

    Returns:
        bool: True if reachable, False otherwise
    """
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
        return True
    except Exception:
        return False


def validate_host_format(host_value: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate and potentially convert host format.

    Args:
        host_value: The host string to validate

    Returns:
        Tuple containing:
        - Boolean indicating if format is valid
        - Converted host string if successful, None otherwise
        - Error message if validation failed, None otherwise
    """
    # Check for URL format (http://hostname:port)
    if re.match(r'^https?://', host_value):
        url_match = re.match(r'^https?://([^/:]+)(:[0-9]+)?', host_value)
        if url_match:
            host = url_match.group(1)
            port = (
                url_match.group(2)[1:] if url_match.group(2) else '80'
            )  # Default to port 80 for HTTP
            hostname_port = f'{host}:{port}'
            return (
                True,
                hostname_port,
                f'Converting URL format to hostname:port format: {host_value} -> {hostname_port}',
            )
        else:
            return False, None, f'Invalid URL format: {host_value}'
    # Check for hostname:port format
    elif not re.match(r'^[a-zA-Z0-9.-]+:[0-9]+$', host_value):
        return False, None, f'Invalid host format: {host_value}'

    # Already in correct format
    return True, host_value, None


def validate_and_resolve_host(
    host_value: str, host_type: str, check_reachable: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Validate a host value, convert if needed, and set in environment.

    Args:
        host_value: The host value to validate and normalize
        host_type: Type of host for error messages
        check_reachable: Whether to check if the host is reachable

    Returns:
        Tuple of (success, normalized_host)
    """
    is_valid, converted_host, message = validate_host_format(host_value)

    if not is_valid:
        print(f'\nERROR: {message}')
        print(
            f"Host should be in the format 'hostname:port' (e.g., 'localhost:{1234 if host_type == 'LMStudio' else 11434}')"
        )
        print("Or a valid URL (e.g., 'http://localhost:1234')")
        return False, None

    resolved_host = converted_host if converted_host is not None else host_value

    if message and converted_host is not None:
        print(f'\nWARNING: {message}')

    # Check if host is reachable (optional early warning)
    if check_reachable:
        host, port = resolved_host.split(':')
        if not check_host_reachable(host, port):
            print(f'\nWARNING: Cannot connect to {host_type} provider at {resolved_host}')
            print('Make sure the service is running and accessible.')
            print('Continuing execution, but analysis may fail later.\n')
            logger.warning(f'{host_type} host {resolved_host} is not reachable')

    return True, resolved_host


def analyze_in_thread(
    source_dir,
    output_file,
    chunk_size,
    include_patterns,
    exclude_patterns,
    obey_gitignore,
    llm_provider,
    disable_dependencies,
    disable_functions,
    result,
    cancel_event,
    folders,
    reporter_type,
):
    """Run the analysis in a separate thread to allow for cancellation."""
    try:
        result['output_path'] = None

        def should_cancel():
            # Check if cancellation has been requested
            return cancel_event.is_set()

        output = analyze_codebase(
            source_dir=source_dir,
            output_file=output_file,
            chunk_size=chunk_size,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            obey_gitignore=obey_gitignore,
            llm_provider=llm_provider,
            disable_dependencies=disable_dependencies,
            disable_functions=disable_functions,
            cancel_callback=should_cancel,
            folders=folders,
            reporter_type=reporter_type,
        )

        # Handle MagicMock objects by converting to string
        if hasattr(output, '_extract_mock_name'):
            # This is a mock object, convert to string to avoid issues
            result['output'] = str(output)
        else:
            result['output'] = output

        # Only set success to True if output isn't empty
        result['success'] = bool(output)
    except Exception as e:
        logger.error(f'Error during analysis: {str(e)}')
        result['error'] = e
        result['success'] = False


def main():
    """Run the code structure analyzer with command-line arguments."""

    # Create a cancellation event
    cancel_event = threading.Event()

    # Store a reference to analysis thread
    analysis_thread = None
    selected_provider = config.LLM_PROVIDER.lower()
    selected_lmstudio_host = config.LMSTUDIO_HOST
    selected_ollama_host = config.OLLAMA_HOST
    selected_ollama_model = config.OLLAMA_MODEL

    try:
        # Print title first
        print(TITLE)
        args = parse_args()

        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            for handler in logging.getLogger().handlers:
                handler.setLevel(logging.DEBUG)

        # Check dependencies
        check_dependencies()

        # If no source directory is provided, print help and exit with error message
        if args.source_dir is None:
            parser = create_parser()
            print("\nERROR: Missing required argument 'source_dir'")
            print('Please specify a source directory to analyze.\n')
            parser.print_help()
            return 1

        # Check if source_dir exists before proceeding
        source_dir = os.path.abspath(args.source_dir)
        if not os.path.exists(source_dir):
            logger.error(f'Error: Source directory not found: {source_dir}')
            raise FileNotFoundError(f'Source directory not found: {source_dir}')

        include_patterns = None
        if args.include:
            include_patterns = [p.strip() for p in args.include.split(',')]
            # Detect likely quoting mistakes where other options got swallowed
            invalid_patterns = [p for p in include_patterns if p.startswith('-')]
            if invalid_patterns:
                print('\nERROR: Detected invalid include pattern(s):', ', '.join(invalid_patterns))
                print('It looks like some CLI flags were captured inside the --include value.')
                print('Ensure you wrap the patterns in quotes and place other flags AFTER the pattern, e.g.\n  --include "*.cs" --folders -o c:/temp/out.md')
                return 1

        exclude_patterns = None
        if args.exclude:
            exclude_patterns = [p.strip() for p in args.exclude.split(',')]
            invalid_patterns = [p for p in exclude_patterns if p.startswith('-')]
            if invalid_patterns:
                print('\nERROR: Detected invalid exclude pattern(s):', ', '.join(invalid_patterns))
                print('It looks like some CLI flags were captured inside the --exclude value.')
                print('Ensure you wrap the patterns in quotes and place other flags AFTER the pattern, e.g.\n  --exclude "*.Test.cs" --folders -o c:/temp/out.md')
                return 1

        supported_providers = ['lmstudio', 'ollama']
        selected_provider = (
            args.llm_provider.lower() if args.llm_provider else config.LLM_PROVIDER.lower()
        )
        if selected_provider not in supported_providers:
            print(f'\nERROR: Unsupported LLM provider: {args.llm_provider}')
            print(f"Supported providers: {', '.join(supported_providers)}")
            return 1

        selected_lmstudio_host = config.LMSTUDIO_HOST
        selected_ollama_host = config.OLLAMA_HOST
        selected_ollama_model = args.ollama_model or config.OLLAMA_MODEL

        legacy_host: Optional[str] = None
        if args.llm_host:
            legacy_host_type = 'Ollama' if selected_provider == 'ollama' else 'LMStudio'
            valid_host, resolved_host = validate_and_resolve_host(
                args.llm_host,
                legacy_host_type,
                check_reachable=True,
            )
            if not valid_host or resolved_host is None:
                return 1
            legacy_host = resolved_host

        if args.lmstudio_host:
            valid_host, resolved_host = validate_and_resolve_host(
                args.lmstudio_host, 'LMStudio'
            )
            if not valid_host or resolved_host is None:
                return 1
            selected_lmstudio_host = resolved_host
        elif selected_provider == 'lmstudio' and legacy_host:
            selected_lmstudio_host = legacy_host

        if args.ollama_host:
            valid_host, resolved_host = validate_and_resolve_host(
                args.ollama_host, 'Ollama'
            )
            if not valid_host or resolved_host is None:
                return 1
            selected_ollama_host = resolved_host
        elif selected_provider == 'ollama' and legacy_host:
            selected_ollama_host = legacy_host

        if selected_provider == 'lmstudio':
            llm_provider = LMStudioProvider(host=selected_lmstudio_host)
        else:
            llm_provider = OllamaProvider(
                host=selected_ollama_host, model=selected_ollama_model
            )

        output_file = args.output

        logger.info('\nStarting Code Structure Analyzer')
        logger.info(f'Source directory: {args.source_dir}')
        # logger.info(f'Output file: {output_file}')
        if args.reporter == 'chromadb':
            logger.info(f'Results will be stored in ChromaDB at {output_file}')
        else:
            logger.info(f'Results will be written to {output_file}')
        logger.info(f'Chunk size: {args.chunk_size}')
        logger.info(f'LLM provider: {selected_provider}')
        logger.info(
            f'LLM host: {selected_ollama_host if selected_provider == "ollama" else selected_lmstudio_host}'
        )

        if selected_provider == 'ollama':
            logger.info(f'Ollama host: {selected_ollama_host}')
            logger.info(f'Ollama model: {selected_ollama_model}')

        logger.info(f'Obey .gitignore: {args.obey_gitignore}')
        if args.no_dependencies:
            logger.info('Dependencies/imports output is disabled')
        if args.no_functions:
            logger.info('Functions list output is disabled')
        if args.include:
            logger.info(f'Include patterns: {args.include}')
        if args.exclude:
            logger.info(f'Exclude patterns: {args.exclude}')

        # Print a message about CTRL+C support
        print('\nPress CTRL+BREAK at any time to stop the analysis.\n')

        # Run analysis in a cancellable thread
        result = {'output': None, 'success': False, 'error': None}
        analysis_thread = threading.Thread(
            target=analyze_in_thread,
            args=(
                source_dir,
                output_file,
                args.chunk_size,
                include_patterns,
                exclude_patterns,
                args.obey_gitignore,
                llm_provider,
                args.no_dependencies,
                args.no_functions,
                result,
                cancel_event,
                args.folders,
                args.reporter,
            ),
        )

        # Start the analysis in the background
        analysis_thread.daemon = True
        analysis_thread.start()

        # Wait for the analysis to complete or for cancellation
        while analysis_thread.is_alive():
            if cancel_event.is_set():
                break
            try:
                # Sleep for a short duration, then check for interruptions
                analysis_thread.join(0.1)

                # If join returns and thread is still alive, loop will continue
                # If join returns and thread is not alive, loop will exit

            except KeyboardInterrupt:
                # This will catch CTRL+C in most environments
                print('\nReceived keyboard interrupt, stopping analysis...')
                cancel_event.set()

                # Wait for thread to finish cleanly (with timeout)
                logger.info('Waiting for analysis to stop gracefully...')
                analysis_thread.join(3.0)  # Wait up to 3 seconds

                if analysis_thread.is_alive():
                    logger.info('Analysis is taking longer to stop, please wait...')

                return 1

        # Check the result after thread completes
        if result['success']:
            logger.info(f"Analysis completed. Output written to {result['output']}")
            return 0
        elif cancel_event.is_set():
            logger.info('Analysis was cancelled by user')
            return 1
        else:
            if isinstance(result['error'], Exception):
                raise result['error']
            else:
                raise RuntimeError(f"Unknown error: {result['error']}")

    except KeyboardInterrupt:
        print('\nAnalysis interrupted by user')
        if cancel_event:
            cancel_event.set()

        if analysis_thread and analysis_thread.is_alive():
            analysis_thread.join(1.0)

        return 1

    except FileNotFoundError:
        logger.error(f'Error: Source directory not found: {args.source_dir}')
        raise

    except ImportError as e:
        logger.error(f'Error: {str(e)}')
        print(f'\nError: Missing required dependency: {str(e)}')
        print(
            'Please install missing dependencies using pip install -r requirements.txt'
        )
        return 1

    except Exception as e:
        if isinstance(e, LMStudioWebsocketError):
            logger.error(f'Error connecting to LM Studio: {str(e)}')
            print(
                f'\nError: Unable to connect to LM Studio at {selected_lmstudio_host}'
            )
            print('Please make sure LM Studio is running and accessible.')
            print('You can start LM Studio or use a different LLM provider.')
            return 1
        elif isinstance(e, OllamaError):
            logger.error(f'Error connecting to Ollama: {str(e)}')
            print(
                f'\nError: Unable to connect to Ollama at {selected_ollama_host}'
            )
            print('Please make sure Ollama is running and accessible.')
            print('You can start Ollama or use a different LLM provider.')
            return 1
        logger.error(f'Error: {str(e)}', exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())

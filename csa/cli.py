import argparse
import logging
import os
import re
import socket
import sys
import threading

from csa.analyzer import analyze_codebase
from csa.config import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler('csa.log')],
)

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
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.custom_epilog = epilog_text
    parser.add_argument("-h", "--help", action="store_true", help="Show this help message and examples.")
    parser.add_argument("--folders", action="store_true", help="Recursively include files in sub-folders of the source directory.")

    parser.add_argument(
        'source_dir',
        nargs='?',
        default=None,
        help='Path to the source directory to analyze',
    )

    parser.add_argument(
        '-o',
        '--output',
        help=f'Path to the output markdown file (default: {config.OUTPUT_FILE})',
        default=config.OUTPUT_FILE,
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
        help=f'Host address for the LLM provider (default: {config.LLM_HOST})',
        default=config.LLM_HOST,
    )

    parser.add_argument(
        '--lmstudio-host',
        help=f'Host address for the LM Studio provider (default: {config.LMSTUDIO_HOST})',
        default=config.LMSTUDIO_HOST,
    )

    parser.add_argument(
        '--ollama-host',
        help=f'Host address for Ollama (default: {config.OLLAMA_HOST})',
        default=config.OLLAMA_HOST,
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
        socket.setdefaulttimeout(timeout)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, int(port)))
        s.close()
        return True
    except Exception:
        return False


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
    folders
):
    """Run the analysis in a separate thread to make it cancellable."""
    try:
        # Pass a cancellation check function to analyze_codebase
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
            folders=folders
        )
        result['output'] = output
        result['success'] = True
    except Exception as e:
        result['error'] = e
        result['success'] = False


def main():
    """Main entry point."""
    # Create a cancellation event
    cancel_event = threading.Event()

    # Store a reference to analysis thread
    analysis_thread = None

    try:
        # Print title first
        print(TITLE)

        # Check dependencies
        check_dependencies()

        # Parse command-line arguments
        args = parse_args()

        # If no source directory is provided, print help and exit with error message
        if args.source_dir is None:
            parser = create_parser()
            print("\nERROR: Missing required argument 'source_dir'")
            print('Please specify a source directory to analyze.\n')
            parser.print_help()
            return 1

        # Check if source_dir exists before proceeding
        if not os.path.exists(args.source_dir):
            logger.error(f'Error: Source directory not found: {args.source_dir}')
            raise FileNotFoundError(f'Source directory not found: {args.source_dir}')

        # Set log level based on verbose flag
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        # Set environment variables for configuration
        if args.llm_provider:
            # Check if the provider is supported
            supported_providers = [
                'lmstudio',
                'ollama',
            ]  # Add more as they become available
            if args.llm_provider.lower() not in [
                p.lower() for p in supported_providers
            ]:
                print(f'\nERROR: Unsupported LLM provider: {args.llm_provider}')
                print(f"Supported providers: {', '.join(supported_providers)}")
                return 1
            os.environ['LLM_PROVIDER'] = args.llm_provider

        if args.llm_host:
            # Validate the host format
            if not re.match(r'^[a-zA-Z0-9.-]+:[0-9]+$', args.llm_host):
                print(f'\nERROR: Invalid LLM host format: {args.llm_host}')
                print(
                    "Host should be in the format 'hostname:port' (e.g., 'localhost:1234')"
                )
                return 1

            # Set the provider-specific host based on the selected provider
            if args.llm_provider and args.llm_provider.lower() == 'ollama':
                os.environ['OLLAMA_HOST'] = args.llm_host
            else:
                # Default to LMStudio
                os.environ['LMSTUDIO_HOST'] = args.llm_host

            # Keep LLM_HOST for backward compatibility
            os.environ['LLM_HOST'] = args.llm_host

            # Check if host is reachable (early warning)
            host, port = args.llm_host.split(':')
            if not check_host_reachable(host, port):
                print(f'\nWARNING: Cannot connect to LLM provider at {args.llm_host}')
                print('Make sure the LLM service is running and accessible.')
                print('Continuing execution, but analysis may fail later.\n')
                logger.warning(f'LLM host {args.llm_host} is not reachable')

        if args.lmstudio_host:
            os.environ['LMSTUDIO_HOST'] = args.lmstudio_host

        if args.ollama_host:
            os.environ['OLLAMA_HOST'] = args.ollama_host

        if args.ollama_model:
            os.environ['OLLAMA_MODEL'] = args.ollama_model

        if args.obey_gitignore:
            os.environ['OBEY_GITIGNORE'] = 'True'

        # Force reimport of the module to get new config
        import importlib

        import csa.config as config_module

        importlib.reload(config_module)
        import csa.llm as llm_module
        from csa.config import config as reloaded_config

        importlib.reload(llm_module)

        from csa.llm import get_llm_provider

        llm_provider = get_llm_provider()

        logger.info('\nStarting Code Structure Analyzer')
        logger.info(f'Source directory: {args.source_dir}')
        logger.info(f'Output file: {args.output}')
        logger.info(f'Chunk size: {args.chunk_size}')
        logger.info(f'LLM provider: {reloaded_config.LLM_PROVIDER}')
        logger.info(f'LLM host: {reloaded_config.LLM_HOST}')

        if reloaded_config.LLM_PROVIDER.lower() == 'ollama':
            logger.info(f'Ollama host: {reloaded_config.OLLAMA_HOST}')
            logger.info(f'Ollama model: {reloaded_config.OLLAMA_MODEL}')

        logger.info(f'Obey .gitignore: {reloaded_config.OBEY_GITIGNORE}')
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
                args.source_dir,
                args.output,
                args.chunk_size,
                args.include.split(',') if args.include else None,
                args.exclude.split(',') if args.exclude else None,
                args.obey_gitignore,
                llm_provider,
                args.no_dependencies,
                args.no_functions,
                result,
                cancel_event,
                args.folders
            ),
        )

        # Start the analysis in the background
        analysis_thread.daemon = True
        analysis_thread.start()

        # Wait for the analysis to complete or for cancellation
        while analysis_thread.is_alive():
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
            # If cancellation was requested and thread completed
            logger.info('Analysis was cancelled by user')
            return 1
        else:
            # Re-raise any exception that occurred
            if isinstance(result['error'], Exception):
                raise result['error']
            else:
                raise RuntimeError(f"Unknown error: {result['error']}")

    except KeyboardInterrupt:
        # This is a fallback in case the inner handler misses it
        print('\nAnalysis interrupted by user')
        if cancel_event:
            cancel_event.set()

        # If thread exists and is running, wait briefly for it to stop
        if analysis_thread and analysis_thread.is_alive():
            analysis_thread.join(1.0)

        return 1

    except FileNotFoundError:
        # Let FileNotFoundError propagate for tests
        logger.error(f'Error: Source directory not found: {args.source_dir}')
        raise

    except ImportError as e:
        # Import errors are handled specifically for better user experience
        logger.error(f'Error: {str(e)}')
        print(f'\nError: Missing required dependency: {str(e)}')
        print(
            'Please install missing dependencies using pip install -r requirements.txt'
        )
        return 1

    except Exception as e:
        # Check if it's an LMStudioWebsocketError
        if 'LMStudioWebsocketError' in str(type(e)):
            logger.error(f'Error connecting to LM Studio: {str(e)}')
            print(
                f'\nError: Unable to connect to LM Studio at {reloaded_config.LLM_HOST}'
            )
            print('Please make sure LM Studio is running and accessible.')
            print('You can start LM Studio or use a different LLM provider.')
            return 1
        # Check if it's an OllamaError
        elif 'OllamaError' in str(type(e)):
            logger.error(f'Error connecting to Ollama: {str(e)}')
            print(
                f'\nError: Unable to connect to Ollama at {reloaded_config.OLLAMA_HOST}'
            )
            print('Please make sure Ollama is running and accessible.')
            print('You can start Ollama or use a different LLM provider.')
            return 1
        # Handle other exceptions
        logger.error(f'Error: {str(e)}', exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())

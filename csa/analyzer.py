import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

import mdformat  # noqa: F401
import pathspec
from tqdm import tqdm

from csa.code_analyzer import CodeAnalyzer, get_code_analyzer
from csa.config import config
from csa.llm import LLMProvider
from csa.reporters import MarkdownAnalysisReporter

logger = logging.getLogger(__name__)


def discover_files(
    source_dir: str,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    obey_gitignore: bool = False,
    folders: bool = False,
) -> List[str]:
    """
    Scan source directory recursively for all code files, filtering by extension
    and excluding binary/generated folders.

    Args:
        source_dir: Path to the source directory
        include_patterns: List of patterns to include (gitignore style)
        exclude_patterns: List of patterns to exclude (gitignore style)
        obey_gitignore: Whether to obey .gitignore files in the processed folder
        folders: Whether to traverse sub-folders

    Returns:
        List of file paths sorted alphabetically
    """
    source_path = Path(source_dir)
    if not source_path.exists():
        raise FileNotFoundError(f'Source directory not found: {source_dir}')

    include_spec = None
    exclude_spec = None
    gitignore_spec = None

    if include_patterns:
        include_spec = pathspec.PathSpec.from_lines('gitwildmatch', include_patterns)

    if exclude_patterns:
        exclude_spec = pathspec.PathSpec.from_lines('gitwildmatch', exclude_patterns)

    if obey_gitignore:
        gitignore_path = source_path / '.gitignore'
        if gitignore_path.exists():
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                gitignore_spec = pathspec.PathSpec.from_lines(
                    'gitwildmatch', f.readlines()
                )
            logger.info(f'Loaded .gitignore from {gitignore_path}')

    files = []

    if folders:
        walker: Union[
            Iterator[tuple[str, list[str], list[str]]],
            list[tuple[str, list[str], list[str]]],
        ] = os.walk(source_path)
    else:
        # Convert single-iteration os.walk to a list containing just the first result
        walker = [next(os.walk(source_path))]
    for root, dirs, filenames in walker:
        # Skip excluded directories
        dirs[:] = [
            d
            for d in dirs
            if d.lower() not in [f.lower() for f in config.EXCLUDED_FOLDERS]
        ]

        for filename in filenames:
            file_path = Path(root) / filename
            file_path_str = str(file_path)

            # Convert to path relative to source_dir for pattern matching
            try:
                rel_path = str(file_path.relative_to(source_path))
            except ValueError:
                # If not a subpath, just use the basename
                rel_path = filename

            # Skip files with unwanted extensions unless include_patterns specified
            if not include_patterns and not any(
                file_path.suffix.lower() == ext.lower()
                for ext in config.FILE_EXTENSIONS
            ):
                continue

            # Apply gitignore patterns if enabled
            if gitignore_spec and gitignore_spec.match_file(rel_path):
                logger.debug(f'Skipping {rel_path} due to .gitignore')
                continue

            # Skip if not in include patterns (when specified)
            if include_spec and not include_spec.match_file(rel_path):
                logger.debug(f'Skipping {rel_path} due to include patterns')
                continue

            # Skip if in exclude patterns
            if exclude_spec and exclude_spec.match_file(rel_path):
                logger.debug(f'Skipping {rel_path} due to exclude patterns')
                continue

            files.append(file_path_str)

    # Sort alphabetically
    return sorted(files)


def read_file_chunk(
    file_path: str, start_line: int, chunk_size: int
) -> Tuple[List[str], bool]:
    """
    Read a chunk of a file starting from the given line.

    Args:
        file_path: Path to the file
        start_line: Line number to start reading from (1-indexed)
        chunk_size: Number of lines to read

    Returns:
        Tuple of (lines read, boolean indicating if end of file was reached)
    """
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()
        total_lines = len(all_lines)

        # Convert from 1-indexed to 0-indexed
        start_idx = start_line - 1
        end_idx = min(start_idx + chunk_size, total_lines)

        chunk_lines = all_lines[start_idx:end_idx]
        # Check if we reached the end of the file
        eof_reached = end_idx >= total_lines
        return chunk_lines, eof_reached


def read_file_chunk_significant(
    file_path: str, start_line: int, chunk_size: int, file_ext: str
) -> Tuple[List[str], bool, int]:
    """
    Read a chunk of a file starting from the given line, ensuring it contains
    the requested number of significant lines (non-empty, non-comment).

    Args:
        file_path: Path to the file
        start_line: Line number to start reading from (1-indexed)
        chunk_size: Number of significant lines to read
        file_ext: File extension to determine comment style

    Returns:
        Tuple of (lines read, boolean indicating if end of file was reached,
                 end line number (1-indexed))
    """
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()
        total_lines = len(all_lines)

        # Convert from 1-indexed to 0-indexed
        start_idx = start_line - 1

        # Read lines until we have enough significant lines or reach EOF
        significant_count = 0
        current_idx = start_idx

        while significant_count < chunk_size and current_idx < total_lines:
            # Check if current line is significant
            if is_significant_line(all_lines[current_idx], file_ext):
                significant_count += 1
            current_idx += 1

        # Get all lines from start to current position (includes insignificant lines)
        chunk_lines = all_lines[start_idx:current_idx]

        # Check if we reached the end of the file
        eof_reached = current_idx >= total_lines

        # Return the chunk, EOF status, and the 1-indexed end line number
        return chunk_lines, eof_reached, current_idx


def is_significant_line(line: str, file_ext: str) -> bool:
    """
    Determines if a line is significant (not empty/comment) based on file extension.

    Args:
        line: The line content to check
        file_ext: The file extension (e.g., '.cs', '.py')

    Returns:
        Boolean indicating if the line is significant for counting
    """
    # Skip empty or whitespace-only lines for all file types
    if not line.strip():
        return False

    # For C# files, skip comment lines
    if file_ext.lower() == '.cs' and line.strip().startswith(('///', '//')):
        return False

    return True


def analyze_file(
    file_path: str,
    code_analyzer: CodeAnalyzer,
    chunk_size: Optional[int] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """
    Analyze a single file by reading it in chunks and analyzing each chunk.

    Args:
        file_path: Path to the file to analyze
        code_analyzer: Code analyzer instance
        chunk_size: Number of significant lines to read in each chunk
        cancel_callback: Function that returns True if analysis should be cancelled

    Returns:
        Dictionary with analysis results
    """
    if chunk_size is None:
        chunk_size = config.CHUNK_SIZE

    # Use a no-op callback if none provided
    if cancel_callback is None:

        def no_op_callback() -> bool:
            return False

        cancel_callback = no_op_callback

    logger.debug(f'Analyzing file: {file_path}')

    analyses = []
    start_line = 1
    total_lines = 0
    chunks_analyzed = 0
    file_ext = os.path.splitext(file_path)[1]
    basename = os.path.basename(file_path)
    error_occurred = False

    # Check if file is likely to exceed context window
    oversized_file = False
    file_size = os.path.getsize(file_path)
    # Rough estimate: ~1 token per 4 characters
    estimated_tokens = file_size // 4

    # Check if file would likely exceed 80% of the model's context length
    model_context_length = code_analyzer.get_context_length()
    if estimated_tokens > int(model_context_length * 0.8):
        oversized_file = True
        logger.info(
            f'File {basename} is oversized ({file_size} bytes, ~{estimated_tokens} tokens). Using simplified analysis.'
        )
        # print(f"\nNOTE: File {basename} is large ({file_size} bytes, ~{estimated_tokens} tokens)")
        # print(f"Using optimized analysis approach")
    else:
        logger.debug(
            f'File {basename} size: {file_size} bytes, ~{estimated_tokens} tokens (context limit: {model_context_length})'
        )

    try:
        # First read to get total lines and count significant lines for special file types
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()

            # For C# files, filter out empty lines and comments for progress calculation
            if file_ext.lower() == '.cs':
                significant_lines = [
                    line for line in all_lines if is_significant_line(line, file_ext)
                ]
                total_significant_lines = len(significant_lines)
                logger.debug(
                    f'File has {len(all_lines)} total lines, {total_significant_lines} significant lines'
                )
            else:
                significant_lines = all_lines
                total_significant_lines = len(all_lines)

            total_lines = len(all_lines)

        progress_bar = tqdm(
            total=total_significant_lines,
            desc=f'Processing {basename}',
            unit='lines',
            bar_format='{desc}: {n_fmt}/{total_fmt} [{percentage:3.0f}%] {bar:30}',
            ncols=80,
            leave=False,
        )

        # Track progress for basic progress reporting
        last_percent = 0
        processed_lines = 0

        # Process the file in chunks
        chunk_count = 0
        while start_line <= total_lines:
            # Check for cancellation request before each chunk
            if cancel_callback():
                logger.debug(f'Analysis of {file_path} cancelled at line {start_line}')
                raise InterruptedError('Analysis cancelled by user')

            # Read the next chunk, getting exactly chunk_size significant lines
            chunk_lines, eof_reached, end_line = read_file_chunk_significant(
                file_path, start_line, chunk_size, file_ext
            )
            if not chunk_lines:
                break

            end_line -= 1  # Convert back to 1-indexed inclusive end line
            logger.debug(f'Analyzing lines {start_line}-{end_line} of {total_lines}')

            # Join chunk lines with original line endings
            chunk_content = ''.join(chunk_lines)

            # Count significant lines in this chunk for progress update
            significant_count = sum(
                1 for line in chunk_lines if is_significant_line(line, file_ext)
            )

            # Track if an error occurred in this chunk
            error_in_chunk = False

            # Set retry parameters
            max_retries = 3
            retry_count = 0
            llm_timeout = 60  # 60 second timeout for LLM requests

            # Process chunk with retries on timeout
            while retry_count < max_retries:
                # Analyze chunk with proper error handling to preserve progress bar
                try:
                    # For oversized files, use structural-only analysis after first 2 chunks
                    if oversized_file and chunk_count >= 2:
                        analysis = code_analyzer.analyze_code_chunk(
                            file_path=file_path,
                            content=chunk_content,
                            start_line=start_line,
                            end_line=end_line,
                            total_lines=total_lines,
                            structural_only=True,
                            timeout=llm_timeout,
                        )
                    else:
                        analysis = code_analyzer.analyze_code_chunk(
                            file_path=file_path,
                            content=chunk_content,
                            start_line=start_line,
                            end_line=end_line,
                            total_lines=total_lines,
                            timeout=llm_timeout,
                        )
                    # If successful, add to analyses and break retry loop
                    analyses.append(analysis)
                    chunks_analyzed += 1
                    chunk_count += 1
                    break  # Success, exit retry loop

                except TimeoutError:
                    # Handle timeout specifically
                    retry_count += 1
                    if retry_count >= max_retries:
                        # Max retries exceeded, abort processing this file
                        error_message = f'LLM request timed out after {llm_timeout} seconds ({retry_count} attempts)'
                        error_in_chunk = True
                        error_occurred = True

                        progress_bar.write(
                            f'- ERROR - {error_message} for {basename}:{start_line}-{end_line}'
                        )

                        logger.error(
                            f'{error_message} for chunk {start_line}-{end_line} of {file_path}'
                        )

                        analyses.append(
                            {
                                'start_line': start_line,
                                'end_line': end_line,
                                'error': error_message,
                            }
                        )

                        logger.warning(
                            f'Aborting analysis of {basename} due to repeated timeouts'
                        )
                        progress_bar.write(
                            f'Aborting analysis of {basename} due to repeated timeouts'
                        )
                        raise InterruptedError(
                            'Analysis aborted due to repeated timeouts'
                        )
                    else:
                        # Retry the chunk
                        retry_delay = 2  # Wait 2 seconds between retries
                        progress_bar.write(
                            f'LLM request timed out, retrying ({retry_count}/{max_retries})...'
                        )
                        time.sleep(retry_delay)

                except Exception as e:
                    # Handle other exceptions (non-timeout)
                    error_in_chunk = True
                    error_occurred = True

                    # Make sure error output starts on a new line
                    progress_bar.write(
                        f'- ERROR - Error analyzing {basename}:{start_line}-{end_line}:'
                    )
                    progress_bar.write(f'  {str(e)}')

                    logger.error(
                        f'Error analyzing chunk {start_line}-{end_line} of {file_path}: {str(e)}'
                    )

                    # Create a minimal analysis entry for this chunk to maintain continuity
                    analyses.append(
                        {
                            'start_line': start_line,
                            'end_line': end_line,
                            'error': str(e),
                        }
                    )

                    # Exit retry loop for non-timeout errors
                    break

            processed_lines = end_line
            percent = min(100, int((processed_lines / total_lines) * 100))
            progress_bar.update(significant_count)
            start_line = end_line + 1
            if eof_reached:
                break

            if cancel_callback():
                logger.debug(
                    f'Analysis of {file_path} cancelled after processing chunk ending at line {end_line}'
                )
                raise InterruptedError('Analysis cancelled by user')

        progress_bar.close()

        if oversized_file:
            summary = code_analyzer.generate_file_summary(analyses, is_partial=True)
        else:
            summary = code_analyzer.generate_file_summary(analyses)

        logger.info(
            f'Completed analysis of {basename}'
            + (' with errors' if error_occurred else '')
        )

        return {
            'file_path': file_path,
            'total_lines': total_lines,
            'chunks_analyzed': chunks_analyzed,
            'analyses': analyses,
            'summary': summary,
            'has_errors': error_occurred,
            'oversized_file': oversized_file,  # Add flag to result for downstream handling
        }

    except InterruptedError:
        if 'progress_bar' in locals():
            progress_bar.close()
        raise
    except Exception as e:
        if 'progress_bar' in locals():
            progress_bar.close()

        logger.error(f'Error analyzing file {file_path}: {str(e)}')
        return {
            'file_path': file_path,
            'error': str(e),
            'analyses': analyses,
            'last_line_analyzed': start_line - 1,
            'has_errors': True,
        }


def analyze_codebase(
    source_dir: str,
    output_file: Optional[str] = None,
    llm_provider: Optional[LLMProvider] = None,
    chunk_size: Optional[int] = None,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    obey_gitignore: Optional[bool] = None,
    disable_dependencies: bool = False,
    disable_functions: bool = False,
    cancel_callback: Optional[Callable[[], bool]] = None,
    folders: bool = False,
) -> str:
    """
    Analyze all code files in the source directory and generate documentation.

    Args:
        source_dir: Path to the source directory
        output_file: Path to the output markdown file
        llm_provider: LLM provider instance (optional)
        chunk_size: Number of lines to read in each chunk
        include_patterns: List of patterns to include (gitignore style)
        exclude_patterns: List of patterns to exclude (gitignore style)
        obey_gitignore: Whether to obey .gitignore files in the processed folder
        disable_dependencies: Whether to disable output of dependencies/imports
        disable_functions: Whether to disable output of functions list
        cancel_callback: Function that returns True if analysis should be cancelled
        folders: Whether to traverse sub-folders

    Returns:
        Path to the generated markdown file
    """
    if output_file is None:
        output_file = config.OUTPUT_FILE

    if chunk_size is None:
        chunk_size = config.CHUNK_SIZE

    if obey_gitignore is None:
        obey_gitignore = config.OBEY_GITIGNORE

    # Use a no-op callback if none provided
    if cancel_callback is None:

        def no_op_callback() -> bool:
            return False

        cancel_callback = no_op_callback

    # Get a code analyzer, either using the provided LLM provider or getting a new one
    if llm_provider is None:
        code_analyzer = get_code_analyzer()
    else:
        code_analyzer = CodeAnalyzer(llm_provider)

    # Set the options for disabling specific outputs
    code_analyzer.disable_dependencies = disable_dependencies
    code_analyzer.disable_functions = disable_functions

    # Display model context length at the start of the run
    model_context_length = code_analyzer.get_context_length()
    logger.info(f'\nLLM Model Context Length: {model_context_length} tokens')
    logger.info(
        f'Files over {int(model_context_length * 0.8)} tokens will use optimized analysis!\n'
    )

    logger.info(f'Analyzing codebase in {source_dir}')
    output_path = str(output_file)

    # Make source_dir a Path object for easier manipulation
    source_dir_path = Path(source_dir)

    # Check if the output path is absolute
    if not os.path.isabs(output_path):
        # For tests, we want to place the output in the source directory
        # to make it easier to find and verify
        if 'pytest' in sys.modules:
            # If running under pytest, prefer source_dir as the base for relative paths
            output_path = str(source_dir_path / output_path)
        else:
            # Otherwise use the configured output path
            output_path = str(config.get_output_path(output_path))

    # Ensure output file path is absolute
    output_path_obj = Path(output_path)
    if not output_path_obj.is_absolute():
        output_path_obj = config.get_project_root() / output_path_obj

    output_path = str(output_path_obj)

    logger.info(f'Starting codebase analysis of {source_dir}')
    logger.info(f'Output will be written to {output_file}')

    # Create the reporter for this analysis
    reporter = MarkdownAnalysisReporter(output_path)

    # Try to extract remaining files from existing output file
    files = reporter.extract_remaining_files(source_dir)

    # If no existing file list was found, discover files with pattern matching
    if files is None:
        logger.info('No valid previous analysis found, discovering files')
        files = discover_files(
            source_dir,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            obey_gitignore=obey_gitignore,
            folders=folders,
        )
        # Initialize markdown file with all discovered files
        reporter.initialize(files, source_dir)
        logger.info(f'Initialized markdown file at {output_file}')
    else:
        logger.info(f'Resuming previous analysis with {len(files)} remaining files')
        # No need to initialize markdown file as it already exists

    logger.info(f'Found {len(files)} files to analyze')

    # Analyze each file
    analyzed_files: list[str] = []
    remaining_files = files.copy()
    current_directory = (
        None  # Track the current directory to show separator only when changing
    )

    # Process files in reverse order so they appear alphabetically in the output
    for file_path in reversed(files):
        # Check for cancellation
        if cancel_callback():
            logger.info('Analysis cancelled by user, stopping gracefully')
            break

        try:
            # Remove from remaining files list
            remaining_files.remove(file_path)

            # Get directory path to check if we've changed directories
            file_directory = os.path.dirname(file_path)
            file_basename = os.path.basename(file_path)

            # If directory changed, print separator and full directory path
            if file_directory != current_directory:
                print(f"\n{'='*79}")
                print(f'Directory: {file_directory}')
                print(f"\n{'='*79}")
                current_directory = file_directory

            # Log with just the filename rather than the full path
            logger.info(f'File {len(analyzed_files)+1}/{len(files)}: {file_basename}')

            # Display only filename for the individual file analysis

            # Analyze file
            analysis_result: Dict[str, Any] = analyze_file(
                file_path=file_path,
                code_analyzer=code_analyzer,
                chunk_size=chunk_size,
                cancel_callback=cancel_callback,
            )

            # Update markdown file using the reporter
            reporter.update_file_analysis(analysis_result, source_dir, remaining_files)

            # Add to analyzed files
            analyzed_files.append(file_path)

            # Check for cancellation again after each file
            if cancel_callback():
                logger.info('Analysis cancelled by user, stopping gracefully')
                break

        except InterruptedError:
            # Handle interruption (cancellation)
            logger.info(f'Analysis of {file_path} was cancelled')
            break
        except Exception as e:
            logger.error(f'Error analyzing file {file_path}: {str(e)}')
            # Check if we should continue on error or if cancellation was requested
            if cancel_callback():
                break

    # Finalize the output
    reporter.finalize()

    logger.info(
        f'Analysis completed. Analyzed {len(analyzed_files)}/{len(files)} files.'
    )
    return output_path

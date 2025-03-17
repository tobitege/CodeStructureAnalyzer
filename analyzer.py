import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import mdformat  # noqa: F401
import pathspec
from tqdm import tqdm

from code_analyzer import CodeAnalyzer, get_code_analyzer
from config import config
from llm import LLMProvider

logger = logging.getLogger(__name__)


def discover_files(
    source_dir: str,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    obey_gitignore: bool = False,
) -> List[str]:
    """
    Scan source directory recursively for all code files, filtering by extension
    and excluding binary/generated folders.

    Args:
        source_dir: Path to the source directory
        include_patterns: List of patterns to include (gitignore style)
        exclude_patterns: List of patterns to exclude (gitignore style)
        obey_gitignore: Whether to obey .gitignore files in the processed folder

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

    for root, dirs, filenames in os.walk(source_path):
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


def generate_mermaid_diagram(files: List[str], source_dir: str) -> str:
    """
    Generate a Mermaid diagram of the code dependencies.

    Args:
        files: List of file paths
        source_dir: Source directory path

    Returns:
        Mermaid diagram as a string
    """

    # Extract basename to path mapping
    file_map = {}
    for file_path in files:
        file_path_obj = Path(file_path)
        basename = file_path_obj.name
        file_map[basename] = file_path

    # Track dependencies between files
    dependencies: dict[str, set[str]] = {}

    # Extract imports for each file
    for file_path in files:
        basename = Path(file_path).name
        if basename not in dependencies:
            dependencies[basename] = set()

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

                # Look for import statements
                import_patterns = [
                    r'import\s+(\w+)',  # import module
                    r'from\s+(\w+)\s+import',  # from module import
                ]

                for pattern in import_patterns:
                    for match in re.finditer(pattern, content):
                        imported_module = match.group(1)
                        # Check if this is a local module (exists in our files)
                        imported_file = f'{imported_module}.py'
                        if imported_file in file_map:
                            dependencies[basename].add(imported_file)
        except Exception as e:
            logger.warning(f'Error parsing imports in {file_path}: {str(e)}')

    # Build Mermaid diagram
    mermaid = ['graph TD']

    # Ensure we have nodes for all files
    for file_path in files:
        basename = Path(file_path).name
        node_id = basename.replace('.', '_')
        mermaid.append(f'  {node_id}[{basename}]')

    # Add connections based on imports
    for source_file, targets in dependencies.items():
        source_id = source_file.replace('.', '_')
        for target_file in targets:
            target_id = target_file.replace('.', '_')
            mermaid.append(f'  {source_id} --> {target_id}')

    # If cli.py exists, make it the entry point with a different style
    if 'cli.py' in file_map:
        cli_id = 'cli_py'
        # Find the line with cli_py and replace it with a styled version
        for i, line in enumerate(mermaid):
            if line.strip().startswith(f'{cli_id}['):
                mermaid[i] = f'  {cli_id}[cli.py]:::entryPoint'
                # Add class definition for entry point
                mermaid.insert(
                    1, '  classDef entryPoint fill:#f96,stroke:#333,stroke-width:2px;'
                )
                break

    return '\n'.join(mermaid)


def initialize_markdown(output_file: str, files: List[str], source_dir: str) -> None:
    """
    Initialize the markdown file with header, diagram, and file lists.

    Args:
        output_file: Path to the output markdown file
        files: List of file paths
        source_dir: Source directory path
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('# Code Structure Analysis\n\n')

        # Omit source directory if it's just "."
        if source_dir != '.':
            f.write(f'Source directory: `{source_dir}`\n\n')

        f.write(
            f"Analysis started: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        f.write('## Codebase Structure\n\n')
        # Ensure exactly three backticks for the mermaid block
        mermaid_diagram = generate_mermaid_diagram(files, source_dir)
        f.write('```mermaid\n')
        f.write(mermaid_diagram)
        f.write('\n```\n\n')

        f.write('## Files Analyzed\n\n')

        # Only add the "Files Remaining to Study" section if there are files to analyze
        if files:
            f.write('## Files Remaining to Study\n\n')
            for file_path in files:
                try:
                    # Make the path relative to source_dir if possible
                    file_path_obj = Path(file_path)
                    source_path = Path(source_dir)
                    try:
                        # For absolute paths, try to make them relative to source_dir
                        if file_path_obj.is_absolute() and source_path.is_absolute():
                            rel_path = str(file_path_obj.relative_to(source_path))
                        else:
                            # For relative paths, use as is
                            rel_path = file_path
                    except ValueError:
                        # If not a subpath, just use the path as is
                        rel_path = file_path
                    f.write(f'- `{rel_path}`\n')
                except Exception:
                    f.write(f'- `{file_path}`\n')


def update_markdown(
    output_file: str,
    file_analysis: Dict[str, Any],
    source_dir: str,
    remaining_files: List[str],
) -> None:
    """
    Update the markdown file with the analysis results for a file.

    Args:
        output_file: Path to the output markdown file
        file_analysis: Analysis results for a file
        source_dir: Source directory path
        remaining_files: List of files remaining to analyze
    """
    file_path = file_analysis['file_path']
    source_path = Path(source_dir)
    file_path_obj = Path(file_path)

    # Get relative path for display
    try:
        # For absolute paths, try to make them relative to source_dir
        if file_path_obj.is_absolute() and source_path.is_absolute():
            try:
                rel_path = str(file_path_obj.relative_to(source_path))
            except ValueError:
                # If not a subpath, just use the basename
                rel_path = file_path_obj.name
        else:
            # For relative paths, use the path as is
            rel_path = file_path
            # Try to make it relative to source_dir if possible
            try:
                rel_path_obj = Path(rel_path)
                rel_path = str(rel_path_obj.relative_to(source_path))
            except (ValueError, TypeError):
                # Keep original if can't make relative
                pass
    except Exception as e:
        logger.warning(f'Error creating relative path for {file_path}: {str(e)}')
        rel_path = os.path.basename(file_path)

    # Read existing content
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        logger.error(f'Error reading markdown file {output_file}: {str(e)}')
        sys.exit(1)

    # Split content into sections
    sections: dict[str, list[str]] = {}
    current_section = None
    section_content = []

    for line in content.split('\n'):
        if line.startswith('## '):
            # Save previous section if it exists
            if current_section:
                sections[current_section] = section_content.copy()  # type: ignore[unreachable]

            # Start new section
            current_section = line
            section_content = [line]
        elif current_section:
            section_content.append(line)
        else:
            # Lines before any section (like title and date)
            header_section = sections.get('header', [])
            if not header_section:
                sections['header'] = header_section
            header_section.append(line)

    # Save the last section
    if current_section:
        sections[current_section] = section_content.copy()  # type: ignore[unreachable]

    # Get file analysis content
    file_content = generate_file_analysis_markdown(file_analysis, rel_path)

    # Update the "Files Analyzed" section
    analyzed_section_key = '## Files Analyzed'
    if analyzed_section_key in sections:
        # Add the new file analysis at the beginning of the section
        sections[analyzed_section_key].insert(1, '')  # Ensure blank line after heading
        sections[analyzed_section_key].insert(2, file_content)
    else:
        # Create the section if it doesn't exist
        sections[analyzed_section_key] = [analyzed_section_key, '', file_content]

    # Update the "Files Remaining to Study" section
    remaining_section_key = '## Files Remaining to Study'
    if remaining_files:
        # Generate the list of remaining files
        remaining_content = [remaining_section_key, '']
        for file_path in remaining_files:
            try:
                file_path_obj = Path(file_path)
                source_path = Path(source_dir)
                # For absolute paths, try to make them relative to source_dir
                if file_path_obj.is_absolute() and source_path.is_absolute():
                    try:
                        rel_path = str(file_path_obj.relative_to(source_path))
                    except ValueError:
                        # If not a subpath, just use the path as is
                        rel_path = file_path
                else:
                    # For relative paths, use as is
                    rel_path = file_path
                remaining_content.append(f'- `{rel_path}`')
            except Exception:
                remaining_content.append(f'- `{file_path}`')

        sections[remaining_section_key] = remaining_content
    elif remaining_section_key in sections:
        # Remove the section if there are no remaining files
        del sections[remaining_section_key]

    # Rebuild the content in the correct order
    new_content = []

    # Add header first
    if 'header' in sections:
        new_content.extend(sections['header'])

    # Add analyzed files section
    if analyzed_section_key in sections:
        if new_content and new_content[-1].strip():
            new_content.append('')  # Ensure blank line before section
        new_content.extend(sections[analyzed_section_key])

    # Add remaining files section if it exists
    if remaining_section_key in sections:
        if new_content and new_content[-1].strip():
            new_content.append('')  # Ensure blank line before section
        new_content.extend(sections[remaining_section_key])

    # Add any other sections that might exist
    for key, content_lines in sections.items():
        if key not in ['header', analyzed_section_key, remaining_section_key]:
            if new_content and new_content[-1].strip():
                new_content.append('')  # Ensure blank line before section
            new_content.extend(content_lines)

    # Write back the updated content
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_content))
    except Exception as e:
        logger.error(f'Error writing to markdown file {output_file}: {str(e)}')


def generate_file_analysis_markdown(
    file_analysis: Dict[str, Any], rel_path: str
) -> str:
    """
    Generate markdown content for a file analysis.

    Args:
        file_analysis: Analysis results for a file
        rel_path: Relative path of the file for display

    Returns:
        Markdown content for the file analysis
    """
    safe_basename = os.path.basename(rel_path).replace('`', '\\`')

    # Create a visual separator header
    separator = '---'
    header_line = f'## 📄 {rel_path}'

    # Handle error case
    if 'error' in file_analysis:
        return f"""
{separator}
{header_line}

**Error**: {file_analysis["error"]}
"""

    # Get summary
    summary = file_analysis.get('summary', 'No summary available.')

    # Clean up summary if it starts with backticks (markdown code block)
    if summary.strip().startswith('```'):
        # Find where the code block ends
        end_marker_pos = summary.find('```', 3)
        if end_marker_pos > 0:
            # If we found the end marker, extract everything between the markers
            # and any content after
            code_start = summary.find('\n', 3) + 1  # Skip ```language line
            content_between = summary[code_start:end_marker_pos].strip()
            content_after = summary[end_marker_pos + 3 :].strip()

            # Combine content between markers and after, ensuring there's proper spacing
            if content_after:
                summary = content_between + '\n\n' + content_after
            else:
                summary = content_between
        else:
            # If no end marker, just remove the initial backticks line
            first_line_end = summary.find('\n')
            if first_line_end > 0:
                summary = summary[first_line_end + 1 :].strip()
            else:
                # If it's just one line with backticks, replace it
                summary = summary.replace('```', '').strip()

    # Clean up LLM-generated content with potential heading issues
    cleaned_lines = []
    seen_headings = set()

    for line in summary.split('\n'):
        # Fix trailing colons in headings
        if re.match(r'^#+\s+.*:$', line) and not re.match(
            r'^#+\s+.*\[.*\]\(.*\):$', line
        ):
            line = line[:-1]  # Remove the trailing colon

        # Fix heading levels - convert h1 to h2, h2 to h3, etc. to avoid MD025 violations
        if line.strip().startswith('#'):
            # Count number of # at the beginning
            heading_match = re.match(r'^(#+)', line)
            if heading_match:
                # Get current heading level
                heading_level = len(heading_match.group(1))

                # Adjust heading level to avoid top-level heading conflicts (MD025)
                if heading_level == 1:  # If it's an H1 heading
                    # Add one # to make it an h2
                    line = '#' + line

                # Skip duplicate headings in the LLM output after adjusting level
                heading_text = line.strip()
                if heading_text in seen_headings:
                    continue
                seen_headings.add(heading_text)

        cleaned_lines.append(line)

    summary = '\n'.join(cleaned_lines)

    # Check if dependencies or functions are disabled
    disable_dependencies = (
        'dependencies' not in file_analysis.get('analyses', [{}])[0]
        if file_analysis.get('analyses')
        else False
    )
    disable_functions = (
        'functions' not in file_analysis.get('analyses', [{}])[0]
        if file_analysis.get('analyses')
        else False
    )

    # Start with common sections - combining file name and line count on one line
    # and separating the Description label from its content
    content = f"""
{separator}
{header_line}

{summary}
"""

    # Check if classes section has items before adding it
    classes_result = format_analysis_section(
        file_analysis.get('analyses', []), 'classes'
    )
    classes_content = classes_result[0]
    has_classes = classes_result[1]
    if has_classes:
        content += f"""
### {safe_basename} - **Classes**
{classes_content}"""

    # Only add functions section if not disabled and has items
    if not disable_functions:
        functions_result = format_analysis_section(
            file_analysis.get('analyses', []), 'functions'
        )
        functions_content = functions_result[0]
        has_functions = functions_result[1]
        if has_functions:
            content += f"""
### {safe_basename} - **Functions/Methods**
{functions_content}"""

    # Only add dependencies section if not disabled and has items
    if not disable_dependencies:
        dependencies_result = format_analysis_section(
            file_analysis.get('analyses', []), 'dependencies'
        )
        dependencies_content = dependencies_result[0]
        has_dependencies = dependencies_result[1]
        if has_dependencies:
            content += f"""
### {safe_basename} - **Dependencies/Imports**
{dependencies_content}"""

    return content.strip()


def format_analysis_section(
    analyses: List[Dict[str, Any]], section_key: str
) -> tuple[str, bool]:
    """
    Format a specific section of analysis results.

    Args:
        analyses: List of analysis results from different chunks
        section_key: Key of the section to format (classes, functions, dependencies)

    Returns:
        Tuple containing formatted section as markdown text and boolean indicating if items were found
    """
    # Collect all unique items
    items = set()
    for analysis in analyses:
        if section_key in analysis:
            for item in analysis[section_key]:
                items.add(item)

    # Format as markdown bullet list with proper blank lines
    if items:
        # Start with a blank line, then add items, then end with blank line
        result = '\n'
        for item in sorted(items):
            # Ensure exactly one space after dash for bullet points
            result += f'- {item}\n'
        result += '\n'
        return result, True
    else:
        return '\nNo items found.\n', False


def lint_markdown(markdown_file: str) -> None:
    """
    Lint and auto-format a markdown file using mdformat.

    Args:
        markdown_file: Path to the markdown file to lint
    """

    try:
        logger.info(f'Linting markdown file: {markdown_file}')

        # Read the file content
        with open(markdown_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Process the content line by line to fix common issues
        lines = content.split('\n')
        in_code_block = False
        code_block_language = None
        processed_lines: list[str] = []
        seen_headings = set()  # Track headings to eliminate duplicates
        first_h1_found = False  # Track if we've found the first h1 heading

        for line in lines:
            # Check if we're entering or exiting a code block
            if line.strip().startswith('```'):
                if not in_code_block:
                    # Starting a code block
                    in_code_block = True
                    # If no language is specified after the backticks, add 'text'
                    if line.strip() == '```':
                        line = '```text'
                    # Keep track of language to know if it's a mermaid diagram
                    code_block_language = line.strip().replace('```', '').strip()
                else:
                    # Ending a code block
                    in_code_block = False
                    code_block_language = None
            # Only process lines that are not in code blocks
            elif not in_code_block and code_block_language != 'mermaid':
                # Fix MD050 - use asterisks for bold instead of underscores
                if '__' in line:
                    line = re.sub(r'__([^_]+)__', r'**\1**', line)
                if '_' in line and not line.strip().startswith('-'):
                    # Modified regex to avoid matching function_names_with_underscores
                    # Only match isolated underscores that are used for emphasis
                    line = re.sub(
                        r'(?<![a-zA-Z0-9_])_([^_]+)_(?![a-zA-Z0-9_])', r'*\1*', line
                    )

                # Convert numbered lists to bullet points
                if re.match(r'^\d+\.\s+', line):
                    line = re.sub(r'^\d+\.\s+', '- ', line)

                # Fix MD030 - spaces after list markers (ensure only one space after asterisk/dash)
                if re.match(r'^(\s*[-*])\s{2,}', line):
                    line = re.sub(r'^(\s*[-*])\s{2,}', r'\1 ', line)

                # Fix trailing colons in headings (MD026) - only if it's not in a link
                if re.match(r'^#+\s+.*:$', line) and not re.match(
                    r'^#+\s+.*\[.*\]\(.*\):$', line
                ):
                    line = line[:-1]  # Remove the trailing colon

                # Handle MD025 - Single-title/single-h1
                if line.strip().startswith('# '):  # Exact h1 match
                    if not first_h1_found:
                        first_h1_found = True
                    else:
                        # Convert additional h1 headings to h2
                        line = '#' + line

                # Skip duplicate headings
                if line.strip().startswith('#'):
                    heading_text = line.strip()
                    heading_match = re.match(r'^#+', heading_text)
                    if heading_match:
                        heading_level = len(heading_match.group())

                        # Check if this is a section heading (level 2 heading)
                        if heading_level <= 2 and heading_text in seen_headings:
                            # Skip duplicate section headings
                            continue

                        # Add to seen headings set
                        seen_headings.add(heading_text)

                        # Ensure proper spacing around headings
                        if processed_lines and processed_lines[-1].strip():
                            processed_lines.append('')

            processed_lines.append(line)

        # Ensure proper spacing after headings
        final_lines = []
        for i, line in enumerate(processed_lines):
            final_lines.append(line)
            if line.strip().startswith('#') and not line.strip().startswith('```'):
                if i + 1 < len(processed_lines) and processed_lines[i + 1].strip():
                    final_lines.append('')

        # Write back the modified content
        with open(markdown_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_lines))

        # Now use mdformat with proper configuration if available
        try:
            import mdformat
            import mdformat.renderer

            # Configure mdformat to preserve code blocks and mermaid diagrams
            extensions = ['gfm']  # GitHub Flavored Markdown
            options = {
                'code_blocks': True,  # Preserve code blocks
                'number': False,  # Don't number headings
            }

            # Read the file again after our manual fixes
            with open(markdown_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract and save code blocks and mermaid diagrams
            code_blocks = []
            mermaid_blocks = []

            # Simple placeholder pattern
            placeholder_pattern = 'PLACEHOLDER_BLOCK_{}'

            # Extract code blocks
            code_block_pattern = r'```(.*?)\n(.*?)```'

            def replace_code_block(match):
                lang = match.group(1).strip()
                code = match.group(2)
                if lang == 'mermaid':
                    mermaid_blocks.append((lang, code))
                    return placeholder_pattern.format(
                        f'MERMAID_{len(mermaid_blocks)-1}'
                    )
                else:
                    code_blocks.append((lang, code))
                    return placeholder_pattern.format(f'CODE_{len(code_blocks)-1}')

            # Replace code blocks with placeholders
            content_with_placeholders = re.sub(
                code_block_pattern, replace_code_block, content, flags=re.DOTALL
            )

            # Format the markdown content
            formatted_content = mdformat.text(
                content_with_placeholders, extensions=extensions, options=options
            )

            # Restore code blocks and mermaid diagrams
            for i, (lang, code) in enumerate(code_blocks):
                placeholder = placeholder_pattern.format(f'CODE_{i}')
                formatted_content = formatted_content.replace(
                    placeholder, f'```{lang}\n{code}```'
                )

            for i, (lang, code) in enumerate(mermaid_blocks):
                placeholder = placeholder_pattern.format(f'MERMAID_{i}')
                formatted_content = formatted_content.replace(
                    placeholder, f'```{lang}\n{code}```'
                )

            # Fix spaces after list markers in the formatted content (for any that mdformat might have missed)
            formatted_lines = formatted_content.split('\n')
            first_h1_found = False

            for i, line in enumerate(formatted_lines):
                # Fix list marker spacing
                if re.match(r'^(\s*[-*])\s{2,}', line):
                    formatted_lines[i] = re.sub(r'^(\s*[-*])\s{2,}', r'\1 ', line)

                # Fix trailing colons in headings (might be reintroduced by mdformat)
                if re.match(r'^#+\s+.*:$', line) and not re.match(
                    r'^#+\s+.*\[.*\]\(.*\):$', line
                ):
                    formatted_lines[i] = line[:-1]  # Remove the trailing colon

                # Handle MD025 again (in case mdformat changed anything)
                if line.strip().startswith('# '):  # Exact h1 match
                    if not first_h1_found:
                        first_h1_found = True
                    else:
                        # Convert additional h1 headings to h2
                        formatted_lines[i] = '#' + line

            formatted_content = '\n'.join(formatted_lines)

            # Write the formatted content back to the file
            with open(markdown_file, 'w', encoding='utf-8') as f:
                f.write(formatted_content)

            logger.info(
                f'Successfully formatted markdown file with mdformat: {markdown_file}'
            )
        except Exception as e:
            logger.error(f'Error using mdformat: {str(e)}')
            logger.info('Falling back to basic markdown linting')

        logger.info(f'Successfully linted markdown file: {markdown_file}')
    except Exception as e:
        logger.error(f'Error linting markdown file {markdown_file}: {str(e)}')


def extract_remaining_files_from_output(
    output_file: str, source_dir: str
) -> Optional[List[str]]:
    """
    Extract the list of files remaining to study from an existing output file.

    Args:
        output_file: Path to the output markdown file
        source_dir: Source directory path

    Returns:
        List of files remaining to study, or None if the file doesn't exist or section is not found
    """
    output_path = Path(output_file)
    source_path = Path(source_dir)

    # Check if output file exists
    if not output_path.exists():
        logger.debug(
            f'Output file {output_file} does not exist, cannot resume analysis'
        )
        return None

    try:
        # Read the content of the output file
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the "Files Remaining to Study" section
        section_marker = '## Files Remaining to Study'
        section_start = content.find(section_marker)

        if section_start == -1:
            logger.debug(f"No '{section_marker}' section found in {output_file}")
            return None

        # Get content after the section marker
        section_content = content[section_start + len(section_marker) :]

        # Parse lines until end of section (empty line or new section)
        remaining_files: list[str] = []
        for line in section_content.split('\n'):
            line = line.strip()

            # Skip empty lines at the beginning
            if not line and not remaining_files:
                continue

            # Stop at empty line after we've found some files or at new section
            if (not line and remaining_files) or line.startswith('#'):
                break

            # Parse file paths from list items (format: "- `path/to/file`")
            if line.startswith('-'):
                # Extract path from markdown backticks if present
                path_match = re.search(r'`([^`]+)`', line)
                if path_match:
                    rel_path = path_match.group(1)
                else:
                    # Try to get path without backticks
                    rel_path = line[1:].strip()

                # Convert relative path to absolute path
                if not os.path.isabs(rel_path):
                    file_path = str(source_path / rel_path)
                else:
                    file_path = rel_path

                # Verify file exists
                if os.path.exists(file_path):
                    remaining_files.append(file_path)
                else:
                    logger.warning(
                        f'File {file_path} listed in remaining files does not exist'
                    )

        if remaining_files:
            logger.info(
                f'Found {len(remaining_files)} files remaining from previous analysis in {output_file}'
            )
            return remaining_files
        else:
            return None

    except Exception:
        return None


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

    # Try to extract remaining files from existing output file
    files = extract_remaining_files_from_output(output_file, source_dir)

    # If no existing file list was found, discover files with pattern matching
    if files is None:
        logger.info('No valid previous analysis found, discovering files')
        files = discover_files(
            source_dir,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            obey_gitignore=obey_gitignore,
        )
        # Initialize markdown file with all discovered files
        initialize_markdown(output_file, files, source_dir)
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

            # Update markdown file
            update_markdown(output_file, analysis_result, source_dir, remaining_files)

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

    # Lint the markdown file
    lint_markdown(output_file)

    logger.info(
        f'Analysis completed. Analyzed {len(analyzed_files)}/{len(files)} files.'
    )
    return output_file

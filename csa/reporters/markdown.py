import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from csa.reporters.reporters import BaseAnalysisReporter

logger = logging.getLogger(__name__)


class MarkdownAnalysisReporter(BaseAnalysisReporter):
    """
    Reporter that outputs analysis results as Markdown documentation.

    This class handles all markdown-specific formatting and file operations.
    """

    def __init__(self, output_file: str):
        """
        Initialize the markdown reporter.

        Args:
            output_file: Path to the output markdown file
        """
        self.output_file = output_file

    def initialize(self, files: List[str], source_dir: str) -> None:
        """
        Initialize the markdown file with header, diagram, and file lists.

        Args:
            files: List of file paths
            source_dir: Source directory path
        """
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write('# Code Structure Analysis\n\n')

            # Convert source_dir to absolute path if it's not already
            abs_source_dir = os.path.abspath(source_dir)

            # Omit source directory if it's just "."
            if source_dir != '.':
                f.write(f'Source directory: `{abs_source_dir}`\n\n')

            f.write(
                f"Analysis started: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            )

            f.write('## Codebase Structure\n\n')
            # Ensure exactly three backticks for the mermaid block
            mermaid_diagram = self._generate_mermaid_diagram(files, source_dir)
            f.write('```mermaid\n')
            f.write(mermaid_diagram)
            f.write('\n```\n\n')

            # Add Files Analyzed section with a marker for appending
            f.write('## Files Analyzed\n\n')
            f.write('<!-- BEGIN_FILE_ANALYSES -->\n')
            f.write('<!-- END_FILE_ANALYSES -->\n\n')

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
                            if (
                                file_path_obj.is_absolute()
                                and source_path.is_absolute()
                            ):
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

    def update_file_analysis(
        self, file_analysis: Dict[str, Any], source_dir: str, remaining_files: List[str]
    ) -> None:
        """
        Update the markdown file with the analysis results for a file.

        Args:
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
            with open(self.output_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f'Error reading markdown file {self.output_file}: {str(e)}')
            content = ''  # Initialize with empty content instead of exiting

        # Generate file analysis content
        file_content = self._generate_file_analysis_markdown(file_analysis, rel_path)

        # Find the marker positions
        begin_marker = '<!-- BEGIN_FILE_ANALYSES -->'
        end_marker = '<!-- END_FILE_ANALYSES -->'
        begin_pos = content.find(begin_marker)
        end_pos = content.find(end_marker)

        if begin_pos == -1 or end_pos == -1:
            # Report error if markers aren't found
            error_msg = f'Required markers not found in {self.output_file}. File may be corrupted or from an older version.'
            logger.error(error_msg)
            # Reinitialize the file with proper markers if needed
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write('# Code Structure Analysis\n\n')
                f.write('## Files Analyzed\n\n')
                f.write('<!-- BEGIN_FILE_ANALYSES -->\n')
                f.write(file_content)  # Add current analysis
                f.write('\n<!-- END_FILE_ANALYSES -->\n\n')
                # Add remaining files section if needed
                if remaining_files:
                    f.write('## Files Remaining to Study\n\n')
                    for file_path in remaining_files:
                        try:
                            file_path_obj = Path(file_path)
                            source_path = Path(source_dir)
                            if (
                                file_path_obj.is_absolute()
                                and source_path.is_absolute()
                            ):
                                try:
                                    rel_path = str(
                                        file_path_obj.relative_to(source_path)
                                    )
                                except ValueError:
                                    rel_path = file_path
                            else:
                                rel_path = file_path
                            f.write(f'- `{rel_path}`\n')
                        except Exception:
                            f.write(f'- `{file_path}`\n')
            logger.warning(f'Reinitialized {self.output_file} with proper markers')
            return

        # Check if there are any existing analyses
        existing_analyses = content[begin_pos + len(begin_marker) : end_pos].strip()

        # Prepare new content
        if existing_analyses:
            # If we already have analyses, add a blank line if needed
            if not existing_analyses.endswith('\n\n'):
                if existing_analyses.endswith('\n'):
                    file_content = '\n' + file_content
                else:
                    file_content = '\n\n' + file_content

        # Insert the new analysis between the markers
        new_content = (
            content[: begin_pos + len(begin_marker)]
            + existing_analyses
            + file_content
            + content[end_pos:]
        )

        # Update the remaining files section in the new content
        remaining_section_marker = '## Files Remaining to Study'
        remaining_pos = new_content.find(remaining_section_marker)

        if remaining_files:
            # Generate the remaining files content
            remaining_content = f'\n\n{remaining_section_marker}\n\n'
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
                    remaining_content += f'- `{rel_path}`\n'
                except Exception:
                    remaining_content += f'- `{file_path}`\n'

            if remaining_pos != -1:
                # Find the next section after the remaining files
                next_section_pos = new_content.find('\n## ', remaining_pos + 1)
                if next_section_pos != -1:
                    # Replace the existing remaining files section
                    new_content = (
                        new_content[:remaining_pos]
                        + remaining_content
                        + new_content[next_section_pos:]
                    )
                else:
                    # Replace to the end of the file
                    new_content = new_content[:remaining_pos] + remaining_content
            else:
                # Add the remaining files section at the end
                new_content += remaining_content
        else:
            # Remove the remaining files section if it exists
            if remaining_pos != -1:
                next_section_pos = new_content.find('\n## ', remaining_pos + 1)
                if next_section_pos != -1:
                    new_content = (
                        new_content[:remaining_pos] + new_content[next_section_pos:]
                    )
                else:
                    new_content = new_content[:remaining_pos]

        # Write back the updated content
        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
        except Exception as e:
            logger.error(f'Error writing to markdown file {self.output_file}: {str(e)}')

    def finalize(self) -> None:
        """
        Finalize the markdown file by removing markers and linting/formatting it.
        """
        # Remove the marker comments
        try:
            with open(self.output_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find and remove the markers
            begin_marker = '<!-- BEGIN_FILE_ANALYSES -->'
            end_marker = '<!-- END_FILE_ANALYSES -->'
            begin_pos = content.find(begin_marker)
            end_pos = content.find(end_marker)

            if begin_pos != -1 and end_pos != -1:
                # Get the content between the markers
                analyses_content = content[
                    begin_pos + len(begin_marker) : end_pos
                ].strip()

                # Create new content without the markers
                new_content = (
                    content[:begin_pos]
                    + analyses_content
                    + content[end_pos + len(end_marker) :]
                )

                # Write back the content without markers
                with open(self.output_file, 'w', encoding='utf-8') as f:
                    f.write(new_content)

                logger.debug(f'Removed analysis markers from {self.output_file}')
        except Exception as e:
            logger.error(f'Error removing markers from {self.output_file}: {str(e)}')

        # Run markdown linting
        self._lint_markdown()

    def _generate_mermaid_diagram(self, files: List[str], source_dir: str) -> str:
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
        dependencies: Dict[str, Set[str]] = {}

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
                        1,
                        '  classDef entryPoint fill:#f96,stroke:#333,stroke-width:2px;',
                    )
                    break

        return '\n'.join(mermaid)

    def _generate_file_analysis_markdown(
        self, file_analysis: Dict[str, Any], rel_path: str
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
{header_line}

**Error**: {file_analysis["error"]}

{separator}
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

        # Start with common sections - file name and summary
        content = f"""
{header_line}

{summary}
"""

        # Check if classes section has items before adding it
        classes_result = self._format_analysis_section(
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
            functions_result = self._format_analysis_section(
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
            dependencies_result = self._format_analysis_section(
                file_analysis.get('analyses', []), 'dependencies'
            )
            dependencies_content = dependencies_result[0]
            has_dependencies = dependencies_result[1]
            if has_dependencies:
                content += f"""
### {safe_basename} - **Dependencies/Imports**
{dependencies_content}"""

        # Add separator at the end of the content
        content += f'\n{separator}'

        return content.strip()

    def _format_analysis_section(
        self, analyses: List[Dict[str, Any]], section_key: str
    ) -> Tuple[str, bool]:
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

    def _lint_markdown(self) -> None:
        """
        Lint and auto-format the markdown file using mdformat.
        """
        try:
            logger.info(f'Linting markdown file: {self.output_file}')

            # Read the file content
            with open(self.output_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Process the content line by line to fix common issues
            lines = content.split('\n')
            in_code_block = False
            code_block_language = None
            processed_lines: List[str] = []
            seen_headings = set()  # Track headings to eliminate duplicates
            first_h1_found = False  # Track if we've found the first h1 heading

            for line in lines:
                # Check if we're entering or exiting a code block
                if line.strip().startswith('```'):
                    if not in_code_block:
                        # Starting a code block
                        in_code_block = True
                        # Fix MD040 - ensure code blocks have a language specified
                        stripped_line = line.strip()
                        if stripped_line == '```' or stripped_line == '```\n':
                            line = '```text'
                        elif len(stripped_line) > 3 and stripped_line[3:].strip() == '':
                            # Handle cases where there might be spaces after the backticks
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

                    # Fix MD026 - no trailing punctuation in headings
                    if re.match(r'^#+\s+.*[.,:;!?]$', line):
                        # Don't remove trailing punctuation if it's part of a URL or path
                        if not re.search(r'\[[^\]]+\]\([^\)]+[.,:;!?]\)$', line):
                            # Remove trailing punctuation
                            line = re.sub(r'[.,:;!?]$', '', line)

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
            with open(self.output_file, 'w', encoding='utf-8') as f:
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
                with open(self.output_file, 'r', encoding='utf-8') as f:
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
                with open(self.output_file, 'w', encoding='utf-8') as f:
                    f.write(formatted_content)

                logger.info(
                    f'Successfully formatted markdown file with mdformat: {self.output_file}'
                )
            except Exception as e:
                logger.error(f'Error using mdformat: {str(e)}')
                logger.info('Falling back to basic markdown linting')

            logger.info(f'Successfully linted markdown file: {self.output_file}')
        except Exception as e:
            logger.error(f'Error linting markdown file {self.output_file}: {str(e)}')

    def extract_remaining_files(self, source_dir: str) -> Optional[List[str]]:
        """
        Extract the list of files remaining to study from the output file.

        Args:
            source_dir: Source directory path

        Returns:
            List of files remaining to study, or None if the file doesn't exist or section is not found
        """
        output_path = Path(self.output_file)
        source_path = Path(source_dir)

        # Check if output file exists
        if not output_path.exists():
            logger.debug(
                f'Output file {self.output_file} does not exist, cannot resume analysis'
            )
            return None

        try:
            # Read the content of the output file
            with open(self.output_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find the "Files Remaining to Study" section
            section_marker = '## Files Remaining to Study'
            section_start = content.find(section_marker)

            if section_start == -1:
                logger.debug(
                    f"No '{section_marker}' section found in {self.output_file}"
                )
                return None

            # Get content after the section marker
            section_content = content[section_start + len(section_marker) :]

            # Parse lines until end of section (empty line or new section)
            remaining_files: List[str] = []
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
                    f'Found {len(remaining_files)} files remaining from previous analysis in {self.output_file}'
                )
                return remaining_files
            else:
                return None

        except Exception:
            return None

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from llm import LLMProvider

logger = logging.getLogger(__name__)


# Common prompt parts as constants
MARKDOWN_RULES = """
Important Markdown Formatting Rules:
- Do NOT use trailing colons in headings (Bad: "### Some title:", Good: "### Some title")
- A single blank line BEFORE and AFTER ALL headings, no multiple blank lines
- Use proper list indentation with no spaces before list items
- Use single backticks for inline code references
- Do not use HTML tags - use only pure markdown syntax
"""

CODE_ELEMENT_RULES = """
- When referring to code elements, wrap them in backticks like `ClassName` or `method_name()`
"""


def get_formatting_rules(include_code_elements: bool = False) -> str:
    """
    Get markdown formatting rules string based on needed components.

    Args:
        include_code_elements: Whether to include code element formatting rules

    Returns:
        Formatted string with selected rules
    """
    rules = MARKDOWN_RULES

    if include_code_elements:
        # Add code element rules without the line break to keep them in the same list
        code_rules = CODE_ELEMENT_RULES.strip()
        rules = f'{rules}\n{code_rules}'

    return rules


class CodeAnalyzer:
    """Class for analyzing code using an LLM provider."""

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize the code analyzer.

        Args:
            llm_provider: The LLM provider to use for analysis
        """
        self.llm_provider = llm_provider
        self.disable_dependencies = False
        self.disable_functions = False

    def get_context_length(self) -> int:
        """
        Get the context length of the underlying model.

        Returns:
            int: The context length of the model, or a default value if not available
        """
        # Try to get context length from the LLM provider
        if hasattr(self.llm_provider, 'get_context_length'):
            return self.llm_provider.get_context_length()

        # If method doesn't exist, use a conservative default
        return 8192  # Default context length (typical for many models)

    def analyze_code_chunk(
        self,
        file_path: str,
        content: str,
        start_line: int,
        end_line: int,
        total_lines: int,
        structural_only: bool = False,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a chunk of code using the LLM provider.

        Args:
            file_path: Path to the file being analyzed
            content: Content of the file chunk
            start_line: Starting line number of the chunk
            end_line: Ending line number of the chunk
            total_lines: Total number of lines in the file
            structural_only: If True, only extract structural information (for large files)
            timeout: Timeout in seconds for the LLM request, None for no timeout

        Returns:
            Dictionary containing analysis results
        """
        file_ext = os.path.splitext(file_path)[1]
        file_name = os.path.basename(file_path)

        # Build the analysis request based on enabled features
        request_parts = [
            '1. A short description of what this code chunk does',
            '2. A list of classes defined in this chunk',
        ]

        # Conditionally add functions to the request
        if not self.disable_functions:
            request_parts.append('3. A list of functions/methods defined in this chunk')

        # Conditionally add dependencies to the request
        if not self.disable_dependencies:
            request_parts.append(
                f"{'4' if not self.disable_functions else '3'}. A list of dependencies or imports used in this chunk"
            )

        # Adjust instruction when structural_only is True
        instructions_prefix = ''
        if structural_only:
            instructions_prefix = """For this large file chunk, focus ONLY on extracting structural elements (classes, functions, imports).
Keep the description very brief (1-2 sentences) and concentrate on identifying the code structure accurately.
"""

        # Build the JSON schema part based on enabled features
        json_schema_parts = ['- description (string)', '- classes (array of strings)']

        if not self.disable_functions:
            json_schema_parts.append('- functions (array of strings)')

        if not self.disable_dependencies:
            json_schema_parts.append('- dependencies (array of strings)')

        formatting_instructions = """
IMPORTANT: All arrays must contain simple strings, not key-value pairs or objects.
For example, when describing functions, use:
  "functions": [
    "function_name(): Description of what it does",
    "another_function(param): Another description"
  ]
NOT:
  "functions": [
    "function_name()": "Description of what it does",
    "another_function(param)": "Another description"
  ]
"""

        prompt = f"""
You are a code structure analyzer. Your task is to analyze a chunk of code and extract key information.

File: {file_name} (lines {start_line}-{end_line} of {total_lines})

CODE CHUNK:
```{file_ext}
{content}
```

{instructions_prefix}Please provide a JSON response with the following information:
{chr(10).join(request_parts)}

Format your response as a valid JSON object with these keys:
{chr(10).join(json_schema_parts)}
{formatting_instructions}
{get_formatting_rules()}
RESPONSE (JSON):
"""
        try:
            response = self.llm_provider.generate_response(prompt, timeout=timeout)

            # The most direct approach: look for complete JSON objects
            # This regex looks for valid JSON objects with the required fields
            valid_json_pattern = r'({[\s\S]*?"description"[\s\S]*?"classes"[\s\S]*?})'
            complete_json_matches = re.findall(valid_json_pattern, response)

            valid_json = None

            # Try each match until we find one that parses
            for json_candidate in complete_json_matches:
                try:
                    # Test if this is valid JSON
                    json.loads(json_candidate)
                    valid_json = json_candidate
                    break
                except json.JSONDecodeError:
                    continue

            # If we found a valid JSON directly, use it
            if valid_json:
                json_str = valid_json
                preprocessed_json = (
                    valid_json  # No preprocessing needed if direct extraction worked
                )
            # Otherwise use our existing extraction logic
            else:
                # Try to extract just the JSON part from the response
                # Look for JSON-like content (between curly braces)
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)

                    # Check if the JSON is wrapped in markdown code blocks and extract just the JSON
                    # This handles cases where the response is like: ```json\n{...}\n```
                    if '```' in response:
                        # Better JSON extraction that avoids markdown code blocks
                        clean_json_match = re.search(
                            r'```(?:json)?\s*\n({\s*".*?"\s*:.*?})\s*\n```',
                            response,
                            re.DOTALL,
                        )
                        if clean_json_match:
                            json_str = clean_json_match.group(1)

                        # If there are multiple JSON blocks, try an alternative pattern
                        if response.count('```') > 2:
                            # Find all JSON objects in the response
                            json_blocks = re.findall(
                                r'```(?:json)?\s*\n({\s*".*?"\s*:.*?})\s*\n```',
                                response,
                                re.DOTALL,
                            )
                            if json_blocks:
                                # Use the first complete JSON block
                                for block in json_blocks:
                                    if all(
                                        key in block
                                        for key in ['"description"', '"classes"']
                                    ):
                                        json_str = block
                                        break

                    # Remove any trailing backticks or markdown markers that might have been included
                    json_str = re.sub(r'\s*```.*$', '', json_str, flags=re.MULTILINE)

                    # Additional cleanup for any stray backticks
                    json_str = json_str.strip('`').strip()

                    # Log what we're actually trying to parse for debugging
                    if '```' in json_str:
                        logger.debug(
                            f'JSON string still contains backticks after cleanup: {json_str[:100]}...'
                        )

                    # Preprocess JSON string to handle common formatting issues
                    # Handle the case where model returns everything in bold (double-asterisks)
                    # This replaces patterns like: "classes": ["**ClassName**"] with "classes": ["ClassName"]
                    preprocessed_json = re.sub(
                        r'"(\*\*.*?\*\*)"', lambda m: f'"{m.group(1)[2:-2]}"', json_str
                    )

                    # Also handle array items with double-asterisks
                    preprocessed_json = re.sub(
                        r'\[\s*"(\*\*.*?\*\*)"',
                        lambda m: f'[ "{m.group(1)[2:-2]}"',
                        preprocessed_json,
                    )
                    preprocessed_json = re.sub(
                        r'"(\*\*.*?\*\*)"\s*\]',
                        lambda m: f'"{m.group(1)[2:-2]}" ]',
                        preprocessed_json,
                    )
                    preprocessed_json = re.sub(
                        r'"(\*\*.*?\*\*)",',
                        lambda m: f'"{m.group(1)[2:-2]}",',
                        preprocessed_json,
                    )

                    # Handle function definitions with return types in the format: "function_name() -> ReturnType": "description"
                    # Pattern: "function_name() -> ReturnType": "description", -> "function_name() -> ReturnType: description",
                    preprocessed_json = re.sub(
                        r'"([^"]+\(\)[^"]*?)\s*->\s*[^"]+"\s*:\s*"([^"]+)"',
                        r'"\1: \2"',
                        preprocessed_json,
                    )

                    # Handle function definitions without return type in the format: "function_name()": "description"
                    # Pattern: "function_name()": "description", -> "function_name(): description",
                    preprocessed_json = re.sub(
                        r'"([^"]+\(\))\s*"\s*:\s*"([^"]+)"',
                        r'"\1: \2"',
                        preprocessed_json,
                    )

                    # More aggressive fix for any array item that looks like a key-value pair in functions, classes, etc.
                    for array_name in ['functions', 'classes', 'dependencies']:
                        array_match = re.search(
                            f'"{array_name}"\\s*:\\s*\\[(.*?)\\]',
                            preprocessed_json,
                            re.DOTALL,
                        )
                        if array_match:
                            array_content = array_match.group(1)
                            # Check if array has key-value pair format items
                            if re.search(r'"[^"]+"\s*:\s*"[^"]+"', array_content):
                                # Convert each key-value pair to a single string
                                fixed_array = re.sub(
                                    r'"([^"]+)"\s*:\s*"([^"]+)"',
                                    r'"\1: \2"',
                                    array_content,
                                )
                                # Replace the original array with fixed version
                                preprocessed_json = preprocessed_json.replace(
                                    array_content, fixed_array
                                )

                    # Try another approach if we still have colons in the wrong places (common issue)
                    # This will convert all array items that look like key-value pairs into simple strings
                    function_array_match = re.search(
                        r'"functions"\s*:\s*\[(.*?)\]', preprocessed_json, re.DOTALL
                    )
                    if function_array_match:
                        function_array = function_array_match.group(1)
                        # If the function array contains key-value pairs (indicated by ": " inside the array items)
                        if '": "' in function_array:
                            # Convert all key-value pairs in the array to simple strings
                            fixed_function_array = re.sub(
                                r'"([^"]+)"\s*:\s*"([^"]+)"',
                                r'"\1: \2"',
                                function_array,
                            )
                            # Replace the original function array with the fixed one
                            preprocessed_json = preprocessed_json.replace(
                                function_array, fixed_function_array
                            )

                    # Handle cases where attribute assignments like "var = value" are in function arrays
                    # This handles cases like: "llm_provider = os.getenv('LLM_PROVIDER', 'lmstudio')": "description"
                    function_array_match = re.search(
                        r'"functions"\s*:\s*\[(.*?)\]', preprocessed_json, re.DOTALL
                    )
                    if function_array_match:
                        function_array = function_array_match.group(1)
                        # Look for entries with equals signs, which are likely assignments, not functions
                        if '=' in function_array:
                            # Convert assignments with quoted values properly
                            fixed_function_array = re.sub(
                                r'"([^"]+\s*=\s*[^"]+)"\s*:\s*"([^"]+)"',
                                r'"\1: \2"',
                                function_array,
                            )
                            # Replace in the preprocessed JSON
                            if fixed_function_array != function_array:
                                preprocessed_json = preprocessed_json.replace(
                                    function_array, fixed_function_array
                                )

                            # Another pattern for attribute assignments without key-value format
                            # For attributes like: "attribute = value"
                            items = re.findall(r'"([^"]+)"', function_array)
                            for item in items:
                                if '=' in item:
                                    # If item contains equals but isn't already processed
                                    if not item.endswith('",') and not item.endswith(
                                        '",]'
                                    ):
                                        # Escape any existing double quotes in the value
                                        escaped_item = item.replace('"', '\\"')
                                        preprocessed_json = preprocessed_json.replace(
                                            f'"{item}"', f'"{escaped_item}"'
                                        )

                    # Fix missing close bracket if the preprocessing stripped it
                    if '"dependencies"' in preprocessed_json and not re.search(
                        r'"functions"\s*:\s*\[[^\]]*\]', preprocessed_json
                    ):
                        preprocessed_json = re.sub(
                            r'("functions"\s*:\s*\[[^\]]*),\s*"dependencies"',
                            r'\1 ],"dependencies"',
                            preprocessed_json,
                        )

                    # Handle common errors in the description field
                    preprocessed_json = re.sub(
                        r'"description":\s*"([^"]*)"',
                        lambda m: f'"description": "{m.group(1).replace(":", "")}"',
                        preprocessed_json,
                    )

                    # Handle unescaped quotes in function entries, especially in error handling code
                    function_array_match = re.search(
                        r'"functions"\s*:\s*\[(.*?)\]', preprocessed_json, re.DOTALL
                    )
                    if function_array_match:
                        function_array = function_array_match.group(1)
                        # Find any string with unescaped quotes inside it, particularly in error handling patterns
                        items = re.findall(r'"([^"]+)"', function_array)
                        for item in items:
                            if 'return f"' in item or 'return "' in item:
                                # Escape the internal quotes
                                fixed_item = item.replace(
                                    'return f"', 'return f\\"'
                                ).replace('return "', 'return \\"')
                                if '"' in fixed_item[fixed_item.find('return') :]:
                                    fixed_item = re.sub(
                                        r'(return f\\".*?)"', r'\1\\"', fixed_item
                                    )
                                    fixed_item = re.sub(
                                        r'(return \\".*?)"', r'\1\\"', fixed_item
                                    )
                                preprocessed_json = preprocessed_json.replace(
                                    f'"{item}"', f'"{fixed_item}"'
                                )

                    # Handle exception handling patterns specifically
                    function_array_match = re.search(
                        r'"functions"\s*:\s*\[(.*?)\]', preprocessed_json, re.DOTALL
                    )
                    if function_array_match:
                        function_array = function_array_match.group(1)
                        # Look for exception handling patterns
                        items = re.findall(r'"([^"]+)"', function_array)
                        for item in items:
                            if 'except ' in item and 'return' in item:
                                # Convert "except Exception as e: ... return f"Error generating summary: {str(e)}""
                                # to a properly escaped format
                                fixed_item = re.sub(
                                    r'except (.*?) as (.*?):\s*\.\.\.?\s*return f"(.*?){str\((.*?)\)}(.*?)"',
                                    r'except \1 as \2: ... return f\\"\3{str(\4)}\5\\"',
                                    item,
                                )
                                if fixed_item != item:
                                    preprocessed_json = preprocessed_json.replace(
                                        f'"{item}"', f'"{fixed_item}"'
                                    )

                                # Also try a simpler pattern in case the regex is too complex
                                if '"' in item and fixed_item == item:
                                    fixed_item = item.replace('"', '\\"')
                                    preprocessed_json = preprocessed_json.replace(
                                        f'"{item}"', f'"{fixed_item}"'
                                    )

                    # Final cleanup pass for malformed arrays
                    # This fixes cases where the LLM uses key-value pairs in arrays despite instructions
                    for array_name in ['functions', 'classes', 'dependencies']:
                        # Regex pattern that finds array syntax like: "functions": [ "key": "value", ... ]
                        pattern = f'"{array_name}"\\s*:\\s*\\[\\s*(.*?)\\s*\\]'
                        array_match = re.search(pattern, preprocessed_json, re.DOTALL)
                        if array_match:
                            array_content = array_match.group(1).strip()
                            # If we have key-value pairs like "key": "value"
                            if re.search(r'"[^"]+"\s*:\s*"[^"]+"', array_content):
                                # Split the array content by commas that are followed by a quote
                                items = re.split(r',\s*(?=")', array_content)
                                fixed_items = []

                                for item in items:
                                    # Check if this is a key-value pair
                                    kv_match = re.match(
                                        r'\s*"([^"]+)"\s*:\s*"([^"]+)"\s*', item
                                    )
                                    if kv_match:
                                        # Convert to single string: "key: value"
                                        key = kv_match.group(1)
                                        value = kv_match.group(2)
                                        fixed_items.append(f'"{key}: {value}"')
                                    else:
                                        # Keep as is if not a key-value pair
                                        fixed_items.append(item)

                                # Reconstruct the array with fixed items
                                fixed_array = ', '.join(fixed_items)
                                # Replace in the full JSON
                                preprocessed_json = re.sub(
                                    pattern,
                                    f'"{array_name}": [ {fixed_array} ]',
                                    preprocessed_json,
                                    flags=re.DOTALL,
                                )
                else:
                    # No JSON match found
                    json_str = '{}'
                    preprocessed_json = '{}'
                    # Create a fallback result with the expected description
                    result = {
                        'file_path': file_path,
                        'start_line': start_line,
                        'end_line': end_line,
                        'total_lines': total_lines,
                        'description': 'Could not analyze chunk',
                        'classes': [],
                        'functions': [],
                        'dependencies': [],
                    }
                    return result

            try:
                # First try with preprocessed JSON
                result = json.loads(preprocessed_json)

                # If preprocessing was needed, log a warning
                if preprocessed_json != json_str:
                    logger.warning(
                        f'JSON response contained formatting issues in {file_name}:{start_line}-{end_line}. Preprocessing was applied.'
                    )

            except json.JSONDecodeError:
                # If preprocessing didn't help, try the original JSON
                try:
                    result = json.loads(json_str)
                except json.JSONDecodeError as json_err:
                    # Provide detailed context for JSON parsing errors
                    # error_line = json_str.splitlines()[json_err.lineno-1] if json_err.lineno <= len(json_str.splitlines()) else "Line not available"
                    # context_start = max(0, json_err.lineno-3)
                    # context_end = min(json_err.lineno+2, len(json_str.splitlines()))
                    # context_lines = json_str.splitlines()[context_start:context_end]

                    error_context = '\nJSON Error context: '
                    error_context += f'Position: line {json_err.lineno}, column {json_err.colno}, char {json_err.pos}\n'
                    # Commented out to not leak sensitive information:
                    # error_context += f"Error: {str(json_err)}\n"
                    # error_context += f"Problem line: {error_line}\n"
                    # error_context += f"Context:\n" + "\n".join([f"{i+context_start+1}: {line}" for i, line in enumerate(context_lines)])
                    # error_context += f"\nComplete JSON string:\n{json_str}\n"
                    # error_context += f"\nPreprocessed JSON string:\n{preprocessed_json}\n"
                    # error_context += f"\nOriginal response excerpt:\n{response[:200]}...\n"
                    # logger.error(f"JSON parsing error for {file_name}:{start_line}-{end_line}: {str(json_err)}{error_context}")
                    # logger.error(f"JSON parsing error for {file_name}:{start_line}-{end_line}: {str(json_err)}{error_context}")
                    print('\n')
                    logger.error(
                        f'JSON parsing error for {file_name}:{start_line}-{end_line}: {error_context}'
                    )

                    # Create a fallback result
                    result = {
                        'file_path': file_path,
                        'start_line': start_line,
                        'end_line': end_line,
                        'total_lines': total_lines,
                        'description': 'Could not analyze chunk',
                        'classes': [],
                        'functions': [],
                        'dependencies': [],
                    }

                    if not self.disable_functions:
                        result['functions'] = []

                    if not self.disable_dependencies:
                        result['dependencies'] = []

            # Add metadata to result
            result['file_path'] = file_path
            result['start_line'] = start_line
            result['end_line'] = end_line
            result['total_lines'] = total_lines

            # Ensure description field is present
            if 'description' not in result:
                result['description'] = 'No description available'

            # Ensure empty arrays for disabled features
            if self.disable_functions and 'functions' in result:
                del result['functions']

            if self.disable_dependencies and 'dependencies' in result:
                del result['dependencies']

            return result

        except Exception as e:
            logger.error(f'Error during code analysis: {str(e)}')

            result = {
                'file_path': file_path,
                'start_line': start_line,
                'end_line': end_line,
                'total_lines': total_lines,
                'description': f'Error during analysis: {str(e)}',
                'classes': [],
                'functions': [],
                'dependencies': [],
            }

            if not self.disable_functions:
                result['functions'] = []

            if not self.disable_dependencies:
                result['dependencies'] = []

            return result

    def generate_file_summary(
        self, analyses: List[Dict[str, Any]], is_partial: bool = False
    ) -> str:
        """
        Generate a summary for a file based on all its chunk analyses.

        Args:
            analyses: List of analysis results for file chunks
            is_partial: If True, this is a partial summary based on limited chunks (for large files)

        Returns:
            A string summary of the file
        """
        if not analyses:
            return 'No analysis available for this file.'

        file_path = analyses[0]['file_path']
        file_name = os.path.basename(file_path)

        # Collect all classes, functions, and dependencies
        all_classes = []

        # Only collect functions and dependencies if not disabled
        all_functions: list[str] = []
        all_dependencies: list[str] = []

        for analysis in analyses:
            all_classes.extend(analysis.get('classes', []))

            if not self.disable_functions and 'functions' in analysis:
                all_functions.extend(analysis.get('functions', []))

            if not self.disable_dependencies and 'dependencies' in analysis:
                all_dependencies.extend(analysis.get('dependencies', []))

        # Remove duplicates
        all_classes = list(set(all_classes))

        if all_functions is not None:
            all_functions = list(set(all_functions))

        if all_dependencies is not None:
            all_dependencies = list(set(all_dependencies))

        # Format information for the prompt
        classes_str = '\n  - '.join([''] + all_classes) if all_classes else 'None'

        # Build the prompt sections based on enabled features
        prompt_sections = [f'Classes:{classes_str}']

        if not self.disable_functions:
            functions_str = (
                '\n  - '.join([''] + all_functions) if all_functions else 'None'
            )
            prompt_sections.append(f'Functions:{functions_str}')

        if not self.disable_dependencies:
            dependencies_str = (
                '\n  - '.join([''] + all_dependencies) if all_dependencies else 'None'
            )
            prompt_sections.append(f'Dependencies:{dependencies_str}')

        # Adjust prompt intro based on whether this is a partial summary
        summary_intro = f'Please provide a concise summary of the file {file_name} based on the following information:'
        if is_partial:
            summary_intro = f'Please provide a concise summary of the BEGINNING PORTION of the file {file_name} based on the following information. Note that this is a PARTIAL analysis of a large file, focusing only on the initial structure:'

        prompt = f"""
{summary_intro}

{chr(10).join(prompt_sections)}
{get_formatting_rules(include_code_elements=True)}
Your summary should be well-structured with proper markdown formatting.
"""

        try:
            summary = self.llm_provider.generate_response(prompt)
            return summary.strip()
        except Exception as e:
            logger.error(f'Error generating summary: {str(e)}')
            return f'Error generating summary: {str(e)}'


def get_code_analyzer() -> CodeAnalyzer:
    """
    Factory function to get a code analyzer with the configured LLM provider.

    Returns:
        CodeAnalyzer: An initialized code analyzer
    """
    from llm import get_llm_provider

    return CodeAnalyzer(get_llm_provider())

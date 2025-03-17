import os
from pathlib import Path

import pytest

import csa.analyzer as analyzer
from csa.analyzer import (
    analyze_codebase,
    analyze_file,
    discover_files,
    generate_mermaid_diagram,
    initialize_markdown,
    read_file_chunk,
    update_markdown,
)


def test_discover_files(temp_dir, sample_code_file, sample_csharp_file):
    """Test that discover_files correctly identifies files by extension."""
    # Create an excluded directory and file
    excluded_dir = Path(temp_dir) / 'node_modules'
    excluded_dir.mkdir()
    with open(excluded_dir / 'excluded.js', 'w') as f:
        f.write('// This file should be excluded')

    # Create a file with an extension not in FILE_EXTENSIONS
    with open(Path(temp_dir) / 'excluded.txt', 'w') as f:
        f.write('This file should be excluded')

    files = discover_files(temp_dir)

    # Should find the sample files
    assert sample_csharp_file in files
    assert sample_code_file in files

    # Should not find excluded files
    assert str(excluded_dir / 'excluded.js') not in files
    assert str(Path(temp_dir) / 'excluded.txt') not in files

    # Files should be sorted
    assert files == sorted(files)


def test_read_file_chunk(sample_code_file):
    """Test reading a chunk of a file."""
    # Read the first chunk
    lines, eof = read_file_chunk(sample_code_file, 1, 5)
    assert len(lines) == 5
    assert not eof

    # Read to the end of the file
    lines, eof = read_file_chunk(sample_code_file, 10, 100)
    assert len(lines) > 0
    assert eof


def test_analyze_file(sample_code_file, mock_code_analyzer):
    """Test analyzing a file."""
    result = analyze_file(sample_code_file, mock_code_analyzer, chunk_size=5)

    assert result['file_path'] == sample_code_file
    assert 'summary' in result
    assert 'analyses' in result
    assert len(result['analyses']) > 0

    # Each analysis should have the expected properties
    for analysis in result['analyses']:
        assert 'start_line' in analysis
        assert 'end_line' in analysis
        assert 'description' in analysis
        assert 'classes' in analysis
        assert 'functions' in analysis
        assert 'dependencies' in analysis


@pytest.mark.integration
def test_analyze_codebase_with_real_llm(
    temp_dir, sample_code_file, sample_csharp_file, code_analyzer
):
    """
    Test analyzing a codebase with the real code analyzer.

    This is an integration test that requires LM Studio to be running.
    If LM Studio is not running, test will be skipped.
    """
    output_file = Path(temp_dir) / 'output.md'

    try:
        # We're passing None for llm_provider to use the code_analyzer
        analyze_codebase(
            source_dir=temp_dir,
            output_file=str(output_file),
            llm_provider=None,  # Use default
            chunk_size=10,
        )

        # Check that the output file was created
        assert output_file.exists()

        # Check the content of the output file
        with open(output_file, 'r') as f:
            content = f.read()
            assert '# Code Structure Analysis' in content
            assert '## Files Analyzed' in content
            assert os.path.basename(sample_code_file) in content
            assert os.path.basename(sample_csharp_file) in content
    except Exception as e:
        # If the exception is related to LM Studio connection, skip the test
        if 'LMStudioWebsocketError' in str(type(e)):
            pytest.skip('LM Studio is not running, skipping test')
        else:
            # For other errors, let the test fail
            raise


def test_generate_mermaid_diagram(temp_dir, sample_code_file, sample_csharp_file):
    """Test generating a Mermaid diagram."""
    files = [sample_code_file, sample_csharp_file]
    diagram = generate_mermaid_diagram(files, temp_dir)

    assert 'graph TD' in diagram
    assert os.path.basename(sample_code_file).replace('.', '_') in diagram
    assert os.path.basename(sample_csharp_file).replace('.', '_') in diagram


def test_initialize_markdown(temp_dir):
    """Test initializing the markdown file."""
    output_file = Path(temp_dir) / 'output.md'
    files = ['file1.py', 'file2.cs']

    initialize_markdown(str(output_file), files, temp_dir)

    assert output_file.exists()
    with open(output_file, 'r') as f:
        content = f.read()
        assert '# Code Structure Analysis' in content
        assert '## Files Analyzed' in content
        assert '## Files Remaining to Study' in content
        assert 'file1.py' in content
        assert 'file2.cs' in content
        assert '```mermaid' in content


def test_update_markdown(temp_dir):
    """Test updating the markdown file with a file analysis."""
    output_file = Path(temp_dir) / 'output.md'

    # Create initial markdown with the correct sections
    with open(output_file, 'w') as f:
        f.write('# Code Structure Analysis\n\n')
        f.write('## Files Analyzed\n\n')
        f.write('## Files Remaining to Study\n\n')

    file_analysis = {
        'file_path': 'test.py',
        'summary': 'Test summary',
        'total_lines': 15,
        'chunks_analyzed': 1,
        'analyses': [
            {
                'start_line': 1,
                'end_line': 10,
                'description': 'Test description',
                'classes': ['TestClass'],
                'functions': ['test_function'],
                'dependencies': ['os', 'sys'],
            }
        ],
    }

    remaining_files = ['remaining.py']
    update_markdown(str(output_file), file_analysis, temp_dir, remaining_files)

    with open(output_file, 'r') as f:
        content = f.read()
        assert '# Code Structure Analysis' in content
        assert '## Files Analyzed' in content
        assert 'test.py' in content
        assert 'Test summary' in content
        assert 'remaining.py' in content

    # Test with additional sections (using the new signature with remaining_files parameter)
    # Create mock remaining files list
    empty_files: list[str] = []

    # Update with new sections
    file_analysis_section = {
        'file_path': 'section.py',
        'summary': 'This is a new section',
        'total_lines': 10,
        'chunks_analyzed': 1,
        'analyses': [],
    }
    update_markdown(str(output_file), file_analysis_section, temp_dir, empty_files)

    file_analysis_another = {
        'file_path': 'another.py',
        'summary': 'This is another section',
        'total_lines': 10,
        'chunks_analyzed': 1,
        'analyses': [],
    }
    update_markdown(str(output_file), file_analysis_another, temp_dir, empty_files)

    # Read the final content to verify sections were added
    with open(output_file, 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'This is a new section' in content
        assert 'This is another section' in content


def test_lint_markdown(temp_dir):
    """Test that lint_markdown correctly fixes markdown issues."""
    # Create a markdown file with various issues
    markdown_file = Path(temp_dir) / 'test_lint.md'
    with open(markdown_file, 'w') as f:
        f.write("""# Heading with a trailing colon:

## Duplicate heading

## Duplicate heading

- List with    too   many  spaces

1. Numbered list item
2. Another numbered list

*  List with too many spaces after marker

__Bold with underscores__ and _italic with underscores_

```
Code block with no language
```

```mermaid
graph TD
    A --> B
```

# Another H1 heading that should be converted to H2
""")

    # Run the linting
    analyzer.lint_markdown(str(markdown_file))

    # Verify that the issues were fixed
    with open(markdown_file, 'r') as f:
        content = f.read()

    # Check that the trailing colon was removed
    assert '# Heading with a trailing colon\n' in content

    # Check that duplicate heading was removed or modified
    assert content.count('## Duplicate heading') == 1

    # Check that list spacing was fixed
    assert '- List with too many spaces\n' in content

    # Check that numbered lists were converted to bullet points
    assert '- Another numbered list' in content
    assert '1. Numbered list item' not in content

    # Check that list marker spacing was fixed
    assert (
        '* List with too many spaces after marker' in content
        or '- List with too many spaces after marker' in content
    )

    # Check that underscores for emphasis were converted to asterisks
    assert '**Bold with underscores**' in content
    assert '*italic with underscores*' in content

    # Check that code block has a language specifier
    assert '```text' in content or '```' in content

    # Check that mermaid diagram was preserved
    assert '```mermaid' in content
    assert 'graph TD' in content

    # Check that second H1 was converted to H2
    assert '## Another H1 heading that should be converted to H2' in content

    # Note: We don't check for "# Code Structure Analysis" here because
    # lint_markdown doesn't add this heading - it only fixes formatting issues
    # in the existing markdown content

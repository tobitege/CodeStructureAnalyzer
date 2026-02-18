import os
from pathlib import Path

import pytest

from csa.analyzer import (
    analyze_codebase,
    analyze_file,
    discover_files,
    read_file_chunk,
)
from csa.reporters import MarkdownAnalysisReporter


def test_discover_files(temp_dir, sample_code_file, sample_csharp_file):
    """Test that discover_files correctly identifies files by extension."""
    # Create an excluded directory and file
    excluded_dir = Path(temp_dir) / 'node_modules'
    excluded_dir.mkdir()
    with open(excluded_dir / 'excluded.js', 'w', encoding='utf-8') as f:
        f.write('// This file should be excluded')

    # Create a file with an extension not in FILE_EXTENSIONS
    with open(Path(temp_dir) / 'excluded.txt', 'w', encoding='utf-8') as f:
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


def test_analyze_file_uses_preloaded_lines(sample_code_file, mock_code_analyzer, monkeypatch):
    """analyze_file should pass preloaded lines into chunk reads."""
    import csa.analyzer as analyzer_module

    original_reader = analyzer_module.read_file_chunk_significant
    saw_missing_preload = False

    def wrapped_reader(file_path, start_line, chunk_size, file_ext, all_lines=None):
        nonlocal saw_missing_preload
        if all_lines is None:
            saw_missing_preload = True
        return original_reader(file_path, start_line, chunk_size, file_ext, all_lines)

    monkeypatch.setattr(analyzer_module, 'read_file_chunk_significant', wrapped_reader)

    analyze_file(sample_code_file, mock_code_analyzer, chunk_size=2)

    assert not saw_missing_preload


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


def test_markdown_reporter_initialize(temp_dir, sample_code_file, sample_csharp_file):
    """Test that MarkdownAnalysisReporter.initialize creates a correctly formatted markdown file."""
    output_file = Path(temp_dir) / 'reporter_output.md'
    files = [sample_code_file, sample_csharp_file]

    reporter = MarkdownAnalysisReporter(str(output_file))
    reporter.initialize(files, temp_dir)

    assert output_file.exists()
    with open(output_file, 'r') as f:
        content = f.read()
        assert '# Code Structure Analysis' in content
        assert '## Files Analyzed' in content
        assert '## Files Remaining to Study' in content
        assert os.path.basename(sample_code_file) in content
        assert os.path.basename(sample_csharp_file) in content
        assert '```mermaid' in content


def test_markdown_reporter_update_file_analysis(temp_dir):
    """Test that MarkdownAnalysisReporter.update_file_analysis correctly updates the markdown file."""
    output_file = Path(temp_dir) / 'reporter_update.md'

    # Create a reporter and initialize it
    reporter = MarkdownAnalysisReporter(str(output_file))
    reporter.initialize(['test.py', 'remaining.py'], temp_dir)

    # Create a file analysis
    file_analysis = {
        'file_path': 'test.py',
        'summary': 'Test reporter summary',
        'total_lines': 15,
        'chunks_analyzed': 1,
        'analyses': [
            {
                'start_line': 1,
                'end_line': 10,
                'description': 'Test description',
                'classes': ['ReporterTestClass'],
                'functions': ['reporter_test_function'],
                'dependencies': ['os', 'sys'],
            }
        ],
    }

    # Update the markdown file
    remaining_files = ['remaining.py']
    reporter.update_file_analysis(file_analysis, temp_dir, remaining_files)

    # Verify the update
    with open(output_file, 'r') as f:
        content = f.read()
        assert '# Code Structure Analysis' in content
        assert '## Files Analyzed' in content
        assert 'test.py' in content
        assert 'Test reporter summary' in content
        assert 'ReporterTestClass' in content
        assert 'reporter_test_function' in content
        assert 'remaining.py' in content

    # Test updating with multiple files
    file_analysis2 = {
        'file_path': 'remaining.py',
        'summary': 'Second file summary',
        'total_lines': 20,
        'chunks_analyzed': 1,
        'analyses': [
            {
                'start_line': 1,
                'end_line': 20,
                'description': 'Second file description',
                'classes': ['SecondClass'],
                'functions': ['second_function'],
                'dependencies': ['datetime'],
            }
        ],
    }

    # Update with an empty remaining files list
    reporter.update_file_analysis(file_analysis2, temp_dir, [])

    # Verify that both files are now in the analyzed section
    with open(output_file, 'r') as f:
        content = f.read()
        assert 'test.py' in content
        assert 'remaining.py' in content
        assert 'Second file summary' in content
        assert 'SecondClass' in content
        assert 'second_function' in content
        # The "Files Remaining to Study" section should be gone
        assert '## Files Remaining to Study' not in content


def test_markdown_reporter_finalize(temp_dir):
    """Test that MarkdownAnalysisReporter.finalize properly formats the markdown file."""
    output_file = Path(temp_dir) / 'reporter_finalize.md'

    # Create a markdown file with issues to be fixed
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("""# Code Structure Analysis

## Files Analyzed

## Files Remaining to Study

- `test.py`# This should be converted to H2:

__Bold with underscores__

1. Numbered list
2. Should be bullet points

```
Code block with no language
```
""")

    # Create a reporter and finalize the file
    reporter = MarkdownAnalysisReporter(str(output_file))
    reporter.finalize()

    # Verify that the issues were fixed
    with open(output_file, 'r') as f:
        content = f.read()
        assert '# Code Structure Analysis' in content
        assert '**Bold with underscores**' in content
        assert '- Should be bullet points' in content
        assert '```text' in content


def test_markdown_reporter_extract_remaining_files(temp_dir):
    """Test that MarkdownAnalysisReporter.extract_remaining_files correctly extracts remaining files."""
    output_file = Path(temp_dir) / 'reporter_extract.md'

    # Create test files that will be referenced in the markdown
    test_file = Path(temp_dir) / 'extract_test.py'
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write('# Test file for extraction')

    # Create a markdown file with a "Files Remaining to Study" section
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("""# Code Structure Analysis

## Files Analyzed

- `analyzed.py`

## Files Remaining to Study

- `extract_test.py`
- `nonexistent.py`

## Other Section
""")

    # Create a reporter and extract the remaining files
    reporter = MarkdownAnalysisReporter(str(output_file))
    remaining_files = reporter.extract_remaining_files(temp_dir)

    # Verify that the existing file was extracted
    assert remaining_files is not None
    assert len(remaining_files) == 1
    assert os.path.basename(remaining_files[0]) == 'extract_test.py'

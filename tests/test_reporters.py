import os
from pathlib import Path

from csa.reporters import BaseAnalysisReporter, MarkdownAnalysisReporter


class MockReporterImplementation(BaseAnalysisReporter):
    """A simple implementation of the BaseAnalysisReporter for testing."""

    def __init__(self):
        self.initialized = False
        self.updated_files = []
        self.finalized = False
        self.source_dir = ''
        self.files = []
        self.remaining_files = []

    def initialize(self, files, source_dir):
        self.initialized = True
        self.files = files
        self.source_dir = source_dir

    def update_file_analysis(self, file_analysis, source_dir, remaining_files):
        self.updated_files.append(file_analysis['file_path'])
        self.remaining_files = remaining_files

    def finalize(self):
        self.finalized = True


def test_base_reporter_interface():
    """Test that the BaseAnalysisReporter interface works correctly when implemented."""
    reporter = MockReporterImplementation()

    # Test initialization
    reporter.initialize(['file1.py', 'file2.py'], '/test/dir')
    assert reporter.initialized
    assert reporter.files == ['file1.py', 'file2.py']
    assert reporter.source_dir == '/test/dir'

    # Test update
    reporter.update_file_analysis({'file_path': 'file1.py'}, '/test/dir', ['file2.py'])
    assert reporter.updated_files == ['file1.py']
    assert reporter.remaining_files == ['file2.py']

    # Test finalize
    reporter.finalize()
    assert reporter.finalized


def test_markdown_reporter_end_to_end(temp_dir):
    """Test the complete workflow of the MarkdownAnalysisReporter."""
    output_file = Path(temp_dir) / 'end_to_end.md'

    # Create test files
    file1 = Path(temp_dir) / 'test1.py'
    file2 = Path(temp_dir) / 'test2.py'

    with open(file1, 'w', encoding='utf-8') as f:
        f.write('# Test file 1')

    with open(file2, 'w', encoding='utf-8') as f:
        f.write('# Test file 2')

    files = [str(file1), str(file2)]

    # Create and initialize reporter
    reporter = MarkdownAnalysisReporter(str(output_file))
    reporter.initialize(files, temp_dir)

    # Create file analyses
    file_analysis1 = {
        'file_path': str(file1),
        'summary': 'Test file 1 summary',
        'total_lines': 1,
        'chunks_analyzed': 1,
        'analyses': [
            {
                'start_line': 1,
                'end_line': 1,
                'description': 'Test description',
                'classes': ['TestClass1'],
                'functions': ['test_function1'],
                'dependencies': ['os'],
            }
        ],
    }

    file_analysis2 = {
        'file_path': str(file2),
        'summary': 'Test file 2 summary',
        'total_lines': 1,
        'chunks_analyzed': 1,
        'analyses': [
            {
                'start_line': 1,
                'end_line': 1,
                'description': 'Test description',
                'classes': [],
                'functions': ['test_function2'],
                'dependencies': ['sys'],
            }
        ],
    }

    # Update with the first file
    reporter.update_file_analysis(file_analysis1, temp_dir, [str(file2)])

    # Verify that the first file is in the output and the second is in remaining
    with open(output_file, 'r') as f:
        content = f.read()
        assert 'Test file 1 summary' in content
        assert 'TestClass1' in content
        assert 'test_function1' in content
        assert os.path.basename(str(file2)) in content

    # Update with the second file
    reporter.update_file_analysis(file_analysis2, temp_dir, [])

    # Finalize the output
    reporter.finalize()

    # Verify the final output
    with open(output_file, 'r') as f:
        content = f.read()
        assert 'Test file 1 summary' in content
        assert 'Test file 2 summary' in content
        assert 'TestClass1' in content
        assert 'test_function1' in content
        assert 'test_function2' in content
        assert '## Files Remaining to Study' not in content


def test_markdown_reporter_with_error_handling(temp_dir):
    """Test that the MarkdownAnalysisReporter handles errors correctly."""
    output_file = Path(temp_dir) / 'error_handling.md'

    # Create and initialize reporter
    reporter = MarkdownAnalysisReporter(str(output_file))
    reporter.initialize(['file.py'], temp_dir)

    # Create file analysis with an error
    file_analysis = {
        'file_path': 'file.py',
        'error': 'Test error message',
    }

    # Update with the file that had an error
    reporter.update_file_analysis(file_analysis, temp_dir, [])

    # Verify that the error is in the output
    with open(output_file, 'r') as f:
        content = f.read()
        assert 'file.py' in content
        assert 'Error' in content
        assert 'Test error message' in content


def test_section_formatting():
    """Test the section formatting function of the MarkdownAnalysisReporter."""
    reporter = MarkdownAnalysisReporter('temp.md')  # Temporary file not actually used

    # Test with multiple items
    analyses = [
        {'classes': ['Class1', 'Class2']},
        {'classes': ['Class3', 'Class1']},  # Duplicate that should be removed
    ]

    content, has_items = reporter._format_analysis_section(analyses, 'classes')
    assert has_items
    assert '- Class1\n' in content
    assert '- Class2\n' in content
    assert '- Class3\n' in content
    assert content.count('Class1') == 1  # Check duplicates were removed

    # Test with no items
    analyses = [
        {'functions': []},
        {'functions': []},
    ]

    content, has_items = reporter._format_analysis_section(analyses, 'functions')
    assert not has_items
    assert 'No items found' in content

    # Test with missing section
    analyses = [
        {'functions': ['func1']},
        {'classes': ['Class1']},
    ]

    content, has_items = reporter._format_analysis_section(analyses, 'dependencies')
    assert not has_items
    assert 'No items found' in content


def test_mermaid_diagram_uses_unique_nodes_for_duplicate_basenames(temp_dir):
    """Mermaid nodes should remain distinct for duplicate basenames in different folders."""
    output_file = Path(temp_dir) / 'diagram.md'
    reporter = MarkdownAnalysisReporter(str(output_file))

    dir_a = Path(temp_dir) / 'a'
    dir_b = Path(temp_dir) / 'b'
    dir_a.mkdir()
    dir_b.mkdir()

    file_a = dir_a / 'utils.py'
    file_b = dir_b / 'utils.py'
    file_a.write_text('import os\n', encoding='utf-8')
    file_b.write_text('import sys\n', encoding='utf-8')

    diagram = reporter._generate_mermaid_diagram(
        [str(file_a), str(file_b)],
        temp_dir,
    )

    assert 'a/utils.py' in diagram
    assert 'b/utils.py' in diagram

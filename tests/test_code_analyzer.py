from unittest.mock import MagicMock, patch

from code_analyzer import CodeAnalyzer, get_code_analyzer


def test_get_code_analyzer():
    """Test that get_code_analyzer returns a valid CodeAnalyzer instance."""
    with patch('llm.get_llm_provider') as mock_get_llm_provider:
        mock_llm_provider = MagicMock()
        mock_get_llm_provider.return_value = mock_llm_provider

        analyzer = get_code_analyzer()
        assert analyzer is not None
        assert isinstance(analyzer, CodeAnalyzer)
        assert analyzer.llm_provider == mock_llm_provider


def test_analyze_code_chunk():
    """Test that CodeAnalyzer can analyze a code chunk."""
    mock_llm_provider = MagicMock()

    # Mock the JSON response from the LLM
    json_response = '{"description": "Test description", "classes": ["TestClass"], "functions": ["test_function"], "dependencies": ["os", "sys"]}'
    mock_llm_provider.generate_response.return_value = json_response

    analyzer = CodeAnalyzer(mock_llm_provider)

    result = analyzer.analyze_code_chunk(
        file_path='test.py',
        content='# Test content',
        start_line=1,
        end_line=10,
        total_lines=10,
    )

    # Check that the LLM provider was called with a prompt
    mock_llm_provider.generate_response.assert_called_once()

    # Verify result structure
    assert result['file_path'] == 'test.py'
    assert result['start_line'] == 1
    assert result['end_line'] == 10
    assert result['total_lines'] == 10
    assert result['description'] == 'Test description'
    assert result['classes'] == ['TestClass']
    assert result['functions'] == ['test_function']
    assert result['dependencies'] == ['os', 'sys']


def test_analyze_code_chunk_json_extraction_error():
    """Test that CodeAnalyzer handles JSON extraction errors gracefully."""
    mock_llm_provider = MagicMock()

    # Return a response that doesn't contain valid JSON
    mock_llm_provider.generate_response.return_value = 'This is not a JSON response'

    analyzer = CodeAnalyzer(mock_llm_provider)

    result = analyzer.analyze_code_chunk(
        file_path='test.py',
        content='# Test content',
        start_line=1,
        end_line=10,
        total_lines=10,
    )

    # Should return a fallback result with empty lists
    assert result['file_path'] == 'test.py'
    assert result['description'] == 'Could not analyze chunk'
    assert result['classes'] == []
    assert result['functions'] == []
    assert result['dependencies'] == []


def test_analyze_code_chunk_exception():
    """Test that CodeAnalyzer handles exceptions gracefully."""
    mock_llm_provider = MagicMock()

    # Simulate an error in the LLM provider
    mock_llm_provider.generate_response.side_effect = Exception('Test error')

    analyzer = CodeAnalyzer(mock_llm_provider)

    result = analyzer.analyze_code_chunk(
        file_path='test.py',
        content='# Test content',
        start_line=1,
        end_line=10,
        total_lines=10,
    )

    # Should return an error result
    assert result['file_path'] == 'test.py'
    assert 'Error during analysis' in result['description']
    assert result['classes'] == []
    assert result['functions'] == []
    assert result['dependencies'] == []


def test_generate_file_summary():
    """Test that CodeAnalyzer can generate a file summary."""
    mock_llm_provider = MagicMock()

    # Mock the summary response from the LLM
    mock_llm_provider.generate_response.return_value = 'This is a summary of the file'

    analyzer = CodeAnalyzer(mock_llm_provider)

    analyses = [
        {
            'file_path': 'test.py',
            'start_line': 1,
            'end_line': 10,
            'total_lines': 20,
            'description': 'Test description',
            'classes': ['TestClass'],
            'functions': ['test_function'],
            'dependencies': ['os', 'sys'],
        },
        {
            'file_path': 'test.py',
            'start_line': 11,
            'end_line': 20,
            'total_lines': 20,
            'description': 'Another test description',
            'classes': ['AnotherClass'],
            'functions': ['another_function'],
            'dependencies': ['json', 'time'],
        },
    ]

    summary = analyzer.generate_file_summary(analyses)

    # Check that the LLM provider was called with a prompt
    mock_llm_provider.generate_response.assert_called_once()

    # Verify the summary
    assert summary == 'This is a summary of the file'


def test_generate_file_summary_empty_analyses():
    """Test that CodeAnalyzer handles empty analyses gracefully."""
    mock_llm_provider = MagicMock()
    analyzer = CodeAnalyzer(mock_llm_provider)

    summary = analyzer.generate_file_summary([])

    # Should return a fallback message
    assert summary == 'No analysis available for this file.'
    # The LLM provider should not have been called
    mock_llm_provider.generate_response.assert_not_called()


def test_generate_file_summary_exception():
    """Test that CodeAnalyzer handles exceptions in summary generation gracefully."""
    mock_llm_provider = MagicMock()

    # Simulate an error in the LLM provider
    mock_llm_provider.generate_response.side_effect = Exception('Test error')

    analyzer = CodeAnalyzer(mock_llm_provider)

    analyses = [
        {
            'file_path': 'test.py',
            'total_lines': 10,
            'classes': ['TestClass'],
            'functions': ['test_function'],
            'dependencies': ['os', 'sys'],
        }
    ]

    summary = analyzer.generate_file_summary(analyses)

    # Should return an error message
    assert 'Error generating summary' in summary

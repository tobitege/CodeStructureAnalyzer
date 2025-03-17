from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from csa.llm import LMStudioProvider, extract_response_content, get_llm_provider


# Mock the import of lmstudio rather than accessing a module attribute
@patch(
    'builtins.__import__',
    side_effect=lambda name, *args: MagicMock()
    if name == 'lmstudio'
    else __import__(name, *args),
)
def test_get_llm_provider(mock_import):
    """Test that get_llm_provider returns a valid LLM provider."""
    provider = get_llm_provider()
    assert provider is not None
    assert hasattr(provider, 'generate_response')


# Mock the import of lmstudio rather than accessing a module attribute
@patch(
    'builtins.__import__',
    side_effect=lambda name, *args: MagicMock()
    if name == 'lmstudio'
    else __import__(name, *args),
)
def test_lmstudio_provider_init(mock_import):
    """Test LMStudioProvider initialization."""
    # Test with default host
    provider = LMStudioProvider()
    assert provider.host is not None

    # Test with custom host
    custom_host = 'localhost:5678'
    provider = LMStudioProvider(host=custom_host)
    assert provider.host == custom_host


@pytest.mark.integration
def test_lmstudio_generate_response(llm_provider):
    """
    Test that LMStudioProvider can generate a response.

    This is an integration test that requires LM Studio to be running.
    If LM Studio is not running, the test will be skipped.
    """
    try:
        prompt = 'What is 2+2?'
        response = llm_provider.generate_response(prompt)

        assert isinstance(response, str)
        assert len(response) > 0
    except Exception as e:
        # If the exception is related to LM Studio connection, skip the test
        if 'LMStudioWebsocketError' in str(type(e)):
            pytest.skip('LM Studio is not running, skipping test')
        else:
            # For other errors, let the test fail
            raise


def test_mock_llm_provider(mock_llm_provider):
    """Test that mock LLM provider functions correctly."""
    response = mock_llm_provider.generate_response('Test prompt')
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.parametrize(
    'response_type,expected_text',
    [
        ('content', 'Extracted from content'),
        ('prediction', 'Extracted from prediction'),
        ('string', 'Extracted from string conversion'),
    ],
)
def test_extract_response_content(response_type, expected_text):
    """Test that we can extract content from different types of LM Studio responses."""
    # Create a mock response object based on the test parameter
    if response_type == 'content':

        class ContentResponse:
            content = expected_text

        response: Any = ContentResponse()
    elif response_type == 'prediction':

        class PredictionResponse:
            prediction = expected_text

        response_pred: Any = PredictionResponse()
    else:  # string

        class StringResponse:
            def __str__(self):
                return expected_text

        response_str: Any = StringResponse()

    # Test the extraction function directly
    result = extract_response_content(
        response
        if response_type == 'content'
        else response_pred
        if response_type == 'prediction'
        else response_str
    )
    assert result == expected_text

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from csa.config import config

logger = logging.getLogger(__name__)


class LMStudioWebsocketError(Exception):
    """Exception raised when unable to connect to LM Studio websocket."""

    pass


class OllamaError(Exception):
    """Exception raised when unable to connect to or use Ollama API."""

    pass


def extract_response_content(response_obj: Any) -> str:
    """
    Extract text content from various LLM response object formats.

    Args:
        response_obj: Response object from an LLM

    Returns:
        Extracted text content as string
    """
    if hasattr(response_obj, 'content'):
        return response_obj.content
    elif hasattr(response_obj, 'prediction'):
        return response_obj.prediction
    else:
        # Convert the object to string if no specific attribute found
        return str(response_obj)


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def generate_response(self, prompt: str, timeout: Optional[int] = None) -> str:
        """
        Generate a response for the given prompt.

        Args:
            prompt: The prompt to send to the LLM
            timeout: Timeout in seconds for the request (None for no timeout)

        Returns:
            Generated response as string
        """
        pass

    @abstractmethod
    def get_context_length(self) -> int:
        """
        Get the context length of the currently loaded model.

        Returns:
            The context length of the model in tokens
        """
        pass


class LMStudioProvider(LLMProvider):
    """LMStudio API client for local LLM inference.

    Uses the LMSTUDIO_HOST configuration value to connect to a local LM Studio instance.
    """

    def __init__(self, host: str | None = None):
        """
        Initialize the LMStudio provider.

        Args:
            host: Host address for LMStudio (default: config.LMSTUDIO_HOST)
        """
        self.host = host or config.LMSTUDIO_HOST

        # Import here instead of at the top to make mocking easier for tests
        try:
            import lmstudio as lms

            # Set websocket-related loggers to DEBUG level
            for logger_name in ['_AsyncWebsocketThread', 'SyncLMStudioWebsocket']:
                logging.getLogger(logger_name).setLevel(logging.DEBUG)

            self.lms = lms

            # Connect to the model - host is managed through LMStudio's config
            # We're not passing host directly as the function doesn't accept it
            self.model = self.lms.llm()
            logger.info(f'Initialized LMStudio provider with host: {self.host}')

        except ImportError:
            raise ImportError('Please install lmstudio: pip install lmstudio')
        except Exception as e:
            logger.error(f'Error initializing LMStudio: {str(e)}')
            raise LMStudioWebsocketError(
                f'Failed to connect to LM Studio at {self.host}: {str(e)}'
            )

    def generate_response(self, prompt: str, timeout: Optional[int] = None) -> str:
        """
        Generate a response for the given prompt.

        Args:
            prompt: The prompt to send to the LLM
            timeout: Timeout in seconds for the request (None for no timeout)

        Returns:
            Generated response as string
        """
        try:
            self.model = (
                self.lms.llm()
            )  # Important to reinitialize the model each time!

            # Use timeout if provided
            if timeout is not None:
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    # Submit the task to the executor
                    future = executor.submit(self.model.respond, prompt)

                    try:
                        # Wait for the result with a timeout
                        response_obj = future.result(timeout=timeout)
                        return extract_response_content(response_obj)
                    except concurrent.futures.TimeoutError:
                        # Cancel the future if possible
                        future.cancel()
                        # Raise timeout for caller handling
                        raise TimeoutError(
                            f'LLM request timed out after {timeout} seconds'
                        )
            else:
                # No timeout specified, use normal call
                response_obj = self.model.respond(prompt)
                return extract_response_content(response_obj)

        except TimeoutError:
            # Re-raise timeout errors to be handled by the caller
            raise
        except Exception as e:
            logger.error(f'Error generating response: {str(e)}')
            raise LMStudioWebsocketError(
                f'Failed to get response from LM Studio: {str(e)}'
            ) from e

    def get_context_length(self) -> int:
        """
        Get the context length of the currently loaded model.

        Returns:
            The context length of the model in tokens
        """
        try:
            # Ensure model is initialized
            if not hasattr(self, 'model') or self.model is None:
                self.model = self.lms.llm()

            # Get context length from the model
            context_length = self.model.get_context_length()
            return context_length
        except Exception as e:
            logger.warning(f'Failed to get context length from LM Studio: {str(e)}')
            # Return a conservative default
            return 8192


class OllamaProvider(LLMProvider):
    """Ollama API client for local LLM inference."""

    def __init__(self, host: str | None = None, model: str | None = None):
        """
        Initialize the Ollama provider.

        Args:
            host: Host address for Ollama (default: config.OLLAMA_HOST)
            model: Model name to use (default: config.OLLAMA_MODEL or 'qwen2.5-coder:14b')
        """
        self.host = host or config.OLLAMA_HOST
        self.model_name = model or getattr(config, 'OLLAMA_MODEL', 'qwen2.5-coder:14b')

        # Import here instead of at the top to make mocking easier for tests
        try:
            from ollama import Client

            # Initialize the Ollama client
            self.client = Client(host=f'{self.host}', timeout=20.0)
            logger.info(
                f'Initialized Ollama provider with host: {self.host}, model: {self.model_name}'
            )

            # Check if model exists
            try:
                models = self.client.list()
                if not any(
                    model['name'] == self.model_name
                    for model in models.get('models', [])
                ):
                    logger.warning(
                        f"Model {self.model_name} not found in Ollama. Please make sure it's available."
                    )
            except Exception as e:
                logger.warning(f'Could not verify model availability: {str(e)}')

        except ImportError:
            raise ImportError('Please install ollama: pip install ollama')
        except Exception as e:
            logger.error(f'Error initializing Ollama: {str(e)}')
            raise OllamaError(f'Failed to connect to Ollama at {self.host}: {str(e)}')

    def generate_response(self, prompt: str, timeout: Optional[int] = None) -> str:
        """
        Generate a response for the given prompt.

        Args:
            prompt: The prompt to send to the LLM
            timeout: Timeout in seconds for the request (None for no timeout)

        Returns:
            Generated response as string
        """
        try:
            # Use timeout if provided
            if timeout is not None:
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    # Submit the task to the executor
                    future = executor.submit(
                        self.client.generate, model=self.model_name, prompt=prompt
                    )

                    try:
                        # Wait for the result with a timeout
                        response = future.result(timeout=timeout)
                        return response.get('response', '')
                    except concurrent.futures.TimeoutError:
                        # Cancel the future if possible
                        future.cancel()
                        # Raise timeout for caller handling
                        raise TimeoutError(
                            f'LLM request timed out after {timeout} seconds'
                        )
            else:
                # No timeout specified, use normal call
                response = self.client.generate(model=self.model_name, prompt=prompt)
                return response.get('response', '')
        except TimeoutError:
            # Re-raise timeout errors to be handled by the caller
            raise
        except Exception as e:
            logger.error(f'Error generating response: {str(e)}')
            raise OllamaError(f'Failed to get response from Ollama: {str(e)}')

    def get_context_length(self) -> int:
        """
        Get the context length of the currently loaded model.

        Returns:
            The context length of the model in tokens
        """
        try:
            # Ensure model is initialized
            if not hasattr(self, 'client') or self.client is None:
                from ollama import Client

                self.client = Client(host=f'{self.host}', timeout=20.0)

            # Try to get direct context length from model info
            model_info = self.client.show(self.model_name)
            if hasattr(model_info, 'modelinfo'):
                # Check for context length in model info
                for key in [
                    'context_length',
                    'qwen2.context_length',
                    'llama.context_length',
                    'mistral.context_length',
                ]:
                    if key in model_info.modelinfo:
                        context_length = int(model_info.modelinfo[key])
                        logger.info(
                            f'Context length for {self.model_name}: {context_length} tokens'
                        )
                        return context_length

            # Fall back to model family-based estimation
            model_base = (
                self.model_name.split(':')[0].lower() if self.model_name else 'unknown'
            )

            # Context window sizes for common models
            context_lengths = {
                'llama3': 8192,
                'llama2': 4096,
                'mistral': 8192,
                'mixtral': 32768,
                'qwen': 32768,
                'phi3': 4096,
                'gemma': 8192,
                'qwen2': 32768,
                'qwen2.5-coder': 32768,
                'codellama': 16384,
                'vicuna': 4096,
                'wizardcoder': 16384,
            }

            # Check if we have a known context length for this model
            for model_prefix, length in context_lengths.items():
                if model_base.startswith(model_prefix):
                    logger.info(
                        f'Using estimated context length for {self.model_name}: {length} tokens'
                    )
                    return length

            # Return a conservative default if we don't recognize the model
            logger.warning(
                f'Unknown model: {self.model_name}, using default context length of 8192 tokens'
            )
            return 8192
        except Exception as e:
            logger.warning(f'Failed to get context length from Ollama: {str(e)}')
            # Return a conservative default
            return 8192


def get_llm_provider() -> LLMProvider:
    """Factory function to get the configured LLM provider."""
    provider = config.LLM_PROVIDER.lower()

    if provider == 'lmstudio':
        return LMStudioProvider()
    elif provider == 'ollama':
        return OllamaProvider()
    else:
        raise ValueError(f'Unsupported LLM provider: {provider}')


# Explicitly export the utility functions for importing by other modules
__all__ = [
    'extract_response_content',
    'LLMProvider',
    'LMStudioProvider',
    'OllamaProvider',
    'get_llm_provider',
]

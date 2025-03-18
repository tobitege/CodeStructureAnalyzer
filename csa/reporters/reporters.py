from typing import Any, Dict, List

class BaseAnalysisReporter:
    """
    Base class for all analysis reporters that format and output codebase analysis results.

    This abstract class defines the interface that all concrete reporters must implement.
    """

    def initialize(self, files: List[str], source_dir: str) -> None:
        """
        Initialize the output with header information and file lists.

        Args:
            files: List of file paths to be analyzed
            source_dir: Source directory path
        """
        raise NotImplementedError

    def update_file_analysis(
        self, file_analysis: Dict[str, Any], source_dir: str, remaining_files: List[str]
    ) -> None:
        """
        Update the output with analysis results for a single file.

        Args:
            file_analysis: Analysis results for a file
            source_dir: Source directory path
            remaining_files: List of files remaining to analyze
        """
        raise NotImplementedError

    def finalize(self) -> None:
        """
        Finalize the output, performing any cleanup or post-processing.
        """
        raise NotImplementedError

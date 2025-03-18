"""Code Structure Analyzer package."""

from csa.analyzer import analyze_codebase
from csa.reporters import BaseAnalysisReporter, MarkdownAnalysisReporter

__version__ = '0.2.0'

__all__ = ['analyze_codebase', 'BaseAnalysisReporter', 'MarkdownAnalysisReporter']

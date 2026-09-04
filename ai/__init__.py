"""Model-independent interfaces for future AI assistance."""

from .error_context import ErrorContext, TokenContext, build_error_contexts
from .error_predictor import AIErrorPredictor, ErrorPrediction

__all__ = ["AIErrorPredictor", "ErrorContext", "ErrorPrediction", "TokenContext", "build_error_contexts"]

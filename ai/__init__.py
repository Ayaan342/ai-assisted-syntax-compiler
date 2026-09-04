"""Model-independent interfaces for future AI assistance."""

from .error_context import ErrorContext, TokenContext, build_error_contexts
from .error_predictor import AIErrorPredictor, ErrorPrediction
from .semantic_context import SemanticContext, build_semantic_contexts

__all__ = [
    "AIErrorPredictor", "ErrorContext", "ErrorPrediction", "SemanticContext",
    "TokenContext", "build_error_contexts", "build_semantic_contexts",
]

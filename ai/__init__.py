"""ML-assisted compiler correction interfaces."""

from .error_context import ErrorContext, TokenContext, build_error_contexts
from .error_predictor import AIErrorPredictor, ErrorPrediction
from .semantic_context import SemanticContext, build_semantic_contexts
from .dataset_generator import CorrectionClass, DatasetRecord, SyntheticDatasetGenerator
from .error_predictor import MLCorrectionPredictor, TrainingReport, train_classifier
from .correction_orchestrator import (
    CorrectionOrchestrator,
    CorrectionPolicy,
    CorrectionResult,
    CorrectionStatus,
    correct_source,
)
from .llm_fallback import GroqFallbackService, LLMFallbackResult, LLMSuggestion

__all__ = [
    "AIErrorPredictor", "CorrectionClass", "CorrectionOrchestrator", "CorrectionPolicy",
    "CorrectionResult", "CorrectionStatus", "DatasetRecord", "ErrorContext",
    "ErrorPrediction", "MLCorrectionPredictor", "SemanticContext",
    "GroqFallbackService", "LLMFallbackResult", "LLMSuggestion",
    "SyntheticDatasetGenerator", "TokenContext", "TrainingReport",
    "build_error_contexts", "build_semantic_contexts", "correct_source", "train_classifier",
]

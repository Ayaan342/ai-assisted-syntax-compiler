"""Model-independent interfaces for future AI assistance."""

from .error_context import ErrorContext, TokenContext, build_error_contexts
from .error_predictor import AIErrorPredictor, ErrorPrediction
from .semantic_context import SemanticContext, build_semantic_contexts
from .dataset_generator import CorrectionClass, DatasetRecord, SyntheticDatasetGenerator
from .error_predictor import MLCorrectionPredictor, TrainingReport, train_classifier

__all__ = [
    "AIErrorPredictor", "CorrectionClass", "DatasetRecord", "ErrorContext",
    "ErrorPrediction", "MLCorrectionPredictor", "SemanticContext",
    "SyntheticDatasetGenerator", "TokenContext", "TrainingReport",
    "build_error_contexts", "build_semantic_contexts", "train_classifier",
]

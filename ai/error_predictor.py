"""Protocol for replaceable ML/LLM error predictors (no Phase 1 model)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .error_context import ErrorContext


@dataclass(frozen=True, slots=True)
class ErrorPrediction:
    label: str
    confidence: float


class AIErrorPredictor(Protocol):
    def predict_error_type(self, context: ErrorContext) -> ErrorPrediction:
        """Predict a correction category from compiler-produced context."""
        ...

    def rank_candidates(
        self, context: ErrorContext, candidates: Sequence[object]
    ) -> Sequence[tuple[object, float]]:
        """Rank compiler-generated candidates without applying them."""
        ...


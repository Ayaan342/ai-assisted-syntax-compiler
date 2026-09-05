"""Shared, cached backend dependencies for model and fallback readiness."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Depends

from ai.correction_orchestrator import CorrectionOrchestrator
from ai.error_predictor import MLCorrectionPredictor
from ai.llm_fallback import GroqFallbackService


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "models" / "syntax_error_classifier.joblib"
ENV_PATH = PROJECT_ROOT / ".env"


class ModelUnavailableError(RuntimeError):
    """Raised when correction is requested without a trained model artifact."""


@lru_cache(maxsize=1)
def get_predictor() -> MLCorrectionPredictor:
    if not MODEL_PATH.is_file():
        raise ModelUnavailableError("Correction model is unavailable; train it first")
    try:
        return MLCorrectionPredictor.load(MODEL_PATH)
    except Exception as exc:
        raise ModelUnavailableError("Correction model could not be loaded") from exc


@lru_cache(maxsize=1)
def get_groq_fallback() -> GroqFallbackService:
    return GroqFallbackService(env_path=ENV_PATH)


def get_orchestrator(
    predictor: MLCorrectionPredictor = Depends(get_predictor),
    fallback: GroqFallbackService = Depends(get_groq_fallback),
) -> CorrectionOrchestrator:
    return CorrectionOrchestrator(predictor, llm_fallback=fallback)

"""Thin HTTP adapter for the existing correction orchestrator."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ai.correction_orchestrator import CorrectionOrchestrator

from ..dependencies import get_orchestrator
from ..schemas import CodeRequest, CorrectionResponse


router = APIRouter(tags=["correction"])


@router.post("/correct", response_model=CorrectionResponse, summary="Correct Mini-C syntax")
def correct_source(
    request: CodeRequest,
    orchestrator: CorrectionOrchestrator = Depends(get_orchestrator),
) -> CorrectionResponse:
    result = orchestrator.correct(request.code)
    return CorrectionResponse(
        success=result.success,
        original_code=result.original_source,
        corrected_code=result.corrected_source,
        fully_syntactically_valid=result.fully_syntactically_valid,
        corrections_applied=result.corrections_applied,
        history=[item.to_dict() for item in result.history],
        predictions=[item.to_dict() for item in result.predictions],
        confidence_values=[item.confidence for item in result.predictions],
        groq_fallback_used=any(
            item.llm_fallback is not None and item.llm_fallback.attempted
            for item in result.history
        ),
        ambiguity_selection_used=any(
            item.ambiguity_selection is not None
            and item.ambiguity_selection.attempted
            for item in result.history
        ),
        needs_llm_fallback=result.needs_llm_fallback,
        unresolved_syntax_diagnostics=[
            item.to_dict() for item in result.unresolved_diagnostics
        ],
        semantic_diagnostics=[item.to_dict() for item in result.semantic_diagnostics],
        stop_reason=result.stop_reason,
    )

"""Model-compatibility scoring boundary for Phase 6 candidate ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from compiler.correction import CorrectionAction, CorrectionCandidate

from .dataset_generator import CorrectionClass
from .error_predictor import ErrorPrediction


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: CorrectionCandidate
    compatibility_score: float
    matched_class: str | None


def candidate_class(candidate: CorrectionCandidate) -> str | None:
    if candidate.action is CorrectionAction.INSERT:
        mapping = {
            "SEMICOLON": CorrectionClass.INSERT_SEMICOLON.value,
            "RPAREN": CorrectionClass.INSERT_RPAREN.value,
            "LPAREN": CorrectionClass.INSERT_LPAREN.value,
            "RBRACKET": CorrectionClass.INSERT_RBRACKET.value,
            "RBRACE": CorrectionClass.INSERT_RBRACE.value,
        }
        return mapping.get(candidate.token_type)
    if candidate.action is CorrectionAction.DELETE:
        return CorrectionClass.DELETE_EXTRA_TOKEN.value
    if candidate.action is CorrectionAction.REPLACE:
        if candidate.token_type in {"LPAREN", "RPAREN", "LBRACKET", "RBRACKET"}:
            return CorrectionClass.REPLACE_BRACKET.value
        if candidate.token_type in {"EQ", "NE", "LE", "GE", "LT", "GT"}:
            return CorrectionClass.REPLACE_OPERATOR.value
        if candidate.token_type in {
            "INT", "FLOAT", "CHAR", "BOOL", "VOID", "IF", "ELSE", "WHILE",
            "FOR", "BREAK", "CONTINUE", "RETURN",
        }:
            return CorrectionClass.CORRECT_KEYWORD.value
    return None


def rank_candidates(
    candidates: Sequence[CorrectionCandidate], prediction: ErrorPrediction
) -> list[RankedCandidate]:
    """Score compatibility only; never apply or automatically select a source edit."""

    ranked = [
        RankedCandidate(
            candidate=candidate,
            compatibility_score=prediction.probabilities.get(candidate_class(candidate) or "", 0.0),
            matched_class=candidate_class(candidate),
        )
        for candidate in candidates
    ]
    return sorted(ranked, key=lambda item: item.compatibility_score, reverse=True)

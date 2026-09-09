"""Model-compatibility scoring boundary for Phase 6 candidate ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from compiler.correction import CandidateValidation, CorrectionAction, CorrectionCandidate

from .dataset_generator import CorrectionClass
from .error_context import ErrorContext
from .error_predictor import ErrorPrediction


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: CorrectionCandidate
    compatibility_score: float
    matched_class: str | None
    matched_classes: tuple[str, ...] = ()
    predicted_class_match: bool = False
    grammar_context_match: bool = False
    parser_validated: bool | None = None
    original_index: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_dict(),
            "compatibility_score": self.compatibility_score,
            "matched_class": self.matched_class,
            "matched_classes": list(self.matched_classes),
            "predicted_class_match": self.predicted_class_match,
            "grammar_context_match": self.grammar_context_match,
            "parser_validated": self.parser_validated,
            "original_index": self.original_index,
        }


def candidate_class(candidate: CorrectionCandidate) -> str | None:
    classes = candidate_classes(candidate)
    return classes[0] if len(classes) == 1 else None


def candidate_classes(candidate: CorrectionCandidate) -> tuple[str, ...]:
    if candidate.action is CorrectionAction.COMPOUND:
        classes = {
            correction_class
            for edit in candidate.edits
            if (
                correction_class := _edit_class(
                    edit.action,
                    edit.token_type,
                    edit.token_lexeme,
                    edit.text,
                )
            )
            is not None
        }
        return tuple(sorted(classes))
    correction_class = _edit_class(
        candidate.action,
        candidate.token_type,
        candidate.token_lexeme,
        candidate.text,
    )
    return (correction_class,) if correction_class is not None else ()


def _edit_class(
    action: CorrectionAction,
    token_type: str | None,
    token_lexeme: str | None,
    text: str,
) -> str | None:
    if action is CorrectionAction.INSERT:
        mapping = {
            "SEMICOLON": CorrectionClass.INSERT_SEMICOLON.value,
            "RPAREN": CorrectionClass.INSERT_RPAREN.value,
            "LPAREN": CorrectionClass.INSERT_LPAREN.value,
            "RBRACKET": CorrectionClass.INSERT_RBRACKET.value,
            "RBRACE": CorrectionClass.INSERT_RBRACE.value,
        }
        return mapping.get(token_type)
    if action is CorrectionAction.DELETE:
        return CorrectionClass.DELETE_EXTRA_TOKEN.value
    if action is CorrectionAction.REPLACE:
        if (
            token_lexeme in {"(", ")", "[", "]"}
            and text in {"(", ")", "[", "]"}
        ):
            return CorrectionClass.REPLACE_BRACKET.value
        if token_type in {"EQ", "NE", "LE", "GE", "LT", "GT"}:
            return CorrectionClass.REPLACE_OPERATOR.value
        if token_type in {
            "INT", "FLOAT", "CHAR", "BOOL", "VOID", "IF", "ELSE", "WHILE",
            "FOR", "BREAK", "CONTINUE", "RETURN",
        }:
            return CorrectionClass.CORRECT_KEYWORD.value
    return None


def rank_candidates(
    candidates: Sequence[CorrectionCandidate],
    prediction: ErrorPrediction,
    *,
    context: ErrorContext | None = None,
    validations: Mapping[str, CandidateValidation | bool] | None = None,
) -> list[RankedCandidate]:
    """Rank candidates with classifier probability as the only numeric score.

    Candidate structure determines its correction class.  Parser validation,
    predicted-class equality, grammar-context equality, and generation order are
    deterministic tie-breaks; they never manufacture an additional AI score.
    """

    ranked: list[RankedCandidate] = []
    for index, candidate in enumerate(candidates):
        classes = candidate_classes(candidate)
        predicted_match = prediction.label in classes
        matched = (
            prediction.label
            if predicted_match
            else max(
                classes,
                key=lambda item: prediction.probabilities.get(item, 0.0),
                default=None,
            )
        )
        validation = validations.get(candidate.id) if validations else None
        parser_validated = (
            validation.relevant_valid if isinstance(validation, CandidateValidation) else validation
        )
        ranked.append(
            RankedCandidate(
                candidate=candidate,
                compatibility_score=prediction.probabilities.get(matched or "", 0.0),
                matched_class=matched,
                matched_classes=classes,
                predicted_class_match=predicted_match,
                grammar_context_match=(
                    context is not None and candidate.grammar_context == context.grammar_context
                ),
                parser_validated=parser_validated,
                original_index=index,
            )
        )
    return sorted(
        ranked,
        key=lambda item: (
            item.parser_validated is True,
            item.compatibility_score,
            item.predicted_class_match,
            item.grammar_context_match,
            -item.original_index,
        ),
        reverse=True,
    )

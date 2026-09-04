"""Source correction candidates and explicit application/validation utilities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from .source_location import SourceSpan


class CorrectionAction(str, Enum):
    INSERT = "INSERT"
    DELETE = "DELETE"
    REPLACE = "REPLACE"


@dataclass(frozen=True, slots=True)
class CorrectionCandidate:
    id: str
    action: CorrectionAction
    token_type: str | None
    token_lexeme: str | None
    offset: int
    span: SourceSpan
    text: str
    reason: str
    grammar_context: str
    diagnostic_id: str
    origin: str = "traditional_recovery"
    parser_validated: bool | None = None
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action.value,
            "token_type": self.token_type,
            "token_lexeme": self.token_lexeme,
            "offset": self.offset,
            "span": self.span.to_dict(),
            "text": self.text,
            "reason": self.reason,
            "grammar_context": self.grammar_context,
            "diagnostic_id": self.diagnostic_id,
            "origin": self.origin,
            "parser_validated": self.parser_validated,
            "score": self.score,
        }


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    candidate: CorrectionCandidate
    corrected_source: str
    valid: bool
    remaining_lexical_errors: int
    remaining_syntax_errors: int


def apply_candidate(source: str, candidate: CorrectionCandidate) -> str:
    """Apply exactly one candidate using its half-open source span."""

    start = candidate.span.start.offset
    end = candidate.span.end.offset
    if not (0 <= start <= end <= len(source)):
        raise ValueError("Candidate span is outside the source text")
    if candidate.offset != start:
        raise ValueError("Candidate offset must equal its span start")
    if candidate.action is CorrectionAction.INSERT:
        if start != end:
            raise ValueError("INSERT candidates require a zero-width span")
        return source[:start] + candidate.text + source[start:]
    if candidate.action is CorrectionAction.DELETE:
        return source[:start] + source[end:]
    if candidate.action is CorrectionAction.REPLACE:
        return source[:start] + candidate.text + source[end:]
    raise ValueError(f"Unsupported correction action: {candidate.action}")


def validate_candidate(source: str, candidate: CorrectionCandidate) -> CandidateValidation:
    """Apply and formally re-lex/re-parse one candidate without selecting it."""

    from .parser import parse

    corrected = apply_candidate(source, candidate)
    result = parse(corrected)
    valid = result.valid
    return CandidateValidation(
        candidate=replace(candidate, parser_validated=valid),
        corrected_source=corrected,
        valid=valid,
        remaining_lexical_errors=len(result.lexical_errors),
        remaining_syntax_errors=len(result.syntax_errors),
    )

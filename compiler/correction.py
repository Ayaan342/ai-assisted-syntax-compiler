"""Source correction candidates and explicit application/validation utilities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, TYPE_CHECKING

from .source_location import SourceSpan

if TYPE_CHECKING:
    from .errors import SyntaxDiagnostic
    from .parser import ParseResult


class CorrectionAction(str, Enum):
    INSERT = "INSERT"
    DELETE = "DELETE"
    REPLACE = "REPLACE"
    COMPOUND = "COMPOUND"


@dataclass(frozen=True, slots=True)
class CorrectionEdit:
    action: CorrectionAction
    token_type: str | None
    token_lexeme: str | None
    offset: int
    span: SourceSpan
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "token_type": self.token_type,
            "token_lexeme": self.token_lexeme,
            "offset": self.offset,
            "span": self.span.to_dict(),
            "text": self.text,
        }


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
    edits: tuple[CorrectionEdit, ...] = ()

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
            "edits": [edit.to_dict() for edit in self.edits],
        }


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    candidate: CorrectionCandidate
    corrected_source: str
    valid: bool
    remaining_lexical_errors: int
    remaining_syntax_errors: int
    target_resolved: bool = False
    introduced_earlier_error: bool = False
    relevant_valid: bool = False
    syntax_error_delta: int = 0
    first_remaining_error_offset: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "corrected_source": self.corrected_source,
            "valid": self.valid,
            "remaining_lexical_errors": self.remaining_lexical_errors,
            "remaining_syntax_errors": self.remaining_syntax_errors,
            "target_resolved": self.target_resolved,
            "introduced_earlier_error": self.introduced_earlier_error,
            "relevant_valid": self.relevant_valid,
            "syntax_error_delta": self.syntax_error_delta,
            "first_remaining_error_offset": self.first_remaining_error_offset,
        }


def apply_candidate(source: str, candidate: CorrectionCandidate) -> str:
    """Apply one single or bounded compound candidate without mutating source."""

    if candidate.action is CorrectionAction.COMPOUND:
        if len(candidate.edits) < 2:
            raise ValueError("COMPOUND candidates require at least two edits")
        edits = sorted(
            candidate.edits,
            key=lambda edit: (edit.span.start.offset, edit.span.end.offset),
            reverse=True,
        )
        prior_start = len(source) + 1
        corrected = source
        for edit in edits:
            start = edit.span.start.offset
            end = edit.span.end.offset
            if edit.action is CorrectionAction.COMPOUND:
                raise ValueError("Nested COMPOUND edits are unsupported")
            if not (0 <= start <= end <= len(source)) or edit.offset != start:
                raise ValueError("Compound edit span is outside the source text")
            if end > prior_start:
                raise ValueError("Compound edits must not overlap")
            corrected = _apply_edit(corrected, edit.action, start, end, edit.text)
            prior_start = start
        return corrected

    if candidate.edits:
        raise ValueError("Only COMPOUND candidates may contain multiple edits")

    start = candidate.span.start.offset
    end = candidate.span.end.offset
    if not (0 <= start <= end <= len(source)):
        raise ValueError("Candidate span is outside the source text")
    if candidate.offset != start:
        raise ValueError("Candidate offset must equal its span start")
    return _apply_edit(source, candidate.action, start, end, candidate.text)


def _apply_edit(
    source: str,
    action: CorrectionAction,
    start: int,
    end: int,
    text: str,
) -> str:
    if action is CorrectionAction.INSERT:
        if start != end:
            raise ValueError("INSERT candidates require a zero-width span")
        return source[:start] + text + source[start:]
    if action is CorrectionAction.DELETE:
        return source[:start] + source[end:]
    if action is CorrectionAction.REPLACE:
        return source[:start] + text + source[end:]
    raise ValueError(f"Unsupported correction action: {action}")


def validate_candidate(
    source: str,
    candidate: CorrectionCandidate,
    *,
    target_diagnostic: SyntaxDiagnostic | None = None,
    baseline_result: ParseResult | None = None,
) -> CandidateValidation:
    """Apply and formally re-lex/re-parse one candidate without selecting it.

    ``valid`` retains its original whole-program meaning.  ``relevant_valid`` is
    the Phase 6 local-progress decision: the selected diagnostic must disappear,
    lexical errors must not increase, and parsing must not regress to an earlier
    source position.  This permits correction of the first error in a file that
    still contains independent later errors.
    """

    from .parser import parse

    before = baseline_result or parse(source)
    corrected = apply_candidate(source, candidate)
    result = parse(corrected)
    valid = result.valid
    first_remaining = (
        result.syntax_errors[0].span.start.offset if result.syntax_errors else None
    )
    syntax_delta = len(result.syntax_errors) - len(before.syntax_errors)

    if target_diagnostic is None:
        target_resolved = valid
        introduced_earlier = False
        relevant_valid = valid
    else:
        target_offset = target_diagnostic.span.start.offset
        if candidate.action is CorrectionAction.COMPOUND:
            edit_delta = sum(
                len(edit.text) - (edit.span.end.offset - edit.span.start.offset)
                for edit in candidate.edits
                if edit.offset <= target_offset
            )
        else:
            edit_delta = (
                len(candidate.text)
                - (candidate.span.end.offset - candidate.span.start.offset)
                if candidate.offset <= target_offset
                else 0
            )
        expected_offset = target_offset + edit_delta
        local_match = any(
            error.code == target_diagnostic.code
            and error.grammar_context == target_diagnostic.grammar_context
            and abs(error.span.start.offset - expected_offset) <= 2
            for error in result.syntax_errors
        )
        moved_past_target = first_remaining is None or first_remaining > max(
            target_offset, expected_offset
        )
        made_progress = valid or syntax_delta < 0 or moved_past_target
        target_resolved = not local_match and made_progress
        introduced_earlier = (
            first_remaining is not None and first_remaining < target_offset - 1
        )
        lexical_not_worse = len(result.lexical_errors) <= len(before.lexical_errors)
        relevant_valid = target_resolved and not introduced_earlier and lexical_not_worse
    return CandidateValidation(
        candidate=replace(candidate, parser_validated=relevant_valid),
        corrected_source=corrected,
        valid=valid,
        remaining_lexical_errors=len(result.lexical_errors),
        remaining_syntax_errors=len(result.syntax_errors),
        target_resolved=target_resolved,
        introduced_earlier_error=introduced_earlier,
        relevant_valid=relevant_valid,
        syntax_error_delta=syntax_delta,
        first_remaining_error_offset=first_remaining,
    )

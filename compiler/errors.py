"""Structured diagnostics produced by compiler phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .source_location import SourceSpan
if TYPE_CHECKING:
    from .correction import CorrectionCandidate
    from .error_recovery import RecoveryAction


@dataclass(frozen=True, slots=True)
class LexicalError:
    phase: str
    code: str
    message: str
    lexeme: str
    span: SourceSpan

    @property
    def line(self) -> int:
        return self.span.start.line

    @property
    def column(self) -> int:
        return self.span.start.column

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "code": self.code,
            "line": self.line,
            "column": self.column,
            "offset": self.span.start.offset,
            "lexeme": self.lexeme,
            "message": self.message,
            "span": self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SyntaxDiagnostic:
    """A parser diagnostic extensible with Phase 3 recovery context."""

    phase: str
    code: str
    message: str
    unexpected_token: str | None
    unexpected_lexeme: str | None
    span: SourceSpan
    nearby_tokens: tuple[dict[str, Any], ...] = ()
    expected_tokens: tuple[str, ...] = ()
    grammar_context: str | None = None
    diagnostic_id: str = ""
    enclosing_construct: str | None = None
    parser_state: int | None = None
    recovery_status: str = "not_attempted"
    parsing_continued: bool = False
    recovery_action: RecoveryAction | None = None
    correction_candidates: tuple[CorrectionCandidate, ...] = ()

    @property
    def line(self) -> int:
        return self.span.start.line

    @property
    def column(self) -> int:
        return self.span.start.column

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "code": self.code,
            "line": self.line,
            "column": self.column,
            "offset": self.span.start.offset,
            "unexpected_token": self.unexpected_token,
            "unexpected_lexeme": self.unexpected_lexeme,
            "message": self.message,
            "nearby_tokens": list(self.nearby_tokens),
            "expected_tokens": list(self.expected_tokens),
            "grammar_context": self.grammar_context,
            "diagnostic_id": self.diagnostic_id,
            "enclosing_construct": self.enclosing_construct,
            "parser_state": self.parser_state,
            "recovery_status": self.recovery_status,
            "parsing_continued": self.parsing_continued,
            "recovery_action": self.recovery_action.to_dict() if self.recovery_action else None,
            "correction_candidates": [candidate.to_dict() for candidate in self.correction_candidates],
            "span": self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SemanticDiagnostic:
    phase: str
    code: str
    message: str
    span: SourceSpan
    identifier: str | None = None
    expected_type: str | None = None
    actual_type: str | None = None
    scope_id: str | None = None
    severity: str = "error"

    @property
    def line(self) -> int:
        return self.span.start.line

    @property
    def column(self) -> int:
        return self.span.start.column

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "code": self.code,
            "severity": self.severity,
            "line": self.line,
            "column": self.column,
            "offset": self.span.start.offset,
            "span": self.span.to_dict(),
            "identifier": self.identifier,
            "message": self.message,
            "expected_type": self.expected_type,
            "actual_type": self.actual_type,
            "scope_id": self.scope_id,
        }

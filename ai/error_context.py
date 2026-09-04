"""Serializable, model-agnostic context records for later AI components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from compiler.correction import CorrectionCandidate
from compiler.error_recovery import DelimiterTracker
from compiler.errors import SyntaxDiagnostic
from compiler.lexer import TokenInfo


@dataclass(frozen=True, slots=True)
class TokenContext:
    type: str
    lexeme: str
    line: int
    column: int
    offset: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "lexeme": self.lexeme,
            "line": self.line,
            "column": self.column,
            "offset": self.offset,
        }


@dataclass(frozen=True, slots=True)
class ErrorContext:
    """Features available to a future classifier or candidate ranker."""

    phase: str
    message: str
    line: int
    column: int
    current_token: TokenContext | None = None
    previous_tokens: tuple[TokenContext, ...] = ()
    next_tokens: tuple[TokenContext, ...] = ()
    expected_tokens: tuple[str, ...] = ()
    grammar_context: str | None = None
    delimiter_depth: dict[str, int] = field(default_factory=dict)
    nearby_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostic_id: str = ""
    unexpected_token: str | None = None
    unexpected_lexeme: str | None = None
    enclosing_construct: str | None = None
    parser_state: int | None = None
    recovery_status: str = "not_attempted"
    parsing_continued: bool = False
    recovery_metadata: dict[str, Any] = field(default_factory=dict)
    correction_candidates: tuple[CorrectionCandidate, ...] = ()

    @classmethod
    def from_diagnostic(
        cls,
        diagnostic: SyntaxDiagnostic,
        tokens: Sequence[TokenInfo],
        source: str,
        *,
        window: int = 4,
    ) -> ErrorContext:
        """Build stable, model-independent features from compiler output."""

        offset = diagnostic.span.start.offset
        current_index = next(
            (index for index, token in enumerate(tokens) if token.offset == offset),
            len(tokens),
        )
        current = tokens[current_index] if current_index < len(tokens) else None

        def convert(token: TokenInfo) -> TokenContext:
            return TokenContext(token.type, token.lexeme, token.line, token.column, token.offset)

        tracker = DelimiterTracker(tokens)
        snapshot = tracker.snapshot_at(offset)
        snippet_start = max(0, offset - 80)
        snippet_end = min(len(source), diagnostic.span.end.offset + 80)
        recovery = diagnostic.recovery_action.to_dict() if diagnostic.recovery_action else {}
        return cls(
            phase=diagnostic.phase,
            message=diagnostic.message,
            line=diagnostic.line,
            column=diagnostic.column,
            current_token=convert(current) if current else None,
            previous_tokens=tuple(convert(token) for token in tokens[max(0, current_index - window) : current_index]),
            next_tokens=tuple(convert(token) for token in tokens[current_index + 1 : current_index + 1 + window]),
            expected_tokens=diagnostic.expected_tokens,
            grammar_context=diagnostic.grammar_context,
            delimiter_depth=snapshot.depths(),
            nearby_source=source[snippet_start:snippet_end],
            metadata={"snippet_start_offset": snippet_start, "snippet_end_offset": snippet_end},
            diagnostic_id=diagnostic.diagnostic_id,
            unexpected_token=diagnostic.unexpected_token,
            unexpected_lexeme=diagnostic.unexpected_lexeme,
            enclosing_construct=diagnostic.enclosing_construct,
            parser_state=diagnostic.parser_state,
            recovery_status=diagnostic.recovery_status,
            parsing_continued=diagnostic.parsing_continued,
            recovery_metadata=recovery,
            correction_candidates=diagnostic.correction_candidates,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "current_token": self.current_token.to_dict() if self.current_token else None,
            "previous_tokens": [token.to_dict() for token in self.previous_tokens],
            "next_tokens": [token.to_dict() for token in self.next_tokens],
            "expected_tokens": list(self.expected_tokens),
            "grammar_context": self.grammar_context,
            "delimiter_depth": dict(self.delimiter_depth),
            "nearby_source": self.nearby_source,
            "metadata": dict(self.metadata),
            "diagnostic_id": self.diagnostic_id,
            "unexpected_token": self.unexpected_token,
            "unexpected_lexeme": self.unexpected_lexeme,
            "enclosing_construct": self.enclosing_construct,
            "parser_state": self.parser_state,
            "recovery_status": self.recovery_status,
            "parsing_continued": self.parsing_continued,
            "recovery_metadata": dict(self.recovery_metadata),
            "correction_candidates": [candidate.to_dict() for candidate in self.correction_candidates],
        }


def build_error_contexts(source: str, parse_result: Any) -> list[ErrorContext]:
    return [
        ErrorContext.from_diagnostic(diagnostic, parse_result.tokens, source)
        for diagnostic in parse_result.syntax_errors
    ]

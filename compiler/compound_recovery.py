"""Bounded structural generation of atomic two-edit correction candidates."""

from __future__ import annotations

from typing import Sequence

from .correction import (
    CorrectionAction,
    CorrectionCandidate,
    CorrectionEdit,
    apply_candidate,
)
from .error_recovery import DelimiterTracker, TOKEN_TEXT
from .errors import SyntaxDiagnostic
from .lexer import TokenInfo
from .source_location import SourceSpan


MAX_COMPOUND_EDITS = 2
MAX_COMPOUND_REGION_WIDTH = 80
MAX_DIAGNOSTIC_DISTANCE = 16
_LOCAL_BOUNDARIES = {"LBRACE", "SEMICOLON", "RBRACE"}
_SUPPORTED_OPENERS = {"LPAREN", "LBRACKET"}


def generate_compound_candidates(
    source: str,
    tokens: Sequence[TokenInfo],
    diagnostics: Sequence[SyntaxDiagnostic],
    target: SyntaxDiagnostic,
) -> tuple[CorrectionCandidate, ...]:
    """Generate local delimiter repairs only when two related edits are required.

    One mismatched closer supplies the replacement edit. The remaining opener in
    the same local delimiter stack supplies exactly one second alternative:
    either insert its closer at the construct boundary or delete the opener.
    """

    tracker = DelimiterTracker(tokens)
    raw: list[tuple[tuple[CorrectionEdit, ...], str]] = []
    target_offset = target.span.start.offset
    diagnostic_offsets = tuple(item.span.start.offset for item in diagnostics)

    for issue in tracker.issues:
        opening = issue.opening
        if (
            issue.kind != "mismatched_closer"
            or opening is None
            or opening.type not in _SUPPORTED_OPENERS
            or issue.expected not in TOKEN_TEXT
            or abs(issue.token.offset - target_offset) > MAX_DIAGNOSTIC_DISTANCE
            or abs(issue.token.line - target.line) > 1
            or not any(
                abs(issue.token.offset - offset) <= MAX_DIAGNOSTIC_DISTANCE
                for offset in diagnostic_offsets
            )
        ):
            continue

        openings = list(tracker.snapshot_at(issue.token.offset).openings)
        try:
            active_index = max(
                index
                for index, token in enumerate(openings)
                if token.offset == opening.offset and token.type == opening.type
            )
        except ValueError:
            continue
        remaining = next(
            (
                token
                for token in reversed(openings[:active_index])
                if token.type == opening.type
            ),
            None,
        )
        if remaining is None:
            continue

        boundary = next(
            (
                token
                for token in tokens
                if token.offset > issue.token.offset and token.type in _LOCAL_BOUNDARIES
            ),
            None,
        )
        if boundary is None:
            continue

        replacement = CorrectionEdit(
            action=CorrectionAction.REPLACE,
            token_type=issue.expected,
            token_lexeme=issue.token.lexeme,
            offset=issue.token.offset,
            span=issue.token.span,
            text=TOKEN_TEXT[issue.expected],
        )
        insertion_location = boundary.span.start
        insertion = CorrectionEdit(
            action=CorrectionAction.INSERT,
            token_type=DelimiterTracker.pairs[remaining.type],
            token_lexeme=TOKEN_TEXT[DelimiterTracker.pairs[remaining.type]],
            offset=insertion_location.offset,
            span=SourceSpan(insertion_location, insertion_location),
            text=TOKEN_TEXT[DelimiterTracker.pairs[remaining.type]],
        )
        deletion = CorrectionEdit(
            action=CorrectionAction.DELETE,
            token_type=remaining.type,
            token_lexeme=remaining.lexeme,
            offset=remaining.offset,
            span=remaining.span,
            text="",
        )
        raw.append(
            (
                (replacement, insertion),
                "Replace the mismatched closer and close the remaining local opener",
            )
        )
        raw.append(
            (
                (deletion, replacement),
                "Remove the extra local opener and replace the mismatched closer",
            )
        )

    candidates: list[CorrectionCandidate] = []
    corrected_sources: set[str] = set()
    for edits, reason in raw:
        ordered = tuple(sorted(edits, key=lambda edit: edit.offset))
        if len(ordered) != MAX_COMPOUND_EDITS:
            continue
        if ordered[-1].span.end.offset - ordered[0].span.start.offset > MAX_COMPOUND_REGION_WIDTH:
            continue
        span = SourceSpan(ordered[0].span.start, ordered[-1].span.end)
        candidate = CorrectionCandidate(
            id=f"{target.diagnostic_id}-M{len(candidates) + 1:02d}",
            action=CorrectionAction.COMPOUND,
            token_type="COMPOUND",
            token_lexeme=None,
            offset=span.start.offset,
            span=span,
            text="",
            reason=reason,
            grammar_context=target.grammar_context or "unknown",
            diagnostic_id=target.diagnostic_id,
            origin="compound_recovery",
            edits=ordered,
        )
        try:
            corrected = apply_candidate(source, candidate)
        except ValueError:
            continue
        if corrected == source or corrected in corrected_sources:
            continue
        corrected_sources.add(corrected)
        candidates.append(candidate)

    return tuple(candidates)

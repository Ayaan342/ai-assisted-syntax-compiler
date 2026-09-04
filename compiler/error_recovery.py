"""Traditional recovery metadata, delimiter awareness, and candidate generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .correction import CorrectionAction, CorrectionCandidate
from .lexer import TokenInfo
from .source_location import SourceLocation, SourceSpan


TOKEN_TEXT = {
    "SEMICOLON": ";",
    "LPAREN": "(",
    "RPAREN": ")",
    "LBRACKET": "[",
    "RBRACKET": "]",
    "LBRACE": "{",
    "RBRACE": "}",
    "COMMA": ",",
}


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    strategy: str
    status: str
    synchronization_token: str | None = None
    skipped_token_types: tuple[str, ...] = ()
    inserted_token: str | None = None
    continued: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "synchronization_token": self.synchronization_token,
            "skipped_token_types": list(self.skipped_token_types),
            "inserted_token": self.inserted_token,
            "continued": self.continued,
        }


@dataclass(frozen=True, slots=True)
class DelimiterSnapshot:
    paren: int
    brace: int
    bracket: int
    openings: tuple[TokenInfo, ...]

    def depths(self) -> dict[str, int]:
        return {"paren": self.paren, "brace": self.brace, "bracket": self.bracket}


@dataclass(frozen=True, slots=True)
class DelimiterIssue:
    kind: str
    token: TokenInfo
    expected: str | None
    opening: TokenInfo | None


class DelimiterTracker:
    """Supplementary delimiter state; the CFG remains the syntax authority."""

    pairs = {"LPAREN": "RPAREN", "LBRACE": "RBRACE", "LBRACKET": "RBRACKET"}
    reverse = {value: key for key, value in pairs.items()}

    def __init__(self, tokens: Sequence[TokenInfo]) -> None:
        self.tokens = list(tokens)
        self.issues: list[DelimiterIssue] = []
        self._snapshots: dict[int, DelimiterSnapshot] = {}
        self.unclosed: list[TokenInfo] = []
        self._scan()

    def _scan(self) -> None:
        stack: list[TokenInfo] = []
        counts = {"LPAREN": 0, "LBRACE": 0, "LBRACKET": 0}
        for token in self.tokens:
            self._snapshots[token.offset] = DelimiterSnapshot(
                counts["LPAREN"], counts["LBRACE"], counts["LBRACKET"], tuple(stack)
            )
            if token.type in self.pairs:
                stack.append(token)
                counts[token.type] += 1
            elif token.type in self.reverse:
                wanted = self.reverse[token.type]
                if stack and stack[-1].type == wanted:
                    opening = stack.pop()
                    counts[opening.type] -= 1
                else:
                    opening = stack[-1] if stack else None
                    expected = self.pairs.get(opening.type) if opening else None
                    self.issues.append(DelimiterIssue("mismatched_closer", token, expected, opening))
        self.unclosed = stack

    def snapshot_at(self, offset: int) -> DelimiterSnapshot:
        prior = [position for position in self._snapshots if position <= offset]
        if not prior:
            return DelimiterSnapshot(0, 0, 0, ())
        return self._snapshots[max(prior)]

    def probable_closers(self) -> tuple[str, ...]:
        return tuple(self.pairs[token.type] for token in reversed(self.unclosed))


def infer_context(tokens: Sequence[TokenInfo], index: int) -> tuple[str, str]:
    previous = list(tokens[max(0, index - 50) : index])
    types = [token.type for token in previous]
    for keyword, context in (("FOR", "for_header"), ("IF", "if_condition"), ("WHILE", "while_condition")):
        if keyword in types:
            keyword_index = len(types) - 1 - types[::-1].index(keyword)
            if "LBRACE" not in types[keyword_index:]:
                return context, context.removesuffix("_condition").removesuffix("_header")
    boundary = max(
        (position for position, token_type in enumerate(types) if token_type in {"SEMICOLON", "LBRACE", "RBRACE"}),
        default=-1,
    )
    current_statement = types[boundary + 1 :]
    if "RETURN" in current_statement:
        return "return_statement", "return_statement"
    statement_lparen = max(
        (i for i, token_type in enumerate(current_statement) if token_type == "LPAREN"),
        default=-1,
    )
    statement_rparen = max(
        (i for i, token_type in enumerate(current_statement) if token_type == "RPAREN"),
        default=-1,
    )
    if (
        statement_lparen > statement_rparen
        and statement_lparen >= 2
        and current_statement[statement_lparen - 1] == "IDENTIFIER"
        and current_statement[0] in {"INT", "FLOAT", "CHAR", "BOOL", "VOID"}
    ):
        return "function_parameter_list", "function_definition"
    if any(token_type in {"INT", "FLOAT", "CHAR", "BOOL", "VOID"} for token_type in current_statement):
        return "declaration", "statement"
    last_lbracket = max((i for i, token_type in enumerate(types) if token_type == "LBRACKET"), default=-1)
    last_rbracket = max((i for i, token_type in enumerate(types) if token_type == "RBRACKET"), default=-1)
    if last_lbracket > last_rbracket:
        return "array_access", "expression"
    last_lparen = max((i for i, token_type in enumerate(types) if token_type == "LPAREN"), default=-1)
    last_rparen = max((i for i, token_type in enumerate(types) if token_type == "RPAREN"), default=-1)
    if last_lparen > last_rparen and last_lparen > 0 and types[last_lparen - 1] == "IDENTIFIER":
        return "function_call", "expression"
    if previous and previous[-1].type in {"ASSIGN", "PLUS_ASSIGN", "MINUS_ASSIGN", "TIMES_ASSIGN", "DIVIDE_ASSIGN", "MODULO_ASSIGN"}:
        return "assignment", "expression"
    return "expression", "statement"


class CandidateGenerator:
    """Grammar-guided candidate enumeration with no ranking or confidence."""

    insert_priority = ("SEMICOLON", "RPAREN", "LPAREN", "RBRACKET", "RBRACE", "COMMA")

    def generate(
        self,
        *,
        diagnostic_id: str,
        tokens: Sequence[TokenInfo],
        index: int,
        unexpected: TokenInfo | None,
        expected: Sequence[str],
        grammar_context: str,
        eof_location: SourceLocation,
    ) -> tuple[CorrectionCandidate, ...]:
        candidates: list[CorrectionCandidate] = []
        current_location = unexpected.span.start if unexpected else eof_location
        insertion_span = SourceSpan(current_location, current_location)

        def add(action: CorrectionAction, token_type: str | None, token_lexeme: str | None,
                span: SourceSpan, text: str, reason: str) -> None:
            candidates.append(
                CorrectionCandidate(
                    id=f"{diagnostic_id}-C{len(candidates) + 1:02d}",
                    action=action,
                    token_type=token_type,
                    token_lexeme=token_lexeme,
                    offset=span.start.offset,
                    span=span,
                    text=text,
                    reason=reason,
                    grammar_context=grammar_context,
                    diagnostic_id=diagnostic_id,
                )
            )

        previous = tokens[index - 1] if index > 0 else None
        if unexpected is None:
            priorities = ("RBRACE", "RPAREN", "RBRACKET", "SEMICOLON", "LPAREN", "COMMA")
        elif unexpected.type == "LBRACE" and "RPAREN" in expected:
            priorities = ("RPAREN", "SEMICOLON", "LPAREN", "RBRACKET", "RBRACE", "COMMA")
        else:
            priorities = self.insert_priority
        for token_type in priorities:
            context_allows = (
                (token_type == "SEMICOLON" and unexpected is not None)
                or (token_type == "RPAREN" and unexpected is not None and unexpected.type in {"LBRACE", "SEMICOLON"})
                or (token_type == "LPAREN" and grammar_context in {"if_condition", "while_condition", "for_header"})
                or (token_type == "RBRACKET" and grammar_context == "array_access")
                or (token_type in {"RBRACE", "RPAREN", "RBRACKET"} and unexpected is None)
            )
            if token_type in expected and context_allows:
                lexeme = TOKEN_TEXT[token_type]
                add(
                    CorrectionAction.INSERT,
                    token_type,
                    lexeme,
                    insertion_span,
                    lexeme,
                    f"The grammar accepts {token_type} before the unexpected token",
                )
                break

        if unexpected and unexpected.type == "LBRACKET" and "LPAREN" in expected:
            add(CorrectionAction.REPLACE, "LPAREN", unexpected.lexeme, unexpected.span, "(",
                "A parenthesized condition requires '(' rather than '['")
        elif unexpected and unexpected.type == "RBRACKET" and "RPAREN" in expected:
            add(CorrectionAction.REPLACE, "RPAREN", unexpected.lexeme, unexpected.span, ")",
                "The opening parenthesis requires a matching ')'")

        if unexpected and previous and previous.type in {
            "ASSIGN", "PLUS_ASSIGN", "MINUS_ASSIGN", "TIMES_ASSIGN", "DIVIDE_ASSIGN", "MODULO_ASSIGN"
        } and unexpected.type in {
            "ASSIGN", "PLUS_ASSIGN", "MINUS_ASSIGN", "TIMES_ASSIGN", "DIVIDE_ASSIGN", "MODULO_ASSIGN"
        }:
            add(CorrectionAction.DELETE, unexpected.type, unexpected.lexeme, unexpected.span, "",
                "Consecutive assignment operators contain an extra token")

        if unexpected and unexpected.type == "LBRACE" and "RPAREN" in expected:
            opening = next((token for token in reversed(tokens[:index]) if token.type == "LPAREN"), None)
            if opening:
                add(CorrectionAction.DELETE, opening.type, opening.lexeme, opening.span, "",
                    "Removing the unmatched opening parenthesis is an alternative interpretation")
            add(CorrectionAction.REPLACE, "RPAREN", unexpected.lexeme, unexpected.span, ")",
                "Replacing the brace would close the condition, though a block brace may still be needed")

        if unexpected and unexpected.type == "SEMICOLON" and previous and previous.type in {
            "PLUS", "MINUS", "TIMES", "DIVIDE", "MODULO", "AND", "OR",
            "EQ", "NE", "LT", "LE", "GT", "GE",
        }:
            add(CorrectionAction.DELETE, previous.type, previous.lexeme, previous.span, "",
                "Deleting the trailing operator yields a complete expression")

        return tuple(candidates)

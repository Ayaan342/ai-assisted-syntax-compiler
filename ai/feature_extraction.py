"""Explainable compiler-context features for classical ML models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .error_context import ErrorContext, TokenContext


MINI_C_KEYWORDS = (
    "int", "float", "char", "bool", "void", "if", "else", "while", "for",
    "break", "continue", "return", "true", "false",
)


@dataclass(frozen=True, slots=True)
class KeywordSimilarity:
    lexeme: str
    keyword: str
    distance: int
    normalized_distance: float
    token_position: str


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def nearest_keyword(context: ErrorContext) -> KeywordSimilarity:
    tokens: list[tuple[str, TokenContext]] = []
    if context.current_token is not None:
        tokens.append(("current", context.current_token))
    tokens.extend(
        (f"previous_{index}", token)
        for index, token in enumerate(reversed(context.previous_tokens), start=1)
    )
    identifiers = [(position, token) for position, token in tokens if token.type == "IDENTIFIER"]
    if not identifiers:
        return KeywordSimilarity("", "", 99, 1.0, "none")
    best: tuple[int, str, TokenContext, str] | None = None
    for position, token in identifiers:
        for keyword in MINI_C_KEYWORDS:
            distance = edit_distance(token.lexeme.lower(), keyword)
            item = (distance, keyword, token, position)
            if best is None or item[0] < best[0]:
                best = item
    assert best is not None
    distance, keyword, token, position = best
    normalizer = max(len(token.lexeme), len(keyword), 1)
    return KeywordSimilarity(token.lexeme, keyword, distance, distance / normalizer, position)


def extract_features(context: ErrorContext) -> dict[str, Any]:
    previous = list(context.previous_tokens)
    following = list(context.next_tokens)

    def token_type(items: list[TokenContext], index: int, *, reverse: bool = False) -> str:
        ordered = list(reversed(items)) if reverse else items
        return ordered[index].type if index < len(ordered) else "<NONE>"

    def token_lexeme(items: list[TokenContext], index: int, *, reverse: bool = False) -> str:
        ordered = list(reversed(items)) if reverse else items
        return ordered[index].lexeme if index < len(ordered) else "<NONE>"

    expected = set(context.expected_tokens)
    actions = {candidate.action.value for candidate in context.correction_candidates}
    candidate_tokens = {candidate.token_type for candidate in context.correction_candidates}
    similarity = nearest_keyword(context)
    current_type = context.current_token.type if context.current_token else "<EOF>"
    current_lexeme = context.current_token.lexeme if context.current_token else "<EOF>"
    pattern_types = [token.type for token in previous[-3:]] + [current_type] + [token.type for token in following[:2]]
    return {
        "unexpected_token": context.unexpected_token or "<EOF>",
        "current_token": current_type,
        "current_lexeme": current_lexeme,
        "previous_token": token_type(previous, 0, reverse=True),
        "previous_lexeme": token_lexeme(previous, 0, reverse=True),
        "second_previous_token": token_type(previous, 1, reverse=True),
        "next_token": token_type(following, 0),
        "second_next_token": token_type(following, 1),
        "grammar_context": context.grammar_context or "<NONE>",
        "enclosing_construct": context.enclosing_construct or "<NONE>",
        "expected_signature": "|".join(sorted(expected)) or "<NONE>",
        "candidate_action_signature": "|".join(sorted(actions)) or "<NONE>",
        "candidate_token_signature": "|".join(sorted(item for item in candidate_tokens if item)) or "<NONE>",
        "nearby_token_pattern": "|".join(pattern_types),
        "paren_depth": int(context.delimiter_depth.get("paren", 0)),
        "brace_depth": int(context.delimiter_depth.get("brace", 0)),
        "bracket_depth": int(context.delimiter_depth.get("bracket", 0)),
        "expects_semicolon": int("SEMICOLON" in expected),
        "expects_rparen": int("RPAREN" in expected),
        "expects_lparen": int("LPAREN" in expected),
        "expects_rbracket": int("RBRACKET" in expected),
        "expects_rbrace": int("RBRACE" in expected),
        "has_insert_candidate": int("INSERT" in actions),
        "has_delete_candidate": int("DELETE" in actions),
        "has_replace_candidate": int("REPLACE" in actions),
        "nearest_keyword": similarity.keyword or "<NONE>",
        "keyword_source_position": similarity.token_position,
        "keyword_edit_distance": similarity.distance,
        "keyword_normalized_distance": similarity.normalized_distance,
        "keyword_is_close": int(similarity.distance <= 2),
    }


def extract_feature_rows(contexts: Iterable[ErrorContext]) -> list[dict[str, Any]]:
    return [extract_features(context) for context in contexts]

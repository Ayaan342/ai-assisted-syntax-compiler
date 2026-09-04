"""Validated synthetic syntax-correction dataset generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from compiler.correction import CorrectionAction, CorrectionCandidate, apply_candidate
from compiler.parser import MiniCParser
from compiler.source_location import SourceLocation, SourceSpan

from .error_context import ErrorContext, TokenContext, build_error_contexts


class CorrectionClass(str, Enum):
    INSERT_SEMICOLON = "INSERT_SEMICOLON"
    INSERT_RPAREN = "INSERT_RPAREN"
    INSERT_LPAREN = "INSERT_LPAREN"
    INSERT_RBRACKET = "INSERT_RBRACKET"
    INSERT_RBRACE = "INSERT_RBRACE"
    DELETE_EXTRA_TOKEN = "DELETE_EXTRA_TOKEN"
    REPLACE_BRACKET = "REPLACE_BRACKET"
    REPLACE_OPERATOR = "REPLACE_OPERATOR"
    CORRECT_KEYWORD = "CORRECT_KEYWORD"


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    sample_id: str
    original_source: str
    corrupted_source: str
    label: str
    injected_location: SourceLocation
    parser_diagnostic: dict[str, Any]
    error_context: ErrorContext
    correction_candidates: tuple[CorrectionCandidate, ...]
    ground_truth: CorrectionCandidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "original_source": self.original_source,
            "corrupted_source": self.corrupted_source,
            "label": self.label,
            "injected_location": self.injected_location.to_dict(),
            "parser_diagnostic": self.parser_diagnostic,
            "error_context": self.error_context.to_dict(),
            "correction_candidates": [item.to_dict() for item in self.correction_candidates],
            "ground_truth": self.ground_truth.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetRecord:
        location = _location_from_dict(data["injected_location"])
        return cls(
            sample_id=data["sample_id"],
            original_source=data["original_source"],
            corrupted_source=data["corrupted_source"],
            label=data["label"],
            injected_location=location,
            parser_diagnostic=data["parser_diagnostic"],
            error_context=_context_from_dict(data["error_context"]),
            correction_candidates=tuple(_candidate_from_dict(item) for item in data["correction_candidates"]),
            ground_truth=_candidate_from_dict(data["ground_truth"]),
        )


@dataclass(frozen=True, slots=True)
class _Mutation:
    original: str
    corrupted: str
    label: CorrectionClass
    action: CorrectionAction
    token_type: str
    token_lexeme: str
    start: int
    end: int
    text: str


class SyntheticDatasetGenerator:
    """Creates one controlled, compiler-validated mutation per sample."""

    def __init__(self, random_seed: int = 42) -> None:
        self.random_seed = random_seed
        self.parser = MiniCParser()

    def generate(self, target_size: int = 1080) -> list[DatasetRecord]:
        if target_size < len(CorrectionClass):
            raise ValueError(f"target_size must be at least {len(CorrectionClass)}")
        records: list[DatasetRecord] = []
        classes = list(CorrectionClass)
        attempts = 0
        base, remainder = divmod(target_size, len(classes))
        desired = {
            label: base + (1 if index < remainder else 0)
            for index, label in enumerate(classes)
        }
        for label in classes:
            accepted = 0
            while accepted < desired[label] and attempts < target_size * 5:
                mutation = self._mutation(label, attempts)
                record = self._validate_mutation(mutation, len(records) + 1)
                attempts += 1
                if record is not None:
                    records.append(record)
                    accepted += 1
        if len(records) != target_size:
            raise RuntimeError(f"Generated only {len(records)} valid samples after {attempts} attempts")
        return records

    def _mutation(self, label: CorrectionClass, index: int) -> _Mutation:
        salt = (index * 1_103_515_245 + self.random_seed * 12_345) & 0x7FFFFFFF
        variable = f"value{salt % 997}"
        number = 1 + (salt // 97) % 997
        array = f"items{(salt // 17) % 991}"
        if label is CorrectionClass.INSERT_SEMICOLON:
            original = f"int main() {{ int {variable} = {number}; return {variable}; }}"
            start = original.index(";", original.index(variable))
            return self._remove(original, start, label, "SEMICOLON", ";")
        if label is CorrectionClass.INSERT_RPAREN:
            original = f"int main() {{ int {variable}={number}; if ({variable} > 0) {{ return 1; }} return 0; }}"
            start = original.index(")", original.index("if"))
            return self._remove(original, start, label, "RPAREN", ")")
        if label is CorrectionClass.INSERT_LPAREN:
            original = f"int main() {{ int {variable}={number}; if ({variable} > 0) {{ return 1; }} return 0; }}"
            start = original.index("(", original.index("if"))
            return self._remove(original, start, label, "LPAREN", "(")
        if label is CorrectionClass.INSERT_RBRACKET:
            original = f"int main() {{ int {array}[10]; int {variable}={array}[{index % 9}]; return {variable}; }}"
            access = original.index(f"{array}[", original.index(";"))
            start = original.index("]", access)
            return self._remove(original, start, label, "RBRACKET", "]")
        if label is CorrectionClass.INSERT_RBRACE:
            original = f"int main() {{ int {variable}={number}; return {variable}; }}"
            start = len(original) - 1
            return self._remove(original, start, label, "RBRACE", "}")
        if label is CorrectionClass.DELETE_EXTRA_TOKEN:
            original = f"int main() {{ int {variable} = {number}; return {variable}; }}"
            insertion = original.index("=", original.index(variable)) + 2
            corrupted = original[:insertion] + "= " + original[insertion:]
            return _Mutation(original, corrupted, label, CorrectionAction.DELETE, "ASSIGN", "=", insertion, insertion + 1, "")
        if label is CorrectionClass.REPLACE_BRACKET:
            original = f"int main() {{ int {variable}={number}; if ({variable} > 0) {{ return 1; }} return 0; }}"
            start = original.index("(", original.index("if"))
            corrupted = original[:start] + "[" + original[start + 1 :]
            return _Mutation(original, corrupted, label, CorrectionAction.REPLACE, "LPAREN", "[", start, start + 1, "(")
        if label is CorrectionClass.REPLACE_OPERATOR:
            original = f"int main() {{ int {variable}={number}; if ({variable} >= 0) {{ return 1; }} return 0; }}"
            start = original.index(">=")
            corrupted = original[:start] + "=>" + original[start + 2 :]
            return _Mutation(original, corrupted, label, CorrectionAction.REPLACE, "GE", "=>", start, start + 2, ">=")
        misspellings = ("retrun", "retun", "retrurn", "reutrn")
        wrong = misspellings[salt % len(misspellings)]
        original = f"int main() {{ int {variable}={number}; return {variable}; }}"
        start = original.index("return")
        corrupted = original[:start] + wrong + original[start + len("return") :]
        return _Mutation(original, corrupted, label, CorrectionAction.REPLACE, "RETURN", wrong, start, start + len(wrong), "return")

    @staticmethod
    def _remove(original: str, start: int, label: CorrectionClass, token_type: str, text: str) -> _Mutation:
        corrupted = original[:start] + original[start + len(text) :]
        return _Mutation(original, corrupted, label, CorrectionAction.INSERT, token_type, text, start, start, text)

    def _validate_mutation(self, mutation: _Mutation, sequence: int) -> DatasetRecord | None:
        original_result = self.parser.parse(mutation.original)
        if not original_result.valid:
            return None
        corrupted_result = self.parser.parse(mutation.corrupted)
        if not corrupted_result.syntax_errors:
            return None
        contexts = build_error_contexts(mutation.corrupted, corrupted_result)
        diagnostic_index = min(
            range(len(corrupted_result.syntax_errors)),
            key=lambda item: abs(corrupted_result.syntax_errors[item].span.start.offset - mutation.start),
        )
        diagnostic = corrupted_result.syntax_errors[diagnostic_index]
        context = contexts[diagnostic_index]
        start_location = _location(mutation.corrupted, mutation.start)
        end_location = _location(mutation.corrupted, mutation.end)
        truth = CorrectionCandidate(
            id=f"GT-{sequence:06d}",
            action=mutation.action,
            token_type=mutation.token_type,
            token_lexeme=mutation.token_lexeme,
            offset=mutation.start,
            span=SourceSpan(start_location, end_location),
            text=mutation.text,
            reason=f"Synthetic ground truth for {mutation.label.value}",
            grammar_context=context.grammar_context or "unknown",
            diagnostic_id=diagnostic.diagnostic_id,
            origin="synthetic_ground_truth",
            parser_validated=True,
        )
        corrected = apply_candidate(mutation.corrupted, truth)
        if not self.parser.parse(corrected).valid:
            return None
        if not any(_candidate_corresponds(item, truth) for item in context.correction_candidates):
            return None
        return DatasetRecord(
            sample_id=f"sample-{sequence:06d}",
            original_source=mutation.original,
            corrupted_source=mutation.corrupted,
            label=mutation.label.value,
            injected_location=start_location,
            parser_diagnostic=diagnostic.to_dict(),
            error_context=context,
            correction_candidates=context.correction_candidates,
            ground_truth=truth,
        )


def write_jsonl(records: Iterable[DatasetRecord], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record.to_dict(), separators=(",", ":")) + "\n")
    return destination


def read_jsonl(path: str | Path) -> list[DatasetRecord]:
    with Path(path).open(encoding="utf-8") as stream:
        return [DatasetRecord.from_dict(json.loads(line)) for line in stream if line.strip()]


def class_counts(records: Iterable[DatasetRecord]) -> dict[str, int]:
    counts = {item.value: 0 for item in CorrectionClass}
    for record in records:
        counts[record.label] = counts.get(record.label, 0) + 1
    return counts


def _candidate_corresponds(candidate: CorrectionCandidate, truth: CorrectionCandidate) -> bool:
    return candidate.action is truth.action and candidate.text == truth.text and candidate.token_type == truth.token_type


def _location(source: str, offset: int) -> SourceLocation:
    line = source.count("\n", 0, offset) + 1
    last_newline = source.rfind("\n", 0, offset)
    column = offset + 1 if last_newline < 0 else offset - last_newline
    return SourceLocation(line, column, offset)


def _location_from_dict(data: dict[str, Any]) -> SourceLocation:
    return SourceLocation(data["line"], data["column"], data["offset"])


def _span_from_dict(data: dict[str, Any]) -> SourceSpan:
    return SourceSpan(_location_from_dict(data["start"]), _location_from_dict(data["end"]))


def _candidate_from_dict(data: dict[str, Any]) -> CorrectionCandidate:
    return CorrectionCandidate(
        id=data["id"],
        action=CorrectionAction(data["action"]),
        token_type=data.get("token_type"),
        token_lexeme=data.get("token_lexeme"),
        offset=data["offset"],
        span=_span_from_dict(data["span"]),
        text=data["text"],
        reason=data["reason"],
        grammar_context=data["grammar_context"],
        diagnostic_id=data["diagnostic_id"],
        origin=data.get("origin", "traditional_recovery"),
        parser_validated=data.get("parser_validated"),
        score=data.get("score"),
    )


def _token_context(data: dict[str, Any] | None) -> TokenContext | None:
    if data is None:
        return None
    return TokenContext(data["type"], data["lexeme"], data["line"], data["column"], data["offset"])


def _context_from_dict(data: dict[str, Any]) -> ErrorContext:
    return ErrorContext(
        phase=data["phase"],
        message=data["message"],
        line=data["line"],
        column=data["column"],
        current_token=_token_context(data.get("current_token")),
        previous_tokens=tuple(_token_context(item) for item in data.get("previous_tokens", [])),
        next_tokens=tuple(_token_context(item) for item in data.get("next_tokens", [])),
        expected_tokens=tuple(data.get("expected_tokens", [])),
        grammar_context=data.get("grammar_context"),
        delimiter_depth=dict(data.get("delimiter_depth", {})),
        nearby_source=data.get("nearby_source", ""),
        metadata=dict(data.get("metadata", {})),
        diagnostic_id=data.get("diagnostic_id", ""),
        unexpected_token=data.get("unexpected_token"),
        unexpected_lexeme=data.get("unexpected_lexeme"),
        enclosing_construct=data.get("enclosing_construct"),
        parser_state=data.get("parser_state"),
        recovery_status=data.get("recovery_status", "not_attempted"),
        parsing_continued=data.get("parsing_continued", False),
        recovery_metadata=dict(data.get("recovery_metadata", {})),
        correction_candidates=tuple(_candidate_from_dict(item) for item in data.get("correction_candidates", [])),
    )

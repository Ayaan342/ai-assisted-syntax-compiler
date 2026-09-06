"""Optional Groq fallback that proposes one structured Mini-C source edit."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Protocol, Sequence

from dotenv import find_dotenv, load_dotenv

from compiler.correction import CandidateValidation, CorrectionAction, CorrectionCandidate
from compiler.errors import SyntaxDiagnostic
from compiler.source_location import SourceLocation, SourceSpan

from .error_context import ErrorContext
from .error_predictor import ErrorPrediction


DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 500
DEFAULT_SELECTION_MAX_TOKENS = 500
DEFAULT_AMBIGUITY_SELECTION_THRESHOLD = 0.75
MAX_REPLACEMENT_LENGTH = 80
SUPPORTED_ACTIONS = {item.value for item in CorrectionAction}


@dataclass(frozen=True, slots=True)
class LLMSuggestion:
    action: CorrectionAction
    replacement_text: str
    target_start: int
    target_end: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "replacement_text": self.replacement_text,
            "target_start": self.target_start,
            "target_end": self.target_end,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LLMFallbackResult:
    available: bool
    attempted: bool
    model: str
    suggestion: LLMSuggestion | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "attempted": self.attempted,
            "model": self.model,
            "suggestion": self.suggestion.to_dict() if self.suggestion else None,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class LLMCandidateSelection:
    selected_candidate_id: str | None
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_candidate_id": self.selected_candidate_id,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LLMCandidateSelectionResult:
    available: bool
    attempted: bool
    model: str
    selection: LLMCandidateSelection | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "attempted": self.attempted,
            "model": self.model,
            "selection": self.selection.to_dict() if self.selection else None,
            "error": self.error,
        }


class LLMFallbackService(Protocol):
    model: str

    def suggest(
        self, context: ErrorContext, prediction: ErrorPrediction
    ) -> LLMFallbackResult:
        """Return one structured edit suggestion without applying it."""
        ...

    def select_candidate(
        self,
        source: str,
        context: ErrorContext,
        candidates: Sequence[CandidateValidation],
    ) -> LLMCandidateSelectionResult:
        """Choose only an ID from compiler-generated, validated candidates."""
        ...


class GroqFallbackService:
    """Small Groq adapter with dependency injection for offline testing."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_GROQ_MODEL,
        client: Any | None = None,
        env_path: str | Path | None = None,
    ) -> None:
        self.model = model
        self._client = client
        self._api_key = api_key
        if client is None and api_key is None:
            dotenv_path = str(env_path) if env_path is not None else find_dotenv(usecwd=True)
            if dotenv_path:
                load_dotenv(dotenv_path=dotenv_path, override=False)
            self._api_key = os.getenv("GROQ_API_KEY")

    @property
    def available(self) -> bool:
        return self._client is not None or bool(self._api_key)

    def suggest(
        self, context: ErrorContext, prediction: ErrorPrediction
    ) -> LLMFallbackResult:
        if not self.available:
            return LLMFallbackResult(
                available=False,
                attempted=False,
                model=self.model,
                error="GROQ_API_KEY is unavailable",
            )
        try:
            client = self._client or self._create_client()
            completion = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(_structured_context(context, prediction)),
                    },
                ],
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            suggestion = parse_llm_suggestion(content)
            return LLMFallbackResult(True, True, self.model, suggestion=suggestion)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError) as exc:
            return LLMFallbackResult(
                available=True,
                attempted=True,
                model=self.model,
                error=f"Malformed Groq response: {exc}",
            )
        except Exception as exc:  # SDK/network failures must not break the compiler.
            return LLMFallbackResult(
                available=True,
                attempted=True,
                model=self.model,
                error=f"Groq request failed: {type(exc).__name__}",
            )

    def select_candidate(
        self,
        source: str,
        context: ErrorContext,
        candidates: Sequence[CandidateValidation],
    ) -> LLMCandidateSelectionResult:
        """Ask Groq to select an existing validated candidate, never an edit."""

        if not self.available:
            return LLMCandidateSelectionResult(
                available=False,
                attempted=False,
                model=self.model,
                error="GROQ_API_KEY is unavailable",
            )
        candidate_ids = {
            validation.candidate.id
            for validation in candidates
            if validation.relevant_valid
        }
        if len(candidate_ids) < 2:
            return LLMCandidateSelectionResult(
                available=True,
                attempted=False,
                model=self.model,
                error="Ambiguity selection requires at least two validated candidates",
            )
        try:
            client = self._client or self._create_client()
            completion = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SELECTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            _selection_context(source, context, candidates)
                        ),
                    },
                ],
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_SELECTION_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            selection = parse_candidate_selection(content, candidate_ids)
            return LLMCandidateSelectionResult(
                True, True, self.model, selection=selection
            )
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError) as exc:
            return LLMCandidateSelectionResult(
                available=True,
                attempted=True,
                model=self.model,
                error=f"Malformed Groq selection response: {exc}",
            )
        except Exception as exc:  # SDK/network failures must not break the compiler.
            return LLMCandidateSelectionResult(
                available=True,
                attempted=True,
                model=self.model,
                error=f"Groq selection request failed: {type(exc).__name__}",
            )

    def _create_client(self) -> Any:
        from groq import Groq

        self._client = Groq(api_key=self._api_key)
        return self._client


def parse_llm_suggestion(content: str | None) -> LLMSuggestion:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("response content is empty")
    payload = json.loads(content)
    required = {"action", "replacement_text", "target_start", "target_end", "reason"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("response must contain exactly the required edit fields")
    action_text = payload["action"]
    replacement = payload["replacement_text"]
    start = payload["target_start"]
    end = payload["target_end"]
    reason = payload["reason"]
    if action_text not in SUPPORTED_ACTIONS:
        raise ValueError("unsupported action")
    if not isinstance(replacement, str) or len(replacement) > MAX_REPLACEMENT_LENGTH:
        raise ValueError("replacement_text is invalid")
    if type(start) is not int or type(end) is not int or start < 0 or end < start:
        raise ValueError("target range is invalid")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required")
    action = CorrectionAction(action_text)
    if action is CorrectionAction.INSERT and start != end:
        raise ValueError("INSERT requires a zero-width target")
    if action is CorrectionAction.DELETE and replacement != "":
        raise ValueError("DELETE requires empty replacement_text")
    if action in {CorrectionAction.DELETE, CorrectionAction.REPLACE} and start == end:
        raise ValueError(f"{action.value} requires a non-empty target")
    return LLMSuggestion(action, replacement, start, end, reason.strip())


def parse_candidate_selection(
    content: str | None,
    allowed_candidate_ids: set[str] | None = None,
) -> LLMCandidateSelection:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("response content is empty")
    payload = json.loads(content)
    required = {"selected_candidate_id", "confidence", "reason"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("response must contain exactly the required selection fields")
    candidate_id = payload["selected_candidate_id"]
    confidence = payload["confidence"]
    reason = payload["reason"]
    if candidate_id is not None and not isinstance(candidate_id, str):
        raise ValueError("selected_candidate_id must be a string or null")
    if (
        candidate_id is not None
        and allowed_candidate_ids is not None
        and candidate_id not in allowed_candidate_ids
    ):
        raise ValueError("selected_candidate_id is not one of the supplied candidates")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a number")
    if not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required")
    return LLMCandidateSelection(candidate_id, float(confidence), reason.strip())


def suggestion_to_candidate(
    suggestion: LLMSuggestion,
    diagnostic: SyntaxDiagnostic,
    source: str,
) -> CorrectionCandidate:
    """Convert the LLM schema to the compiler's existing edit representation."""

    if suggestion.target_end > len(source):
        raise ValueError("LLM target range is outside the source text")
    start = _location(source, suggestion.target_start)
    end = _location(source, suggestion.target_end)
    original = source[suggestion.target_start : suggestion.target_end]
    return CorrectionCandidate(
        id=f"{diagnostic.diagnostic_id}-groq",
        action=suggestion.action,
        token_type=None,
        token_lexeme=original or None,
        offset=suggestion.target_start,
        span=SourceSpan(start, end),
        text=suggestion.replacement_text,
        reason=suggestion.reason,
        grammar_context=diagnostic.grammar_context or "unknown",
        diagnostic_id=diagnostic.diagnostic_id,
        origin="groq_fallback",
    )


def _location(source: str, offset: int) -> SourceLocation:
    prefix = source[:offset]
    line = prefix.count("\n") + 1
    newline = prefix.rfind("\n")
    column = offset + 1 if newline < 0 else offset - newline
    return SourceLocation(line, column, offset)


def _structured_context(
    context: ErrorContext, prediction: ErrorPrediction
) -> dict[str, Any]:
    return {
        "language": "Mini-C",
        "instruction": "Propose exactly one minimal syntax edit using absolute source offsets.",
        "grammar_context": context.grammar_context,
        "unexpected_token": context.unexpected_token,
        "unexpected_lexeme": context.unexpected_lexeme,
        "expected_tokens": list(context.expected_tokens),
        "previous_tokens": [item.to_dict() for item in context.previous_tokens],
        "current_token": context.current_token.to_dict() if context.current_token else None,
        "next_tokens": [item.to_dict() for item in context.next_tokens],
        "nearby_source": context.nearby_source,
        "snippet_start_offset": context.metadata.get("snippet_start_offset"),
        "snippet_end_offset": context.metadata.get("snippet_end_offset"),
        "delimiter_depth": dict(context.delimiter_depth),
        "traditional_candidates": [item.to_dict() for item in context.correction_candidates],
        "ml_prediction": prediction.to_dict(),
        "required_output": {
            "action": "INSERT | DELETE | REPLACE",
            "replacement_text": "string",
            "target_start": "integer",
            "target_end": "integer",
            "reason": "short string",
        },
    }


def _selection_context(
    source: str,
    context: ErrorContext,
    candidates: Sequence[CandidateValidation],
) -> dict[str, Any]:
    return {
        "language": "Mini-C",
        "task": "Select the most plausible programmer-intent repair from the supplied validated candidates.",
        "original_source": source,
        "diagnostic": {
            "grammar_context": context.grammar_context,
            "unexpected_token": context.unexpected_token,
            "unexpected_lexeme": context.unexpected_lexeme,
            "expected_tokens": list(context.expected_tokens),
            "previous_tokens": [item.to_dict() for item in context.previous_tokens],
            "current_token": context.current_token.to_dict() if context.current_token else None,
            "next_tokens": [item.to_dict() for item in context.next_tokens],
            "delimiter_depth": dict(context.delimiter_depth),
        },
        "validated_candidates": [
            {
                "candidate_id": validation.candidate.id,
                "action": validation.candidate.action.value,
                "token_type": validation.candidate.token_type,
                "token_lexeme": validation.candidate.token_lexeme,
                "target_start": validation.candidate.span.start.offset,
                "target_end": validation.candidate.span.end.offset,
                "replacement_text": validation.candidate.text,
                "compiler_reason": validation.candidate.reason,
                "corrected_source": validation.corrected_source,
                "parser_validation": {
                    "valid": validation.valid,
                    "relevant_valid": validation.relevant_valid,
                    "remaining_lexical_errors": validation.remaining_lexical_errors,
                    "remaining_syntax_errors": validation.remaining_syntax_errors,
                },
            }
            for validation in candidates
            if validation.relevant_valid
        ],
        "selection_policy": (
            "Choose exactly one supplied candidate ID only when it is clearly more plausible. "
            "Otherwise return null. Never propose source text or a new edit."
        ),
        "required_output": {
            "selected_candidate_id": "supplied candidate_id string | null",
            "confidence": "number from 0 to 1",
            "reason": "short explanation",
        },
    }


_SYSTEM_PROMPT = """You are a constrained Mini-C syntax correction fallback.
Use only the supplied compiler context. Propose one minimal syntax edit, not a
rewritten program. Return one JSON object with exactly these fields: action,
replacement_text, target_start, target_end, reason. action must be INSERT, DELETE,
or REPLACE. Offsets are absolute and the target range is half-open. For INSERT,
target_start must equal target_end. For DELETE, replacement_text must be empty.
Do not include Markdown, explanations outside JSON, or additional fields."""


_SELECTION_SYSTEM_PROMPT = """You are a constrained Mini-C correction candidate selector.
You may choose only one candidate_id from the validated_candidates supplied by the
compiler, or null when programmer intent is uncertain. Never propose, rewrite, or
describe a new edit. Return exactly one JSON object with selected_candidate_id,
confidence, and reason. Do not include Markdown or text outside the JSON object."""

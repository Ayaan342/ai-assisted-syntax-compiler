from __future__ import annotations

from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from ai.correction_orchestrator import CorrectionOrchestrator, CorrectionStatus
from ai.dataset_generator import CorrectionClass
from ai.error_context import ErrorContext
from ai.error_predictor import ErrorPrediction
from ai.llm_fallback import (
    DEFAULT_GROQ_MODEL,
    GroqFallbackService,
    LLMFallbackResult,
    LLMSuggestion,
    parse_llm_suggestion,
    suggestion_to_candidate,
)
from compiler.correction import CorrectionAction, apply_candidate
from compiler.parser import parse


class FixedPredictor:
    def __init__(self, confidence: float) -> None:
        self.prediction = ErrorPrediction(
            CorrectionClass.INSERT_RPAREN.value,
            confidence,
            {CorrectionClass.INSERT_RPAREN.value: confidence},
        )

    def predict_error_type(self, context):
        return self.prediction


class FakeFallback:
    model = "mock-groq-model"

    def __init__(self, result: LLMFallbackResult) -> None:
        self.result = result
        self.calls = 0

    def suggest(self, context, prediction):
        self.calls += 1
        return self.result


class FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_client(content: str):
    completions = FakeCompletions(content)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def context_for(source: str):
    result = parse(source)
    diagnostic = result.syntax_errors[0]
    return result, diagnostic, ErrorContext.from_diagnostic(diagnostic, result.tokens, source)


def insert_rparen_suggestion(source: str) -> LLMSuggestion:
    offset = source.index(" {", source.index("if"))
    return LLMSuggestion(
        CorrectionAction.INSERT,
        ")",
        offset,
        offset,
        "Missing closing parenthesis",
    )


def successful_result(source: str) -> LLMFallbackResult:
    return LLMFallbackResult(
        True,
        True,
        "mock-groq-model",
        suggestion=insert_rparen_suggestion(source),
    )


def test_missing_api_key_returns_clean_unavailable_result(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    service = GroqFallbackService(env_path=Path(".missing-env-for-test"))
    _, _, context = context_for("int main(){if(true {return 0;}}")
    result = service.suggest(context, FixedPredictor(0.4).prediction)
    assert not result.available and not result.attempted
    assert result.suggestion is None
    assert "GROQ_API_KEY" in result.error


def test_fallback_not_called_for_high_confidence_ml_correction() -> None:
    source = "int main(){if(true {return 0;}}"
    fallback = FakeFallback(successful_result(source))
    result = CorrectionOrchestrator(FixedPredictor(0.99), llm_fallback=fallback).correct(source)
    assert result.success and fallback.calls == 0
    assert result.history[0].llm_fallback is None


def test_fallback_called_once_for_low_confidence_case() -> None:
    source = "int main(){if(true {return 0;}}"
    fallback = FakeFallback(successful_result(source))
    result = CorrectionOrchestrator(FixedPredictor(0.40), llm_fallback=fallback).correct(source)
    assert fallback.calls == 1
    assert result.success and result.history[0].llm_fallback.accepted


def test_valid_structured_json_response_and_context_payload() -> None:
    source = "int main(){if(true {return 0;}}"
    suggestion = insert_rparen_suggestion(source)
    client, completions = fake_client(json.dumps(suggestion.to_dict()))
    service = GroqFallbackService(client=client)
    _, _, context = context_for(source)
    result = service.suggest(context, FixedPredictor(0.4).prediction)
    assert result.suggestion == suggestion
    call = completions.calls[0]
    payload = json.loads(call["messages"][1]["content"])
    assert payload["language"] == "Mini-C"
    assert payload["traditional_candidates"]
    assert payload["ml_prediction"]["confidence"] == 0.4
    assert call["response_format"] == {"type": "json_object"}
    assert call["model"] == DEFAULT_GROQ_MODEL


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"action":"MOVE"}',
        '{"action":"INSERT","replacement_text":")","target_start":1,"target_end":2,"reason":"bad"}',
    ],
)
def test_malformed_llm_response_is_rejected(content) -> None:
    client, _ = fake_client(content)
    service = GroqFallbackService(client=client)
    _, _, context = context_for("int main(){if(true {return 0;}}")
    result = service.suggest(context, FixedPredictor(0.4).prediction)
    assert result.attempted and result.suggestion is None
    assert result.error.startswith("Malformed Groq response")


@pytest.mark.parametrize(
    "source,payload,expected",
    [
        (
            "int main(){return 0;}",
            {"action": "INSERT", "replacement_text": ";", "target_start": 10, "target_end": 10, "reason": "insert"},
            CorrectionAction.INSERT,
        ),
        (
            "int main(){int x = = 1;}",
            {"action": "DELETE", "replacement_text": "", "target_start": 19, "target_end": 20, "reason": "delete"},
            CorrectionAction.DELETE,
        ),
        (
            "int main(){retrun 0;}",
            {"action": "REPLACE", "replacement_text": "return", "target_start": 11, "target_end": 17, "reason": "replace"},
            CorrectionAction.REPLACE,
        ),
    ],
)
def test_insert_delete_replace_conversion(source, payload, expected) -> None:
    diagnostic = parse("int main(){retrun 0;}").syntax_errors[0]
    suggestion = parse_llm_suggestion(json.dumps(payload))
    candidate = suggestion_to_candidate(suggestion, diagnostic, source)
    assert candidate.action is expected
    assert candidate.origin == "groq_fallback"
    assert apply_candidate(source, candidate) != source


def test_valid_llm_correction_is_compiler_validated_and_accepted() -> None:
    source = "int main(){if(true {return 0;}}"
    result = CorrectionOrchestrator(
        FixedPredictor(0.40), llm_fallback=FakeFallback(successful_result(source))
    ).correct(source)
    entry = result.history[0]
    assert entry.status is CorrectionStatus.APPLIED
    assert entry.reason == "llm_fallback_parser_validated"
    assert entry.validation.relevant_valid
    assert entry.selected_candidate.origin == "groq_fallback"


def test_invalid_llm_correction_is_rejected_and_source_unchanged() -> None:
    source = "int main(){if(true {return 0;}}"
    suggestion = LLMSuggestion(CorrectionAction.INSERT, "(", 0, 0, "bad edit")
    fallback = FakeFallback(LLMFallbackResult(True, True, "mock", suggestion))
    result = CorrectionOrchestrator(FixedPredictor(0.40), llm_fallback=fallback).correct(source)
    assert not result.success
    assert result.corrected_source == source
    assert not result.history[0].llm_fallback.accepted
    assert result.history[0].llm_fallback.validation is not None


def test_out_of_range_llm_edit_is_rejected_without_source_change() -> None:
    source = "int main(){if(true {return 0;}}"
    suggestion = LLMSuggestion(CorrectionAction.INSERT, ")", 999, 999, "bad range")
    fallback = FakeFallback(LLMFallbackResult(True, True, "mock", suggestion))
    result = CorrectionOrchestrator(FixedPredictor(0.40), llm_fallback=fallback).correct(source)
    assert result.corrected_source == source
    assert result.history[0].llm_fallback.error.startswith("Unsafe LLM suggestion")


def test_fallback_history_serialization_contains_no_api_key() -> None:
    source = "int main(){if(true {return 0;}}"
    result = CorrectionOrchestrator(
        FixedPredictor(0.40), llm_fallback=FakeFallback(successful_result(source))
    ).correct(source)
    serialized = json.dumps(result.to_dict())
    payload = json.loads(serialized)["history"][0]["llm_fallback"]
    assert payload["attempted"] and payload["accepted"]
    assert payload["model"] == "mock-groq-model"
    assert "api_key" not in serialized.lower()


def test_unavailable_fallback_preserves_phase6_unresolved_behavior() -> None:
    source = "int main(){if(true {return 0;}}"
    unavailable = LLMFallbackResult(False, False, "mock", error="unavailable")
    result = CorrectionOrchestrator(
        FixedPredictor(0.40), llm_fallback=FakeFallback(unavailable)
    ).correct(source)
    assert result.needs_llm_fallback and not result.success
    assert result.stop_reason == "low_confidence_unresolved"
    assert result.history[0].status is CorrectionStatus.UNRESOLVED

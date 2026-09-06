from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import json
from pathlib import Path

import pytest

import ai.correction_orchestrator as orchestrator_module
from ai.correction_orchestrator import CorrectionOrchestrator, CorrectionStatus
from ai.dataset_generator import CorrectionClass
from ai.error_context import ErrorContext
from ai.error_predictor import ErrorPrediction
from ai.llm_fallback import (
    DEFAULT_GROQ_MODEL,
    GroqFallbackService,
    LLMCandidateSelection,
    LLMCandidateSelectionResult,
    LLMFallbackResult,
    LLMSuggestion,
    parse_llm_suggestion,
    parse_candidate_selection,
    suggestion_to_candidate,
)
from compiler.correction import CorrectionAction, apply_candidate, validate_candidate
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


class FakeAmbiguitySelector(FakeFallback):
    def __init__(self, selection_result: LLMCandidateSelectionResult) -> None:
        super().__init__(LLMFallbackResult(False, False, self.model, error="unused"))
        self.selection_result = selection_result
        self.selection_calls = 0
        self.selection_payload = None

    def select_candidate(self, source, context, candidates):
        self.selection_calls += 1
        self.selection_payload = (source, context, tuple(candidates))
        return self.selection_result


class LabelPredictor:
    def __init__(self, label: CorrectionClass, confidence: float = 0.99) -> None:
        self.prediction = ErrorPrediction(
            label.value,
            confidence,
            {label.value: confidence},
        )

    def predict_error_type(self, context):
        return self.prediction


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


def ambiguity_source() -> str:
    return "int main(){ int x=10; if(x>5){ return x; } return 0; { }"


def selection_result(
    candidate_id: str | None,
    confidence: float = 0.91,
    reason: str = "The local deletion better preserves the surrounding function.",
) -> LLMCandidateSelectionResult:
    return LLMCandidateSelectionResult(
        True,
        True,
        "mock-groq-model",
        selection=LLMCandidateSelection(candidate_id, confidence, reason),
    )


def ambiguity_candidate_id(action: CorrectionAction) -> str:
    diagnostic = parse(ambiguity_source()).syntax_errors[0]
    return next(
        candidate.id
        for candidate in diagnostic.correction_candidates
        if candidate.action is action
    )


def validated_ambiguity_candidates():
    source = ambiguity_source()
    result, diagnostic, context = context_for(source)
    validations = tuple(
        validate_candidate(
            source,
            candidate,
            target_diagnostic=diagnostic,
            baseline_result=result,
        )
        for candidate in diagnostic.correction_candidates
    )
    assert all(validation.valid for validation in validations)
    return source, context, validations


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


def test_ambiguity_ml_unique_match_does_not_call_groq() -> None:
    selector = FakeAmbiguitySelector(selection_result(None))

    result = CorrectionOrchestrator(
        LabelPredictor(CorrectionClass.INSERT_RBRACE),
        llm_fallback=selector,
    ).correct(ambiguity_source())

    assert result.success and selector.selection_calls == 0
    assert result.history[0].selected_candidate.action is CorrectionAction.INSERT
    assert result.history[0].ambiguity_selection is None


def test_ambiguity_unrelated_ml_calls_groq_selector() -> None:
    selector = FakeAmbiguitySelector(selection_result(None, 0.42, "Both are plausible."))

    result = CorrectionOrchestrator(
        LabelPredictor(CorrectionClass.REPLACE_BRACKET),
        llm_fallback=selector,
    ).correct(ambiguity_source())

    assert selector.selection_calls == 1
    assert not result.success and result.corrected_source == result.original_source
    record = result.history[0].ambiguity_selection
    assert record is not None and record.attempted and not record.accepted
    assert record.selected_candidate_id is None and record.confidence == 0.42


def test_ambiguity_groq_selection_is_revalidated_and_prepared() -> None:
    candidate_id = ambiguity_candidate_id(CorrectionAction.DELETE)
    selector = FakeAmbiguitySelector(selection_result(candidate_id))
    source = ambiguity_source()

    result = CorrectionOrchestrator(
        LabelPredictor(CorrectionClass.REPLACE_BRACKET),
        llm_fallback=selector,
    ).correct(source)

    assert result.success and result.corrections_applied == 1
    assert result.original_source == source
    assert result.corrected_source != source and "return 0;  }" in result.corrected_source
    entry = result.history[0]
    assert entry.reason == "ambiguity_selection_groq_parser_validated"
    assert entry.selected_candidate.id == candidate_id
    assert entry.selected_candidate.action is CorrectionAction.DELETE
    assert entry.validation is not None and entry.validation.valid
    assert entry.ambiguity_selection is not None
    assert entry.ambiguity_selection.accepted
    assert entry.ambiguity_selection.validation is entry.validation
    assert parse(result.corrected_source).valid


def test_ambiguity_invalid_candidate_id_remains_unresolved() -> None:
    selector = FakeAmbiguitySelector(selection_result("not-a-compiler-candidate"))
    source = ambiguity_source()

    result = CorrectionOrchestrator(
        LabelPredictor(CorrectionClass.REPLACE_BRACKET),
        llm_fallback=selector,
    ).correct(source)

    assert not result.success and result.corrected_source == source
    record = result.history[0].ambiguity_selection
    assert record is not None and not record.accepted
    assert record.error == "Groq selected an unknown candidate ID"


def test_ambiguity_low_selection_confidence_remains_unresolved() -> None:
    candidate_id = ambiguity_candidate_id(CorrectionAction.DELETE)
    selector = FakeAmbiguitySelector(selection_result(candidate_id, 0.74))

    result = CorrectionOrchestrator(
        LabelPredictor(CorrectionClass.REPLACE_BRACKET),
        llm_fallback=selector,
    ).correct(ambiguity_source())

    record = result.history[0].ambiguity_selection
    assert not result.success and result.corrections_applied == 0
    assert record is not None and not record.accepted
    assert record.confidence == 0.74
    assert record.error == "Groq selection confidence is below threshold"


def test_ambiguity_selector_rejects_malformed_json() -> None:
    source, context, candidates = validated_ambiguity_candidates()
    client, _ = fake_client("not json")

    result = GroqFallbackService(client=client).select_candidate(
        source, context, candidates
    )

    assert result.attempted and result.selection is None
    assert result.error.startswith("Malformed Groq selection response")


def test_ambiguity_selector_handles_provider_failure() -> None:
    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("provider unavailable")

    source, context, candidates = validated_ambiguity_candidates()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailingCompletions())
    )

    result = GroqFallbackService(client=client).select_candidate(
        source, context, candidates
    )

    assert result.attempted and result.selection is None
    assert result.error == "Groq selection request failed: RuntimeError"


def test_ambiguity_selected_candidate_must_pass_final_revalidation(monkeypatch) -> None:
    candidate_id = ambiguity_candidate_id(CorrectionAction.DELETE)
    selector = FakeAmbiguitySelector(selection_result(candidate_id))
    real_validate = orchestrator_module.validate_candidate
    calls = 0

    def fail_only_final_validation(*args, **kwargs):
        nonlocal calls
        validation = real_validate(*args, **kwargs)
        if validation.candidate.id == candidate_id:
            calls += 1
            if calls == 2:
                return replace(validation, valid=False, relevant_valid=False)
        return validation

    monkeypatch.setattr(
        orchestrator_module, "validate_candidate", fail_only_final_validation
    )
    source = ambiguity_source()

    result = CorrectionOrchestrator(
        LabelPredictor(CorrectionClass.REPLACE_BRACKET),
        llm_fallback=selector,
    ).correct(source)

    assert not result.success and result.corrected_source == source
    record = result.history[0].ambiguity_selection
    assert record is not None and record.validation is not None
    assert not record.accepted and not record.validation.relevant_valid


def test_ambiguity_prompt_contains_only_source_context_and_validated_candidates() -> None:
    source, context, candidates = validated_ambiguity_candidates()
    candidate_id = ambiguity_candidate_id(CorrectionAction.DELETE)
    content = json.dumps(
        LLMCandidateSelection(candidate_id, 0.91, "Delete the stray opener.").to_dict()
    )
    client, completions = fake_client(content)

    result = GroqFallbackService(client=client).select_candidate(
        source, context, candidates
    )

    assert result.selection is not None
    call = completions.calls[0]
    payload = json.loads(call["messages"][1]["content"])
    assert set(payload) == {
        "language",
        "task",
        "original_source",
        "diagnostic",
        "validated_candidates",
        "selection_policy",
        "required_output",
    }
    assert payload["original_source"] == source
    assert {item["candidate_id"] for item in payload["validated_candidates"]} == {
        validation.candidate.id for validation in candidates
    }
    assert all(item["parser_validation"]["valid"] for item in payload["validated_candidates"])
    assert "ml_prediction" not in payload
    assert "replacement_text" not in payload["required_output"]
    assert call["response_format"] == {"type": "json_object"}


def test_parse_candidate_selection_is_strict() -> None:
    candidate_id = ambiguity_candidate_id(CorrectionAction.DELETE)
    parsed = parse_candidate_selection(
        json.dumps(
            {
                "selected_candidate_id": candidate_id,
                "confidence": 0.91,
                "reason": "Delete the stray opener.",
            }
        ),
        {candidate_id},
    )
    assert parsed.selected_candidate_id == candidate_id
    with pytest.raises(ValueError):
        parse_candidate_selection(
            '{"selected_candidate_id":"bad","confidence":0.9,"reason":"x"}',
            {candidate_id},
        )


def test_single_deterministic_candidate_never_calls_ambiguity_selector() -> None:
    selector = FakeAmbiguitySelector(selection_result(None))
    source = "int main(){ return 0 }"

    result = CorrectionOrchestrator(
        LabelPredictor(CorrectionClass.CORRECT_KEYWORD, 0.70),
        llm_fallback=selector,
    ).correct(source)

    assert result.success and result.corrections_applied == 1
    assert selector.selection_calls == 0
    assert result.history[0].selected_candidate.token_type == "SEMICOLON"

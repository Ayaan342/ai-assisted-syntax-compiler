from __future__ import annotations

import json
from dataclasses import replace

import pytest

import ai.correction_orchestrator as orchestrator_module
from ai.candidate_ranker import candidate_class, rank_candidates
from ai.correction_orchestrator import (
    CandidateAttempt,
    CorrectionOrchestrator,
    CorrectionPolicy,
    CorrectionStatus,
)
from ai.dataset_generator import CorrectionClass
from ai.error_predictor import ErrorPrediction
from compiler.correction import CandidateValidation, CorrectionAction, validate_candidate
from compiler.parser import parse


class FixedPredictor:
    def __init__(self, label: str, confidence: float, probabilities=None) -> None:
        self.prediction = ErrorPrediction(
            label,
            confidence,
            probabilities or {label: confidence},
        )

    def predict_error_type(self, context):
        return self.prediction


class CandidateAwarePredictor:
    """Deterministic test double that gives the compiler's first safe class high confidence."""

    def predict_error_type(self, context):
        classes = [candidate_class(item) for item in context.correction_candidates]
        label = next(item for item in classes if item is not None)
        if CorrectionClass.CORRECT_KEYWORD.value in classes:
            label = CorrectionClass.CORRECT_KEYWORD.value
        return ErrorPrediction(label, 0.99, {label: 0.99})


def fixed(label: CorrectionClass, confidence: float = 0.99, probabilities=None):
    return FixedPredictor(label.value, confidence, probabilities)


def run(source: str, label: CorrectionClass, **policy_overrides):
    policy = CorrectionPolicy(**policy_overrides) if policy_overrides else CorrectionPolicy()
    return CorrectionOrchestrator(fixed(label), policy).correct(source)


def test_candidate_ranking_uses_model_probability() -> None:
    error = parse("int main(){ if (true { return 0; } }").syntax_errors[0]
    prediction = ErrorPrediction(
        CorrectionClass.DELETE_EXTRA_TOKEN.value,
        0.51,
        {
            CorrectionClass.DELETE_EXTRA_TOKEN.value: 0.51,
            CorrectionClass.INSERT_RPAREN.value: 0.48,
        },
    )
    ranked = rank_candidates(error.correction_candidates, prediction)
    assert ranked[0].matched_class == CorrectionClass.DELETE_EXTRA_TOKEN.value
    assert ranked[0].compatibility_score == pytest.approx(0.51)


@pytest.mark.parametrize(
    "source,action,expected_class",
    [
        ("int main(){int x=1 return x;}", CorrectionAction.INSERT, CorrectionClass.INSERT_SEMICOLON),
        ("int main(){if(true {return 0;}}", CorrectionAction.INSERT, CorrectionClass.INSERT_RPAREN),
        ("int main(){if true) return 0;}", CorrectionAction.INSERT, CorrectionClass.INSERT_LPAREN),
        ("int main(){x=a[i;return 0;}", CorrectionAction.INSERT, CorrectionClass.INSERT_RBRACKET),
        ("int main(){return 0;", CorrectionAction.INSERT, CorrectionClass.INSERT_RBRACE),
        ("int main(){int x = = 1;}", CorrectionAction.DELETE, CorrectionClass.DELETE_EXTRA_TOKEN),
        ("int main(){if [true) return 0;}", CorrectionAction.REPLACE, CorrectionClass.REPLACE_BRACKET),
        ("int main(){if(1 => 0)return 1;return 0;}", CorrectionAction.REPLACE, CorrectionClass.REPLACE_OPERATOR),
        ("int main(){retrun 0;}", CorrectionAction.REPLACE, CorrectionClass.CORRECT_KEYWORD),
    ],
)
def test_correction_class_mapping(source, action, expected_class) -> None:
    candidates = [
        candidate
        for error in parse(source).syntax_errors
        for candidate in error.correction_candidates
        if candidate.action is action
    ]
    assert any(candidate_class(item) == expected_class.value for item in candidates)


def test_high_confidence_auto_apply() -> None:
    result = run("int main(){if(true {return 0;}}", CorrectionClass.INSERT_RPAREN)
    assert result.success and result.corrections_applied == 1
    assert result.history[0].status is CorrectionStatus.APPLIED


def test_medium_confidence_returns_suggestion_only() -> None:
    result = CorrectionOrchestrator(
        fixed(CorrectionClass.INSERT_RPAREN, 0.70)
    ).correct("int main(){if(true {return 0;}}")
    assert not result.success and result.corrections_applied == 0
    assert result.history[0].status is CorrectionStatus.SUGGESTED
    assert result.corrected_source == result.original_source
    assert not result.needs_llm_fallback


def test_misclassified_missing_return_semicolon_uses_unique_compiler_candidate() -> None:
    source = """int main() {
int x = 10;
if (x > 5) {
    return x
}

return 0;
}"""
    prediction = FixedPredictor(
        CorrectionClass.CORRECT_KEYWORD.value,
        0.7131919144492387,
        {
            CorrectionClass.CORRECT_KEYWORD.value: 0.7131919144492387,
            CorrectionClass.INSERT_SEMICOLON.value: 0.09367653851895673,
        },
    )

    result = CorrectionOrchestrator(prediction).correct(source)

    assert result.original_source == source
    assert result.corrected_source != result.original_source
    assert "return x;\n}" in result.corrected_source
    assert parse(result.corrected_source).valid
    assert result.success and result.corrections_applied == 1
    entry = result.history[0]
    assert entry.status is CorrectionStatus.APPLIED
    assert entry.selected_candidate.action is CorrectionAction.INSERT
    assert entry.selected_candidate.token_type == "SEMICOLON"
    assert candidate_class(entry.selected_candidate) == CorrectionClass.INSERT_SEMICOLON.value
    assert entry.validation is not None and entry.validation.relevant_valid
    assert entry.prediction.label == CorrectionClass.CORRECT_KEYWORD.value
    assert entry.reason == "unique_compiler_candidate_parser_validated"


def test_low_confidence_remains_unresolved_for_future_fallback() -> None:
    result = CorrectionOrchestrator(
        fixed(CorrectionClass.INSERT_RPAREN, 0.40)
    ).correct("int main(){if(true {return 0;}}")
    assert result.history[0].status is CorrectionStatus.UNRESOLVED
    assert result.needs_llm_fallback


@pytest.mark.parametrize(
    "source,label,fragment",
    [
        ("int main(){int x=1 return x;}", CorrectionClass.INSERT_SEMICOLON, "1; return"),
        ("int main(){if(true {return 0;}}", CorrectionClass.INSERT_RPAREN, "true) {"),
        ("int main(){if true) return 0;}", CorrectionClass.INSERT_LPAREN, "if (true)"),
        ("int main(){int a[2];x=a[i;return 0;}", CorrectionClass.INSERT_RBRACKET, "a[i];"),
        ("int main(){return 0;", CorrectionClass.INSERT_RBRACE, "0;}"),
        ("int main(){if [true) return 0;}", CorrectionClass.REPLACE_BRACKET, "if (true)"),
        ("int main(){int x = = 1;return x;}", CorrectionClass.DELETE_EXTRA_TOKEN, "x =  1"),
        ("int main(){retrun 0;}", CorrectionClass.CORRECT_KEYWORD, "return 0"),
        ("int main(){if(1 => 0)return 1;return 0;}", CorrectionClass.REPLACE_OPERATOR, "1 >= 0"),
    ],
)
def test_supported_automatic_corrections(source, label, fragment) -> None:
    result = run(source, label)
    assert result.success
    assert fragment in result.corrected_source


def test_parser_rejects_bad_top_candidate_and_tries_next_ranked() -> None:
    probabilities = {
        CorrectionClass.DELETE_EXTRA_TOKEN.value: 0.51,
        CorrectionClass.INSERT_RPAREN.value: 0.48,
        CorrectionClass.REPLACE_BRACKET.value: 0.01,
    }
    predictor = FixedPredictor(CorrectionClass.DELETE_EXTRA_TOKEN.value, 0.90, probabilities)
    result = CorrectionOrchestrator(predictor).correct(
        "int main(){if(true {return 0;}}"
    )
    assert result.success
    assert len(result.history[0].attempts) == 3
    assert not result.history[0].attempts[0].accepted
    assert result.history[0].candidate_rank == 2


def test_trailing_block_eof_ambiguity_is_not_silently_resolved() -> None:
    source = "int main(){ int x=10; if(x>5){ return x; } return 0; { }"
    predictor = FixedPredictor(
        CorrectionClass.REPLACE_BRACKET.value,
        0.99,
        {
            CorrectionClass.REPLACE_BRACKET.value: 0.99,
            CorrectionClass.INSERT_RBRACE.value: 0.005,
            CorrectionClass.DELETE_EXTRA_TOKEN.value: 0.005,
        },
    )

    result = CorrectionOrchestrator(predictor).correct(source)

    assert not result.success and result.corrections_applied == 0
    assert result.corrected_source == source == result.original_source
    assert result.stop_reason == "ambiguous_valid_candidates"
    entry = result.history[0]
    assert entry.status is CorrectionStatus.UNRESOLVED
    assert entry.reason == "ambiguous_valid_candidates_without_reliable_model_preference"
    valid_edits = {
        (attempt.ranked_candidate.candidate.action, attempt.ranked_candidate.candidate.token_type)
        for attempt in entry.attempts
        if attempt.validation.valid
    }
    assert valid_edits == {
        (CorrectionAction.INSERT, "RBRACE"),
        (CorrectionAction.DELETE, "LBRACE"),
    }


def test_adjacent_operator_ambiguity_preserves_original_source() -> None:
    source = "int main(){ int x=1; int y=2; x + * y; return 0; }"
    predictor = fixed(CorrectionClass.DELETE_EXTRA_TOKEN, 0.99)

    result = CorrectionOrchestrator(predictor).correct(source)

    assert not result.success and result.corrections_applied == 0
    assert result.corrected_source == source
    assert result.stop_reason == "ambiguous_valid_candidates"
    attempts = result.history[0].attempts
    assert len([attempt for attempt in attempts if attempt.validation.valid]) == 2
    assert {attempt.validation.corrected_source for attempt in attempts} == {
        "int main(){ int x=1; int y=2; x +  y; return 0; }",
        "int main(){ int x=1; int y=2; x  * y; return 0; }",
    }


def test_whole_program_repair_wins_over_higher_ranked_partial_repair() -> None:
    source = "int main(){ int a[2]; int i=0; return a[i]]; }"
    predictor = FixedPredictor(
        CorrectionClass.INSERT_SEMICOLON.value,
        0.99,
        {
            CorrectionClass.INSERT_SEMICOLON.value: 0.99,
            CorrectionClass.DELETE_EXTRA_TOKEN.value: 0.01,
        },
    )

    result = CorrectionOrchestrator(predictor).correct(source)

    assert result.success and result.corrections_applied == 1
    assert result.history[0].selected_candidate.action is CorrectionAction.DELETE
    assert result.history[0].selected_candidate.token_type == "RBRACKET"
    assert parse(result.corrected_source).valid


def test_adjacent_operand_ambiguity_does_not_invent_an_operator() -> None:
    source = "int main(){ int x=1; int y=2; x y; return 0; }"
    result = CorrectionOrchestrator(
        fixed(CorrectionClass.CORRECT_KEYWORD, 0.99)
    ).correct(source)

    assert result.stop_reason == "ambiguous_valid_candidates"
    assert result.corrected_source == source
    actions = {
        (attempt.ranked_candidate.candidate.action, attempt.ranked_candidate.candidate.text)
        for attempt in result.history[0].attempts
        if attempt.validation.valid
    }
    assert actions == {
        (CorrectionAction.INSERT, ";"),
        (CorrectionAction.DELETE, ""),
    }


def test_surplus_closer_is_a_unique_validated_compiler_deletion() -> None:
    source = "int main(){ int x=10; if(x>5)) { return x; } return 0; }"
    result = CorrectionOrchestrator(
        fixed(CorrectionClass.CORRECT_KEYWORD, 0.40)
    ).correct(source)

    assert result.success and result.corrections_applied == 1
    entry = result.history[0]
    assert entry.selected_candidate.action is CorrectionAction.DELETE
    assert entry.selected_candidate.token_type == "RPAREN"
    assert entry.validation is not None and entry.validation.valid
    assert parse(result.corrected_source).valid


def test_wrong_closer_type_remains_a_unique_validated_replacement() -> None:
    source = "int main(){ int x=10; if(x>5] { return x; } return 0; }"
    result = CorrectionOrchestrator(
        fixed(CorrectionClass.INSERT_RPAREN, 0.40)
    ).correct(source)

    assert result.success and result.corrections_applied == 1
    entry = result.history[0]
    assert entry.selected_candidate.action is CorrectionAction.REPLACE
    assert entry.selected_candidate.token_type == "RPAREN"
    assert entry.validation is not None and entry.validation.valid
    assert parse(result.corrected_source).valid


def test_target_can_resolve_while_later_error_remains() -> None:
    source = "int main(){int x=1 if(true {return x;}}"
    baseline = parse(source)
    candidate = baseline.syntax_errors[0].correction_candidates[0]
    validation = validate_candidate(
        source,
        candidate,
        target_diagnostic=baseline.syntax_errors[0],
        baseline_result=baseline,
    )
    assert not validation.valid
    assert validation.relevant_valid
    assert validation.remaining_syntax_errors >= 1


def test_multiple_errors_are_corrected_iteratively() -> None:
    source = "int main(){int x=1 if(x>0 {retrun x;} return 0;}"
    result = CorrectionOrchestrator(CandidateAwarePredictor()).correct(source)
    assert result.success
    assert result.corrections_applied == 3
    assert all(item.status is CorrectionStatus.APPLIED for item in result.history)


def test_maximum_correction_limit_stops_iteration() -> None:
    source = "int main(){int x=1 if(x>0 {return x;} return 0;}"
    policy = CorrectionPolicy(max_corrections=1)
    result = CorrectionOrchestrator(CandidateAwarePredictor(), policy).correct(source)
    assert not result.success and result.corrections_applied == 1
    assert result.stop_reason == "maximum_correction_count_reached"


def test_no_progress_source_state_is_rejected(monkeypatch) -> None:
    source = "int main(){if(true {return 0;}}"

    def no_progress(current, candidate, **kwargs):
        return CandidateValidation(candidate, current, False, 0, 1, True, False, True)

    monkeypatch.setattr(orchestrator_module, "validate_candidate", no_progress)
    result = CorrectionOrchestrator(fixed(CorrectionClass.INSERT_RPAREN)).correct(source)
    assert result.stop_reason == "no_candidate_passed_parser_validation"
    assert all(not attempt.accepted for attempt in result.history[0].attempts)


def test_history_and_corrected_source_are_json_serializable() -> None:
    result = run("int main(){if(true {return 0;}}", CorrectionClass.INSERT_RPAREN)
    payload = json.loads(json.dumps(result.to_dict()))
    assert payload["corrected_source"] == result.corrected_source
    assert payload["history"][0]["status"] == "APPLIED"
    assert payload["history"][0]["validation"]["target_resolved"]


def test_suggestion_mode_never_applies_even_high_confidence() -> None:
    result = CorrectionOrchestrator(fixed(CorrectionClass.INSERT_RPAREN)).correct(
        "int main(){if(true {return 0;}}", auto_apply=False
    )
    assert result.history[0].status is CorrectionStatus.SUGGESTED
    assert result.corrections_applied == 0
    assert result.corrected_source == result.original_source


def test_semantic_diagnostics_are_separate_from_syntax_success() -> None:
    result = run("int main(){return missing}", CorrectionClass.INSERT_SEMICOLON)
    assert result.success and result.fully_syntactically_valid
    assert result.semantic_diagnostics
    assert result.unresolved_diagnostics == ()


def test_valid_source_requires_no_prediction_or_change() -> None:
    result = CorrectionOrchestrator(fixed(CorrectionClass.INSERT_RPAREN)).correct(
        "int main(){return 0;}"
    )
    assert result.success and not result.history and not result.predictions
    assert result.corrected_source == result.original_source


def test_policy_rejects_invalid_threshold_order() -> None:
    with pytest.raises(ValueError):
        CorrectionPolicy(auto_apply_threshold=0.5, llm_fallback_threshold=0.6)

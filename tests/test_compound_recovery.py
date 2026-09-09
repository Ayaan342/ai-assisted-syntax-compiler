from __future__ import annotations

from collections import Counter

import pytest

import ai.correction_orchestrator as orchestrator_module
from ai.candidate_ranker import candidate_classes
from ai.correction_orchestrator import CorrectionOrchestrator, CorrectionStatus
from ai.dataset_generator import CorrectionClass
from ai.error_predictor import ErrorPrediction
from ai.llm_fallback import (
    LLMCandidateSelection,
    LLMCandidateSelectionResult,
    LLMFallbackResult,
)
from compiler.compound_recovery import MAX_COMPOUND_EDITS, generate_compound_candidates
from compiler.correction import CorrectionAction, apply_candidate, validate_candidate
from compiler.parser import parse


A_IF_MIXED = "int main(){ int x=1; if ((x > 5] { return x; } return 0; }"
B_NESTED = "int main(){ int x=1; if (((x > 5))] { return x; } return 0; }"
C_ARRAY = "int main(){ int a[2]; int i=0; return a[[i); }"
D_CALL = (
    "int add(int x,int y){return x+y;} "
    "int main(){int x=1;int y=2;return add((x, y];}"
)
E_WHILE = "int main(){ int x=1; while ((x > 0] { x=x-1; } return 0; }"
F_SINGLE = "int main(){ int x=1; if (x > 5 { return x; } return 0; }"
H_UNSAFE = "int main(){ int x = ; return 0; }"
MULTI_ERROR = """int main() {
    int x = 10

    if ((x > 5] {
        retrun x
    }

    return 0;
}"""


class FixedPredictor:
    def __init__(self, label: CorrectionClass, confidence: float = 0.99) -> None:
        self.label = label.value
        self.confidence = confidence

    def predict_error_type(self, context):
        return ErrorPrediction(
            self.label,
            self.confidence,
            {self.label: self.confidence},
        )


class MultiErrorPredictor:
    def predict_error_type(self, context):
        classes = {
            item
            for candidate in context.correction_candidates
            for item in candidate_classes(candidate)
        }
        if context.unexpected_token == "RBRACKET" and "RPAREN" in context.expected_tokens:
            label = CorrectionClass.INSERT_RPAREN.value
        elif CorrectionClass.CORRECT_KEYWORD.value in classes:
            label = CorrectionClass.CORRECT_KEYWORD.value
        elif CorrectionClass.INSERT_SEMICOLON.value in classes:
            label = CorrectionClass.INSERT_SEMICOLON.value
        else:
            label = next(iter(classes), CorrectionClass.REPLACE_BRACKET.value)
        return ErrorPrediction(label, 0.99, {label: 0.99})


class SelectingCompoundFallback:
    model = "mock-groq"

    def __init__(self) -> None:
        self.selection_calls = 0
        self.received = ()

    def suggest(self, context, prediction):
        return LLMFallbackResult(False, False, self.model, error="unused")

    def select_candidate(self, source, context, candidates):
        self.selection_calls += 1
        self.received = tuple(candidates)
        selected = next(
            item
            for item in candidates
            if any(edit.action is CorrectionAction.DELETE for edit in item.candidate.edits)
        )
        return LLMCandidateSelectionResult(
            True,
            True,
            self.model,
            selection=LLMCandidateSelection(
                selected.candidate.id,
                0.91,
                "Deleting the extra opener is the more plausible validated repair.",
            ),
        )


def compound_validations(source: str):
    baseline = parse(source)
    diagnostic = baseline.syntax_errors[0]
    candidates = generate_compound_candidates(
        source,
        baseline.tokens,
        baseline.syntax_errors,
        diagnostic,
    )
    validations = tuple(
        validate_candidate(
            source,
            candidate,
            target_diagnostic=diagnostic,
            baseline_result=baseline,
        )
        for candidate in candidates
    )
    return baseline, candidates, validations


@pytest.mark.parametrize("source", [A_IF_MIXED, E_WHILE])
def test_mismatched_and_missing_condition_delimiters_have_two_valid_repairs(source) -> None:
    _, candidates, validations = compound_validations(source)

    assert len(candidates) == 2
    assert all(len(candidate.edits) == MAX_COMPOUND_EDITS == 2 for candidate in candidates)
    assert all(validation.valid and validation.relevant_valid for validation in validations)
    assert {candidate.id for candidate in candidates} == {"SYN-0001-M01", "SYN-0001-M02"}


@pytest.mark.parametrize(
    "source,expected",
    [
        (C_ARRAY, "return a[i];"),
        (D_CALL, "return add(x, y);"),
    ],
)
def test_only_compiler_valid_array_and_call_compound_repairs_survive(source, expected) -> None:
    _, _, validations = compound_validations(source)
    valid = [item for item in validations if item.relevant_valid]

    assert len(valid) == 1
    assert valid[0].valid
    assert expected in valid[0].corrected_source

    result = CorrectionOrchestrator(
        FixedPredictor(CorrectionClass.REPLACE_BRACKET, confidence=0.70)
    ).correct(source)
    assert result.success
    assert result.history[0].selected_candidate.id == valid[0].candidate.id
    assert result.history[0].selected_candidate.action is CorrectionAction.COMPOUND
    assert result.history[0].reason == "unique_compiler_candidate_parser_validated"


def test_compound_edits_apply_atomically_from_highest_offset() -> None:
    _, candidates, validations = compound_validations(A_IF_MIXED)
    source_before = A_IF_MIXED
    candidate = candidates[0]

    corrected = apply_candidate(A_IF_MIXED, candidate)

    assert A_IF_MIXED == source_before
    assert corrected == validations[0].corrected_source
    assert parse(corrected).valid
    assert candidate.to_dict()["edits"] == [edit.to_dict() for edit in candidate.edits]


def test_single_edit_nested_delimiter_repair_remains_unchanged() -> None:
    baseline, compounds, _ = compound_validations(B_NESTED)
    single = baseline.syntax_errors[0].correction_candidates

    assert len(single) == 1
    assert validate_candidate(B_NESTED, single[0]).valid
    assert compounds == ()
    result = CorrectionOrchestrator(
        FixedPredictor(CorrectionClass.REPLACE_BRACKET)
    ).correct(B_NESTED)
    assert result.success and result.corrections_applied == 1
    assert result.history[0].selected_candidate.origin == "traditional_recovery"
    assert result.history[0].selected_candidate.action is CorrectionAction.REPLACE


def test_existing_single_edit_control_condition_path_does_not_attempt_compound() -> None:
    result = CorrectionOrchestrator(
        FixedPredictor(CorrectionClass.INSERT_RPAREN)
    ).correct(F_SINGLE)

    assert result.success and result.corrections_applied == 1
    assert result.history[0].selected_candidate.origin == "traditional_recovery"
    assert all(
        attempt.ranked_candidate.candidate.action is not CorrectionAction.COMPOUND
        for attempt in result.history[0].attempts
    )


def test_original_multi_error_program_continues_after_compound_repair() -> None:
    result = CorrectionOrchestrator(MultiErrorPredictor()).correct(MULTI_ERROR)

    assert result.success and parse(result.corrected_source).valid
    assert result.original_source == MULTI_ERROR
    assert result.corrections_applied == 4
    assert [item.selected_candidate.action for item in result.history] == [
        CorrectionAction.INSERT,
        CorrectionAction.COMPOUND,
        CorrectionAction.REPLACE,
        CorrectionAction.INSERT,
    ]
    assert "int x = 10;" in result.corrected_source
    assert "return x;" in result.corrected_source
    assert "retrun" not in result.corrected_source
    assert all(item.status is CorrectionStatus.APPLIED for item in result.history)


def test_ml_unique_compound_class_skips_groq() -> None:
    fallback = SelectingCompoundFallback()
    result = CorrectionOrchestrator(
        FixedPredictor(CorrectionClass.INSERT_RPAREN),
        llm_fallback=fallback,
    ).correct(A_IF_MIXED)

    assert result.success
    assert fallback.selection_calls == 0
    assert result.history[0].selected_candidate.action is CorrectionAction.COMPOUND
    assert any(
        edit.action is CorrectionAction.INSERT
        for edit in result.history[0].selected_candidate.edits
    )


def test_low_confidence_unique_compound_class_uses_constrained_groq() -> None:
    fallback = SelectingCompoundFallback()
    result = CorrectionOrchestrator(
        FixedPredictor(CorrectionClass.INSERT_RPAREN, confidence=0.70),
        llm_fallback=fallback,
    ).correct(A_IF_MIXED)

    assert result.success and fallback.selection_calls == 1
    assert result.history[0].ambiguity_selection is not None
    assert result.history[0].ambiguity_selection.accepted
    assert result.history[0].llm_fallback is None


def test_ambiguous_compound_candidates_use_groq_and_revalidate(monkeypatch) -> None:
    fallback = SelectingCompoundFallback()
    real_validate = orchestrator_module.validate_candidate
    validation_calls: Counter[str] = Counter()

    def counting_validate(*args, **kwargs):
        validation = real_validate(*args, **kwargs)
        if validation.candidate.action is CorrectionAction.COMPOUND:
            validation_calls[validation.candidate.id] += 1
        return validation

    monkeypatch.setattr(orchestrator_module, "validate_candidate", counting_validate)
    result = CorrectionOrchestrator(
        FixedPredictor(CorrectionClass.REPLACE_BRACKET),
        llm_fallback=fallback,
    ).correct(A_IF_MIXED)

    assert result.success and fallback.selection_calls == 1
    assert len(fallback.received) == 2
    assert all(item.relevant_valid for item in fallback.received)
    entry = result.history[0]
    assert entry.ambiguity_selection is not None
    assert entry.ambiguity_selection.accepted
    assert entry.ambiguity_selection.validation.relevant_valid
    assert validation_calls[entry.selected_candidate.id] == 2
    assert parse(result.corrected_source).valid


def test_ambiguous_compound_without_selector_and_unsafe_case_remain_unresolved() -> None:
    ambiguous = CorrectionOrchestrator(
        FixedPredictor(CorrectionClass.REPLACE_BRACKET)
    ).correct(A_IF_MIXED)
    unsafe = CorrectionOrchestrator(
        FixedPredictor(CorrectionClass.REPLACE_BRACKET)
    ).correct(H_UNSAFE)

    assert not ambiguous.success
    assert ambiguous.corrected_source == ambiguous.original_source == A_IF_MIXED
    assert ambiguous.stop_reason == "ambiguous_valid_candidates"
    assert not unsafe.success
    assert unsafe.corrected_source == unsafe.original_source == H_UNSAFE
    assert unsafe.stop_reason == "no_safe_candidate"

"""High-level ML-assisted, compiler-validated syntax correction pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from compiler.correction import CandidateValidation, CorrectionCandidate, validate_candidate
from compiler.errors import SemanticDiagnostic, SyntaxDiagnostic
from compiler.parser import ParseResult, parse
from compiler.semantic_analyzer import analyze_source_semantics
from compiler.source_location import SourceLocation, SourceSpan

from .candidate_ranker import RankedCandidate, rank_candidates
from .error_context import ErrorContext
from .error_predictor import AIErrorPredictor, ErrorPrediction, MLCorrectionPredictor
from .llm_fallback import (
    DEFAULT_AMBIGUITY_SELECTION_THRESHOLD,
    LLMCandidateSelectionResult,
    LLMFallbackResult,
    LLMFallbackService,
    LLMSuggestion,
    suggestion_to_candidate,
)


AUTO_APPLY_THRESHOLD = 0.80
LLM_FALLBACK_THRESHOLD = 0.60


class CorrectionStatus(str, Enum):
    APPLIED = "APPLIED"
    SUGGESTED = "SUGGESTED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class CorrectionPolicy:
    """Tunable guardrails; the confidence defaults are not scientifically calibrated."""

    auto_apply_threshold: float = AUTO_APPLY_THRESHOLD
    llm_fallback_threshold: float = LLM_FALLBACK_THRESHOLD
    ambiguity_selection_threshold: float = DEFAULT_AMBIGUITY_SELECTION_THRESHOLD
    max_corrections: int = 10
    max_candidate_attempts: int = 5
    max_repeated_offset_attempts: int = 2

    def __post_init__(self) -> None:
        if not 0.0 <= self.llm_fallback_threshold <= self.auto_apply_threshold <= 1.0:
            raise ValueError("Thresholds must satisfy 0 <= fallback <= auto-apply <= 1")
        if not 0.0 <= self.ambiguity_selection_threshold <= 1.0:
            raise ValueError("Ambiguity selection threshold must be between 0 and 1")
        if min(
            self.max_corrections,
            self.max_candidate_attempts,
            self.max_repeated_offset_attempts,
        ) < 1:
            raise ValueError("Correction limits must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_apply_threshold": self.auto_apply_threshold,
            "llm_fallback_threshold": self.llm_fallback_threshold,
            "ambiguity_selection_threshold": self.ambiguity_selection_threshold,
            "max_corrections": self.max_corrections,
            "max_candidate_attempts": self.max_candidate_attempts,
            "max_repeated_offset_attempts": self.max_repeated_offset_attempts,
        }


@dataclass(frozen=True, slots=True)
class CandidateAttempt:
    rank: int
    ranked_candidate: RankedCandidate
    validation: CandidateValidation | None
    accepted: bool
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "ranked_candidate": self.ranked_candidate.to_dict(),
            "validation": self.validation.to_dict() if self.validation else None,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
        }


@dataclass(frozen=True, slots=True)
class LLMFallbackRecord:
    attempted: bool
    available: bool
    model: str
    suggestion: LLMSuggestion | None = None
    candidate: CorrectionCandidate | None = None
    validation: CandidateValidation | None = None
    accepted: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "available": self.available,
            "model": self.model,
            "suggestion": self.suggestion.to_dict() if self.suggestion else None,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "validation": self.validation.to_dict() if self.validation else None,
            "accepted": self.accepted,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class AmbiguitySelectionRecord:
    attempted: bool
    available: bool
    model: str
    selected_candidate_id: str | None = None
    confidence: float | None = None
    reason: str | None = None
    selected_candidate: CorrectionCandidate | None = None
    validation: CandidateValidation | None = None
    accepted: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "available": self.available,
            "model": self.model,
            "selected_candidate_id": self.selected_candidate_id,
            "confidence": self.confidence,
            "reason": self.reason,
            "selected_candidate": (
                self.selected_candidate.to_dict() if self.selected_candidate else None
            ),
            "validation": self.validation.to_dict() if self.validation else None,
            "accepted": self.accepted,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class CorrectionHistoryEntry:
    sequence: int
    status: CorrectionStatus
    diagnostic: SyntaxDiagnostic
    prediction: ErrorPrediction
    selected_candidate: CorrectionCandidate | None
    candidate_rank: int | None
    candidate_probability: float | None
    before_snippet: str
    after_snippet: str | None
    source_offset: int
    validation: CandidateValidation | None
    attempts: tuple[CandidateAttempt, ...] = ()
    reason: str | None = None
    llm_fallback: LLMFallbackRecord | None = None
    ambiguity_selection: AmbiguitySelectionRecord | None = None

    @property
    def applied(self) -> bool:
        return self.status is CorrectionStatus.APPLIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "status": self.status.value,
            "applied": self.applied,
            "diagnostic_id": self.diagnostic.diagnostic_id,
            "original_error": self.diagnostic.to_dict(),
            "prediction": self.prediction.to_dict(),
            "selected_candidate": (
                self.selected_candidate.to_dict() if self.selected_candidate else None
            ),
            "candidate_rank": self.candidate_rank,
            "candidate_probability": self.candidate_probability,
            "before_snippet": self.before_snippet,
            "after_snippet": self.after_snippet,
            "source_offset": self.source_offset,
            "validation": self.validation.to_dict() if self.validation else None,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "reason": self.reason,
            "llm_fallback": self.llm_fallback.to_dict() if self.llm_fallback else None,
            "ambiguity_selection": (
                self.ambiguity_selection.to_dict() if self.ambiguity_selection else None
            ),
        }


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    original_source: str
    corrected_source: str
    success: bool
    fully_syntactically_valid: bool
    corrections_applied: int
    unresolved_diagnostics: tuple[SyntaxDiagnostic, ...]
    history: tuple[CorrectionHistoryEntry, ...]
    predictions: tuple[ErrorPrediction, ...]
    semantic_diagnostics: tuple[SemanticDiagnostic, ...]
    needs_llm_fallback: bool
    stop_reason: str
    policy: CorrectionPolicy

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_source": self.original_source,
            "corrected_source": self.corrected_source,
            "success": self.success,
            "fully_syntactically_valid": self.fully_syntactically_valid,
            "corrections_applied": self.corrections_applied,
            "unresolved_diagnostics": [item.to_dict() for item in self.unresolved_diagnostics],
            "history": [item.to_dict() for item in self.history],
            "predictions": [item.to_dict() for item in self.predictions],
            "semantic_diagnostics": [item.to_dict() for item in self.semantic_diagnostics],
            "needs_llm_fallback": self.needs_llm_fallback,
            "stop_reason": self.stop_reason,
            "policy": self.policy.to_dict(),
        }


class CorrectionOrchestrator:
    def __init__(
        self,
        predictor: AIErrorPredictor,
        policy: CorrectionPolicy | None = None,
        llm_fallback: LLMFallbackService | None = None,
    ) -> None:
        self.predictor = predictor
        self.policy = policy or CorrectionPolicy()
        self.llm_fallback = llm_fallback

    def correct(self, source: str, *, auto_apply: bool = True) -> CorrectionResult:
        current = source
        history: list[CorrectionHistoryEntry] = []
        predictions: list[ErrorPrediction] = []
        seen_sources = {source}
        repeated_locations: dict[tuple[int, str | None, str | None], int] = {}
        corrections = 0
        needs_llm = False
        stop_reason = "source_is_syntactically_valid"

        while True:
            baseline = parse(current)
            if baseline.valid:
                stop_reason = "source_is_syntactically_valid"
                break
            if baseline.lexical_errors:
                stop_reason = "lexical_errors_make_automatic_correction_unsafe"
                needs_llm = True
                break
            if not baseline.syntax_errors:
                stop_reason = "parser_could_not_produce_a_recoverable_diagnostic"
                needs_llm = True
                break
            if corrections >= self.policy.max_corrections:
                stop_reason = "maximum_correction_count_reached"
                needs_llm = True
                break

            diagnostic = baseline.syntax_errors[0]
            location_key = (
                diagnostic.span.start.offset,
                diagnostic.unexpected_token,
                diagnostic.grammar_context,
            )
            repeated_locations[location_key] = repeated_locations.get(location_key, 0) + 1
            if repeated_locations[location_key] > self.policy.max_repeated_offset_attempts:
                stop_reason = "repeated_diagnostic_without_safe_progress"
                needs_llm = True
                break

            context = ErrorContext.from_diagnostic(diagnostic, baseline.tokens, current)
            prediction = self.predictor.predict_error_type(context)
            predictions.append(prediction)
            ranked = rank_candidates(
                diagnostic.correction_candidates,
                prediction,
                context=context,
            )
            before_snippet = _snippet(current, diagnostic.span.start.offset)

            if not ranked:
                fallback = self._try_llm_fallback(
                    current, baseline, diagnostic, context, prediction, seen_sources
                ) if auto_apply else None
                if fallback is not None and fallback.accepted:
                    history.append(
                        self._fallback_applied_entry(
                            history, diagnostic, prediction, before_snippet, fallback
                        )
                    )
                    current = fallback.validation.corrected_source
                    seen_sources.add(current)
                    corrections += 1
                    continue
                history.append(
                    self._unresolved_entry(
                        history,
                        diagnostic,
                        prediction,
                        before_snippet,
                        "no_safe_candidate",
                        llm_fallback=fallback,
                    )
                )
                stop_reason = "no_safe_candidate"
                needs_llm = True
                break

            attempts: list[CandidateAttempt] = []
            progressing: list[tuple[int, RankedCandidate, CandidateValidation]] = []
            for rank, ranked_item in enumerate(
                ranked[: self.policy.max_candidate_attempts], start=1
            ):
                prepared = _prepare_candidate(current, ranked_item.candidate)
                scored = replace(
                    prepared,
                    score=ranked_item.compatibility_score,
                )
                validation = validate_candidate(
                    current,
                    scored,
                    target_diagnostic=diagnostic,
                    baseline_result=baseline,
                )
                makes_progress = (
                    validation.relevant_valid
                    and validation.corrected_source != current
                    and validation.corrected_source not in seen_sources
                )
                reason = None if makes_progress else _rejection_reason(validation, current, seen_sources)
                attempts.append(
                    CandidateAttempt(rank, ranked_item, validation, makes_progress, reason)
                )
                if makes_progress:
                    progressing.append((rank, ranked_item, validation))

            if not progressing:
                fallback = self._try_llm_fallback(
                    current, baseline, diagnostic, context, prediction, seen_sources
                ) if auto_apply else None
                if fallback is not None and fallback.accepted:
                    history.append(
                        self._fallback_applied_entry(
                            history,
                            diagnostic,
                            prediction,
                            before_snippet,
                            fallback,
                            attempts=tuple(attempts),
                        )
                    )
                    current = fallback.validation.corrected_source
                    seen_sources.add(current)
                    corrections += 1
                    continue
                history.append(
                    CorrectionHistoryEntry(
                        sequence=len(history) + 1,
                        status=CorrectionStatus.UNRESOLVED,
                        diagnostic=diagnostic,
                        prediction=prediction,
                        selected_candidate=None,
                        candidate_rank=None,
                        candidate_probability=None,
                        before_snippet=before_snippet,
                        after_snippet=None,
                        source_offset=diagnostic.span.start.offset,
                        validation=None,
                        attempts=tuple(attempts),
                        reason="no_candidate_passed_parser_validation",
                        llm_fallback=fallback,
                    )
                )
                stop_reason = "no_candidate_passed_parser_validation"
                needs_llm = True
                break

            whole_program_repairs = [
                item for item in progressing if item[2].valid
            ]
            eligible = whole_program_repairs or progressing
            distinct_repairs: dict[str, tuple[int, RankedCandidate, CandidateValidation]] = {}
            for item in eligible:
                distinct_repairs.setdefault(item[2].corrected_source, item)
            choices = list(distinct_repairs.values())

            predicted_choices = [
                item
                for item in choices
                if item[1].matched_class == prediction.label
            ]
            if len(choices) > 1 and len(predicted_choices) != 1:
                ambiguity = (
                    self._try_ambiguity_selection(
                        current,
                        baseline,
                        diagnostic,
                        context,
                        choices,
                        seen_sources,
                    )
                    if auto_apply
                    else None
                )
                if ambiguity is not None and ambiguity.accepted:
                    assert ambiguity.selected_candidate is not None
                    assert ambiguity.validation is not None
                    selected_choice = next(
                        item
                        for item in choices
                        if item[2].candidate.id == ambiguity.selected_candidate_id
                    )
                    rank, ranked_item, _ = selected_choice
                    history.append(
                        CorrectionHistoryEntry(
                            sequence=len(history) + 1,
                            status=CorrectionStatus.APPLIED,
                            diagnostic=diagnostic,
                            prediction=prediction,
                            selected_candidate=ambiguity.selected_candidate,
                            candidate_rank=rank,
                            candidate_probability=ranked_item.compatibility_score,
                            before_snippet=before_snippet,
                            after_snippet=_snippet(
                                ambiguity.validation.corrected_source,
                                ambiguity.selected_candidate.offset,
                            ),
                            source_offset=ambiguity.selected_candidate.offset,
                            validation=ambiguity.validation,
                            attempts=tuple(attempts),
                            reason="ambiguity_selection_groq_parser_validated",
                            ambiguity_selection=ambiguity,
                        )
                    )
                    current = ambiguity.validation.corrected_source
                    seen_sources.add(current)
                    corrections += 1
                    continue
                history.append(
                    CorrectionHistoryEntry(
                        sequence=len(history) + 1,
                        status=CorrectionStatus.UNRESOLVED,
                        diagnostic=diagnostic,
                        prediction=prediction,
                        selected_candidate=None,
                        candidate_rank=None,
                        candidate_probability=None,
                        before_snippet=before_snippet,
                        after_snippet=None,
                        source_offset=diagnostic.span.start.offset,
                        validation=None,
                        attempts=tuple(attempts),
                        reason=(
                            "ambiguity_selection_unresolved"
                            if ambiguity is not None
                            else "ambiguous_valid_candidates_without_reliable_model_preference"
                        ),
                        ambiguity_selection=ambiguity,
                    )
                )
                stop_reason = "ambiguous_valid_candidates"
                needs_llm = True
                break

            selected = predicted_choices[0] if len(predicted_choices) == 1 else choices[0]

            rank, ranked_item, validation = selected
            selected_candidate = validation.candidate
            deterministic_compiler_edit = (
                len(ranked) == 1
                and ranked_item.matched_class is not None
                and selected_candidate.origin == "traditional_recovery"
                and validation.relevant_valid
            )

            # A unique compiler-generated edit that resolves the diagnostic is
            # authoritative. The classifier still ranks and explains it, but an
            # unrelated/low model class must not discard deterministic parser
            # recovery or trigger an unnecessary remote fallback.
            if (
                prediction.confidence < self.policy.llm_fallback_threshold
                and not deterministic_compiler_edit
            ):
                fallback = (
                    self._try_llm_fallback(
                        current,
                        baseline,
                        diagnostic,
                        context,
                        prediction,
                        seen_sources,
                    )
                    if auto_apply
                    else None
                )
                if fallback is not None and fallback.accepted:
                    history.append(
                        self._fallback_applied_entry(
                            history,
                            diagnostic,
                            prediction,
                            before_snippet,
                            fallback,
                            attempts=tuple(attempts),
                        )
                    )
                    current = fallback.validation.corrected_source
                    seen_sources.add(current)
                    corrections += 1
                    continue
                history.append(
                    self._unresolved_entry(
                        history,
                        diagnostic,
                        prediction,
                        before_snippet,
                        "prediction_below_fallback_threshold",
                        ranked[0],
                        llm_fallback=fallback,
                    )
                )
                stop_reason = "low_confidence_unresolved"
                needs_llm = True
                break

            should_suggest = not auto_apply or (
                prediction.confidence < self.policy.auto_apply_threshold
                and not deterministic_compiler_edit
            )
            if should_suggest:
                history.append(
                    CorrectionHistoryEntry(
                        sequence=len(history) + 1,
                        status=CorrectionStatus.SUGGESTED,
                        diagnostic=diagnostic,
                        prediction=prediction,
                        selected_candidate=selected_candidate,
                        candidate_rank=rank,
                        candidate_probability=ranked_item.compatibility_score,
                        before_snippet=before_snippet,
                        after_snippet=_snippet(
                            validation.corrected_source, selected_candidate.offset
                        ),
                        source_offset=selected_candidate.offset,
                        validation=validation,
                        attempts=tuple(attempts),
                        reason=(
                            "suggestion_only_mode"
                            if not auto_apply
                            else "prediction_below_auto_apply_threshold"
                        ),
                    )
                )
                stop_reason = "suggestion_returned_without_source_mutation"
                break

            history.append(
                CorrectionHistoryEntry(
                    sequence=len(history) + 1,
                    status=CorrectionStatus.APPLIED,
                    diagnostic=diagnostic,
                    prediction=prediction,
                    selected_candidate=selected_candidate,
                    candidate_rank=rank,
                    candidate_probability=ranked_item.compatibility_score,
                    before_snippet=before_snippet,
                    after_snippet=_snippet(
                        validation.corrected_source, selected_candidate.offset
                    ),
                    source_offset=selected_candidate.offset,
                    validation=validation,
                    attempts=tuple(attempts),
                    reason=(
                        "unique_compiler_candidate_parser_validated"
                        if deterministic_compiler_edit
                        and prediction.confidence < self.policy.auto_apply_threshold
                        else "high_confidence_and_parser_validated"
                    ),
                )
            )
            current = validation.corrected_source
            seen_sources.add(current)
            corrections += 1

        final_parse = parse(current)
        semantic_diagnostics: tuple[SemanticDiagnostic, ...] = ()
        if final_parse.valid:
            semantic = analyze_source_semantics(current).semantic_result
            if semantic is not None:
                semantic_diagnostics = tuple(semantic.diagnostics)
        return CorrectionResult(
            original_source=source,
            corrected_source=current,
            success=final_parse.valid,
            fully_syntactically_valid=final_parse.valid,
            corrections_applied=corrections,
            unresolved_diagnostics=tuple(final_parse.syntax_errors),
            history=tuple(history),
            predictions=tuple(predictions),
            semantic_diagnostics=semantic_diagnostics,
            needs_llm_fallback=needs_llm,
            stop_reason=stop_reason,
            policy=self.policy,
        )

    @staticmethod
    def _unresolved_entry(
        history: list[CorrectionHistoryEntry],
        diagnostic: SyntaxDiagnostic,
        prediction: ErrorPrediction,
        before_snippet: str,
        reason: str,
        ranked: RankedCandidate | None = None,
        *,
        llm_fallback: LLMFallbackRecord | None = None,
    ) -> CorrectionHistoryEntry:
        return CorrectionHistoryEntry(
            sequence=len(history) + 1,
            status=CorrectionStatus.UNRESOLVED,
            diagnostic=diagnostic,
            prediction=prediction,
            selected_candidate=ranked.candidate if ranked else None,
            candidate_rank=1 if ranked else None,
            candidate_probability=ranked.compatibility_score if ranked else None,
            before_snippet=before_snippet,
            after_snippet=None,
            source_offset=diagnostic.span.start.offset,
            validation=None,
            reason=reason,
            llm_fallback=llm_fallback,
        )

    def _try_llm_fallback(
        self,
        source: str,
        baseline: ParseResult,
        diagnostic: SyntaxDiagnostic,
        context: ErrorContext,
        prediction: ErrorPrediction,
        seen_sources: set[str],
    ) -> LLMFallbackRecord | None:
        if self.llm_fallback is None:
            return None
        result: LLMFallbackResult = self.llm_fallback.suggest(context, prediction)
        record = LLMFallbackRecord(
            attempted=result.attempted,
            available=result.available,
            model=result.model,
            suggestion=result.suggestion,
            error=result.error,
        )
        if result.suggestion is None:
            return record
        try:
            candidate = suggestion_to_candidate(result.suggestion, diagnostic, source)
            validation = validate_candidate(
                source,
                candidate,
                target_diagnostic=diagnostic,
                baseline_result=baseline,
            )
        except ValueError as exc:
            return replace(record, error=f"Unsafe LLM suggestion: {exc}")
        accepted = (
            validation.relevant_valid
            and validation.corrected_source != source
            and validation.corrected_source not in seen_sources
        )
        error = None if accepted else _rejection_reason(validation, source, seen_sources)
        return replace(
            record,
            candidate=validation.candidate,
            validation=validation,
            accepted=accepted,
            error=error,
        )

    def _try_ambiguity_selection(
        self,
        source: str,
        baseline: ParseResult,
        diagnostic: SyntaxDiagnostic,
        context: ErrorContext,
        choices: list[tuple[int, RankedCandidate, CandidateValidation]],
        seen_sources: set[str],
    ) -> AmbiguitySelectionRecord | None:
        if self.llm_fallback is None:
            return None
        selector = getattr(self.llm_fallback, "select_candidate", None)
        if not callable(selector):
            return AmbiguitySelectionRecord(
                attempted=False,
                available=False,
                model=getattr(self.llm_fallback, "model", "unknown"),
                error="Groq ambiguity selection is unavailable",
            )
        result: LLMCandidateSelectionResult = selector(
            source,
            context,
            [item[2] for item in choices],
        )
        selection = result.selection
        record = AmbiguitySelectionRecord(
            attempted=result.attempted,
            available=result.available,
            model=result.model,
            selected_candidate_id=(
                selection.selected_candidate_id if selection else None
            ),
            confidence=selection.confidence if selection else None,
            reason=selection.reason if selection else None,
            error=result.error,
        )
        if selection is None or selection.selected_candidate_id is None:
            return record
        selected = next(
            (
                item
                for item in choices
                if item[2].candidate.id == selection.selected_candidate_id
            ),
            None,
        )
        if selected is None:
            return replace(record, error="Groq selected an unknown candidate ID")
        candidate = selected[2].candidate
        record = replace(record, selected_candidate=candidate)
        if selection.confidence < self.policy.ambiguity_selection_threshold:
            return replace(record, error="Groq selection confidence is below threshold")
        validation = validate_candidate(
            source,
            candidate,
            target_diagnostic=diagnostic,
            baseline_result=baseline,
        )
        accepted = (
            validation.relevant_valid
            and validation.corrected_source != source
            and validation.corrected_source not in seen_sources
        )
        error = None if accepted else _rejection_reason(validation, source, seen_sources)
        return replace(
            record,
            selected_candidate=validation.candidate,
            validation=validation,
            accepted=accepted,
            error=error,
        )

    @staticmethod
    def _fallback_applied_entry(
        history: list[CorrectionHistoryEntry],
        diagnostic: SyntaxDiagnostic,
        prediction: ErrorPrediction,
        before_snippet: str,
        fallback: LLMFallbackRecord,
        *,
        attempts: tuple[CandidateAttempt, ...] = (),
    ) -> CorrectionHistoryEntry:
        assert fallback.candidate is not None and fallback.validation is not None
        return CorrectionHistoryEntry(
            sequence=len(history) + 1,
            status=CorrectionStatus.APPLIED,
            diagnostic=diagnostic,
            prediction=prediction,
            selected_candidate=fallback.candidate,
            candidate_rank=None,
            candidate_probability=None,
            before_snippet=before_snippet,
            after_snippet=_snippet(
                fallback.validation.corrected_source, fallback.candidate.offset
            ),
            source_offset=fallback.candidate.offset,
            validation=fallback.validation,
            attempts=attempts,
            reason="llm_fallback_parser_validated",
            llm_fallback=fallback,
        )


def correct_source(
    source: str,
    *,
    predictor: AIErrorPredictor | None = None,
    model_path: str | Path = Path("models/syntax_error_classifier.joblib"),
    policy: CorrectionPolicy | None = None,
    auto_apply: bool = True,
    llm_fallback: LLMFallbackService | None = None,
) -> CorrectionResult:
    """Convenience entry point used by the CLI and future API layer."""

    active_predictor = predictor or MLCorrectionPredictor.load(model_path)
    return CorrectionOrchestrator(active_predictor, policy, llm_fallback).correct(
        source, auto_apply=auto_apply
    )


def _snippet(source: str, offset: int, radius: int = 70) -> str:
    start = max(0, offset - radius)
    end = min(len(source), offset + radius)
    return source[start:end]


def _prepare_candidate(source: str, candidate: CorrectionCandidate) -> CorrectionCandidate:
    """Place closing punctuation before inter-token whitespace for readable edits.

    Recovery candidates intentionally point at the unexpected token. For a
    missing semicolon or closing delimiter, that token can be on the next line;
    moving only across whitespace preserves token-stream semantics and produces
    conventional source formatting (``x = 1;\n`` rather than ``\n;return``).
    """

    if (
        candidate.action.value != "INSERT"
        or candidate.token_type not in {"SEMICOLON", "RPAREN", "RBRACKET"}
    ):
        return candidate
    offset = candidate.offset
    while offset > 0 and source[offset - 1].isspace():
        offset -= 1
    if offset == candidate.offset:
        return candidate
    prefix = source[:offset]
    line = prefix.count("\n") + 1
    last_newline = prefix.rfind("\n")
    column = offset + 1 if last_newline < 0 else offset - last_newline
    location = SourceLocation(line, column, offset)
    return replace(
        candidate,
        offset=offset,
        span=SourceSpan(location, location),
        reason=candidate.reason + "; insertion normalized before whitespace",
    )


def _rejection_reason(
    validation: CandidateValidation, current: str, seen_sources: set[str]
) -> str:
    if validation.corrected_source == current:
        return "candidate_did_not_change_source"
    if validation.corrected_source in seen_sources:
        return "candidate_repeats_a_previous_source_state"
    if validation.introduced_earlier_error:
        return "candidate_introduced_an_earlier_syntax_error"
    if not validation.target_resolved:
        return "target_diagnostic_was_not_resolved"
    return "candidate_failed_relevant_parser_validation"

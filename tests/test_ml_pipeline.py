from __future__ import annotations

import json
from pathlib import Path

import pytest
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from ai.candidate_ranker import candidate_class, rank_candidates
from ai.dataset_generator import (
    CorrectionClass,
    DatasetRecord,
    SyntheticDatasetGenerator,
    _Mutation,
    class_counts,
    read_jsonl,
    write_jsonl,
)
from ai.error_predictor import MLCorrectionPredictor, build_pipeline, train_classifier
from ai.feature_extraction import edit_distance, extract_features, nearest_keyword
from compiler.correction import CorrectionAction, apply_candidate
from compiler.parser import parse


@pytest.fixture(scope="module")
def records():
    return SyntheticDatasetGenerator(42).generate(90)


@pytest.fixture(scope="module")
def trained(records):
    return train_classifier(records, test_fraction=0.3, random_seed=42)


def record_for(records, label: CorrectionClass):
    return next(record for record in records if record.label == label.value)


def test_valid_source_corruption(records) -> None:
    for record in records:
        assert parse(record.original_source).valid
        assert parse(record.corrupted_source).syntax_errors
        assert apply_candidate(record.corrupted_source, record.ground_truth)


@pytest.mark.parametrize(
    "label,action,token",
    [
        (CorrectionClass.INSERT_SEMICOLON, CorrectionAction.INSERT, "SEMICOLON"),
        (CorrectionClass.INSERT_RPAREN, CorrectionAction.INSERT, "RPAREN"),
        (CorrectionClass.INSERT_LPAREN, CorrectionAction.INSERT, "LPAREN"),
        (CorrectionClass.INSERT_RBRACKET, CorrectionAction.INSERT, "RBRACKET"),
        (CorrectionClass.INSERT_RBRACE, CorrectionAction.INSERT, "RBRACE"),
        (CorrectionClass.DELETE_EXTRA_TOKEN, CorrectionAction.DELETE, "ASSIGN"),
        (CorrectionClass.REPLACE_BRACKET, CorrectionAction.REPLACE, "LPAREN"),
        (CorrectionClass.REPLACE_OPERATOR, CorrectionAction.REPLACE, "GE"),
        (CorrectionClass.CORRECT_KEYWORD, CorrectionAction.REPLACE, "RETURN"),
    ],
)
def test_each_corruption_class(records, label, action, token) -> None:
    record = record_for(records, label)
    assert record.ground_truth.action is action
    assert record.ground_truth.token_type == token
    assert parse(apply_candidate(record.corrupted_source, record.ground_truth)).valid


def test_semicolon_removal_generation(records) -> None:
    record = record_for(records, CorrectionClass.INSERT_SEMICOLON)
    assert record.original_source.count(";") == record.corrupted_source.count(";") + 1


def test_keyword_corruption_does_not_change_lexer_policy(records) -> None:
    record = record_for(records, CorrectionClass.CORRECT_KEYWORD)
    assert "return" not in record.corrupted_source[record.ground_truth.span.start.offset : record.ground_truth.span.end.offset]
    assert record.error_context.previous_tokens[-1].type == "IDENTIFIER"


def test_dataset_record_serialization_round_trip(records) -> None:
    record = records[0]
    restored = DatasetRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert restored.sample_id == record.sample_id
    assert restored.label == record.label
    assert restored.error_context.expected_tokens == record.error_context.expected_tokens
    assert restored.ground_truth == record.ground_truth


def test_jsonl_round_trip(records) -> None:
    path = Path(__file__).parent / ".artifacts" / "data.jsonl"
    try:
        write_jsonl(records[:9], path)
        restored = read_jsonl(path)
        assert len(restored) == 9
        assert [item.label for item in restored] == [item.label for item in records[:9]]
    finally:
        path.unlink(missing_ok=True)


def test_invalid_generated_sample_is_rejected() -> None:
    generator = SyntheticDatasetGenerator()
    mutation = _Mutation(
        original="int main( {",
        corrupted="int main( {",
        label=CorrectionClass.INSERT_SEMICOLON,
        action=CorrectionAction.INSERT,
        token_type="SEMICOLON",
        token_lexeme=";",
        start=0,
        end=0,
        text=";",
    )
    assert generator._validate_mutation(mutation, 1) is None


def test_balanced_class_generation(records) -> None:
    counts = class_counts(records)
    assert set(counts) == {item.value for item in CorrectionClass}
    assert set(counts.values()) == {10}


def test_non_divisible_dataset_is_balanced_within_one() -> None:
    generated = SyntheticDatasetGenerator().generate(20)
    counts = class_counts(generated)
    assert max(counts.values()) - min(counts.values()) <= 1


def test_feature_extraction_from_error_context(records) -> None:
    features = extract_features(records[0].error_context)
    assert features["unexpected_token"]
    assert features["previous_token"]
    assert "paren_depth" in features
    assert all(isinstance(value, (str, int, float)) for value in features.values())


def test_grammar_context_feature(records) -> None:
    record = record_for(records, CorrectionClass.INSERT_RPAREN)
    assert extract_features(record.error_context)["grammar_context"] == "if_condition"


def test_expected_token_features(records) -> None:
    record = record_for(records, CorrectionClass.INSERT_RBRACKET)
    features = extract_features(record.error_context)
    assert features["expects_rbracket"] == 1
    assert "RBRACKET" in features["expected_signature"]


def test_delimiter_depth_features(records) -> None:
    record = record_for(records, CorrectionClass.INSERT_RPAREN)
    features = extract_features(record.error_context)
    assert features["paren_depth"] == 1
    assert features["brace_depth"] >= 1


def test_edit_distance() -> None:
    assert edit_distance("retrun", "return") == 2
    assert edit_distance("whille", "while") == 1
    assert edit_distance("innt", "int") == 1


def test_nearest_keyword_feature(records) -> None:
    record = record_for(records, CorrectionClass.CORRECT_KEYWORD)
    similarity = nearest_keyword(record.error_context)
    assert similarity.keyword == "return"
    assert similarity.distance <= 2
    assert similarity.token_position.startswith("previous")


def test_preprocessing_pipeline_structure() -> None:
    pipeline = build_pipeline()
    assert isinstance(pipeline.named_steps["features"], DictVectorizer)
    assert isinstance(pipeline.named_steps["classifier"], LogisticRegression)


def test_model_training(trained) -> None:
    predictor, report = trained
    assert isinstance(predictor, MLCorrectionPredictor)
    assert report.train_size + report.test_size == 90
    assert len(report.classes) == len(CorrectionClass)
    assert report.accuracy >= 0.8


def test_model_prediction_and_confidence(records, trained) -> None:
    predictor, _ = trained
    record = record_for(records, CorrectionClass.INSERT_RPAREN)
    prediction = predictor.predict(record.error_context)
    assert prediction.label == CorrectionClass.INSERT_RPAREN.value
    assert 0.0 <= prediction.confidence <= 1.0
    assert prediction.confidence == prediction.probabilities[prediction.label]


def test_probability_distribution(records, trained) -> None:
    predictor, _ = trained
    prediction = predictor.predict(records[-1].error_context)
    assert set(prediction.probabilities) == {item.value for item in CorrectionClass}
    assert sum(prediction.probabilities.values()) == pytest.approx(1.0)


def test_model_save_and_load(records, trained) -> None:
    predictor, _ = trained
    path = Path(__file__).parent / ".artifacts" / "classifier.joblib"
    try:
        predictor.save(path)
        loaded = MLCorrectionPredictor.load(path)
        before = predictor.predict(records[3].error_context)
        after = loaded.predict(records[3].error_context)
        assert after.label == before.label
        assert after.probabilities == pytest.approx(before.probabilities)
    finally:
        path.unlink(missing_ok=True)


def test_deterministic_train_test_metrics(records) -> None:
    _, first = train_classifier(records, test_fraction=0.3, random_seed=17)
    _, second = train_classifier(records, test_fraction=0.3, random_seed=17)
    assert first.to_dict() == second.to_dict()


def test_classifier_predicts_unseen_example(trained) -> None:
    predictor, _ = trained
    generator = SyntheticDatasetGenerator(99)
    mutation = generator._mutation(CorrectionClass.REPLACE_BRACKET, 999)
    record = generator._validate_mutation(mutation, 999)
    assert record is not None
    assert predictor.predict(record.error_context).label == CorrectionClass.REPLACE_BRACKET.value


def test_candidate_ranking_boundary(records, trained) -> None:
    predictor, _ = trained
    record = record_for(records, CorrectionClass.INSERT_RPAREN)
    prediction = predictor.predict(record.error_context)
    ranked = rank_candidates(record.correction_candidates, prediction)
    assert ranked
    assert ranked[0].matched_class == CorrectionClass.INSERT_RPAREN.value
    assert ranked[0].compatibility_score == prediction.probabilities[CorrectionClass.INSERT_RPAREN.value]


def test_candidate_class_mapping(records) -> None:
    for record in records[:9]:
        matches = [
            candidate_class(candidate)
            for candidate in record.correction_candidates
            if candidate_class(candidate) == record.label
        ]
        assert matches


def test_training_report_has_per_class_metrics(trained) -> None:
    _, report = trained
    for label in report.classes:
        assert {"precision", "recall", "f1-score", "support"} <= set(
            report.classification_report[label]
        )
    assert len(report.confusion_matrix) == len(CorrectionClass)


def test_compiler_valid_behavior_remains_unchanged() -> None:
    result = parse("int main(){int x=1; return x;}")
    assert result.valid
    assert result.ast is not None and result.ast.functions[0].name == "main"


def test_parser_recovery_behavior_remains_available() -> None:
    result = parse("int main(){if (true {return 0;} }")
    assert result.syntax_errors
    assert result.syntax_errors[0].correction_candidates

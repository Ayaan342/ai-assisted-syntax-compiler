"""Scikit-learn correction classifier and persistence API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

import joblib
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from .error_context import ErrorContext
from .feature_extraction import extract_feature_rows, extract_features


@dataclass(frozen=True, slots=True)
class ErrorPrediction:
    label: str
    confidence: float
    probabilities: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "probabilities": dict(self.probabilities),
        }


@dataclass(frozen=True, slots=True)
class TrainingReport:
    train_size: int
    test_size: int
    random_seed: int
    accuracy: float
    classes: tuple[str, ...]
    classification_report: dict[str, Any]
    confusion_matrix: list[list[int]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "train_size": self.train_size,
            "test_size": self.test_size,
            "random_seed": self.random_seed,
            "accuracy": self.accuracy,
            "classes": list(self.classes),
            "classification_report": self.classification_report,
            "confusion_matrix": self.confusion_matrix,
        }


class AIErrorPredictor(Protocol):
    def predict_error_type(self, context: ErrorContext) -> ErrorPrediction:
        """Predict a correction category from compiler-produced context."""
        ...


class MLCorrectionPredictor:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline

    def predict(self, context: ErrorContext) -> ErrorPrediction:
        row = extract_features(context)
        label = str(self.pipeline.predict([row])[0])
        probabilities_array = self.pipeline.predict_proba([row])[0]
        classifier = self.pipeline.named_steps["classifier"]
        probabilities = {
            str(class_name): float(probability)
            for class_name, probability in zip(classifier.classes_, probabilities_array)
        }
        return ErrorPrediction(label, probabilities[label], probabilities)

    def predict_error_type(self, context: ErrorContext) -> ErrorPrediction:
        return self.predict(context)

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, destination)
        return destination

    @classmethod
    def load(cls, path: str | Path) -> MLCorrectionPredictor:
        pipeline = joblib.load(Path(path))
        if not isinstance(pipeline, Pipeline):
            raise TypeError("Saved artifact is not a Scikit-learn Pipeline")
        return cls(pipeline)


def build_pipeline(random_seed: int = 42) -> Pipeline:
    return Pipeline(
        [
            ("features", DictVectorizer(sparse=True)),
            (
                "classifier",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=random_seed,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def train_classifier(
    records: Sequence[Any],
    *,
    test_fraction: float = 0.2,
    random_seed: int = 42,
) -> tuple[MLCorrectionPredictor, TrainingReport]:
    if not records:
        raise ValueError("At least one dataset record is required")
    contexts = [record.error_context for record in records]
    labels = [record.label for record in records]
    if len(set(labels)) < 2:
        raise ValueError("Training requires at least two correction classes")
    rows = extract_feature_rows(contexts)
    x_train, x_test, y_train, y_test = train_test_split(
        rows,
        labels,
        test_size=test_fraction,
        random_state=random_seed,
        stratify=labels,
    )
    pipeline = build_pipeline(random_seed)
    pipeline.fit(x_train, y_train)
    predictions = pipeline.predict(x_test)
    classes = tuple(sorted(set(labels)))
    report = TrainingReport(
        train_size=len(x_train),
        test_size=len(x_test),
        random_seed=random_seed,
        accuracy=float(accuracy_score(y_test, predictions)),
        classes=classes,
        classification_report=classification_report(
            y_test,
            predictions,
            labels=list(classes),
            output_dict=True,
            zero_division=0,
        ),
        confusion_matrix=confusion_matrix(y_test, predictions, labels=list(classes)).tolist(),
    )
    return MLCorrectionPredictor(pipeline), report

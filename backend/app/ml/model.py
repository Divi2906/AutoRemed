
"""Train and evaluate the AutoRemed remediation strategy classifier."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    f1_score,
)
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


CATEGORICAL_FEATURES = [
    "incident_type",
    "severity",
    "metric",
    "strategy_kind",
]

NUMERIC_FEATURES = [
    "value",
    "warning_threshold",
    "critical_threshold",
    "strategy_power",
]

FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TARGET = "verified_recovered"


def load_dataset(csv_path: str | Path) -> tuple[list[dict[str, Any]], list[int], list[str]]:
    """Load experiments and reject malformed or incomplete records."""
    path = Path(csv_path)

    if not path.is_file():
        raise FileNotFoundError(f"Training dataset not found: {path}")

    with path.open("r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    if len(rows) < 12:
        raise ValueError("At least 12 experiment records are required.")

    required = FEATURES + [TARGET]
    missing = [column for column in required if column not in rows[0]]

    if missing:
        raise ValueError(f"Dataset is missing columns: {missing}")

    samples = []
    labels = []
    groups = []

    for index, row in enumerate(rows):
        try:
            sample = {name: row[name] for name in CATEGORICAL_FEATURES}
            numeric_values = {}
            for name in NUMERIC_FEATURES:
                raw_value = row[name]

                if name == "value" and row["metric"] == "service":
                    numeric_values[name] = (
                        1.0 if raw_value == "degraded"
                        else 2.0 if raw_value == "failed"
                        else 0.0
                    )
                else:
                    numeric_values[name] = (
                        float(raw_value) if raw_value else float("nan")
                    )

            sample.update(numeric_values)
            label = int(row[TARGET])

            if label not in (0, 1):
                raise ValueError("Target must be 0 or 1.")

            samples.append(sample)
            labels.append(label)

            # Strategies tested against the same starting condition
            # must remain together during cross-validation.
            groups.append(
                f"{row['incident_type']}|{row['metric']}|{row['value']}"
            )

        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid experiment record at CSV row {index + 2}: {exc}"
            ) from exc

    return samples, labels, groups



def build_pipeline() -> Pipeline:
    """Create a preprocessing and classification pipeline."""
    preprocessing = ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                CATEGORICAL_FEATURES,
            ),
            ("numeric", "passthrough", NUMERIC_FEATURES),
        ]
    )

    classifier = RandomForestClassifier(
        n_estimators=100,
        max_depth=4,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
    )

    return Pipeline([
        ("preprocessing", preprocessing),
        ("classifier", classifier),
    ])


def train_and_evaluate(
    csv_path: str | Path,
    model_path: str | Path,
) -> dict[str, Any]:
    """Evaluate with grouped cross-validation, then train the final model."""
    samples, labels, groups = load_dataset(csv_path)

    unique_groups = len(set(groups))
    if unique_groups < 2:
        raise ValueError("At least two distinct starting conditions are required.")

    folds = min(5, unique_groups)
    cross_validator = GroupKFold(n_splits=folds)

    pipeline = build_pipeline()
    import pandas as pd
    feature_data = pd.DataFrame(samples, columns=FEATURES)
    predictions = cross_val_predict(
        pipeline,
        feature_data,
        labels,
        groups=groups,
        cv=cross_validator,
    )

    metrics = {
        "samples": len(samples),
        "groups": unique_groups,
        "folds": folds,
        "accuracy": round(float(accuracy_score(labels, predictions)), 4),
        "balanced_accuracy": round(
            float(balanced_accuracy_score(labels, predictions)), 4
        ),
        "f1": round(float(f1_score(labels, predictions, zero_division=0)), 4),
        "classification_report": classification_report(
            labels,
            predictions,
            labels=[0, 1],
            target_names=["not_recovered", "recovered"],
            zero_division=0,
            output_dict=True,
        ),
    }

    # Fit the final model on all available experiments after evaluation.
    pipeline.fit(feature_data, labels)

    destination = Path(model_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump({
        "model": pipeline,
        "features": FEATURES,
        "target": TARGET,
        "model_version": 1,
        "training_samples": len(samples),
    }, destination)

    metrics["model_path"] = str(destination)
    return metrics

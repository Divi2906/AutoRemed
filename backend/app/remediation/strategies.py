

"""Remediation strategy catalog, ML ranker, and explainable selector."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import joblib
import pandas as pd

SAFE_NOTE = (
    "Simulated action: affects only AutoRemed's simulation state, "
    "never the real host."
)

logger = logging.getLogger("autoremed")


@dataclass(frozen=True)
class Strategy:
    name: str
    incident_type: str
    action: str
    description: str
    expected_outcome: str
    power: float
    fixes_states: tuple[str, ...] = ()
    kind: str = "corrective"


CATALOG: dict[str, tuple[Strategy, ...]] = {
    "high_cpu": (
        Strategy(
            "process_analysis", "high_cpu", "analyze_processes",
            "Profile the simulated process table to find CPU hogs.",
            "Identifies heavy processes; small CPU reduction",
            10, kind="diagnostic",
        ),
        Strategy(
            "workload_reduction", "high_cpu", "throttle_workload",
            "Throttle simulated low-priority workloads.",
            "Moderate CPU reduction", 35,
        ),
        Strategy(
            "cpu_optimization_simulation", "high_cpu", "optimize_cpu",
            "Rebalance simulated workloads.",
            "Large CPU reduction", 55,
        ),
    ),
    "high_memory": (
        Strategy(
            "memory_analysis", "high_memory", "analyze_memory",
            "Inspect simulated memory consumers.",
            "Identifies memory consumers; small memory reduction",
            8, kind="diagnostic",
        ),
        Strategy(
            "cache_optimization", "high_memory", "optimize_cache",
            "Trim simulated in-memory caches.",
            "Moderate memory reduction", 30,
        ),
        Strategy(
            "memory_recovery_simulation", "high_memory", "recover_memory",
            "Reclaim simulated memory from idle workloads.",
            "Large memory reduction", 50,
        ),
    ),
    "high_disk": (
        Strategy(
            "disk_analysis", "high_disk", "analyze_disk",
            "Scan the simulated volume for large directories.",
            "Identifies space consumers; small disk reduction",
            5, kind="diagnostic",
        ),
        Strategy(
            "temp_file_cleanup_simulation", "high_disk",
            "cleanup_temp_files",
            "Delete simulated temporary files.",
            "Moderate disk reduction", 20,
        ),
        Strategy(
            "cache_cleanup_simulation", "high_disk", "cleanup_cache",
            "Purge simulated application caches.",
            "Large disk reduction", 30,
        ),
    ),
    "service_failure": (
        Strategy(
            "service_health_check", "service_failure",
            "check_service_health",
            "Run the simulated service health check.",
            "Service returns to running if merely degraded",
            1, ("degraded",), "diagnostic",
        ),
        Strategy(
            "service_recovery_simulation", "service_failure",
            "recover_service",
            "Run the simulated service recovery procedure.",
            "Service returns to running", 2,
            ("degraded", "failed"),
        ),
        Strategy(
            "service_restart_simulation", "service_failure",
            "restart_service",
            "Restart the simulated service.",
            "Service returns to running", 3,
            ("degraded", "failed"),
        ),
    ),
}


def get_strategy(name: str) -> Strategy:
    for group in CATALOG.values():
        for strategy in group:
            if strategy.name == name:
                return strategy
    raise KeyError(name)


@dataclass
class AttemptRecord:
    attempt: int
    strategy: str
    execution_status: str
    verification_result: str | None
    failure_reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


@dataclass
class SelectionContext:
    incident_type: str
    severity: str
    environment: str
    metric: str
    value: float | str
    warning_threshold: float | None
    critical_threshold: float | None
    attempt: int
    history: list[AttemptRecord] = field(default_factory=list)


@dataclass
class RankedStrategy:
    strategy: Strategy
    score: float
    rationale: str


class StrategyRanker(Protocol):
    kind: str
    trained: bool

    def rank(self, ctx: SelectionContext) -> list[RankedStrategy]: ...


class RuleBasedRanker:
    """Deterministic fallback strategy ranker."""

    kind = "rule_based"
    trained = False

    def _needed(self, ctx: SelectionContext) -> float:
        if ctx.metric == "service" or ctx.warning_threshold is None:
            return 0.0
        return max(
            0.0,
            float(ctx.value) - (ctx.warning_threshold - 5.0),
        )

    def _sufficient(self, strategy: Strategy, ctx: SelectionContext) -> bool:
        if ctx.metric == "service":
            return str(ctx.value) in strategy.fixes_states
        return strategy.power >= self._needed(ctx)

    def rank(self, ctx: SelectionContext) -> list[RankedStrategy]:
        tried = {record.strategy for record in ctx.history}
        candidates = [
            strategy
            for strategy in CATALOG[ctx.incident_type]
            if strategy.name not in tried
        ]

        exhausted = not candidates
        if exhausted:
            candidates = list(CATALOG[ctx.incident_type])

        sufficient = sorted(
            [s for s in candidates if self._sufficient(s, ctx)],
            key=lambda s: s.power,
        )
        insufficient = sorted(
            [s for s in candidates if not self._sufficient(s, ctx)],
            key=lambda s: -s.power,
        )

        needed = self._needed(ctx)
        ranked = []

        for index, strategy in enumerate(sufficient):
            reason = (
                "Least-invasive untried strategy expected to be sufficient"
                if index == 0
                else "Sufficient but more invasive than the preferred option"
            )
            if ctx.metric != "service":
                reason += (
                    f"; expected relief {strategy.power:.0f} points "
                    f"versus approximately {needed:.0f} needed"
                )
            ranked.append(
                RankedStrategy(strategy, 100.0 - index, reason)
            )

        for index, strategy in enumerate(insufficient):
            ranked.append(
                RankedStrategy(
                    strategy,
                    50.0 - index,
                    "Not expected to be sufficient alone; ranked by strength",
                )
            )

        if exhausted and ranked:
            ranked[0].rationale = (
                "All strategies were tried; repeating the most promising one. "
                + ranked[0].rationale
            )

        return ranked


class ModelUnavailable(RuntimeError):
    pass


class MLStrategyRanker:
    """Ranks catalog strategies using a trained recovery-probability model."""

    kind = "ml"
    trained = True

    # This order must match the saved training artifact.
    FEATURES = [
        "incident_type",
        "severity",
        "metric",
        "strategy_kind",
        "value",
        "warning_threshold",
        "critical_threshold",
        "strategy_power",
    ]

    def __init__(self, model_path: str | None):
        if not model_path or not os.path.isfile(model_path):
            raise ModelUnavailable(
                f"model artifact not found: {model_path}"
            )

        try:
            artifact = joblib.load(model_path)

            if not isinstance(artifact, dict):
                raise ModelUnavailable("invalid model artifact format")

            self.model = artifact["model"]
            self.features = artifact["features"]

            if self.features != self.FEATURES:
                raise ModelUnavailable(
                    "model feature schema does not match ranker"
                )

            if not hasattr(self.model, "predict_proba"):
                raise ModelUnavailable(
                    "loaded model does not support probability predictions"
                )

        except ModelUnavailable:
            raise
        except Exception as exc:
            raise ModelUnavailable(
                f"model could not be loaded: {exc}"
            ) from exc

    def _features(
        self,
        strategy: Strategy,
        ctx: SelectionContext,
    ) -> dict[str, Any]:
        if ctx.metric == "service":
            raw_value = str(ctx.value)
            value = (
                1.0 if raw_value == "degraded"
                else 2.0 if raw_value == "failed"
                else 0.0
            )
        else:
            value = float(ctx.value)

        return {
            "incident_type": ctx.incident_type,
            "severity": ctx.severity,
            "metric": ctx.metric,
            "strategy_kind": strategy.kind,
            "value": value,
            "warning_threshold": (
                float(ctx.warning_threshold)
                if ctx.warning_threshold is not None else float("nan")
            ),
            "critical_threshold": (
                float(ctx.critical_threshold)
                if ctx.critical_threshold is not None else float("nan")
            ),
            "strategy_power": float(strategy.power),
        }

    def rank(self, ctx: SelectionContext) -> list[RankedStrategy]:
        candidates = list(CATALOG[ctx.incident_type])

        tried = {record.strategy for record in ctx.history}
        untried = [
            strategy for strategy in candidates
            if strategy.name not in tried
        ]

        exhausted = not untried
        if not exhausted:
            candidates = untried

        try:
            frame = pd.DataFrame(
                [
                    self._features(strategy, ctx)
                    for strategy in candidates
                ],
                columns=self.features,
            )

            probabilities = self.model.predict_proba(frame)
            classes = list(self.model.classes_)

            if 1 not in classes:
                raise ModelUnavailable(
                    "trained model has no recovered class"
                )

            positive_index = classes.index(1)

            scored = []
            for strategy, probability in zip(candidates, probabilities):
                score = float(probability[positive_index]) * 100.0
                rationale = (
                    f"ML model estimates {score:.1f}% probability "
                    "of verified recovery"
                )
                if exhausted:
                    rationale += (
                        "; all strategies were tried, so repetition "
                        "is permitted"
                    )

                scored.append(
                    RankedStrategy(strategy, score, rationale)
                )

            return sorted(
                scored,
                key=lambda item: item.score,
                reverse=True,
            )

        except Exception as exc:
            logger.exception("ML strategy prediction failed")
            raise ModelUnavailable(
                f"ML prediction failed: {exc}"
            ) from exc


def build_ranker(
    kind: str = "rule_based",
    model_path: str | None = None,
) -> tuple[StrategyRanker, str | None]:
    """Build ML ranker or explicitly fall back to deterministic rules."""
    if kind == "ml":
        try:
            return MLStrategyRanker(model_path), None
        except ModelUnavailable as exc:
            return (
                RuleBasedRanker(),
                f"ML ranker unavailable ({exc}); using rule-based ranker",
            )

    return RuleBasedRanker(), None


@dataclass
class StrategyDecision:
    strategy: Strategy
    reason: str
    expected_outcome: str
    attempt: int
    context: dict[str, Any]
    previous_outcomes: list[dict[str, Any]]
    alternatives: list[dict[str, Any]]
    ranker: str


def _describe_prev(record: AttemptRecord) -> str:
    if record.execution_status == "failed":
        return (
            f"attempt {record.attempt} `{record.strategy}` failed "
            f"during execution ({record.failure_reason or 'no detail'})"
        )

    return (
        f"attempt {record.attempt} `{record.strategy}` executed "
        "but verification did not confirm recovery "
        f"({record.failure_reason or 'issue remained'})"
    )


class StrategySelector:
    def __init__(
        self,
        ranker: StrategyRanker,
        note: str | None = None,
    ):
        self.ranker = ranker
        self.note = note

    def select(self, ctx: SelectionContext) -> StrategyDecision:
        try:
            ranked = self.ranker.rank(ctx)
        except Exception as exc:
            logger.exception("Ranker failed; using rule-based fallback")
            self.ranker = RuleBasedRanker()
            self.note = (
                f"ML prediction failed ({exc}); "
                "using rule-based fallback"
            )
            ranked = self.ranker.rank(ctx)

        if not ranked:
            raise RuntimeError(
                f"no strategies available for {ctx.incident_type}"
            )

        top = ranked[0]
        strategy = top.strategy

        labels = {
            "high_cpu": "CPU utilisation",
            "high_memory": "memory utilisation",
            "high_disk": "disk utilisation",
            "service_failure": "service state",
        }

        if ctx.metric == "service":
            condition = (
                f"the service is '{ctx.value}' "
                "(expected 'running')"
            )
        else:
            threshold = (
                ctx.critical_threshold
                if ctx.severity == "critical"
                else ctx.warning_threshold
            )
            condition = (
                f"{labels[ctx.incident_type]} ({float(ctx.value):.1f}%) "
                f"exceeded the {ctx.severity} threshold "
                f"({threshold:.1f}%)"
            )

        parts = [
            f"Selected `{strategy.name}` because {condition}",
            top.rationale,
        ]

        if ctx.history:
            parts.insert(
                1,
                "previous attempts did not confirm recovery",
            )

        reason = "; ".join(parts) + "."

        previous = [
            {
                "attempt": record.attempt,
                "strategy": record.strategy,
                "execution_status": record.execution_status,
                "verification_result": record.verification_result,
                "failure_reason": record.failure_reason,
            }
            for record in ctx.history
        ]

        if ctx.history:
            reason += (
                " Previous outcomes: "
                + "; ".join(
                    _describe_prev(record)
                    for record in ctx.history
                )
                + "."
            )

        return StrategyDecision(
            strategy=strategy,
            reason=reason,
            expected_outcome=strategy.expected_outcome,
            attempt=ctx.attempt,
            context={
                "incident_type": ctx.incident_type,
                "severity": ctx.severity,
                "environment": ctx.environment,
                "metric": ctx.metric,
                "value": ctx.value,
                "warning_threshold": ctx.warning_threshold,
                "critical_threshold": ctx.critical_threshold,
                "note": SAFE_NOTE,
            },
            previous_outcomes=previous,
            alternatives=[
                {
                    "strategy": item.strategy.name,
                    "score": item.score,
                    "rationale": item.rationale,
                }
                for item in ranked[1:]
            ],
            ranker=(
                "ml (trained model)"
                if self.ranker.trained
                else "rule_based (deterministic rules; no trained model)"
            ) + (f" - {self.note}" if self.note else ""),
        )

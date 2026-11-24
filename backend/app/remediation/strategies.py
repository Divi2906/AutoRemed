"""Remediation strategy catalog, ML-compatible ranker interface, and explainable selector.

There is NO trained model in this project (no meaningful historical dataset exists). The only
shipped ranker is ``RuleBasedRanker``; ``MLStrategyRanker`` is an interface placeholder that
refuses to load without a real model artifact, and ``build_ranker`` falls back to the rule-based
ranker while saying so. Nothing here fabricates predictions, accuracy or training metrics.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

SAFE_NOTE = "Simulated action: affects only AutoRemed's simulation state, never the real host."


@dataclass(frozen=True)
class Strategy:
    name: str
    incident_type: str
    action: str
    description: str
    expected_outcome: str
    # Metric incidents: percentage points removed by the default simulation model.
    # Service incidents: ordering only (less invasive = lower).
    power: float
    fixes_states: tuple[str, ...] = ()
    kind: str = "corrective"  # or "diagnostic"


CATALOG: dict[str, tuple[Strategy, ...]] = {
    "high_cpu": (
        Strategy("process_analysis", "high_cpu", "analyze_processes",
                 "Profile the simulated process table to find CPU hogs (diagnostic, minimal relief).",
                 "Identifies heavy processes; small CPU reduction", 10, kind="diagnostic"),
        Strategy("workload_reduction", "high_cpu", "throttle_workload",
                 "Throttle simulated low-priority workloads to shed CPU load.",
                 "Moderate CPU reduction without stopping services", 35),
        Strategy("cpu_optimization_simulation", "high_cpu", "optimize_cpu",
                 "Rebalance and optimise simulated workloads for maximum CPU relief.",
                 "Large CPU reduction", 55),
    ),
    "high_memory": (
        Strategy("memory_analysis", "high_memory", "analyze_memory",
                 "Inspect simulated memory consumers (diagnostic, minimal relief).",
                 "Identifies leaking consumers; small memory reduction", 8, kind="diagnostic"),
        Strategy("cache_optimization", "high_memory", "optimize_cache",
                 "Trim simulated in-memory caches.",
                 "Moderate memory reduction", 30),
        Strategy("memory_recovery_simulation", "high_memory", "recover_memory",
                 "Reclaim simulated memory from idle workloads.",
                 "Large memory reduction", 50),
    ),
    "high_disk": (
        Strategy("disk_analysis", "high_disk", "analyze_disk",
                 "Scan the simulated volume for large directories (diagnostic, minimal relief).",
                 "Identifies space consumers; small disk reduction", 5, kind="diagnostic"),
        Strategy("temp_file_cleanup_simulation", "high_disk", "cleanup_temp_files",
                 "Delete simulated temporary files.",
                 "Moderate disk reduction", 20),
        Strategy("cache_cleanup_simulation", "high_disk", "cleanup_cache",
                 "Purge simulated application caches.",
                 "Large disk reduction", 30),
    ),
    "service_failure": (
        Strategy("service_health_check", "service_failure", "check_service_health",
                 "Run the simulated service health check; recovers a merely degraded service.",
                 "Service returns to running if only degraded", 1, ("degraded",), "diagnostic"),
        Strategy("service_recovery_simulation", "service_failure", "recover_service",
                 "Run the simulated recovery procedure for the service.",
                 "Service returns to running", 2, ("degraded", "failed")),
        Strategy("service_restart_simulation", "service_failure", "restart_service",
                 "Restart the simulated service.",
                 "Service returns to running", 3, ("degraded", "failed")),
    ),
}


def get_strategy(name: str) -> Strategy:
    for group in CATALOG.values():
        for s in group:
            if s.name == name:
                return s
    raise KeyError(name)


@dataclass
class AttemptRecord:
    """What happened on a previous attempt (input to the next selection)."""
    attempt: int
    strategy: str
    execution_status: str            # success | failed
    verification_result: str | None  # recovered | not_recovered | None
    failure_reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


@dataclass
class SelectionContext:
    incident_type: str
    severity: str
    environment: str
    metric: str
    value: float | str           # current live value (after earlier attempts, if any)
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
    kind: str          # "rule_based" | "ml"
    trained: bool      # True only if a real trained model is loaded

    def rank(self, ctx: SelectionContext) -> list[RankedStrategy]: ...


class RuleBasedRanker:
    """Deterministic ranking. Least-invasive strategy that is expected to be sufficient comes first."""

    kind = "rule_based"
    trained = False

    def _needed(self, ctx: SelectionContext) -> float:
        if ctx.metric == "service" or ctx.warning_threshold is None:
            return 0.0
        # Aim 5 points below the warning threshold so recovery has headroom.
        return max(0.0, float(ctx.value) - (ctx.warning_threshold - 5.0))

    def _sufficient(self, s: Strategy, ctx: SelectionContext) -> bool:
        if ctx.metric == "service":
            return str(ctx.value) in s.fixes_states
        return s.power >= self._needed(ctx)

    def rank(self, ctx: SelectionContext) -> list[RankedStrategy]:
        tried = {h.strategy for h in ctx.history}
        candidates = [s for s in CATALOG[ctx.incident_type] if s.name not in tried]
        reasons_exhausted = False
        if not candidates:  # every strategy has been tried: allow a justified repeat (never silent)
            candidates, reasons_exhausted = list(CATALOG[ctx.incident_type]), True
        sufficient = sorted([s for s in candidates if self._sufficient(s, ctx)], key=lambda s: s.power)
        insufficient = sorted([s for s in candidates if not self._sufficient(s, ctx)], key=lambda s: -s.power)
        need = self._needed(ctx)
        ranked: list[RankedStrategy] = []
        for i, s in enumerate(sufficient):
            why = ("least invasive untried strategy expected to be sufficient"
                   if i == 0 else "sufficient but more invasive than the preferred option")
            if ctx.metric != "service":
                why += f" (expected relief ~{s.power:.0f} points vs ~{need:.0f} needed)"
            ranked.append(RankedStrategy(s, 100.0 - i, why))
        for i, s in enumerate(insufficient):
            why = "not expected to be sufficient on its own; ranked by strength"
            ranked.append(RankedStrategy(s, 50.0 - i, why))
        if reasons_exhausted and ranked:
            ranked[0].rationale = "all strategies were already tried; repeating the most promising one: " + ranked[0].rationale
        return ranked


class ModelUnavailable(RuntimeError):
    pass


class MLStrategyRanker:
    """Interface placeholder for a future trained ranker. It cannot be constructed without a model file."""

    kind = "ml"
    trained = True

    def __init__(self, model_path: str | None):
        if not model_path or not os.path.exists(model_path):
            raise ModelUnavailable("no trained model artifact available (no training dataset exists yet)")
        raise ModelUnavailable("model loading is not implemented: no model has ever been trained")

    def rank(self, ctx: SelectionContext) -> list[RankedStrategy]:  # pragma: no cover
        raise ModelUnavailable


def build_ranker(kind: str = "rule_based", model_path: str | None = None) -> tuple[StrategyRanker, str | None]:
    """Return (ranker, note). Falls back to the rule-based ranker, explicitly noting why."""
    if kind == "ml":
        try:
            return MLStrategyRanker(model_path), None
        except ModelUnavailable as exc:
            return RuleBasedRanker(), f"ML ranker unavailable ({exc}); using rule-based ranker"
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


def _describe_prev(h: AttemptRecord) -> str:
    if h.execution_status == "failed":
        return f"attempt {h.attempt} `{h.strategy}` failed during execution ({h.failure_reason or 'no detail'})"
    return (f"attempt {h.attempt} `{h.strategy}` executed but verification did not confirm recovery "
            f"({h.failure_reason or 'issue remained'})")


class StrategySelector:
    def __init__(self, ranker: StrategyRanker, note: str | None = None):
        self.ranker = ranker
        self.note = note

    def select(self, ctx: SelectionContext) -> StrategyDecision:
        ranked = self.ranker.rank(ctx)
        if not ranked:
            raise RuntimeError(f"no strategies available for {ctx.incident_type}")
        top = ranked[0]
        s = top.strategy
        label = {"high_cpu": "CPU utilisation", "high_memory": "memory utilisation",
                 "high_disk": "disk utilisation", "service_failure": "service state"}[ctx.incident_type]
        if ctx.metric == "service":
            cond = f"the service is '{ctx.value}' (expected 'running')"
        else:
            thr = ctx.critical_threshold if ctx.severity == "critical" else ctx.warning_threshold
            cond = (f"{label} ({float(ctx.value):.1f}%) exceeded the {ctx.severity} threshold ({thr:.1f}%)")
        parts = [f"Selected `{s.name}` because {cond}"]
        if ctx.history:
            parts.append("the previous " + ("attempts failed" if len(ctx.history) > 1 else "attempt failed"))
            parts.append(f"this strategy has not yet been attempted" if all(h.strategy != s.name for h in ctx.history)
                         else "all strategies were exhausted")
        parts.append(top.rationale)
        reason = ", and ".join(parts[:-1]) + f"; {parts[-1]}." if len(parts) > 1 else parts[0] + "."
        prev = [{"attempt": h.attempt, "strategy": h.strategy, "execution_status": h.execution_status,
                 "verification_result": h.verification_result, "failure_reason": h.failure_reason}
                for h in ctx.history]
        if ctx.history:
            reason += " Not repeated: " + "; ".join(_describe_prev(h) for h in ctx.history) + "."
        return StrategyDecision(
            strategy=s, reason=reason, expected_outcome=s.expected_outcome, attempt=ctx.attempt,
            context={"incident_type": ctx.incident_type, "severity": ctx.severity, "environment": ctx.environment,
                     "metric": ctx.metric, "value": ctx.value, "warning_threshold": ctx.warning_threshold,
                     "critical_threshold": ctx.critical_threshold, "note": SAFE_NOTE},
            previous_outcomes=prev,
            alternatives=[{"strategy": r.strategy.name, "score": r.score, "rationale": r.rationale}
                          for r in ranked[1:]],
            ranker=("rule_based (deterministic rules; no trained model)" if not self.ranker.trained
                    else "ml (trained model)") + (f" - {self.note}" if self.note else ""),
        )

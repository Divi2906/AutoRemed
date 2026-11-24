"""Interchangeable remediation executors.

* ``SimulationExecutor`` (default) mutates ONLY the application's simulated state.
* ``TestExecutor`` is programmable for unit tests.
* ``RealExecutor`` exists as a placeholder and is permanently disabled: AutoRemed never runs
  shell commands, kills processes, deletes files or restarts services on the real host.

Executors report what they *did*; they never decide whether the incident is resolved
(that is the verifier's job).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..core.errors import ExecutorDisabled, SafetyViolation
from ..core.util import ENV_SIM
from ..simulation.state import BASELINE, SimulationState, StaleEpoch
from .strategies import Strategy

OUTCOMES = ("recover", "exec_fail", "partial", "no_effect")


@dataclass
class ExecutionRequest:
    incident_id: str
    attempt: int
    strategy: Strategy
    environment: str
    metric: str
    warning_threshold: float | None
    epoch: int
    plan_outcome: str | None = None   # scenario-controlled outcome for deterministic demos


@dataclass
class ExecutionResult:
    status: str                       # "success" | "failed"
    message: str
    error: str | None = None


class SimulatedExecutionError(Exception):
    pass


class Executor(Protocol):
    name: str

    def execute(self, req: ExecutionRequest) -> ExecutionResult: ...


def _guard_env(req: ExecutionRequest) -> None:
    if req.environment != ENV_SIM:
        raise SafetyViolation(
            f"refusing to execute '{req.strategy.name}' against environment '{req.environment}': "
            "only the simulation may be remediated")


class SimulationExecutor:
    name = "simulation"

    def __init__(self, sim: SimulationState):
        self.sim = sim

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        _guard_env(req)
        s, metric, epoch = req.strategy, req.metric, req.epoch
        try:
            outcome = req.plan_outcome
            if outcome == "exec_fail":
                raise SimulatedExecutionError(
                    f"simulated executor failure while running '{s.action}' (scenario-controlled)")
            if outcome == "no_effect":
                return ExecutionResult("success", f"{s.action} completed (simulated) but had no effect on state")
            if outcome == "partial":
                self._partial(req)
                return ExecutionResult("success", f"{s.action} completed (simulated) with only partial improvement")
            if outcome == "recover":
                self._full_recovery(req)
                return ExecutionResult("success", f"{s.action} completed (simulated): state restored to healthy range")
            # No scenario plan: default simulation model driven by the strategy's strength.
            self._default_model(req)
            return ExecutionResult("success", f"{s.action} completed (simulated)")
        except SimulatedExecutionError as exc:
            return ExecutionResult("failed", f"{s.action} failed (simulated)", error=str(exc))
        except StaleEpoch as exc:
            return ExecutionResult("failed", f"{s.action} aborted", error=f"{exc}")

    # -- effects (all on simulated state only) --------------------------------------------------
    def _full_recovery(self, req: ExecutionRequest) -> None:
        if req.metric == "service":
            self.sim.set_service("running", req.epoch)
        else:
            self.sim.set_metric(req.metric, BASELINE[req.metric], req.epoch)

    def _partial(self, req: ExecutionRequest) -> None:
        if req.metric == "service":
            self.sim.set_service("degraded", req.epoch)  # still unhealthy
            return
        cur = self.sim.snapshot()[req.metric]
        floor = (req.warning_threshold or 0.0) + 1.0     # stays above the warning threshold
        self.sim.set_metric(req.metric, max(cur - 5.0, floor) if cur > floor else cur, req.epoch)

    def _default_model(self, req: ExecutionRequest) -> None:
        s = req.strategy
        if req.metric == "service":
            cur = self.sim.snapshot()["service_state"]
            if cur in s.fixes_states:
                self.sim.set_service("running", req.epoch)
            return
        self.sim.adjust_metric(req.metric, -s.power, req.epoch)


class TestExecutor:
    """Programmable executor for tests. Each outcome is 'success', 'fail', 'raise' or a callable."""

    __test__ = False  # not a pytest class
    name = "test"

    def __init__(self, outcomes: list[Any] | None = None, effect: Callable[[ExecutionRequest], None] | None = None):
        self.outcomes = list(outcomes or [])
        self.effect = effect
        self.calls: list[ExecutionRequest] = []

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        self.calls.append(req)
        outcome = self.outcomes.pop(0) if self.outcomes else "success"
        if callable(outcome):
            return outcome(req)
        if outcome == "raise":
            raise RuntimeError("test executor exploded")
        if outcome == "fail":
            return ExecutionResult("failed", "test executor failure", error="test failure")
        if self.effect:
            self.effect(req)
        return ExecutionResult("success", "test executor success")


class RealExecutor:
    """Permanently disabled. There is intentionally no code path that touches the real host."""

    name = "real"
    enabled = False

    def execute(self, req: ExecutionRequest) -> ExecutionResult:
        raise ExecutorDisabled("the real executor is disabled: AutoRemed never modifies the real host")


class ExecutorRegistry:
    def __init__(self, default: str = "simulation"):
        self._executors: dict[str, Executor] = {}
        self.default = default

    def register(self, executor: Executor) -> None:
        self._executors[executor.name] = executor

    def get(self, name: str | None = None) -> Executor:
        return self._executors[name or self.default]

    def names(self) -> list[str]:
        return list(self._executors)

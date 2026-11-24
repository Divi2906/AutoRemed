"""Typed request/response schemas for the REST API."""
from __future__ import annotations

from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")
Fault = Literal["cpu", "memory", "disk", "service"]
Environment = Literal["real_host", "simulation"]
PlanOutcome = Literal["recover", "exec_fail", "partial", "no_effect"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ------------------------------------------------------------------ errors / generic
class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(_Out, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------ requests
class ThresholdPair(BaseModel):
    warning: Optional[float] = Field(None, gt=0, le=100)
    critical: Optional[float] = Field(None, gt=0, le=100)


class ThresholdUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu: Optional[ThresholdPair] = None
    memory: Optional[ThresholdPair] = None
    disk: Optional[ThresholdPair] = None


class ModeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["autonomous", "approval"]


class MonitoringUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_seconds: Optional[float] = Field(None, ge=1, le=3600)
    consecutive_violations_real_host: Optional[int] = Field(None, ge=1, le=20)
    consecutive_violations_simulation: Optional[int] = Field(None, ge=1, le=20)


class MonitoringStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_seconds: Optional[float] = Field(None, ge=1, le=3600)


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fault: Fault
    value: Optional[float | Literal["degraded", "failed"]] = None
    plan: Optional[list[PlanOutcome]] = Field(None, max_length=3)
    mode_override: Optional[Literal["autonomous", "approval"]] = None

    @field_validator("value")
    @classmethod
    def _range(cls, v):
        if isinstance(v, float) and not 0 <= v <= 100:
            raise ValueError("value must be between 0 and 100")
        return v


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = Field(min_length=1, max_length=64)
    fault: Fault


class RecoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fault: Fault


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field("operator", min_length=1, max_length=64)
    note: Optional[str] = Field(None, max_length=500)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(None, max_length=500)


# ------------------------------------------------------------------ responses
class IncidentOut(_Out):
    id: str
    fingerprint: str
    type: str
    severity: str
    environment: Environment
    environment_label: str
    metric: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    value_label: Optional[str] = None
    threshold_label: Optional[str] = None
    description: str
    root_cause: Optional[str] = None
    status: str
    is_active: bool
    workflow_state: str
    mode: str
    observe_only: bool
    diagnosis: Optional[dict[str, Any]] = None
    scenario: Optional[dict[str, Any]] = None
    resolution: Optional[str] = None
    resolution_type: Optional[str] = None
    closed_reason: Optional[str] = None
    manual_intervention_required: bool
    recommended_action: Optional[str] = None
    attempts_made: int
    max_attempts: int
    final_state: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str
    resolved_at: Optional[str] = None
    escalated_at: Optional[str] = None


class ExecutionOut(_Out):
    id: str
    incident_id: str
    remediation_id: Optional[str] = None
    environment: str
    action: str
    strategy: str
    executor: str
    attempt: int
    status: str
    started_at: str
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


class VerificationOut(_Out):
    id: str
    incident_id: str
    execution_id: Optional[str] = None
    attempt: int
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    criteria: Optional[dict[str, Any]] = None
    result: str
    failure_reason: Optional[str] = None
    created_at: str


class DecisionOut(_Out):
    id: str
    incident_id: str
    attempt: int
    strategy: str
    reason: str
    expected_outcome: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    previous_outcomes: Optional[list[dict[str, Any]]] = None
    alternatives: Optional[list[dict[str, Any]]] = None
    ranker: str
    created_at: str


class AttemptOut(_Out):
    attempt: int
    strategy: Optional[str] = None
    outcome: str
    decision: Optional[DecisionOut] = None
    execution: Optional[ExecutionOut] = None
    verification: Optional[VerificationOut] = None
    state_before: Optional[dict[str, Any]] = None
    state_after: Optional[dict[str, Any]] = None
    failure_reason: Optional[str] = None
    started_at: Optional[str] = None
    duration_ms: Optional[int] = None
    message: Optional[str] = None


class ApprovalOut(_Out):
    id: str
    remediation_id: str
    incident_id: str
    action: str
    actor: Optional[str] = None
    note: Optional[str] = None
    created_at: str


class ActivityOut(_Out):
    id: int
    ts: str
    event_type: str
    incident_id: Optional[str] = None
    action: Optional[str] = None
    status: Optional[str] = None
    attempt: Optional[int] = None
    environment: Optional[str] = None
    message: str
    details: Optional[Any] = None


class RemediationOut(_Out):
    id: str
    incident_id: str
    mode: str
    approval_state: str
    status: str
    proposed_strategy: Optional[str] = None
    proposal: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    # joined from the incident (list endpoint)
    incident_type: Optional[str] = None
    severity: Optional[str] = None
    environment: Optional[str] = None
    metric: Optional[str] = None
    incident_status: Optional[str] = None
    attempts_made: Optional[int] = None
    max_attempts: Optional[int] = None
    manual_intervention_required: Optional[bool] = None
    is_active: Optional[bool] = None


class RemediationDetail(RemediationOut):
    incident: IncidentOut
    attempts: list[AttemptOut]
    approvals: list[ApprovalOut]


class IncidentDetail(_Out):
    incident: IncidentOut
    remediation: Optional[RemediationOut] = None
    attempts: list[AttemptOut]
    decisions: list[dict[str, Any]] = []
    approvals: list[ApprovalOut]
    timeline: list[ActivityOut]
    current_value: Optional[str] = None


class MetricPoint(_Out):
    ts: str
    environment: Environment
    cpu: Optional[float] = None
    memory: Optional[float] = None
    disk: Optional[float] = None
    service_state: Optional[str] = None
    health: str


class EnvironmentMetrics(_Out):
    environment: Environment
    label: str
    ts: str
    cpu: Optional[float] = None
    memory: Optional[float] = None
    disk: Optional[float] = None
    service_state: Optional[str] = None
    health: str
    statuses: dict[str, str]
    errors: list[str] = []


class MonitoringStatus(_Out):
    running: bool
    interval_seconds: float
    started_at: Optional[str] = None
    tick_count: int
    error_count: int
    last_tick_at: Optional[str] = None
    last_error: Optional[str] = None
    thread_count: int


class CurrentMetrics(_Out):
    real_host: EnvironmentMetrics
    simulation: EnvironmentMetrics
    thresholds: dict[str, dict[str, float]]
    monitoring: MonitoringStatus
    mode: str


class MonitoringAction(_Out):
    changed: bool
    status: MonitoringStatus


class HealthOut(_Out):
    status: str
    database: str
    monitoring_running: bool
    mode: str
    version: str
    time: str


class SummaryOut(_Out):
    active: int
    active_critical: int
    resolved: int
    escalated: int
    pending_approvals: int
    manual_intervention: int
    total: int
    remediated: int
    remediation_success_rate: Optional[float] = None
    real_host_health: str
    simulation_health: str
    mode: str


class ConfigOut(_Out):
    thresholds: dict[str, dict[str, float]]
    mode: str
    monitoring: dict[str, Any]
    consecutive_violations: dict[str, int]
    ranker: str
    ranker_info: dict[str, Any]
    max_attempts: int
    executors: list[str]


class FaultInfo(_Out):
    id: str
    label: str
    initial: str


class ScenarioInfo(_Out):
    id: str
    title: str
    group: str
    description: str
    plan: list[str]
    mode: Optional[str] = None
    expected: str


class ScenarioList(_Out):
    faults: list[FaultInfo]
    scenarios: list[ScenarioInfo]


class DemoRun(_Out):
    id: str
    ts: str
    scenario: str
    fault: str
    incident_id: Optional[str] = None
    status: str
    params: Optional[dict[str, Any]] = None
    note: Optional[str] = None
    incident_status: Optional[str] = None
    attempts_made: Optional[int] = None


class SimulateOut(_Out):
    fault: str
    scenario: Optional[str] = None
    state: dict[str, Any]
    incident_id: Optional[str] = None


class ScenarioTriggerOut(_Out):
    run_id: str
    scenario: str
    fault: str
    incident_id: Optional[str] = None
    expected: str
    note: Optional[str] = None


class ResetOut(_Out):
    state: dict[str, Any]
    closed_incidents: int


class RecoverOut(_Out):
    fault: str
    state: dict[str, Any]

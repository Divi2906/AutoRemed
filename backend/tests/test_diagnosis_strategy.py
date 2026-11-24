"""Diagnosis + strategy selection: classification, reasoning, adjustment, no blind repetition."""
from __future__ import annotations

import pytest

from app.remediation.strategies import (AttemptRecord, RuleBasedRanker, SelectionContext, StrategySelector,
                                        build_ranker, get_strategy)
from tests.conftest import run


def ctx(metric="disk", attempt=1, history=None, value=97.0):
    thr = {"cpu": (75, 90), "memory": (80, 90), "disk": (85, 95)}.get(metric, (None, None))
    return SelectionContext(incident_type="service_failure" if metric == "service" else f"high_{metric}", severity="critical", environment="simulation",
                            metric=metric, value=value, warning_threshold=thr[0], critical_threshold=thr[1],
                            attempt=attempt, history=history or [])


def rec(n, strategy, exec_status="failed", ver=None):
    return AttemptRecord(attempt=n, strategy=strategy, execution_status=exec_status, verification_result=ver,
                         failure_reason="x", before={}, after={})


@pytest.fixture
def selector():
    return StrategySelector(RuleBasedRanker())


@pytest.mark.parametrize("fault,itype", [("cpu", "high_cpu"), ("memory", "high_memory"),
                                         ("disk", "high_disk"), ("service", "service_failure")])
def test_incident_classification_and_diagnosis(container, fault, itype):
    container.config.set_mode("approval")
    container.demo.inject(fault)
    inc = container.repos.list_incidents()[0][0]
    assert inc["type"] == itype
    d = inc["diagnosis"]
    assert d["probable_root_cause"] and d["rule_id"] and d["recommended_manual_step"]


def test_first_decision_has_full_explanation(selector):
    d = selector.select(ctx("disk"))
    assert d.strategy.name and d.expected_outcome and d.attempt == 1
    assert "disk" in d.reason.lower() and d.ranker
    assert d.context and isinstance(d.previous_outcomes, list)


@pytest.mark.parametrize("metric", ["cpu", "memory", "disk", "service"])
def test_no_blind_repetition_across_attempts(selector, metric):
    history, used = [], []
    for n in (1, 2, 3):
        d = selector.select(ctx(metric, n, history))
        used.append(d.strategy.name)
        history.append(rec(n, d.strategy.name))
    assert len(set(used)) == 3, used


def test_reason_mentions_previous_failure_and_why_not_repeated(selector):
    first = selector.select(ctx("disk"))
    second = selector.select(ctx("disk", 2, [rec(1, first.strategy.name)]))
    assert second.strategy.name != first.strategy.name
    low = second.reason.lower()
    assert first.strategy.name in second.reason and "fail" in low
    assert second.previous_outcomes and second.previous_outcomes[0]["strategy"] == first.strategy.name


def test_strategies_are_metric_appropriate(selector):
    assert selector.select(ctx("cpu")).strategy.incident_type == "high_cpu"
    assert selector.select(ctx("disk")).strategy.incident_type == "high_disk"


def test_ranker_is_labelled_rule_based_and_ml_is_not_faked():
    ranker, note = build_ranker("rule_based")
    assert isinstance(ranker, RuleBasedRanker)
    ml, note = build_ranker("ml")
    assert isinstance(ml, RuleBasedRanker) and note and "rule" in note.lower()   # falls back, says so


def test_persisted_decisions_per_attempt(container):
    inc = run(container, "third_attempt_succeeds")
    decs = container.repos.decisions(inc["id"])
    assert [d["attempt"] for d in decs] == [1, 2, 3]
    assert len({d["strategy"] for d in decs}) == 3
    assert all(d["reason"] and d["expected_outcome"] for d in decs)

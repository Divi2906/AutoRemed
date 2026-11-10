
import json
import pytest

from metrics_logger import log_metrics


def test_log_metrics_saves_data(tmp_path, monkeypatch):
    log_file = tmp_path / "metrics_history.json"
    monkeypatch.setattr("metrics_logger.METRICS_FILE", str(log_file))

    metrics = {
        "cpu": 45.5,
        "memory": 70.2,
        "disk": 43.3
    }

    log_metrics(metrics)

    with open(log_file, "r", encoding="utf-8") as file:
        history = json.load(file)

    assert len(history) == 1
    assert history[0]["cpu"] == 45.5
    assert history[0]["memory"] == 70.2
    assert history[0]["disk"] == 43.3
    assert "timestamp" in history[0]


def test_log_metrics_appends_data(tmp_path, monkeypatch):
    log_file = tmp_path / "metrics_history.json"
    monkeypatch.setattr("metrics_logger.METRICS_FILE", str(log_file))

    log_metrics({"cpu": 20, "memory": 40, "disk": 50})
    log_metrics({"cpu": 30, "memory": 60, "disk": 70})

    with open(log_file, "r", encoding="utf-8") as file:
        history = json.load(file)

    assert len(history) == 2
    assert history[0]["cpu"] == 20
    assert history[1]["cpu"] == 30


def test_log_metrics_rejects_missing_metric():
    metrics = {
        "cpu": 45,
        "memory": 70
    }

    with pytest.raises(ValueError, match="Missing metric: disk"):
        log_metrics(metrics)


def test_log_metrics_rejects_non_dictionary():
    with pytest.raises(ValueError, match="Metrics must be a dictionary"):
        log_metrics(None)

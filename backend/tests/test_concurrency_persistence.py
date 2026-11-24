"""Attempt-limit enforcement under concurrency, simultaneous incidents, restart/persistence."""
from __future__ import annotations

import threading

import pytest

from app.container import Container
from app.core.errors import AttemptLimitReached
from app.remediation.strategies import get_strategy
from tests.conftest import executions_of, make_settings, run


def hammer(fn, n=12):
    barrier, errors, results = threading.Barrier(n), [], []

    def w():
        barrier.wait()
        try:
            results.append(fn())
        except Exception as e:      # noqa: BLE001 - collected for assertions
            errors.append(e)
    ts = [threading.Thread(target=w) for _ in range(n)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return results, errors


def test_concurrent_workflow_starts_run_only_one_workflow(async_container):
    c = async_container
    res = c.demo.trigger("all_attempts_fail", "cpu")
    hammer(lambda: c.orchestrator.run_workflow(res["incident_id"]))
    for _ in range(5):
        c.orchestrator.dispatch_pending()
    assert c.orchestrator.wait_idle(30)
    inc = c.repos.incident(res["incident_id"])
    ex = executions_of(c, res["incident_id"])
    assert len(ex) == 3 and sorted(e["attempt"] for e in ex) == [1, 2, 3]
    assert inc["status"] == "escalated" and inc["attempts_made"] == 3


def test_concurrent_attempt_reservation_cannot_bypass_limit(container):
    c = container
    inc = run(c, "approval_required")
    rem = c.repos.remediation_for_incident(inc["id"])
    c.db.execute("UPDATE incidents SET workflow_state='running', status='approved' WHERE id=?", (inc["id"],))
    inc = c.repos.incident(inc["id"])
    dec = c.orchestrator._decision_from_row(c.repos.decision(inc["id"], 1))
    results, errors = hammer(lambda: c.orchestrator._reserve_attempt(inc, rem["id"], dec, 1), n=16)
    assert len(results) == 1 and all(isinstance(e, AttemptLimitReached) for e in errors)
    assert c.repos.incident(inc["id"])["attempts_made"] == 1


def test_fourth_attempt_is_refused_by_backend_and_schema(container):
    c = container
    inc = run(c, "all_attempts_fail")
    rem = c.repos.remediation_for_incident(inc["id"])
    c.db.execute("UPDATE incidents SET workflow_state='running' WHERE id=?", (inc["id"],))
    dec = c.orchestrator._make_decision(c.repos.incident(inc["id"]), 4, [])
    with pytest.raises(AttemptLimitReached):
        c.orchestrator._reserve_attempt(c.repos.incident(inc["id"]), rem["id"], dec, 4)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):          # DB CHECK(attempt BETWEEN 1 AND 3)
        with c.db.tx() as cx:
            cx.execute("INSERT INTO executions (id, incident_id, remediation_id, environment, action, strategy,"
                       " executor, attempt, status, started_at) VALUES ('E4',?,?,'simulation','a','s','x',4,'running','t')",
                       (inc["id"], rem["id"]))
    assert len(executions_of(c, inc["id"])) == 3


def test_simultaneous_cpu_and_memory_incidents(async_container):
    c = async_container
    a = c.demo.trigger("first_attempt_succeeds", "cpu")
    b = c.demo.trigger("all_attempts_fail", "memory")
    assert c.orchestrator.wait_idle(30)
    ia, ib = c.repos.incident(a["incident_id"]), c.repos.incident(b["incident_id"])
    assert (ia["status"], len(executions_of(c, ia["id"]))) == ("resolved", 1)
    assert (ib["status"], len(executions_of(c, ib["id"]))) == ("escalated", 3)


def test_same_fault_repeatedly_detected_during_remediation(async_container):
    c = async_container
    res = c.demo.trigger("third_attempt_succeeds", "disk")
    for _ in range(20):
        c.monitor.tick()
    assert c.orchestrator.wait_idle(30)
    assert c.repos.list_incidents()[1] == 1
    assert len(executions_of(c, res["incident_id"])) == 3


# ------------------------------------------------------------------ persistence
def reopen(tmp_path, **kw) -> Container:
    return Container(make_settings(tmp_path, **kw))


def test_history_survives_restart(tmp_path):
    c1 = reopen(tmp_path)
    a = run(c1, "all_attempts_fail", "cpu")
    b = run(c1, "second_attempt_succeeds", "memory")
    n_logs = c1.activity.query(limit=1)[1]
    c1.monitor.tick()
    c1.config.set_thresholds({"cpu": {"warning": 70, "critical": 88}})
    c1.shutdown()

    c2 = reopen(tmp_path)
    ia, ib = c2.repos.incident(a["id"]), c2.repos.incident(b["id"])
    assert ia["status"] == "escalated" and ia["attempts_made"] == 3 and ia["manual_intervention_required"]
    assert ib["status"] == "resolved" and ib["attempts_made"] == 2
    assert len(executions_of(c2, a["id"])) == 3 and len(c2.repos.verifications(a["id"])[0]) == 3
    assert c2.activity.query(limit=1)[1] >= n_logs
    assert c2.config.thresholds()["cpu"] == {"warning": 70.0, "critical": 88.0}
    assert len(c2.monitor.history("simulation", 10)) >= 1
    c2.start()                                            # restart must not re-run finished workflows
    assert len(executions_of(c2, a["id"])) == 3
    c2.shutdown()


class Crash(BaseException):
    pass


def test_attempt_count_preserved_and_workflow_resumed_after_crash(tmp_path):
    from app.remediation.executors import TestExecutor
    c1 = reopen(tmp_path)
    c1.executors.register(TestExecutor(outcomes=[lambda r: (_ for _ in ()).throw(Crash())]))
    c1.executors.default = "test"
    with pytest.raises(Crash):
        c1.demo.inject("cpu")
    inc = c1.repos.list_incidents()[0][0]
    # emulate process death: the 'finally' never ran
    c1.db.execute("UPDATE incidents SET workflow_state='running' WHERE id=?", (inc["id"],))
    assert c1.repos.incident(inc["id"])["attempts_made"] == 1
    c1.shutdown()

    c2 = reopen(tmp_path)
    c2.start()                                            # resume_after_restart
    after = c2.repos.incident(inc["id"])
    ex = sorted(executions_of(c2, inc["id"]), key=lambda e: e["attempt"])
    assert ex[0]["attempt"] == 1 and ex[0]["status"] == "failed" and "restart" in ex[0]["error"]
    assert after["attempts_made"] <= 3 and len(ex) <= 3 and len(ex) >= 2   # continued from attempt 2, not 1
    assert after["status"] in ("resolved", "escalated")
    assert len({e["attempt"] for e in ex}) == len(ex)
    c2.shutdown()


def test_demo_reset_resets_simulation_but_keeps_history(container):
    inc = run(container, "all_attempts_fail")
    logs_before = container.activity.query(limit=1)[1]
    container.demo.reset()
    assert container.sim.snapshot()["cpu"] == 22.0
    kept = container.repos.incident(inc["id"])
    assert kept is not None and kept["attempts_made"] == 3 and not kept["is_active"]
    assert len(executions_of(container, inc["id"])) == 3
    assert container.activity.query(limit=1)[1] > logs_before
    assert container.repos.active_incidents("simulation") == []


def test_reset_cancels_pending_approval_incident(container):
    inc = run(container, "approval_required")
    container.demo.reset()
    assert container.repos.incident(inc["id"])["status"] == "cancelled"
    assert executions_of(container, inc["id"]) == []


# ------------------------------------------------------------------ schema migration
def test_schema_migration_v1_to_v2_populated_db(tmp_path):
    import sqlite3
    from app.core.db import Database, SCHEMA_V1, _split_statements

    db_file = str(tmp_path / "populated_v1.db")

    # 1. Create a pure v1 database (user_version = 1) and populate with full relational graph
    conn = sqlite3.connect(db_file, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    for stmt in _split_statements(SCHEMA_V1):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version=1")

    conn.execute(
        "INSERT INTO incidents (id, fingerprint, type, severity, environment, metric, description, status, "
        "mode, created_at, updated_at) VALUES ('INC-1', 'fp-1', 'high_cpu', 'warning', 'simulation', 'cpu', "
        "'CPU spike', 'remediating', 'autonomous', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO remediations (id, incident_id, mode, approval_state, status, created_at, updated_at) "
        "VALUES ('REM-1', 'INC-1', 'autonomous', 'not_required', 'in_progress', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO executions (id, incident_id, remediation_id, environment, action, strategy, executor, "
        "attempt, status, started_at) VALUES ('EXE-1', 'INC-1', 'REM-1', 'simulation', 'kill', 'restart', 'sim', "
        "1, 'failed', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO verifications (id, incident_id, execution_id, attempt, result, created_at) "
        "VALUES ('VER-1', 'INC-1', 'EXE-1', 1, 'not_recovered', '2026-01-01T00:00:00')"
    )
    conn.close()

    # 2. Upgrade to v2 via Database.migrate()
    db = Database(db_file)
    try:
        assert db.query("PRAGMA user_version")[0]["user_version"] == 2
        assert db.query("PRAGMA foreign_keys")[0]["foreign_keys"] == 1

        ex_rows = db.query("SELECT * FROM executions WHERE id='EXE-1'")
        assert len(ex_rows) == 1 and ex_rows[0]["status"] == "failed"
        ver_rows = db.query("SELECT * FROM verifications WHERE id='VER-1'")
        assert len(ver_rows) == 1 and ver_rows[0]["execution_id"] == "EXE-1"

        assert db.query("PRAGMA foreign_key_check") == []

        # Check status='blocked' is accepted
        with db.tx() as c:
            c.execute(
                "INSERT INTO executions (id, incident_id, remediation_id, environment, action, strategy, executor, "
                "attempt, status, started_at) VALUES ('EXE-2', 'INC-1', 'REM-1', 'simulation', 'kill', 'restart', 'sim', "
                "2, 'blocked', '2026-01-01T00:00:01')"
            )

        # Check invalid status is rejected
        with pytest.raises(sqlite3.IntegrityError):
            with db.tx() as c:
                c.execute(
                    "INSERT INTO executions (id, incident_id, remediation_id, environment, action, strategy, executor, "
                    "attempt, status, started_at) VALUES ('EXE-INV', 'INC-1', 'REM-1', 'simulation', 'kill', 'restart', 'sim', "
                    "3, 'invalid_status', '2026-01-01T00:00:02')"
                )

        # Check duplicate (incident_id, attempt) is rejected
        with pytest.raises(sqlite3.IntegrityError):
            with db.tx() as c:
                c.execute(
                    "INSERT INTO executions (id, incident_id, remediation_id, environment, action, strategy, executor, "
                    "attempt, status, started_at) VALUES ('EXE-DUP', 'INC-1', 'REM-1', 'simulation', 'kill', 'restart', 'sim', "
                    "1, 'failed', '2026-01-01T00:00:02')"
                )

        # Check foreign key enforcement on invalid reference
        with pytest.raises(sqlite3.IntegrityError):
            with db.tx() as c:
                c.execute(
                    "INSERT INTO verifications (id, incident_id, execution_id, attempt, result, created_at) "
                    "VALUES ('VER-BAD', 'INC-1', 'EXE-NONEXISTENT', 2, 'recovered', '2026-01-01T00:00:02')"
                )
    finally:
        db.close()


def test_schema_migration_fresh_db(tmp_path):
    import sqlite3
    from app.core.db import Database

    db_file = str(tmp_path / "fresh.db")
    db = Database(db_file)
    try:
        assert db.query("PRAGMA user_version")[0]["user_version"] == 2
        assert db.query("PRAGMA foreign_keys")[0]["foreign_keys"] == 1
        assert db.query("PRAGMA foreign_key_check") == []

        with db.tx() as c:
            c.execute(
                "INSERT INTO incidents (id, fingerprint, type, severity, environment, metric, description, status, "
                "mode, created_at, updated_at) VALUES ('INC-F', 'fp-f', 'high_cpu', 'warning', 'simulation', 'cpu', "
                "'CPU spike', 'remediating', 'autonomous', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            )
            c.execute(
                "INSERT INTO executions (id, incident_id, environment, action, strategy, executor, "
                "attempt, status, started_at) VALUES ('EXE-F', 'INC-F', 'simulation', 'kill', 'restart', 'sim', "
                "1, 'blocked', '2026-01-01T00:00:00')"
            )

        row = db.query("SELECT status FROM executions WHERE id='EXE-F'")[0]
        assert row["status"] == "blocked"

        with pytest.raises(sqlite3.IntegrityError):
            with db.tx() as c:
                c.execute(
                    "INSERT INTO executions (id, incident_id, environment, action, strategy, executor, "
                    "attempt, status, started_at) VALUES ('EXE-BAD', 'INC-F', 'simulation', 'kill', 'restart', 'sim', "
                    "2, 'invalid', '2026-01-01T00:00:00')"
                )
    finally:
        db.close()


def test_schema_migration_rollback_on_foreign_key_failure(tmp_path):
    import sqlite3
    import threading
    from app.core.db import Database, SCHEMA_V1, _split_statements

    db_file = str(tmp_path / "rollback_v1.db")

    # 1. Create a temporary version-1 database
    conn = sqlite3.connect(db_file, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    for stmt in _split_statements(SCHEMA_V1):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version=1")

    conn.execute(
        "INSERT INTO incidents (id, fingerprint, type, severity, environment, metric, description, status, "
        "mode, created_at, updated_at) VALUES ('INC-1', 'fp-1', 'high_cpu', 'warning', 'simulation', 'cpu', "
        "'CPU spike', 'remediating', 'autonomous', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO executions (id, incident_id, environment, action, strategy, executor, "
        "attempt, status, started_at) VALUES ('EXE-1', 'INC-1', 'simulation', 'kill', 'restart', 'sim', "
        "1, 'failed', '2026-01-01T00:00:00')"
    )

    # 2. Introduce a condition that makes migration's foreign_key_check fail:
    # Temporarily disable foreign keys on the setup connection to insert an orphan execution referencing a nonexistent incident
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO executions (id, incident_id, environment, action, strategy, executor, "
        "attempt, status, started_at) VALUES ('EXE-ORPHAN', 'INC-NONEXISTENT', 'simulation', 'kill', 'restart', 'sim', "
        "2, 'failed', '2026-01-01T00:00:00')"
    )
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()

    # Subclass Database to control the exact point of migration execution on an open instance
    class UnmigratedDatabase(Database):
        def __init__(self, path: str):
            self.path = path
            self._local = threading.local()
            self._write_lock = threading.RLock()
            self._all = []
            self._all_lock = threading.Lock()
            self._closed = False

    db = UnmigratedDatabase(db_file)
    try:
        # 3. Attempt migration and confirm it raises an exception
        with pytest.raises(RuntimeError, match="foreign key violations after migration"):
            db.migrate()

        # 4. Confirm the transaction rolls back and PRAGMA user_version remains 1
        assert db.query("PRAGMA user_version")[0]["user_version"] == 1

        # 5. Confirm the original executions table and its records remain intact
        rows = db.query("SELECT id, incident_id, status FROM executions ORDER BY attempt")
        assert len(rows) == 2
        assert rows[0]["id"] == "EXE-1" and rows[0]["status"] == "failed"
        assert rows[1]["id"] == "EXE-ORPHAN"
        table_sql = db.query("SELECT sql FROM sqlite_master WHERE name='executions'")[0]["sql"]
        assert "CHECK (status IN ('running','success','failed'))" in table_sql
        assert "'blocked'" not in table_sql

        # 6. Confirm PRAGMA foreign_keys returns 1 afterward
        assert db.query("PRAGMA foreign_keys")[0]["foreign_keys"] == 1

        # 7. Confirm the database connection remains usable
        with db.tx() as c:
            c.execute(
                "INSERT INTO incidents (id, fingerprint, type, severity, environment, metric, description, status, "
                "mode, created_at, updated_at) VALUES ('INC-2', 'fp-2', 'high_cpu', 'warning', 'simulation', 'cpu', "
                "'Second incident', 'remediating', 'autonomous', '2026-01-01T00:00:01', '2026-01-01T00:00:01')"
            )
        assert db.query("SELECT COUNT(*) AS total FROM incidents")[0]["total"] == 2
    finally:
        db.close()

"""SQLite access layer.

* One connection per thread (``threading.local``), WAL journal, foreign keys on.
* Writes go through ``Database.tx()``: an in-process re-entrant lock plus
  ``BEGIN IMMEDIATE`` so related changes commit atomically and concurrent writers
  (monitor thread, remediation workers, API threads) are serialized.
* ``tx()`` is re-entrant per thread: nested use joins the outer transaction.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

logger = logging.getLogger("autoremed.db")

SCHEMA_V1 = """
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('real_host','simulation')),
    cpu REAL, memory REAL, disk REAL,
    service_state TEXT,
    health TEXT NOT NULL
);
CREATE INDEX idx_metrics_env_id ON metrics(environment, id);

CREATE TABLE sim_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cpu REAL NOT NULL, memory REAL NOT NULL, disk REAL NOT NULL,
    service_state TEXT NOT NULL,
    epoch INTEGER NOT NULL DEFAULT 0,
    control_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE incidents (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('warning','critical')),
    environment TEXT NOT NULL CHECK (environment IN ('real_host','simulation')),
    metric TEXT NOT NULL,
    value REAL, threshold REAL,
    value_label TEXT, threshold_label TEXT,
    description TEXT NOT NULL,
    root_cause TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'detected','investigating','pending_approval','approved','rejected',
        'remediating','retry_in_progress','resolved','escalated','cancelled')),
    is_active INTEGER NOT NULL DEFAULT 1,
    workflow_state TEXT NOT NULL DEFAULT 'idle'
        CHECK (workflow_state IN ('idle','awaiting_approval','running','finished')),
    mode TEXT NOT NULL CHECK (mode IN ('autonomous','approval')),
    observe_only INTEGER NOT NULL DEFAULT 0,
    diagnosis_json TEXT,
    scenario_json TEXT,
    resolution TEXT,
    resolution_type TEXT,
    closed_reason TEXT,
    manual_intervention_required INTEGER NOT NULL DEFAULT 0,
    recommended_action TEXT,
    attempts_made INTEGER NOT NULL DEFAULT 0 CHECK (attempts_made BETWEEN 0 AND 3),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 3),
    final_state_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    escalated_at TEXT
);
-- Duplicate-incident prevention enforced by the database itself.
CREATE UNIQUE INDEX uq_incident_active_fingerprint ON incidents(fingerprint) WHERE is_active = 1;
CREATE INDEX idx_incidents_status ON incidents(status);
CREATE INDEX idx_incidents_created ON incidents(created_at);

CREATE TABLE remediations (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL UNIQUE REFERENCES incidents(id),
    mode TEXT NOT NULL,
    approval_state TEXT NOT NULL CHECK (approval_state IN
        ('not_required','pending','approved','rejected','cancelled')),
    status TEXT NOT NULL CHECK (status IN
        ('pending_approval','approved','rejected','in_progress','resolved','escalated','cancelled')),
    proposed_strategy TEXT,
    proposal_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE approvals (
    id TEXT PRIMARY KEY,
    remediation_id TEXT NOT NULL REFERENCES remediations(id),
    incident_id TEXT NOT NULL REFERENCES incidents(id),
    action TEXT NOT NULL CHECK (action IN ('requested','approved','rejected')),
    actor TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE strategy_decisions (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id),
    remediation_id TEXT REFERENCES remediations(id),
    attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 3),
    strategy TEXT NOT NULL,
    reason TEXT NOT NULL,
    expected_outcome TEXT,
    context_json TEXT,
    previous_outcomes_json TEXT,
    alternatives_json TEXT,
    ranker TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (incident_id, attempt)
);

CREATE TABLE executions (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id),
    remediation_id TEXT REFERENCES remediations(id),
    environment TEXT NOT NULL,
    action TEXT NOT NULL,
    strategy TEXT NOT NULL,
    executor TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 3),
    status TEXT NOT NULL CHECK (status IN ('running','success','failed')),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_ms INTEGER,
    message TEXT,
    error TEXT,
    -- Backend-level guarantee: one execution per (incident, attempt number), attempts 1..3.
    UNIQUE (incident_id, attempt)
);

CREATE TABLE verifications (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id),
    execution_id TEXT REFERENCES executions(id),
    attempt INTEGER NOT NULL,
    before_json TEXT,
    after_json TEXT,
    criteria_json TEXT,
    result TEXT NOT NULL CHECK (result IN ('recovered','not_recovered')),
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (incident_id, attempt)
);

CREATE TABLE activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    incident_id TEXT,
    action TEXT,
    status TEXT,
    attempt INTEGER,
    environment TEXT,
    message TEXT NOT NULL,
    details_json TEXT
);
CREATE INDEX idx_activity_incident ON activity_logs(incident_id);
CREATE INDEX idx_activity_type ON activity_logs(event_type);

CREATE TABLE demo_runs (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    scenario TEXT NOT NULL,
    fault TEXT NOT NULL,
    incident_id TEXT,
    status TEXT NOT NULL,
    params_json TEXT,
    note TEXT
);
"""

MIGRATIONS: list[tuple[int, str]] = [(1, SCHEMA_V1)]


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._all: list[sqlite3.Connection] = []
        self._all_lock = threading.Lock()
        self._closed = False
        self.migrate()

    # ------------------------------------------------------------------ connections
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            if self._closed:
                raise RuntimeError("database is closed")
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
            self._local.depth = 0
            with self._all_lock:
                self._all.append(c)
        return c

    def close(self) -> None:
        self._closed = True
        with self._all_lock:
            for c in self._all:
                try:
                    c.close()
                except Exception:  # pragma: no cover - best effort on shutdown
                    logger.exception("error closing sqlite connection")
            self._all.clear()
        self._local = threading.local()

    # ------------------------------------------------------------------ schema
    def migrate(self) -> None:
        with self.tx() as c:
            current = c.execute("PRAGMA user_version").fetchone()[0]
            for version, sql in MIGRATIONS:
                if version > current:
                    for stmt in _split_statements(sql):
                        c.execute(stmt)
                    c.execute(f"PRAGMA user_version={version}")
                    logger.info("applied schema migration v%s", version)

    # ------------------------------------------------------------------ transactions
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        c = self.conn()
        with self._write_lock:
            depth = getattr(self._local, "depth", 0)
            if depth > 0:
                self._local.depth = depth + 1
                try:
                    yield c
                finally:
                    self._local.depth -= 1
                return
            c.execute("BEGIN IMMEDIATE")
            self._local.depth = 1
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")
            finally:
                self._local.depth = 0

    # ------------------------------------------------------------------ helpers
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self.tx() as c:
            return c.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn().execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        r = self.conn().execute(sql, params).fetchone()
        return dict(r) if r else None


def _split_statements(script: str) -> list[str]:
    # Schema contains no semicolons inside string literals, so a plain split is safe.
    return [s.strip() for s in script.split(";") if s.strip()]

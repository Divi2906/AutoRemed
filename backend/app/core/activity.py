from __future__ import annotations

import logging
from typing import Any

from .db import Database
from .util import dumps, loads, utcnow

logger = logging.getLogger("autoremed.activity")


class ActivityLog:
    """Chronological, persisted activity log. Joins an open transaction if there is one."""

    def __init__(self, db: Database):
        self.db = db

    def log(
        self,
        event_type: str,
        message: str,
        *,
        incident_id: str | None = None,
        action: str | None = None,
        status: str | None = None,
        attempt: int | None = None,
        environment: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO activity_logs (ts, event_type, incident_id, action, status, attempt,"
            " environment, message, details_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                utcnow(),
                event_type,
                incident_id,
                action,
                status,
                attempt,
                environment,
                message,
                dumps(details) if details is not None else None,
            ),
        )
        logger.info("[%s] %s%s", event_type, f"{incident_id}: " if incident_id else "", message)

    def query(
        self,
        *,
        event_type: str | None = None,
        incident_id: str | None = None,
        status: str | None = None,
        environment: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
        newest_first: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = ["1=1"], []
        for col, val in (
            ("event_type", event_type),
            ("incident_id", incident_id),
            ("status", status),
            ("environment", environment),
        ):
            if val:
                where.append(f"{col} = ?")
                params.append(val)
        if search:
            where.append("(message LIKE ? OR action LIKE ? OR incident_id LIKE ?)")
            params += [f"%{search}%"] * 3
        clause = " AND ".join(where)
        total = self.db.query_one(f"SELECT COUNT(*) AS n FROM activity_logs WHERE {clause}", params)["n"]
        order = "DESC" if newest_first else "ASC"
        rows = self.db.query(
            f"SELECT * FROM activity_logs WHERE {clause} ORDER BY id {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        for r in rows:
            r["details"] = loads(r.pop("details_json"))
        return rows, total

"""Small SQLite-backed incident state store."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .security import redact_text

INCIDENT_STATES = {
    "DETECTED",
    "TRIAGING",
    "INVESTIGATING",
    "SOLUTION_RECOMMENDED",
    "AWAITING_REMEDIATION",
    "VALIDATING",
    "RECOVERED",
    "STILL_ACTIVE",
    "INCONCLUSIVE",
}
_TERMINAL_STATES = {"RECOVERED"}
_LOCK = threading.RLock()
_CONNECTIONS: dict[str, sqlite3.Connection] = {}


def _database_path() -> str:
    return os.environ.get(
        "INCIDENT_DB_PATH", "/data/incidents.sqlite3"
    )


def _connection() -> sqlite3.Connection:
    path = _database_path()
    connection = _CONNECTIONS.get(path)
    if connection is not None:
        return connection
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            alert_name TEXT NOT NULL,
            namespace TEXT NOT NULL,
            workload TEXT NOT NULL,
            severity TEXT NOT NULL,
            detected_at TEXT,
            last_seen_at TEXT NOT NULL,
            status TEXT NOT NULL,
            probable_cause TEXT,
            recommended_solution TEXT,
            validation_result TEXT,
            final_status TEXT
        )
        """
    )
    connection.commit()
    _CONNECTIONS[path] = connection
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_incident_id(alert: dict[str, Any]) -> tuple[str, str]:
    fingerprint = str(alert.get("fingerprint") or "")
    if not fingerprint:
        identity = {
            "alert_name": alert.get("alert_name") or alert.get("labels", {}).get("alertname"),
            "namespace": alert.get("namespace") or alert.get("labels", {}).get("namespace"),
            "workload": alert.get("workload") or alert.get("labels", {}).get("deployment"),
            "pod": alert.get("pod") or alert.get("labels", {}).get("pod"),
        }
        fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode("utf-8")
        ).hexdigest()
    incident_id = f"inc-{hashlib.sha256(fingerprint.encode()).hexdigest()[:16]}"
    return incident_id, fingerprint


def register_incident(alert: dict[str, Any]) -> dict[str, Any]:
    labels = alert.get("labels") or {}
    incident_id, fingerprint = stable_incident_id(alert)
    name = str(alert.get("alert_name") or labels.get("alertname") or "unknown")
    namespace = str(alert.get("namespace") or labels.get("namespace") or "unknown")
    workload = str(
        alert.get("workload")
        or labels.get("deployment")
        or labels.get("workload")
        or labels.get("job")
        or "unknown"
    )
    severity = str(alert.get("severity") or labels.get("severity") or "unknown")
    detected_at = alert.get("starts_at") or alert.get("activeAt")
    now = _now()
    with _LOCK:
        connection = _connection()
        existing = connection.execute(
            "SELECT status FROM incidents WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        created = existing is None
        reactivated = existing is not None and existing["status"] == "RECOVERED"
        connection.execute(
            """
            INSERT INTO incidents (
                incident_id, fingerprint, alert_name, namespace, workload,
                severity, detected_at, last_seen_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DETECTED')
            ON CONFLICT(fingerprint) DO UPDATE SET
                alert_name = excluded.alert_name,
                namespace = excluded.namespace,
                workload = excluded.workload,
                severity = excluded.severity,
                detected_at = CASE
                    WHEN incidents.status = 'RECOVERED' THEN excluded.detected_at
                    ELSE incidents.detected_at
                END,
                last_seen_at = excluded.last_seen_at,
                status = CASE
                    WHEN incidents.status = 'RECOVERED' THEN 'DETECTED'
                    ELSE incidents.status
                END,
                probable_cause = CASE
                    WHEN incidents.status = 'RECOVERED' THEN NULL
                    ELSE incidents.probable_cause
                END,
                recommended_solution = CASE
                    WHEN incidents.status = 'RECOVERED' THEN NULL
                    ELSE incidents.recommended_solution
                END,
                validation_result = CASE
                    WHEN incidents.status = 'RECOVERED' THEN NULL
                    ELSE incidents.validation_result
                END,
                final_status = CASE
                    WHEN incidents.status = 'RECOVERED' THEN NULL
                    ELSE incidents.final_status
                END
            """,
            (
                incident_id, fingerprint, name, namespace, workload, severity,
                detected_at, now,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM incidents WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
    return {
        "created": created,
        "reactivated": reactivated,
        "duplicate_active": not created and not reactivated,
        "incident": _serialize(row),
    }


def update_incident(
    incident_id: str,
    status: str,
    probable_cause: str | None = None,
    recommended_solution: str | None = None,
    validation_result: str | None = None,
) -> dict[str, Any]:
    status = status.upper()
    if status not in INCIDENT_STATES:
        raise ValueError(f"Unsupported incident state: {status}")
    safe_values = (
        redact_text(probable_cause, max_length=1000) if probable_cause else None,
        redact_text(recommended_solution, max_length=1500)
        if recommended_solution else None,
        redact_text(validation_result, max_length=1000)
        if validation_result else None,
    )
    with _LOCK:
        connection = _connection()
        existing = connection.execute(
            "SELECT status FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if existing is None:
            raise ValueError(f"Incident not found: {incident_id}")
        if existing["status"] in _TERMINAL_STATES and status not in _TERMINAL_STATES:
            raise ValueError("A terminal incident cannot transition to an active state")
        connection.execute(
            """
            UPDATE incidents SET status = ?,
                probable_cause = COALESCE(?, probable_cause),
                recommended_solution = COALESCE(?, recommended_solution),
                validation_result = COALESCE(?, validation_result),
                final_status = CASE
                    WHEN ? IN ('RECOVERED', 'STILL_ACTIVE', 'INCONCLUSIVE') THEN ?
                    ELSE final_status
                END,
                last_seen_at = ?
            WHERE incident_id = ?
            """,
            (status, *safe_values, status, status, _now(), incident_id),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
    return _serialize(row)


def get_incidents(limit: int = 50) -> list[dict[str, Any]]:
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    with _LOCK:
        rows = _connection().execute(
            "SELECT * FROM incidents ORDER BY last_seen_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_serialize(row) for row in rows]


def find_incident(incident_id: str) -> dict[str, Any] | None:
    with _LOCK:
        row = _connection().execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
    return _serialize(row) if row else None


def close_state_store() -> None:
    with _LOCK:
        for connection in _CONNECTIONS.values():
            connection.close()
        _CONNECTIONS.clear()


def _serialize(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        key: row[key]
        for key in row.keys()
    }

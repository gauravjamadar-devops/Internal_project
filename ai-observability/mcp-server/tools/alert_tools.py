"""Read-only Alertmanager integration for active alerts and silences."""
from __future__ import annotations

from typing import Any

import httpx

from .security import (
    approved_service_url,
    allowed_namespaces,
    allowed_workloads,
    redact_mapping,
    redact_text,
    validate_alert_name,
    validate_namespace,
    workload_aliases,
)

_DEFAULT_ALERTMANAGER_URL = (
    "http://monitoring-kube-prometheus-alertmanager.monitoring.svc:9093"
)


def _request(path: str) -> Any:
    base_url = approved_service_url("ALERTMANAGER_URL", _DEFAULT_ALERTMANAGER_URL)
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
        response = client.get(f"{base_url}{path}")
        response.raise_for_status()
        return response.json()


def _normalize_alert(alert: dict[str, Any]) -> dict[str, Any]:
    labels = redact_mapping(alert.get("labels") or {})
    annotations = redact_mapping(alert.get("annotations") or {})
    status = alert.get("status") or {}
    pod = labels.get("pod")
    workload = (
        labels.get("deployment")
        or labels.get("workload")
        or labels.get("app")
    )
    if not workload and pod:
        workload = next(
            (name for name in allowed_workloads() if pod.startswith(name + "-")),
            None,
        )
    if not workload:
        workload = labels.get("job")
    if workload:
        workload = workload_aliases().get(workload, workload)
    return {
        "fingerprint": redact_text(str(alert.get("fingerprint") or ""), max_length=128),
        "alert_name": labels.get("alertname", "unknown"),
        "state": str(status.get("state") or "unknown").upper(),
        "severity": labels.get("severity", "unknown"),
        "namespace": labels.get("namespace", "unknown"),
        "workload": workload or "unknown",
        "pod": pod,
        "starts_at": alert.get("startsAt"),
        "ends_at": alert.get("endsAt"),
        "summary": annotations.get("summary", ""),
        "description": annotations.get("description", ""),
        "labels": labels,
        "annotations": annotations,
        "generator_url": redact_text(str(alert.get("generatorURL") or ""), max_length=500),
        "silenced": bool(status.get("silencedBy")),
        "inhibited": bool(status.get("inhibitedBy")),
        "detection_source": "Alertmanager",
    }


def get_active_alerts() -> dict[str, Any]:
    """Return active, silenced, and inhibited Alertmanager alerts."""
    try:
        alerts = _request(
            "/api/v2/alerts?active=true&silenced=true&inhibited=true"
        )
        if not isinstance(alerts, list):
            return {"error": "Alertmanager returned an invalid alert response"}
        normalized = [_normalize_alert(item) for item in alerts if isinstance(item, dict)]
        active = [
            alert for alert in normalized
            if alert["state"] not in {"RESOLVED", "SUPPRESSED"}
            and alert["namespace"] in allowed_namespaces()
            and alert["workload"] in allowed_workloads()
        ]
        return {"source": "Alertmanager", "count": len(active), "alerts": active}
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "error": f"Unable to retrieve active alerts from Alertmanager: "
                     f"{redact_text(str(exc), max_length=300)}"
        }


def get_alert_details(
    alert_name: str, namespace: str | None = None
) -> dict[str, Any]:
    """Return active details for an exact alert name and optional namespace."""
    validate_alert_name(alert_name)
    if namespace is not None:
        validate_namespace(namespace)
    result = get_active_alerts()
    if "error" in result:
        return result
    matches = [
        alert for alert in result["alerts"]
        if alert["alert_name"] == alert_name
        and (namespace is None or alert["namespace"] == namespace)
    ]
    return {
        "source": "Alertmanager",
        "alert_name": alert_name,
        "namespace": namespace,
        "count": len(matches),
        "alerts": matches,
    }


def get_silenced_alerts() -> dict[str, Any]:
    """Return active Alertmanager silences without comments or creator details."""
    try:
        silences = _request("/api/v2/silences")
        if not isinstance(silences, list):
            return {"error": "Alertmanager returned an invalid silence response"}
        result = []
        namespaces = allowed_namespaces()
        workloads = allowed_workloads()
        for silence in silences:
            if not isinstance(silence, dict):
                continue
            status = silence.get("status") or {}
            if status.get("state") != "active":
                continue
            matchers = []
            for matcher in silence.get("matchers") or []:
                matchers.append({
                    "name": redact_text(str(matcher.get("name") or ""), max_length=100),
                    "value": redact_text(str(matcher.get("value") or ""), max_length=200),
                    "is_regex": bool(matcher.get("isRegex")),
                    "is_equal": bool(matcher.get("isEqual", True)),
                })
            namespace_matcher = next(
                (item for item in matchers if item["name"] == "namespace"), None
            )
            workload_matcher = next(
                (
                    item for item in matchers
                    if item["name"] in {"deployment", "workload", "job", "app"}
                ),
                None,
            )
            if namespace_matcher and (
                namespace_matcher["is_regex"]
                or namespace_matcher["value"] not in namespaces
            ):
                continue
            if workload_matcher and (
                workload_matcher["is_regex"]
                or workload_matcher["value"] not in workloads
            ):
                continue
            result.append({
                "id": redact_text(str(silence.get("id") or ""), max_length=100),
                "state": "ACTIVE",
                "starts_at": silence.get("startsAt"),
                "ends_at": silence.get("endsAt"),
                "matchers": matchers,
            })
        return {"source": "Alertmanager", "count": len(result), "silences": result}
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "error": f"Unable to retrieve silences from Alertmanager: "
                     f"{redact_text(str(exc), max_length=300)}"
        }

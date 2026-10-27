"""Deterministic alert classification and recovery decision logic."""
from __future__ import annotations

import re
from typing import Any

from .incident_state import register_incident
from .security import redact_text, validate_namespace, validate_workload

_CLASSIFIERS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("image_pull", ("imagepullbackoff", "errimagepull"), "configuration"),
    ("oom", ("oomkilled", "highmemory", "memorypressure"), "resource"),
    ("crash_loop", ("crashloopbackoff", "crashlooping"), "kubernetes_workload"),
    ("pending", ("podpending", "pendingpod", "failedscheduling"), "kubernetes_workload"),
    ("probe_failure", ("readiness", "liveness", "probe"), "kubernetes_workload"),
    ("high_cpu", ("highcpu", "cpuusage", "cpuutilization"), "resource"),
    ("http_5xx", ("high5xx", "higherrorrate", "http5xx", "5xx"), "application"),
    ("availability", ("unavailable", "targetdown", "notscraping"), "kubernetes_workload"),
    ("deployment_degraded", ("replicasmismatch", "deploymentdegraded"), "deployment_gitops"),
    ("argocd_degraded", ("argocd", "outofsync", "syncfailed"), "deployment_gitops"),
    ("container_restart", ("restart",), "kubernetes_workload"),
)

_CATEGORY_TOOLS: dict[str, list[str]] = {
    "http_5xx": [
        "get_application_health_tool", "get_error_rate_tool",
        "get_request_rate_tool", "get_request_latency_tool",
        "get_pods_tool", "get_pod_restarts_tool", "get_resource_usage_tool",
        "get_pod_logs_tool", "get_recent_rollout_tool",
    ],
    "crash_loop": [
        "get_pod_status_tool", "get_pod_logs_tool",
        "get_previous_pod_logs_tool", "get_kubernetes_events_tool",
        "get_deployment_status_tool", "get_recent_rollout_tool",
        "get_argocd_application_status_tool",
    ],
    "oom": [
        "get_pod_status_tool", "get_pod_memory_tool",
        "get_resource_usage_tool", "get_pod_restarts_tool",
        "get_previous_pod_logs_tool", "get_recent_rollout_tool",
        "get_request_rate_tool", "get_error_rate_tool",
    ],
    "high_cpu": [
        "get_pod_cpu_tool", "get_resource_usage_tool",
        "get_request_rate_tool", "get_request_latency_tool",
        "get_error_rate_tool", "get_deployment_status_tool",
    ],
    "probe_failure": [
        "get_pod_status_tool", "get_kubernetes_events_tool",
        "get_pod_logs_tool", "check_application_endpoint_tool",
        "get_resource_usage_tool", "get_deployment_status_tool",
    ],
    "image_pull": [
        "get_pod_status_tool", "get_kubernetes_events_tool",
        "get_deployment_status_tool", "get_current_image_tool",
        "get_deployment_revision_tool",
    ],
    "pending": [
        "get_pod_status_tool", "get_kubernetes_events_tool",
        "get_deployment_status_tool",
    ],
    "deployment_degraded": [
        "get_argocd_application_status_tool", "get_argocd_sync_status_tool",
        "get_deployment_status_tool", "get_current_image_tool",
        "get_deployment_revision_tool", "get_kubernetes_events_tool",
    ],
    "argocd_degraded": [
        "get_argocd_application_status_tool", "get_argocd_sync_status_tool",
        "get_deployment_status_tool", "get_current_image_tool",
        "get_deployment_revision_tool",
    ],
    "availability": [
        "get_application_health_tool", "get_deployment_status_tool",
        "get_available_replicas_tool", "get_pods_tool",
        "get_kubernetes_events_tool", "check_application_endpoint_tool",
    ],
    "container_restart": [
        "get_pod_restarts_tool", "get_container_restart_metrics_tool",
        "get_pod_status_tool", "get_kubernetes_events_tool",
        "get_previous_pod_logs_tool", "get_recent_rollout_tool",
    ],
    "unknown": [
        "get_alert_details_tool", "get_pods_tool",
        "get_kubernetes_events_tool", "get_application_health_tool",
    ],
}


def _alert_text(alert: dict[str, Any]) -> str:
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    return " ".join(
        str(value)
        for value in (
            alert.get("alert_name"), labels.get("alertname"),
            annotations.get("summary"), annotations.get("description"),
        )
        if value
    ).lower()


def classify_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Classify an alert by stable names/annotations, preserving its severity."""
    labels = alert.get("labels") or {}
    text = re.sub(r"[^a-z0-9]+", "", _alert_text(alert))
    category, ownership = "unknown", "unknown"
    for candidate, keywords, domain in _CLASSIFIERS:
        if any(re.sub(r"[^a-z0-9]+", "", keyword.lower()) in text for keyword in keywords):
            category, ownership = candidate, domain
            break
    severity = str(alert.get("severity") or labels.get("severity") or "").lower()
    if not severity:
        severity = {
            "availability": "critical",
            "crash_loop": "high",
            "oom": "high",
            "http_5xx": "high",
            "high_cpu": "medium",
            "probe_failure": "medium",
        }.get(category, "low")
    return {
        "category": category,
        "ownership": ownership,
        "severity": severity,
        "severity_source": (
            "Alertmanager label" if alert.get("severity") or labels.get("severity")
            else "derived fallback; alert did not provide severity"
        ),
        "alert_name": redact_text(
            str(alert.get("alert_name") or labels.get("alertname") or "unknown"),
            max_length=128,
        ),
        "namespace": alert.get("namespace") or labels.get("namespace"),
        "workload": (
            alert.get("workload") or labels.get("deployment")
            or labels.get("workload") or labels.get("job")
        ),
        "pod": alert.get("pod") or labels.get("pod"),
    }


def get_investigation_plan(
    alert_name: str, namespace: str | None = None
) -> dict[str, Any]:
    """Return a targeted, deterministic tool plan for a currently active alert."""
    from .alert_tools import get_alert_details

    details = get_alert_details(alert_name, namespace)
    if details.get("error"):
        return details
    if not details["alerts"]:
        return {
            "error": "No matching active Alertmanager alert",
            "alert_name": alert_name,
            "namespace": namespace,
        }
    alert = details["alerts"][0]
    classification = classify_alert(alert)
    alert_namespace = classification.get("namespace")
    if alert_namespace and alert_namespace != "unknown":
        try:
            validate_namespace(alert_namespace)
        except ValueError as exc:
            return {
                "error": "Alert is outside the enabled troubleshooting scope",
                "detail": str(exc),
                "classification": classification,
            }
    workload = classification.get("workload")
    if workload and workload != "unknown":
        try:
            validate_workload(workload)
        except ValueError:
            classification["workload"] = None
    registration = register_incident(alert)
    return {
        "incident": registration["incident"],
        "duplicate_active_incident": registration["duplicate_active"],
        "reactivated_incident": registration["reactivated"],
        "classification": classification,
        "selected_skill": {
            "http_5xx": "root-cause-analysis",
            "crash_loop": "kubernetes-troubleshooting",
            "oom": "kubernetes-troubleshooting",
            "high_cpu": "kubernetes-troubleshooting",
            "probe_failure": "kubernetes-troubleshooting",
            "image_pull": "kubernetes-troubleshooting",
            "pending": "kubernetes-troubleshooting",
            "deployment_degraded": "remediation-recommendation",
            "argocd_degraded": "remediation-recommendation",
            "availability": "incident-triage",
            "container_restart": "kubernetes-troubleshooting",
            "unknown": "root-cause-analysis",
        }[classification["category"]],
        "targeted_tools": _CATEGORY_TOOLS[classification["category"]],
        "safety": "Read-only evidence collection; remediation requires human action.",
    }


def validate_recovery(
    namespace: str, workload: str, incident_id: str | None = None
) -> dict[str, Any]:
    """Verify alert, deployment, endpoint, and metrics before declaring recovery."""
    validate_namespace(namespace)
    validate_workload(workload)
    from .alert_tools import get_active_alerts
    from .kubernetes_tools import get_deployment_status, get_pod_restarts
    from .prometheus_tools import get_application_health
    from .kubernetes_tools import check_application_endpoint

    alerts = get_active_alerts()
    deployment = get_deployment_status(namespace, workload)
    health = get_application_health(namespace, workload)
    endpoint = check_application_endpoint(namespace, "/health", workload)
    restarts = get_pod_restarts(namespace, workload)
    evidence = {
        "alerts": alerts,
        "deployment": deployment,
        "application_health": health,
        "endpoint": endpoint,
        "restarts": restarts,
    }
    errors = [
        key for key, value in evidence.items()
        if isinstance(value, dict) and value.get("error")
    ]
    if errors:
        status = "VALIDATION_INCONCLUSIVE"
        reason = f"Required telemetry is unavailable: {', '.join(errors)}"
    else:
        active = [
            alert for alert in alerts.get("alerts", [])
            if alert.get("namespace") == namespace
            and alert.get("workload") in {workload, "unknown"}
        ]
        desired = deployment.get("desired_replicas")
        available = deployment.get("available_replicas")
        endpoint_ok = endpoint.get("status_code") == 200
        metrics_ok = (
            health.get("all_targets_healthy") is True
            and health.get("prometheus_health") == "HEALTHY"
        )
        replicas_ok = (
            isinstance(desired, int) and desired > 0
            and isinstance(available, int) and available >= desired
        )
        if active:
            status, reason = "STILL_ACTIVE", "A matching active alert remains."
        elif replicas_ok and endpoint_ok and metrics_ok:
            status, reason = (
                "RECOVERED",
                "No matching active alert; all desired replicas are available; "
                "the health endpoint and Prometheus targets are healthy.",
            )
        elif available and available > 0:
            status, reason = (
                "PARTIALLY_RECOVERED",
                "Some workload capacity is available, but one or more recovery "
                "checks have not passed.",
            )
        else:
            status, reason = (
                "STILL_ACTIVE",
                "The workload has no available replicas or critical recovery checks failed.",
            )
    if incident_id:
        from .incident_state import update_incident

        update_incident(
            incident_id,
            {
                "RECOVERED": "RECOVERED",
                "PARTIALLY_RECOVERED": "VALIDATING",
                "STILL_ACTIVE": "STILL_ACTIVE",
                "VALIDATION_INCONCLUSIVE": "INCONCLUSIVE",
            }[status],
            validation_result=reason,
        )
    return {
        "status": status,
        "namespace": namespace,
        "workload": workload,
        "reason": reason,
        "evidence": evidence,
        "limitations": [
            "Recovery is not inferred from pod Running state alone.",
            "Restart stability is reported from the current restart snapshot; "
            "a historical trend is not available in this check.",
        ],
    }

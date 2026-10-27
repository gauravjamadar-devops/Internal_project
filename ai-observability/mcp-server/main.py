"""AI DevOps incident-response MCP server (read-only evidence tools)."""
from __future__ import annotations

import functools
import inspect
import logging
import os
import sys
import time
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
from tools import alert_tools, argocd_tools, incident_state, incident_workflow
from tools import kubernetes_tools as k8s
from tools import prometheus_tools as prom

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
_logger = logging.getLogger("devops-observability")

mcp = FastMCP(
    name="devops-observability",
    instructions=(
        "You are an evidence-based DevOps incident investigation assistant. "
        "Use active Alertmanager data first, obtain a targeted investigation plan, "
        "and call only relevant read-only tools. Distinguish observed facts from "
        "inference, report telemetry errors and limitations, and never perform "
        "remediation. The human follows the GitOps process and approves changes."
    ),
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_PORT", "8080")),
)


def _audited(function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        namespace = inspect.signature(function).bind_partial(
            *args, **kwargs
        ).arguments.get("namespace")
        _logger.info(
            "mcp_tool_start tool=%s namespace=%s",
            function.__name__,
            namespace if isinstance(namespace, str) else "not-applicable",
        )
        try:
            result = function(*args, **kwargs)
        except Exception as error:
            _logger.warning(
                "mcp_tool_failure tool=%s error_type=%s duration_ms=%.2f",
                function.__name__,
                type(error).__name__,
                (time.monotonic() - started) * 1000,
            )
            raise
        is_error = isinstance(result, dict) and "error" in result
        _logger.info(
            "mcp_tool_complete tool=%s outcome=%s duration_ms=%.2f",
            function.__name__,
            "error" if is_error else "success",
            (time.monotonic() - started) * 1000,
        )
        return result

    return wrapper


def _register_alerts(result: dict[str, Any]) -> dict[str, Any]:
    if "error" in result:
        return result
    alerts = result.get("alerts", [])
    for alert in alerts:
        registration = incident_state.register_incident(alert)
        alert["incident_id"] = registration["incident"]["incident_id"]
        alert["duplicate_active_incident"] = registration["duplicate_active"]
        alert["reactivated_incident"] = registration["reactivated"]
    return result


@mcp.tool()
@_audited
def get_active_alerts_tool() -> dict[str, Any]:
    """Fetch active dev alerts from the configured Alertmanager and deduplicate incident state."""
    return _register_alerts(alert_tools.get_active_alerts())


@mcp.tool()
@_audited
def get_alert_details_tool(alert_name: str, namespace: str | None = None) -> dict[str, Any]:
    """Fetch details for an exact currently active alert name in the enabled namespace."""
    result = alert_tools.get_alert_details(alert_name, namespace)
    if "error" not in result:
        _register_alerts(result)
    return result


@mcp.tool()
@_audited
def get_silenced_alerts_tool() -> dict[str, Any]:
    """List active Alertmanager silences without comments or creator details."""
    return alert_tools.get_silenced_alerts()


@mcp.tool()
@_audited
def get_investigation_plan_tool(
    alert_name: str, namespace: str | None = None
) -> dict[str, Any]:
    """Classify an active alert and return its targeted tool path and selected skill."""
    return incident_workflow.get_investigation_plan(alert_name, namespace)


@mcp.tool()
@_audited
def classify_alert_tool(alert_name: str, namespace: str | None = None) -> dict[str, Any]:
    """Return a deterministic category and ownership classification for an active alert."""
    result = alert_tools.get_alert_details(alert_name, namespace)
    if "error" in result:
        return result
    if not result["alerts"]:
        return {"error": "No matching active Alertmanager alert"}
    return incident_workflow.classify_alert(result["alerts"][0])


@mcp.tool()
@_audited
def get_pods_tool(namespace: str, workload: str | None = None) -> dict[str, Any]:
    """List readiness, restart count, phase, and node for allowlisted workload pods."""
    return k8s.get_pods(namespace, workload)


@mcp.tool()
@_audited
def get_pod_status_tool(namespace: str, pod: str) -> dict[str, Any]:
    """Read detailed state, conditions, and termination information for an allowlisted pod."""
    return k8s.get_pod_status(namespace, pod)


@mcp.tool()
@_audited
def get_pod_restarts_tool(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    """List restart counts for allowlisted workload containers."""
    return k8s.get_pod_restarts(namespace, workload)


@mcp.tool()
@_audited
def get_deployment_status_tool(namespace: str, deployment: str) -> dict[str, Any]:
    """Read replica health, image, resource requests/limits, probes, and rollout conditions."""
    return k8s.get_deployment_status(namespace, deployment)


@mcp.tool()
@_audited
def get_replicaset_status_tool(
    namespace: str, deployment: str | None = None
) -> dict[str, Any]:
    """Read ReplicaSet readiness and revision for allowlisted deployments."""
    return k8s.get_replicaset_status(namespace, deployment)


@mcp.tool()
@_audited
def get_kubernetes_events_tool(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    """Return up to 20 recent warning events, optionally filtered to one workload."""
    return k8s.get_kubernetes_events(namespace, workload)


@mcp.tool()
@_audited
def get_recent_rollout_tool(namespace: str, deployment: str) -> dict[str, Any]:
    """Read recent ReplicaSet revisions and deployment revision without changing the rollout."""
    return k8s.get_recent_rollout(namespace, deployment)


@mcp.tool()
@_audited
def describe_workload_tool(namespace: str, workload: str) -> dict[str, Any]:
    """Summarize an allowlisted deployment, its pods, and ReplicaSets without environment values."""
    return k8s.describe_workload(namespace, workload)


@mcp.tool()
@_audited
def get_pod_logs_tool(
    namespace: str,
    pod: str,
    container: str | None = None,
    tail_lines: int = 200,
) -> dict[str, Any]:
    """Read bounded, redacted current logs from an allowlisted pod container."""
    return k8s.get_pod_logs(namespace, pod, container, tail_lines)


@mcp.tool()
@_audited
def get_previous_pod_logs_tool(
    namespace: str,
    pod: str,
    container: str | None = None,
    tail_lines: int = 200,
) -> dict[str, Any]:
    """Read bounded, redacted logs from the previous container instance."""
    return k8s.get_previous_pod_logs(namespace, pod, container, tail_lines)


@mcp.tool()
@_audited
def search_pod_logs_tool(
    namespace: str,
    workload: str,
    patterns: list[str],
    tail_lines: int = 500,
) -> dict[str, Any]:
    """Search bounded allowlisted workload logs using up to five literal patterns."""
    return k8s.search_pod_logs(namespace, workload, patterns, tail_lines)


@mcp.tool()
@_audited
def query_prometheus_tool(query: str) -> dict[str, Any]:
    """Run one exact pre-approved dev PromQL expression; arbitrary PromQL is rejected."""
    return prom.query_prometheus(query)


@mcp.tool()
@_audited
def get_error_rate_tool(
    namespace: str, window: str = "5m", workload: str | None = None
) -> dict[str, Any]:
    """Return 5xx rate, total request rate, error percentage, and simulated errors."""
    return prom.get_error_rate(namespace, window, workload)


@mcp.tool()
@_audited
def get_request_rate_tool(
    namespace: str, workload: str | None = None, window: str = "5m"
) -> dict[str, Any]:
    """Return an application request rate over an allowed Prometheus time window."""
    return prom.get_request_rate(namespace, workload, window)


@mcp.tool()
@_audited
def get_request_latency_tool(
    namespace: str, workload: str | None = None, window: str = "5m"
) -> dict[str, Any]:
    """Return P99 request latency from application histogram buckets."""
    return prom.get_request_latency(namespace, workload, window)


@mcp.tool()
@_audited
def get_resource_usage_tool(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    """Query available CPU/memory usage, requests, and limits without inventing missing metrics."""
    return prom.get_resource_usage(namespace, workload)


@mcp.tool()
@_audited
def get_pod_cpu_tool(namespace: str, pod: str | None = None) -> dict[str, Any]:
    """Read CPU usage for the configured workload or one of its pods."""
    return prom.get_pod_cpu(namespace, pod)


@mcp.tool()
@_audited
def get_pod_memory_tool(namespace: str, pod: str | None = None) -> dict[str, Any]:
    """Read memory working set for the configured workload or one of its pods."""
    return prom.get_pod_memory(namespace, pod)


@mcp.tool()
@_audited
def get_available_replicas_tool(namespace: str, deployment: str) -> dict[str, Any]:
    """Read available replicas from kube-state-metrics."""
    return prom.get_available_replicas(namespace, deployment)


@mcp.tool()
@_audited
def get_container_restart_metrics_tool(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    """Read container restart counters from Prometheus for the selected workload."""
    return prom.get_container_restart_metrics(namespace, workload)


@mcp.tool()
@_audited
def get_application_health_tool(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    """Summarize scrape health, request/error rates, and P99 latency."""
    return prom.get_application_health(namespace, workload)


@mcp.tool()
@_audited
def check_application_endpoint_tool(
    namespace: str,
    endpoint: str = "/health",
    workload: str = "fastapi-dev-deployment",
) -> dict[str, Any]:
    """Check only the configured in-cluster application service and approved endpoint paths."""
    return k8s.check_application_endpoint(namespace, endpoint, workload)


@mcp.tool()
@_audited
def validate_recovery_tool(
    namespace: str,
    workload: str = "fastapi-dev-deployment",
    incident_id: str | None = None,
) -> dict[str, Any]:
    """Validate alert clearance, ready replicas, health endpoint, and Prometheus before reporting recovery."""
    return incident_workflow.validate_recovery(namespace, workload, incident_id)


@mcp.tool()
@_audited
def get_argocd_application_status_tool(application: str) -> dict[str, Any]:
    """Read sync and health state for the allowlisted ArgoCD application."""
    return argocd_tools.get_argocd_application_status(application)


@mcp.tool()
@_audited
def get_argocd_sync_status_tool(application: str) -> dict[str, Any]:
    """Read sync/health status for the allowlisted ArgoCD application."""
    return argocd_tools.get_argocd_sync_status(application)


@mcp.tool()
@_audited
def get_current_image_tool(namespace: str, deployment: str) -> dict[str, Any]:
    """Read the currently configured container image without exposing environment values."""
    return argocd_tools.get_current_image(namespace, deployment)


@mcp.tool()
@_audited
def get_deployment_revision_tool(namespace: str, deployment: str) -> dict[str, Any]:
    """Read the deployment revision and observed generation."""
    return argocd_tools.get_deployment_revision(namespace, deployment)


@mcp.tool()
@_audited
def get_incidents_tool(limit: int = 50) -> dict[str, Any]:
    """List recent tracked incident state records (maximum 100)."""
    return {"incidents": incident_state.get_incidents(limit)}


@mcp.tool()
@_audited
def update_incident_state_tool(
    incident_id: str,
    status: str,
    probable_cause: str | None = None,
    recommended_solution: str | None = None,
    validation_result: str | None = None,
) -> dict[str, Any]:
    """Record an investigation state and redacted summary; this does not remediate workloads."""
    return incident_state.update_incident(
        incident_id,
        status,
        probable_cause,
        recommended_solution,
        validation_result,
    )


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError("MCP_TRANSPORT must be either 'stdio' or 'streamable-http'")
    mcp.run(transport=transport)

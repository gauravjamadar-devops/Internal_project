"""Approved Prometheus queries for the dev FastAPI workload."""
from __future__ import annotations

import os
from typing import Any

import httpx
import yaml

from .security import (
    allowed_workloads,
    approved_service_url,
    redact_text,
    validate_namespace,
    validate_pod_name,
    validate_workload,
)

_CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml")
)
_ALLOWED_WINDOWS = {"1m", "5m", "15m"}
_DEFAULT_PROMETHEUS_URL = (
    "http://monitoring-kube-prometheus-prometheus.monitoring.svc:9090"
)
def _load_config() -> dict[str, Any]:
    path = os.environ.get("MCP_CONFIG_PATH", _CONFIG_PATH)
    with open(path, encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _prometheus_url() -> str:
    config_url = (
        _load_config().get("prometheus", {}).get("url", _DEFAULT_PROMETHEUS_URL)
    )
    return approved_service_url("PROMETHEUS_URL", config_url)


def _validate_window(window: str) -> None:
    if window not in _ALLOWED_WINDOWS:
        raise ValueError(f"window must be one of: {', '.join(sorted(_ALLOWED_WINDOWS))}")


def _workload_selector(workload: str | None) -> str:
    selected = workload or next(iter(sorted(allowed_workloads())), "")
    validate_workload(selected)
    return selected + r"-.*"


def _query(promql: str) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as http:
            response = http.get(
                f"{_prometheus_url()}/api/v1/query", params={"query": promql}
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != "success":
            return {"error": "Prometheus returned an unsuccessful or invalid response"}
        response_data = payload.get("data")
        results = response_data.get("result") if isinstance(response_data, dict) else None
        if not isinstance(results, list):
            return {"error": "Prometheus response is missing query results"}
        return {"status": "success", "result": results}
    except httpx.HTTPStatusError as error:
        return {"error": f"Prometheus returned HTTP {error.response.status_code}"}
    except httpx.RequestError as error:
        return {
            "error": f"Cannot reach the configured Prometheus service: "
                     f"{redact_text(str(error), max_length=250)}"
        }
    except ValueError as error:
        return {"error": f"Invalid Prometheus response: {redact_text(str(error), max_length=200)}"}


def _scalar(result: dict[str, Any]) -> float | None:
    items = result.get("result", [])
    if not items:
        return None
    try:
        return float(items[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def query_prometheus(query: str) -> dict[str, Any]:
    """Run only pre-approved dev expressions; arbitrary PromQL is rejected."""
    approved = {
        'up{namespace="dev"}',
        'sum(rate(app_requests_total{namespace="dev"}[5m]))',
        'sum(rate(app_requests_total{status=~"5..",namespace="dev"}[5m]))',
        'sum(increase(app_http_errors_total{namespace="dev"}[5m]))',
        'sum(rate(container_cpu_usage_seconds_total{namespace="dev",container!="",pod=~"fastapi-dev-deployment-.*"}[5m]))',
        'sum(container_memory_working_set_bytes{namespace="dev",container!="",pod=~"fastapi-dev-deployment-.*"})',
    }
    if not isinstance(query, str) or query not in approved:
        raise ValueError("query must exactly match a pre-approved dev PromQL expression")
    return _query(query)


def get_error_rate(
    namespace: str, window: str = "5m", workload: str | None = None
) -> dict[str, Any]:
    validate_namespace(namespace)
    selector = _workload_selector(workload)
    _validate_window(window)
    base = f'namespace="{namespace}",pod=~"{selector}"'
    queries = {
        "http_5xx_rate_per_sec": (
            f'sum(rate(app_requests_total{{status=~"5..",{base}}}[{window}]))'
        ),
        "total_request_rate_per_sec": (
            f'sum(rate(app_requests_total{{{base}}}[{window}]))'
        ),
        "simulated_errors_in_window": (
            f'sum(increase(app_http_errors_total{{{base}}}[{window}]))'
        ),
    }
    results = {name: _query(query) for name, query in queries.items()}
    errors = {
        name: result["error"] for name, result in results.items()
        if "error" in result
    }
    if errors:
        return {
            "error": "One or more Prometheus queries failed",
            "namespace": namespace,
            "workload": workload or next(iter(sorted(allowed_workloads())), ""),
            "query_errors": errors,
        }
    error_rate = _scalar(results["http_5xx_rate_per_sec"]) or 0.0
    total_rate = _scalar(results["total_request_rate_per_sec"]) or 0.0
    simulated = _scalar(results["simulated_errors_in_window"]) or 0.0
    error_pct = f"{(error_rate / total_rate) * 100:.2f}%" if total_rate > 0 else "N/A"
    return {
        "namespace": namespace,
        "workload": workload or next(iter(sorted(allowed_workloads())), ""),
        "window": window,
        "http_5xx_rate_per_sec": error_rate,
        "total_request_rate_per_sec": total_rate,
        "error_percentage": error_pct,
        "simulated_errors_in_window": simulated,
    }


def get_request_rate(
    namespace: str, workload: str | None = None, window: str = "5m"
) -> dict[str, Any]:
    validate_namespace(namespace)
    selector = _workload_selector(workload)
    _validate_window(window)
    result = _query(
        f'sum(rate(app_requests_total{{namespace="{namespace}",pod=~"{selector}"}}[{window}]))'
    )
    if "error" in result:
        return result
    return {
        "namespace": namespace,
        "workload": workload or next(iter(sorted(allowed_workloads())), ""),
        "window": window,
        "requests_per_sec": _scalar(result) or 0.0,
    }


def get_request_latency(
    namespace: str, workload: str | None = None, window: str = "5m"
) -> dict[str, Any]:
    validate_namespace(namespace)
    selector = _workload_selector(workload)
    _validate_window(window)
    result = _query(
        "histogram_quantile(0.99, "
        f'sum(rate(app_request_duration_seconds_bucket{{namespace="{namespace}",'
        f'pod=~"{selector}"}}[{window}])) by (le))'
    )
    if "error" in result:
        return result
    return {
        "namespace": namespace,
        "workload": workload or next(iter(sorted(allowed_workloads())), ""),
        "window": window,
        "p99_latency_seconds": _scalar(result),
    }


def get_resource_usage(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    validate_namespace(namespace)
    selector = _workload_selector(workload)
    expressions = {
        "cpu_cores": (
            f'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}",'
            f'pod=~"{selector}"}}[5m]))'
        ),
        "memory_working_set_bytes": (
            f'sum(container_memory_working_set_bytes{{namespace="{namespace}",'
            f'pod=~"{selector}"}})'
        ),
        "cpu_requests_cores": (
            f'sum(kube_pod_container_resource_requests{{namespace="{namespace}",'
            f'resource="cpu",pod=~"{selector}"}})'
        ),
        "memory_requests_bytes": (
            f'sum(kube_pod_container_resource_requests{{namespace="{namespace}",'
            f'resource="memory",pod=~"{selector}"}})'
        ),
        "cpu_limits_cores": (
            f'sum(kube_pod_container_resource_limits{{namespace="{namespace}",'
            f'resource="cpu",pod=~"{selector}"}})'
        ),
        "memory_limits_bytes": (
            f'sum(kube_pod_container_resource_limits{{namespace="{namespace}",'
            f'resource="memory",pod=~"{selector}"}})'
        ),
    }
    output: dict[str, Any] = {
        "namespace": namespace,
        "workload": workload or next(iter(sorted(allowed_workloads())), ""),
        "metrics": {},
        "unavailable_metrics": [],
    }
    for metric, expression in expressions.items():
        result = _query(expression)
        if "error" in result:
            output["unavailable_metrics"].append({"metric": metric, "error": result["error"]})
        else:
            output["metrics"][metric] = _scalar(result)
    if output["unavailable_metrics"] and not output["metrics"]:
        output["error"] = "Prometheus resource telemetry is unavailable"
    return output


def get_pod_cpu(namespace: str, pod: str | None = None) -> dict[str, Any]:
    return _pod_resource_metric(namespace, pod, "cpu")


def get_pod_memory(namespace: str, pod: str | None = None) -> dict[str, Any]:
    return _pod_resource_metric(namespace, pod, "memory")


def _pod_resource_metric(
    namespace: str, pod: str | None, resource: str
) -> dict[str, Any]:
    validate_namespace(namespace)
    workload = next(iter(sorted(allowed_workloads())), "")
    validate_workload(workload)
    if pod is not None:
        validate_pod_name(pod)
        if not pod.startswith(workload + "-"):
            raise ValueError("Pod is outside the configured workload allowlist")
        pod_matcher = f'pod="{pod}"'
    else:
        pod_matcher = f'pod=~"{workload}-.*"'
    metric = (
        "container_cpu_usage_seconds_total" if resource == "cpu"
        else "container_memory_working_set_bytes"
    )
    aggregation = f"sum(rate({metric}" if resource == "cpu" else f"sum({metric}"
    window = "[5m]" if resource == "cpu" else ""
    result = _query(
        f'{aggregation}{{namespace="{namespace}",{pod_matcher}}}'
        f'{window}{"))" if resource == "cpu" else ")"}'
    )
    if "error" in result:
        return result
    return {
        "namespace": namespace,
        "workload": workload,
        "pod": pod,
        "resource": resource,
        "unit": "cores" if resource == "cpu" else "bytes",
        "value": _scalar(result),
    }


def get_available_replicas(namespace: str, deployment: str) -> dict[str, Any]:
    validate_namespace(namespace)
    validate_workload(deployment)
    result = _query(
        f'kube_deployment_status_replicas_available{{namespace="{namespace}",'
        f'deployment="{deployment}"}}'
    )
    if "error" in result:
        return result
    value = _scalar(result)
    return {
        "namespace": namespace,
        "deployment": deployment,
        "available_replicas": int(value) if value is not None else None,
        "metric_available": value is not None,
    }


def get_container_restart_metrics(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    validate_namespace(namespace)
    selector = _workload_selector(workload)
    result = _query(
        f'kube_pod_container_status_restarts_total{{namespace="{namespace}",'
        f'pod=~"{selector}"}}'
    )
    if "error" in result:
        return result
    values = [
        {
            "pod": item.get("metric", {}).get("pod"),
            "container": item.get("metric", {}).get("container"),
            "restarts": float(item.get("value", [None, "0"])[1]),
        }
        for item in result.get("result", [])
    ]
    return {"namespace": namespace, "workload": workload, "containers": values}


def get_application_health(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    validate_namespace(namespace)
    selector = _workload_selector(workload)
    expressions = {
        "scrape_status": (
            f'up{{job=~".*fastapi.*",namespace="{namespace}",pod=~"{selector}"}}'
        ),
        "request_rate": (
            f'sum(rate(app_requests_total{{namespace="{namespace}",'
            f'pod=~"{selector}"}}[5m]))'
        ),
        "error_rate": (
            f'sum(rate(app_requests_total{{status=~"5..",namespace="{namespace}",'
            f'pod=~"{selector}"}}[5m]))'
        ),
        "p99_latency": (
            "histogram_quantile(0.99, "
            f'sum(rate(app_request_duration_seconds_bucket{{namespace="{namespace}",'
            f'pod=~"{selector}"}}[5m])) by (le))'
        ),
    }
    results = {key: _query(expression) for key, expression in expressions.items()}
    errors = {key: value["error"] for key, value in results.items() if "error" in value}
    if errors:
        return {
            "namespace": namespace,
            "workload": workload,
            "prometheus_health": "ERROR",
            "query_errors": errors,
        }
    targets = results["scrape_status"].get("result", [])
    all_up = bool(targets) and all(
        float(target.get("value", [None, "0"])[1]) == 1 for target in targets
    )
    request_rate = _scalar(results["request_rate"])
    error_rate = _scalar(results["error_rate"])
    error_pct = (
        f"{(error_rate / request_rate) * 100:.2f}%"
        if error_rate is not None and request_rate and request_rate > 0 else "N/A"
    )
    if not targets:
        health = "UNKNOWN — not being scraped by Prometheus"
    elif not all_up:
        health = "DEGRADED — some scrape targets are down"
    elif error_rate and error_rate > 0:
        health = "DEGRADED — active 5xx errors"
    else:
        health = "HEALTHY"
    return {
        "namespace": namespace,
        "workload": workload or next(iter(sorted(allowed_workloads())), ""),
        "prometheus_health": health,
        "scrape_targets_up": sum(
            float(target.get("value", [None, "0"])[1]) == 1 for target in targets
        ),
        "all_targets_healthy": all_up,
        "request_rate_per_sec": request_rate,
        "error_rate_per_sec": error_rate,
        "error_percentage": error_pct,
        "p99_latency_seconds": _scalar(results["p99_latency"]),
    }

"""
Prometheus tools for the AI DevOps Observability MCP Server.

Queries the Prometheus HTTP API to retrieve application-level metrics
(error rate, request rate, latency) for the FastAPI service.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import yaml

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml")

def _load_config() -> dict:
    """Load MCP server config from YAML file."""
    config_path = os.environ.get("MCP_CONFIG_PATH", _CONFIG_PATH)
    try:
        with open(config_path) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {}


def _prometheus_url() -> str:
    """Return Prometheus base URL from env var or config file."""
    return os.environ.get(
        "PROMETHEUS_URL",
        _load_config().get("prometheus", {}).get("url", "http://localhost:9090"),
    )


# ---------------------------------------------------------------------------
# PromQL query helper
# ---------------------------------------------------------------------------
def _query(promql: str) -> dict[str, Any]:
    """Execute an instant PromQL query against Prometheus and return results."""
    url = f"{_prometheus_url()}/api/v1/query"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params={"query": promql})
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success":
                return {"error": f"Prometheus returned status: {data.get('status')}", "query": promql}
            return {"status": "success", "result": data["data"]["result"]}
    except httpx.ConnectError:
        return {
            "error": f"Cannot connect to Prometheus at {_prometheus_url()}. "
                     "If running locally, ensure: kubectl port-forward svc/prometheus-operated 9090:9090 -n monitoring",
            "query": promql,
        }
    except Exception as e:
        return {"error": str(e), "query": promql}


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------
def get_error_rate(namespace: str, window: str = "5m") -> dict[str, Any]:
    """
    Return the HTTP 5xx error rate for the FastAPI app in the given namespace.

    Uses app_requests_total metric (instrumented in FastAPI app).
    Returns rate per second over the specified window (default: 5m).
    """
    # Total 5xx rate
    error_query = (
        f'sum(rate(app_requests_total{{status=~"5..",namespace="{namespace}"}}[{window}]))'
    )
    # Total request rate (for error %)
    total_query = (
        f'sum(rate(app_requests_total{{namespace="{namespace}"}}[{window}]))'
    )
    # Intentional simulate-error counter
    simulated_query = (
        f'sum(increase(app_http_errors_total{{namespace="{namespace}"}}[{window}]))'
    )

    error_result = _query(error_query)
    total_result = _query(total_query)
    simulated_result = _query(simulated_query)

    def _extract_value(result: dict) -> float | str:
        """Extract scalar value from PromQL instant query result."""
        if "error" in result:
            return result["error"]
        items = result.get("result", [])
        if not items:
            return 0.0
        return float(items[0]["value"][1])

    error_rate = _extract_value(error_result)
    total_rate = _extract_value(total_result)
    simulated = _extract_value(simulated_result)

    error_pct = "N/A"
    if isinstance(error_rate, float) and isinstance(total_rate, float) and total_rate > 0:
        error_pct = f"{(error_rate / total_rate) * 100:.2f}%"

    return {
        "namespace": namespace,
        "window": window,
        "http_5xx_rate_per_sec": error_rate,
        "total_request_rate_per_sec": total_rate,
        "error_percentage": error_pct,
        "simulated_errors_in_window": simulated,
        "prometheus_url": _prometheus_url(),
    }


def get_application_health(namespace: str) -> dict[str, Any]:
    """
    Return a composite application health summary using Prometheus metrics:
    - Is the FastAPI service being scraped (up metric)?
    - Current request rate
    - Error rate
    - P99 latency

    Complements Kubernetes pod health from kubernetes_tools.
    """
    config = _load_config()
    job = config.get("fastapi_job", "fastapi-servicemonitor")

    # Scrape target health
    up_query = f'up{{job=~".*fastapi.*",namespace="{namespace}"}}'
    req_rate_query = f'sum(rate(app_requests_total{{namespace="{namespace}"}}[5m]))'
    error_rate_query = f'sum(rate(app_requests_total{{status=~"5..",namespace="{namespace}"}}[5m]))'
    p99_query = (
        f'histogram_quantile(0.99, sum(rate(app_request_duration_seconds_bucket{{namespace="{namespace}"}}[5m])) by (le))'
    )

    up_result     = _query(up_query)
    req_result    = _query(req_rate_query)
    error_result  = _query(error_rate_query)
    p99_result    = _query(p99_query)

    def _val(r: dict) -> Any:
        if "error" in r:
            return r["error"]
        items = r.get("result", [])
        if not items:
            return None
        return float(items[0]["value"][1])

    scrape_targets = up_result.get("result", [])
    all_up = all(float(t["value"][1]) == 1.0 for t in scrape_targets) if scrape_targets else False

    req_rate  = _val(req_result)
    error_rate = _val(error_result)
    p99_latency = _val(p99_result)

    error_pct = "N/A"
    if isinstance(req_rate, float) and isinstance(error_rate, float) and req_rate > 0:
        error_pct = f"{(error_rate / req_rate) * 100:.2f}%"

    # Simple health determination
    health = "HEALTHY"
    if not scrape_targets:
        health = "UNKNOWN — not being scraped by Prometheus"
    elif not all_up:
        health = "DEGRADED — some scrape targets are down"
    elif isinstance(error_rate, float) and error_rate > 0:
        health = "DEGRADED — active 5xx errors"

    return {
        "namespace": namespace,
        "prometheus_health": health,
        "scrape_targets_up": len(scrape_targets),
        "all_targets_healthy": all_up,
        "request_rate_per_sec": req_rate,
        "error_rate_per_sec": error_rate,
        "error_percentage": error_pct,
        "p99_latency_seconds": p99_latency,
        "prometheus_url": _prometheus_url(),
    }

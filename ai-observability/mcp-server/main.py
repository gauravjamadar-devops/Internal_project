"""
AI DevOps Observability MCP Server
===================================
Exposes 6 read-only DevOps tools via the Model Context Protocol (MCP).

Tools:
    1. get_pods(namespace)              - List pods and their phase/ready/restart status
    2. get_pod_status(namespace, pod)   - Detailed status for a specific pod
    3. get_pod_restarts(namespace)      - Restart counts, sorted highest first
    4. get_kubernetes_events(namespace) - Warning-level Kubernetes events
    5. get_error_rate(namespace)        - HTTP 5xx error rate via Prometheus PromQL
    6. get_application_health(namespace)- Composite health: scrape status + metrics

Transport:
    - stdio (for local AI client integration, e.g. Claude Desktop / Antigravity)
    - Runs inside Kubernetes pod using in-cluster ServiceAccount for K8s auth

Usage:
    python main.py

Environment variables:
    PROMETHEUS_URL   - Override Prometheus URL (default: from config.yaml)
    MCP_CONFIG_PATH  - Override config file path
    MCP_TRANSPORT    - stdio (default) or streamable-http
    MCP_HOST         - HTTP bind address (default: 127.0.0.1)
    MCP_PORT         - HTTP bind port (default: 8080)
"""
import os
import sys

# Ensure the mcp-server directory is on the path when running directly
sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
from tools import (
    get_pods,
    get_pod_status,
    get_pod_restarts,
    get_kubernetes_events,
    get_error_rate,
    get_application_health,
)

# ---------------------------------------------------------------------------
# Create MCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="devops-observability",
    instructions=(
        "You are an AI DevOps Observability Assistant. "
        "You have access to real Kubernetes and Prometheus data. "
        "Use the available tools to investigate incidents, diagnose pod failures, "
        "analyse error rates, and produce evidence-based incident reports. "
        "Always retrieve live data before drawing conclusions. "
        "When asked to 'investigate', call multiple tools to gather a full picture."
    ),
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_PORT", "8080")),
)

# ---------------------------------------------------------------------------
# Tool 1: get_pods
# ---------------------------------------------------------------------------
@mcp.tool()
def get_pods_tool(namespace: str) -> dict:
    """
    List all pods in the given Kubernetes namespace.

    Returns pod name, phase (Running/Pending/Failed), ready container ratio,
    total restart count, and assigned node.

    Args:
        namespace: Kubernetes namespace to query (e.g. 'dev', 'prod')
    """
    return get_pods(namespace)


# ---------------------------------------------------------------------------
# Tool 2: get_pod_status
# ---------------------------------------------------------------------------
@mcp.tool()
def get_pod_status_tool(namespace: str, pod_name: str) -> dict:
    """
    Get detailed status for a specific pod including container states,
    restart counts, pod conditions, and IP information.

    Useful for diagnosing CrashLoopBackOff, OOMKilled, or Pending pods.

    Args:
        namespace: Kubernetes namespace
        pod_name:  Exact pod name (get from get_pods_tool first)
    """
    return get_pod_status(namespace, pod_name)


# ---------------------------------------------------------------------------
# Tool 3: get_pod_restarts
# ---------------------------------------------------------------------------
@mcp.tool()
def get_pod_restarts_tool(namespace: str) -> dict:
    """
    Return restart counts for every container in every pod in the namespace.

    Pods are sorted by restart count (highest first). Containers with
    more than 5 restarts are flagged for attention.

    Args:
        namespace: Kubernetes namespace to check (e.g. 'dev', 'prod')
    """
    return get_pod_restarts(namespace)


# ---------------------------------------------------------------------------
# Tool 4: get_kubernetes_events
# ---------------------------------------------------------------------------
@mcp.tool()
def get_kubernetes_events_tool(namespace: str) -> dict:
    """
    Return Warning-level Kubernetes events in the namespace.

    Filters out normal/informational events. Returns the 20 most recent
    warnings sorted by timestamp, including reason, message, and object.

    Useful for detecting OOMKilled, BackOff, Unhealthy, FailedScheduling events.

    Args:
        namespace: Kubernetes namespace to query
    """
    return get_kubernetes_events(namespace)


# ---------------------------------------------------------------------------
# Tool 5: get_error_rate
# ---------------------------------------------------------------------------
@mcp.tool()
def get_error_rate_tool(namespace: str, window: str = "5m") -> dict:
    """
    Query Prometheus for HTTP 5xx error rate for the FastAPI application.

    Uses the app_requests_total metric (instrumented in the FastAPI app).
    Returns both the raw rate/sec and error percentage over the window.

    Tip: call /simulate-error on the dev app first to generate test errors,
    then call this tool to see them appear in metrics.

    Args:
        namespace: Kubernetes namespace (e.g. 'dev', 'prod')
        window:    PromQL rate window (default '5m', options: '1m', '5m', '15m')
    """
    return get_error_rate(namespace, window)


# ---------------------------------------------------------------------------
# Tool 6: get_application_health
# ---------------------------------------------------------------------------
@mcp.tool()
def get_application_health_tool(namespace: str) -> dict:
    """
    Return a composite application health summary combining:
    - Prometheus scrape target status (is FastAPI being scraped?)
    - Current request rate (req/sec)
    - 5xx error rate and percentage
    - P99 request latency

    Health states: HEALTHY | DEGRADED | UNKNOWN

    Args:
        namespace: Kubernetes namespace (e.g. 'dev', 'prod')
    """
    return get_application_health(namespace)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError(
            "MCP_TRANSPORT must be either 'stdio' or 'streamable-http'"
        )
    mcp.run(transport=transport)

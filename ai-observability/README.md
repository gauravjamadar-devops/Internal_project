# AI DevOps Observability Assistant

A lightweight AI observability component that extends the existing FastAPI + Kubernetes + ArgoCD + Prometheus GitOps stack.

## Architecture

```
FastAPI (/metrics)
    ↓ scraped every 30s
Prometheus (kube-prometheus-stack)
    ↓ PromQL HTTP API
MCP Server (ai-observability/mcp-server/)
    ↓ stdio / SSE transport
AI Assistant (Claude / Antigravity)
    ↓ structured investigation
Incident Analysis Report
```

## Directory Structure

```
ai-observability/
├── mcp-server/
│   ├── main.py                  # MCP server entrypoint (6 tools)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── tools/
│       ├── kubernetes_tools.py  # get_pods, get_pod_status, get_pod_restarts, get_kubernetes_events
│       └── prometheus_tools.py  # get_error_rate, get_application_health
├── skills/
│   └── devops_investigator.md   # AI investigation protocol
├── config/
│   └── config.yaml              # Prometheus URL, namespace config
└── k8s/
    ├── rbac.yaml                # Read-only ServiceAccount + ClusterRole
    └── deployment.yaml          # MCP server Deployment + Service
```

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `get_pods_tool(namespace)` | List pods with phase, ready status, restart count |
| `get_pod_status_tool(namespace, pod_name)` | Detailed container state, conditions, IP |
| `get_pod_restarts_tool(namespace)` | Restart counts sorted highest first |
| `get_kubernetes_events_tool(namespace)` | Warning-level K8s events (last 20) |
| `get_error_rate_tool(namespace)` | HTTP 5xx rate + % via PromQL |
| `get_application_health_tool(namespace)` | Composite health: scrape + req rate + P99 latency |

## Quick Start — Local Development

### Prerequisites
```bash
# Ensure Minikube is running
minikube status

# Port-forward Prometheus for local access
kubectl port-forward svc/prometheus-operated 9090:9090 -n monitoring
```

### Install and Run MCP Server Locally
```bash
cd ai-observability/mcp-server
pip install -r requirements.txt

# Set Prometheus to localhost (port-forwarded)
export PROMETHEUS_URL=http://localhost:9090

# Run MCP server
python main.py
```

### Test MCP Tools Directly
```python
# Quick smoke test
from tools.kubernetes_tools import get_pods, get_pod_restarts, get_kubernetes_events
from tools.prometheus_tools import get_error_rate, get_application_health

print(get_pods("dev"))
print(get_pod_restarts("dev"))
print(get_error_rate("dev"))
print(get_application_health("dev"))
```

## Quick Start — Kubernetes Deployment

```bash
# 1. Build MCP server image into Minikube
eval $(minikube docker-env)
docker build -t mcp-observability:latest ./ai-observability/mcp-server

# 2. Apply RBAC
kubectl apply -f ai-observability/k8s/rbac.yaml

# 3. Deploy MCP server
kubectl apply -f ai-observability/k8s/deployment.yaml

# 4. Check it's running
kubectl get pods -n dev -l app=mcp-observability
```

## Testing the Full Flow

### Generate Controlled Errors (dev only)
```bash
# Hit the simulate-error endpoint a few times
MINIKUBE_IP=$(minikube ip)
for i in {1..10}; do curl http://$MINIKUBE_IP:30008/simulate-error; done
```

### Ask the AI to Investigate
With the MCP server running and configured in your AI client:

> "Investigate the dev FastAPI application."

The AI will:
1. Call `get_pods_tool("dev")` — pod health
2. Call `get_pod_restarts_tool("dev")` — restart patterns
3. Call `get_kubernetes_events_tool("dev")` — warning events
4. Call `get_application_health_tool("dev")` — Prometheus metrics
5. Call `get_error_rate_tool("dev")` — HTTP error rate
6. Synthesize into a structured incident report

## Prometheus Validation

After applying the ServiceMonitor fix:
```bash
# Check Prometheus targets
kubectl port-forward svc/prometheus-operated 9090:9090 -n monitoring
# Then open: http://localhost:9090/targets
# Look for: fastapi-servicemonitor target — should be UP

# Test PromQL directly
curl 'http://localhost:9090/api/v1/query?query=app_requests_total'
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMETHEUS_URL` | from config.yaml | Prometheus HTTP API base URL |
| `MCP_CONFIG_PATH` | `../config/config.yaml` | Path to MCP config file |

## FastAPI Changes (main branch)

- **`/simulate-error`** — Returns HTTP 500. Only active when `ENABLE_SIMULATE_ERROR=true`.
  - Enabled in `dev` via `environment/dev/values.yaml`
  - Disabled in `prod` (default `false`)
- **`app_http_errors_total`** — New Prometheus Counter tracking intentional errors

## What Was NOT Changed

- ✅ ArgoCD applications untouched
- ✅ Existing Helm chart structure preserved
- ✅ Prod environment unchanged
- ✅ No second Prometheus/Grafana installed
- ✅ Jenkins CI/CD flow unaffected
- ✅ kube-prometheus-stack untouched (only ServiceMonitor fixed)

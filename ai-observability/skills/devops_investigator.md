---
name: devops-investigator
description: >
  Guides the AI to perform a structured, evidence-based DevOps incident investigation
  using real Kubernetes and Prometheus data from the MCP server tools.
  Activate when the user asks to "investigate", "diagnose", "analyze", or "check"
  an application or namespace.
---

# DevOps Incident Investigator Skill

## When to Activate
Activate this skill when the user:
- Asks to investigate, diagnose, or check an application or environment
- Reports an incident, alert, or anomaly
- Asks "what's wrong with..." or "why is ... failing"
- Asks for an incident analysis or incident report

## Investigation Protocol

When investigating an environment (e.g. "investigate the dev FastAPI application"):

### Step 1 — Gather Kubernetes State
Call ALL of these tools for the target namespace:
1. `get_pods_tool(namespace)` — get pod list and basic health
2. `get_pod_restarts_tool(namespace)` — identify crashing/restarting pods
3. `get_kubernetes_events_tool(namespace)` — surface Warning events

For any pod that is NOT Running or has high restarts:
4. `get_pod_status_tool(namespace, pod_name)` — get detailed container state

### Step 2 — Gather Application Metrics
5. `get_application_health_tool(namespace)` — composite Prometheus health check
6. `get_error_rate_tool(namespace, window="5m")` — HTTP error rate

### Step 3 — Synthesise Findings
Based on the retrieved data, produce an incident report in this format:

---

## INCIDENT ANALYSIS

**Environment:** {namespace}
**Investigation Time:** {current time}

---

### Kubernetes Health

| Pod | Phase | Ready | Restarts | Status |
|-----|-------|-------|----------|--------|
| ... | ...   | ...   | ...      | ...    |

**Pod Restarts Summary:**
- Total restarts in namespace: {N}
- Flagged pods (>5 restarts): {list or "None"}

**Kubernetes Warning Events:**
- {count} warnings found
- Notable: {list key events or "None"}

---

### Application Metrics (from Prometheus)

| Metric | Value |
|--------|-------|
| Prometheus scrape status | UP / DOWN / UNKNOWN |
| Request rate (req/sec) | ... |
| HTTP 5xx error rate (req/sec) | ... |
| Error percentage | ...% |
| P99 Latency | ...s |

---

### Assessment

**Overall Health:** ✅ HEALTHY / ⚠️ DEGRADED / 🔴 CRITICAL

**Root Cause Analysis:**
{Based on evidence, state what is wrong or confirm all is healthy.
If errors are present, correlate them to K8s events or restart patterns.}

**Evidence:**
- {Bullet point each piece of supporting evidence}

**Recommendations:**
- {Actionable next steps based on findings}

---

## Important Rules
- ALWAYS call the tools first — do NOT guess or use knowledge without live data
- If a tool returns an error (e.g. Prometheus unreachable), state this clearly
- Correlate data across tools: high restarts + OOMKilled events = memory issue
- If `/simulate-error` was called recently, connect error rate spikes to that
- Be concise — the report should be scannable by an on-call engineer

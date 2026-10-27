# AI-Assisted Incident Response

## Purpose and safety model

This extension turns the existing observability MCP server into a guided,
human-approved incident workflow. It combines current alert state, Kubernetes
workload evidence, Prometheus telemetry, selected application logs, and
read-only ArgoCD status.

It does **not** execute remediation. It does not restart, scale, delete, sync,
roll back, or change workloads. A recommendation is a proposal for a reviewed
Git change followed by the team's normal GitOps process. The engineer confirms
the change; the MCP server then performs read-only recovery checks.

## System flow

1. `get_active_alerts_tool` fetches active Alertmanager alerts in the configured
   namespace/workload scope and registers stable incident records.
2. `get_investigation_plan_tool` fetches an exact active alert, classifies it,
   validates its scope, deduplicates it, and returns a targeted list of tools.
3. The selected skill guides the AI to collect only the relevant evidence.
4. The AI separates returned facts from hypotheses and records its findings
   with `update_incident_state_tool`.
5. The AI recommends a human-reviewed GitOps change; it makes no cluster
   change.
6. After the engineer confirms remediation, `validate_recovery_tool` checks
   alert clearance, available replicas, the approved health endpoint, and
   Prometheus health. Its status—not a Running pod alone—determines the result.

## Incident states

| State | Meaning |
|---|---|
| `DETECTED` | Alert is first registered. |
| `TRIAGING` | Alert category, scope, and initial impact are being assessed. |
| `INVESTIGATING` | Targeted evidence collection is underway. |
| `SOLUTION_RECOMMENDED` | An evidence-based proposal is ready for human review. |
| `AWAITING_REMEDIATION` | The engineer is reviewing or applying a change. |
| `VALIDATING` | A remediation was reported and recovery checks are in progress. |
| `RECOVERED` | All configured recovery checks passed and no matching active alert remains. |
| `STILL_ACTIVE` | A matching alert remains or critical recovery checks show the issue persists. |
| `INCONCLUSIVE` | Required evidence was unavailable, so recovery cannot be confirmed. |

Alert fingerprints are the deduplication key. A repeat observation of an
unresolved fingerprint reuses the active incident. A fingerprint observed
after `RECOVERED` reopens the record as `DETECTED`. This stores the latest
incident state for a fingerprint; it does not preserve a complete immutable
timeline.

## Investigation and evidence policy

- Alertmanager is the source of active-alert state. Never invent an incident
  from a dashboard value or assume a past alert is still firing.
- The returned investigation plan is the source for targeted tool selection.
- Preserve Alertmanager severity. If absent, label any fallback as derived.
- State facts, inference, confidence, alternatives, and missing evidence
  separately.
- Never infer OOM from restart count alone, throttling without a throttling
  metric, or user impact without measured evidence.
- Tool errors and missing metrics must be reported; they are not success.
- Logs are limited and redacted. Do not retrieve Secret data, expose
  credentials, or bypass namespace/workload allowlists.
- Endpoint checks are limited to configured in-cluster services and approved
  paths such as `/health` and `/metrics`.
- ArgoCD access is read-only. Report sync/health, image, and revision as
  evidence; do not trigger sync or rollback.

## Skills

| Skill | Responsibility |
|---|---|
| `devops_investigator` | Alert-first orchestration, targeted tool sequence, report structure, and human handoff. |
| `incident_detection` | Active alert verification, fingerprint identity, and duplicate handling. |
| `incident_triage` | Category, scope, ownership, impact, and source-severity handling. |
| `root_cause_analysis` | Evidence correlation, competing hypotheses, confidence, and unknowns. |
| `kubernetes_troubleshooting` | Category-specific pod, event, rollout, probe, image, and resource evidence. |
| `remediation_recommendation` | Specific, risk-aware GitOps proposal with rollback and human approval. |
| `recovery_validation` | Post-change checks and exact recovery-status reporting. |

These are instructions for a compatible AI client; they are not executable
server plugins and do not grant additional access. The client must load the
skills from the repository or its configured skill directory.

## Alert coverage

`monitoring/templates/fastapi-alert-rules.yaml` creates dev-scoped Prometheus
rules for:

- sustained `FastAPICrashLooping` waiting state
- sustained HTTP 5xx ratio
- Prometheus target down or absent
- zero available deployment replicas
- high pod CPU use
- memory use near the configured container limit
- a last termination reason of `OOMKilled`

Rules use the configured dev namespace, workload/service names, and thresholds
in `monitoring/values.yaml`. They depend on the relevant kube-state-metrics and
application series being present. Render and query-check the rules before
applying them. The memory alert deliberately does not fire without a configured
memory-limit metric; the currently checked-in FastAPI deployment does not
establish that such a limit exists.

## Controlled dev scenarios

These scenarios are demonstrations, not automatic actions. Use the reviewed
GitOps process, keep an engineer watching the dev service, and restore the
normal values immediately after the test. Do not run them in production.

### 1. Application 5xx alert

The dev values already expose the application's `ENABLE_SIMULATE_ERROR`
setting. First confirm that it is enabled in the dev values and that the
service is healthy. Port-forward the dev service, then issue a small,
deliberate number of requests to `/simulate-error`:

```powershell
kubectl port-forward -n dev svc/fastapi-dev-service 8000:8000
```

In another terminal:

```powershell
1..20 | ForEach-Object {
  Invoke-WebRequest http://127.0.0.1:8000/simulate-error -SkipHttpErrorCheck | Out-Null
  Start-Sleep -Seconds 6
}
```

The endpoint is expected to return HTTP 500 when enabled. Confirm the
application counter and alert state using Prometheus/Alertmanager, then ask the
AI to investigate the exact alert. Do not continue generating errors once the
alert is observed. Because the rule uses a five-minute rate window and a
two-minute `for` duration, resolution can take several minutes after requests
stop. Validate recovery only after Alertmanager clears it.

If the endpoint is disabled or absent, stop; do not enable or invent app
behavior without reviewing the app deployment change.

### 2. Controlled startup failure / CrashLoopBackOff

The FastAPI Helm chart has a hard-coded startup-failure mode,
`incidentTestMode: false` by default. It runs only in the `dev` release
namespace; rendering with it enabled in another namespace fails. To demonstrate:

1. Set `incidentTestMode: true` in the dev release values via a reviewed Git
   change and deploy through the normal ArgoCD workflow.
2. Confirm `FastAPICrashLooping` or `FastAPIUnavailable` fires and inspect the
   pod's current/previous logs, events, deployment status, rollout, and ArgoCD
   status through the MCP server.
3. Revert `incidentTestMode` to `false` through Git, allow ArgoCD to reconcile,
   and confirm the normal application becomes healthy.
4. Run `validate_recovery_tool` and record its exact result.

This scenario intentionally interrupts the dev application. Schedule it with
an engineer present. It is an opt-in Helm value, not an MCP remediation tool.

### 3. Resource and OOM alerts

Do not deliberately exhaust cluster CPU or memory to demonstrate these rules.
The checked-in app source is not available here, and a memory threshold cannot
be evaluated without a configured limit series. The safe current procedure is
to:

1. Verify the rendered dev deployment's resource requests/limits and the
   required Prometheus metric series.
2. Review the rendered `FastAPIHighCPU`, `FastAPIHighMemory`, and
   `FastAPIContainerOOMKilled` expressions and query them read-only.
3. Use only a separately approved bounded load test if the application and
   cluster have an established load-test procedure; set explicit duration and
   resource caps, observe the service, and stop on unexpected impact.
4. If no approved load test or memory limit exists, demonstrate the evidence
   collection path without claiming that the alert fired.

No synthetic OOM test is provided. A test that kills a real workload or risks
the Minikube host is not considered safe or repeatable.

## Recovery result semantics

`validate_recovery_tool` evaluates the matching active alert, desired versus
available replicas, the approved `/health` endpoint, and Prometheus target /
application health. Its possible results are:

- `RECOVERED`: no matching active alert and all configured checks pass.
- `PARTIALLY_RECOVERED`: some capacity is available, but one or more checks
  have not passed.
- `STILL_ACTIVE`: an alert remains or the service has no available capacity.
- `VALIDATION_INCONCLUSIVE`: one or more required evidence sources failed.

Restart count is a current snapshot, not a historical trend. Report that
limitation where relevant.

## Persistence, deployment, and security follow-ups

- Incident records currently live in SQLite on a Kubernetes `emptyDir`.
  Recreating the MCP pod loses them. Use a persistent volume or external
  database before relying on long-term incident history.
- The incident table holds one latest-state record per fingerprint, not a
  complete audit history.
- Validate the expanded Kubernetes/ArgoCD RBAC and rendered manifests before
  applying them. The intended policy is read-only and restricted to the dev
  workload and named ArgoCD application.
- Keep the MCP Service internal. Do not expose Streamable HTTP publicly
  without authentication and TLS.
- The existing Alertmanager notification configuration needs a separate
  migration to Kubernetes Secret-backed configuration and credential rotation.
  Do not copy its credential into documentation or logs.
- FastAPI application code is not tracked in this checkout; its endpoint and
  metric behavior must be confirmed from the deployed image or source before
  changing application behavior.

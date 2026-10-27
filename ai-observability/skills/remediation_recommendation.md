---
name: remediation-recommendation
description: >
  Produces a specific, risk-aware remediation proposal that follows the
  repository's GitOps workflow and requires human action.
---

# Remediation Recommendation

Every recommendation must include:

- the proposed technical change and the evidence it addresses
- the likely source file or component (application, Helm values/template,
  ConfigMap reference, resource settings, or ArgoCD source)
- implementation steps through a reviewed Git change and normal ArgoCD
  reconciliation
- risk and expected impact
- a rollback procedure using a reviewed Git revert/restore
- post-change validation

Rules:

- Recommend only what the collected evidence supports; state uncertainty.
- Never expose secret values. Refer only to a Secret name/key reference where
  necessary.
- Do not tell the MCP server to execute kubectl, Git, shell, Jenkins, sync,
  rollback, restart, scale, delete, or alert-silence operations.
- Do not suggest a permanent manual cluster change where the source belongs in
  Git.
- Clearly mark that a human must review and apply the change.

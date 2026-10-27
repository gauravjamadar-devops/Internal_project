"""Read-only, allowlisted ArgoCD application and deployment context."""
from __future__ import annotations

import os
from typing import Any

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from .kubernetes_tools import get_deployment_status
from .security import redact_text, validate_namespace, validate_workload

_ARGOCD_NAMESPACE = "argocd"
_DEFAULT_APPLICATIONS = {"fastapi-dev"}
_GROUP = "argoproj.io"
_VERSION = "v1alpha1"
_PLURAL = "applications"


def _allowed_applications() -> set[str]:
    configured = os.environ.get(
        "OBSERVABILITY_ARGOCD_APPLICATIONS", "fastapi-dev"
    )
    return {value.strip() for value in configured.split(",") if value.strip()} or _DEFAULT_APPLICATIONS


def _application(application: str) -> dict[str, Any]:
    if not isinstance(application, str) or application not in _allowed_applications():
        raise ValueError("ArgoCD application is outside the configured allowlist")
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    try:
        result = client.CustomObjectsApi().get_namespaced_custom_object(
            _GROUP, _VERSION, _ARGOCD_NAMESPACE, _PLURAL, application
        )
    except ApiException as error:
        raise RuntimeError(
            f"ArgoCD API error: {error.status} {redact_text(error.reason or '', max_length=200)}"
        ) from error
    status = result.get("status") or {}
    source = (result.get("spec") or {}).get("source") or {}
    return {
        "application": application,
        "namespace": (result.get("spec") or {}).get("destination", {}).get("namespace"),
        "source_path": source.get("path"),
        "target_revision": source.get("targetRevision"),
        "resolved_revision": status.get("sync", {}).get("revision"),
        "sync_status": status.get("sync", {}).get("status", "Unknown"),
        "health_status": status.get("health", {}).get("status", "Unknown"),
        "conditions": [
            {
                "type": item.get("type"),
                "message": redact_text(str(item.get("message") or ""), max_length=500),
            }
            for item in (status.get("conditions") or [])
        ],
    }


def get_argocd_application_status(application: str) -> dict[str, Any]:
    try:
        return _application(application)
    except (ValueError, RuntimeError) as error:
        return {"error": str(error)}


def get_argocd_sync_status(application: str) -> dict[str, Any]:
    result = get_argocd_application_status(application)
    if "error" in result:
        return result
    return {
        "application": result["application"],
        "sync_status": result["sync_status"],
        "health_status": result["health_status"],
        "target_revision": result["target_revision"],
        "resolved_revision": result["resolved_revision"],
        "conditions": result["conditions"],
    }


def get_current_image(namespace: str, deployment: str) -> dict[str, Any]:
    validate_namespace(namespace)
    validate_workload(deployment)
    result = get_deployment_status(namespace, deployment)
    if "error" in result:
        return result
    return {
        "namespace": namespace,
        "deployment": deployment,
        "images": [
            container["image"] for container in result.get("containers", [])
        ],
    }


def get_deployment_revision(namespace: str, deployment: str) -> dict[str, Any]:
    validate_namespace(namespace)
    validate_workload(deployment)
    result = get_deployment_status(namespace, deployment)
    if "error" in result:
        return result
    return {
        "namespace": namespace,
        "deployment": deployment,
        "revision": result.get("revision"),
        "observed_generation": result.get("observed_generation"),
        "generation": result.get("generation"),
    }

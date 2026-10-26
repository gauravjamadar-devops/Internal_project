"""
Kubernetes tools for the AI DevOps Observability MCP Server.

Provides read-only access to pods, statuses, restarts, and events
using the in-cluster Kubernetes Python client.
"""
from __future__ import annotations

import os
from datetime import timezone
from typing import Any

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException


def _load_k8s_config() -> None:
    """Load kubeconfig: in-cluster if running on K8s, else local ~/.kube/config."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()


def get_pods(namespace: str) -> dict[str, Any]:
    """
    Return a summary of all pods in the given namespace.

    Returns pod name, phase, ready containers, total containers, and age.
    """
    _load_k8s_config()
    v1 = client.CoreV1Api()
    try:
        pods = v1.list_namespaced_pod(namespace)
    except ApiException as e:
        return {"error": f"Kubernetes API error: {e.status} {e.reason}", "namespace": namespace}

    pod_list = []
    for pod in pods.items:
        containers = pod.spec.containers
        statuses = pod.status.container_statuses or []
        ready_count = sum(1 for s in statuses if s.ready)
        pod_list.append({
            "name": pod.metadata.name,
            "phase": pod.status.phase,
            "ready": f"{ready_count}/{len(containers)}",
            "restarts": sum(s.restart_count for s in statuses),
            "node": pod.spec.node_name,
        })

    return {
        "namespace": namespace,
        "pod_count": len(pod_list),
        "pods": pod_list,
    }


def get_pod_status(namespace: str, pod_name: str) -> dict[str, Any]:
    """
    Return detailed status for a specific pod, including container states.
    """
    _load_k8s_config()
    v1 = client.CoreV1Api()
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    except ApiException as e:
        return {"error": f"Pod '{pod_name}' not found in '{namespace}': {e.reason}"}

    container_details = []
    for status in (pod.status.container_statuses or []):
        state_info = {}
        if status.state.running:
            state_info = {"state": "running"}
        elif status.state.waiting:
            state_info = {
                "state": "waiting",
                "reason": status.state.waiting.reason,
                "message": status.state.waiting.message,
            }
        elif status.state.terminated:
            state_info = {
                "state": "terminated",
                "reason": status.state.terminated.reason,
                "exit_code": status.state.terminated.exit_code,
            }

        container_details.append({
            "name": status.name,
            "ready": status.ready,
            "restarts": status.restart_count,
            "image": status.image,
            **state_info,
        })

    # Conditions (e.g. PodScheduled, ContainersReady, Ready)
    conditions = [
        {"type": c.type, "status": c.status, "reason": c.reason}
        for c in (pod.status.conditions or [])
    ]

    return {
        "namespace": namespace,
        "pod": pod_name,
        "phase": pod.status.phase,
        "host_ip": pod.status.host_ip,
        "pod_ip": pod.status.pod_ip,
        "containers": container_details,
        "conditions": conditions,
    }


def get_pod_restarts(namespace: str) -> dict[str, Any]:
    """
    Return restart counts for every container in every pod in the namespace.
    Highlights pods with restarts > 0.
    """
    _load_k8s_config()
    v1 = client.CoreV1Api()
    try:
        pods = v1.list_namespaced_pod(namespace)
    except ApiException as e:
        return {"error": f"Kubernetes API error: {e.status} {e.reason}", "namespace": namespace}

    restart_info = []
    total_restarts = 0
    for pod in pods.items:
        for status in (pod.status.container_statuses or []):
            rc = status.restart_count
            total_restarts += rc
            restart_info.append({
                "pod": pod.metadata.name,
                "container": status.name,
                "restarts": rc,
                "flagged": rc > 5,
            })

    # Sort highest restarts first for quick triage
    restart_info.sort(key=lambda x: x["restarts"], reverse=True)

    return {
        "namespace": namespace,
        "total_restarts": total_restarts,
        "containers": restart_info,
        "high_restart_threshold": 5,
    }


def get_kubernetes_events(namespace: str) -> dict[str, Any]:
    """
    Return Warning-level Kubernetes events in the namespace, sorted by recency.
    Normal events are filtered out to reduce noise.
    """
    _load_k8s_config()
    v1 = client.CoreV1Api()
    try:
        events = v1.list_namespaced_event(namespace)
    except ApiException as e:
        return {"error": f"Kubernetes API error: {e.status} {e.reason}", "namespace": namespace}

    warning_events = []
    for event in events.items:
        if event.type != "Warning":
            continue
        warning_events.append({
            "time": str(event.last_timestamp),
            "type": event.type,
            "reason": event.reason,
            "message": event.message,
            "object": f"{event.involved_object.kind}/{event.involved_object.name}",
            "count": event.count,
        })

    # Sort most recent first
    warning_events.sort(key=lambda x: x["time"] or "", reverse=True)

    return {
        "namespace": namespace,
        "warning_event_count": len(warning_events),
        "events": warning_events[:20],  # cap at 20 most recent for readability
    }

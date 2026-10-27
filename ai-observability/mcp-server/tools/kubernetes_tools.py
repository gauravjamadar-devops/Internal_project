"""Read-only, allowlisted Kubernetes workload and application tools."""
from __future__ import annotations

import time
import os
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml
from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from .security import (
    allowed_workloads,
    redact_text,
    validate_namespace,
    validate_pod_name,
    validate_workload,
)

_ENDPOINTS = {"/health", "/metrics"}
_MAX_LOG_LINES = 500
_MAX_RETURNED_LOG_LINES = 100


def _load_k8s_config() -> None:
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()


def _scope(namespace: str, workload: str | None = None) -> None:
    validate_namespace(namespace)
    if workload is not None:
        validate_workload(workload)


def _api_error(error: ApiException) -> dict[str, Any]:
    return {
        "error": f"Kubernetes API error: {error.status} {redact_text(error.reason or '', max_length=200)}"
    }


def _apps() -> client.AppsV1Api:
    return client.AppsV1Api()


def _core() -> client.CoreV1Api:
    return client.CoreV1Api()


def _deployment(namespace: str, deployment: str) -> Any:
    _scope(namespace, deployment)
    _load_k8s_config()
    try:
        return _apps().read_namespaced_deployment(deployment, namespace)
    except ApiException as error:
        if error.status == 404:
            raise ValueError(f"Deployment {deployment!r} was not found in {namespace}") from error
        raise


def _pods_for_deployment(namespace: str, deployment: str) -> list[Any]:
    resource = _deployment(namespace, deployment)
    selector = resource.spec.selector.match_labels or {}
    if not selector:
        return []
    label_selector = ",".join(f"{key}={value}" for key, value in selector.items())
    return _core().list_namespaced_pod(
        namespace, label_selector=label_selector
    ).items


def _pod_deployment(pod: Any) -> str | None:
    owners = pod.metadata.owner_references or []
    replica_set = next(
        (owner for owner in owners if owner.kind == "ReplicaSet"), None
    )
    if replica_set is None:
        return None
    try:
        rs = _apps().read_namespaced_replica_set(
            replica_set.name, pod.metadata.namespace
        )
    except ApiException:
        return None
    rs_owners = rs.metadata.owner_references or []
    deployment_owner = next(
        (owner for owner in rs_owners if owner.kind == "Deployment"), None
    )
    return deployment_owner.name if deployment_owner else None


def _allowed_pod(namespace: str, pod_name: str) -> Any:
    validate_namespace(namespace)
    validate_pod_name(pod_name)
    _load_k8s_config()
    try:
        pod = _core().read_namespaced_pod(pod_name, namespace)
    except ApiException as error:
        if error.status == 404:
            raise ValueError(f"Pod {pod_name!r} was not found in {namespace}") from error
        raise
    workload = _pod_deployment(pod)
    if workload not in allowed_workloads():
        raise ValueError("Pod is outside the configured workload allowlist")
    return pod


def _container_summary(container: Any) -> dict[str, Any]:
    resources = container.resources
    probe_summary = {}
    for key in ("readiness_probe", "liveness_probe", "startup_probe"):
        probe = getattr(container, key, None)
        if probe:
            http_get = probe.http_get
            probe_summary[key] = {
                "path": http_get.path if http_get else None,
                "port": http_get.port if http_get else None,
                "initial_delay_seconds": probe.initial_delay_seconds,
                "period_seconds": probe.period_seconds,
                "timeout_seconds": probe.timeout_seconds,
                "failure_threshold": probe.failure_threshold,
            }
    return {
        "name": container.name,
        "image": redact_text(container.image, max_length=300),
        "image_pull_policy": container.image_pull_policy,
        "resources": {
            "requests": dict(resources.requests or {}),
            "limits": dict(resources.limits or {}),
        },
        "probes": probe_summary,
    }


def get_pods(namespace: str, workload: str | None = None) -> dict[str, Any]:
    _scope(namespace, workload)
    _load_k8s_config()
    try:
        if workload:
            pods = _pods_for_deployment(namespace, workload)
        else:
            pods = []
            for name in sorted(allowed_workloads()):
                try:
                    pods.extend(_pods_for_deployment(namespace, name))
                except ValueError:
                    continue
        result = []
        for pod in pods:
            statuses = pod.status.container_statuses or []
            result.append({
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "ready": f"{sum(status.ready for status in statuses)}/{len(pod.spec.containers)}",
                "restarts": sum(status.restart_count for status in statuses),
                "node": pod.spec.node_name,
                "workload": _pod_deployment(pod),
            })
        return {"namespace": namespace, "pod_count": len(result), "pods": result}
    except ApiException as error:
        return _api_error(error)
    except ValueError as error:
        return {"error": str(error)}


def get_pod_status(namespace: str, pod_name: str) -> dict[str, Any]:
    try:
        pod = _allowed_pod(namespace, pod_name)
    except ApiException as error:
        return _api_error(error)
    except ValueError as error:
        return {"error": str(error)}
    details = []
    for status in pod.status.container_statuses or []:
        state: dict[str, Any] = {"state": "unknown"}
        if status.state.running:
            state = {"state": "running", "started_at": status.state.running.started_at}
        elif status.state.waiting:
            state = {
                "state": "waiting",
                "reason": status.state.waiting.reason,
                "message": redact_text(status.state.waiting.message or "", max_length=500),
            }
        elif status.state.terminated:
            state = {
                "state": "terminated",
                "reason": status.state.terminated.reason,
                "exit_code": status.state.terminated.exit_code,
                "finished_at": status.state.terminated.finished_at,
            }
        last_state = (
            status.last_state.terminated if status.last_state else None
        )
        details.append({
            "name": status.name,
            "ready": status.ready,
            "restarts": status.restart_count,
            "image": redact_text(status.image, max_length=300),
            **state,
            "last_termination": (
                {
                    "reason": last_state.reason,
                    "exit_code": last_state.exit_code,
                    "finished_at": last_state.finished_at,
                }
                if last_state else None
            ),
        })
    return {
        "namespace": namespace,
        "pod": pod_name,
        "workload": _pod_deployment(pod),
        "phase": pod.status.phase,
        "host_ip": pod.status.host_ip,
        "pod_ip": pod.status.pod_ip,
        "containers": details,
        "conditions": [
            {"type": condition.type, "status": condition.status, "reason": condition.reason}
            for condition in (pod.status.conditions or [])
        ],
    }


def get_pod_restarts(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    pods_result = get_pods(namespace, workload)
    if "error" in pods_result:
        return pods_result
    containers = []
    for pod in pods_result["pods"]:
        status = get_pod_status(namespace, pod["name"])
        if "error" in status:
            continue
        for container in status["containers"]:
            containers.append({
                "pod": pod["name"],
                "container": container["name"],
                "restarts": container["restarts"],
                "flagged": container["restarts"] > 5,
            })
    containers.sort(key=lambda item: item["restarts"], reverse=True)
    return {
        "namespace": namespace,
        "total_restarts": sum(item["restarts"] for item in containers),
        "containers": containers,
        "high_restart_threshold": 5,
    }


def get_deployment_status(namespace: str, deployment: str) -> dict[str, Any]:
    try:
        resource = _deployment(namespace, deployment)
    except ValueError as error:
        return {"error": str(error)}
    except ApiException as error:
        return _api_error(error)
    conditions = [
        {
            "type": item.type,
            "status": item.status,
            "reason": item.reason,
            "message": redact_text(item.message or "", max_length=500),
        }
        for item in (resource.status.conditions or [])
    ]
    return {
        "namespace": namespace,
        "deployment": deployment,
        "desired_replicas": resource.spec.replicas or 0,
        "ready_replicas": resource.status.ready_replicas or 0,
        "available_replicas": resource.status.available_replicas or 0,
        "updated_replicas": resource.status.updated_replicas or 0,
        "observed_generation": resource.status.observed_generation,
        "generation": resource.metadata.generation,
        "revision": (resource.metadata.annotations or {}).get(
            "deployment.kubernetes.io/revision"
        ),
        "strategy": resource.spec.strategy.type if resource.spec.strategy else None,
        "image_pull_secrets": [
            item.name for item in (resource.spec.template.spec.image_pull_secrets or [])
        ],
        "containers": [
            _container_summary(container)
            for container in resource.spec.template.spec.containers
        ],
        "conditions": conditions,
    }


def get_replicaset_status(
    namespace: str, deployment: str | None = None
) -> dict[str, Any]:
    _scope(namespace, deployment)
    _load_k8s_config()
    try:
        replica_sets = _apps().list_namespaced_replica_set(namespace).items
        if deployment:
            replica_sets = [
                rs for rs in replica_sets
                if any(
                    owner.kind == "Deployment" and owner.name == deployment
                    for owner in (rs.metadata.owner_references or [])
                )
            ]
        else:
            allowed = allowed_workloads()
            replica_sets = [
                rs for rs in replica_sets
                if any(
                    owner.kind == "Deployment" and owner.name in allowed
                    for owner in (rs.metadata.owner_references or [])
                )
            ]
        return {
            "namespace": namespace,
            "replica_sets": [
                {
                    "name": rs.metadata.name,
                    "deployment": next(
                        (owner.name for owner in (rs.metadata.owner_references or [])
                         if owner.kind == "Deployment"),
                        None,
                    ),
                    "desired_replicas": rs.spec.replicas or 0,
                    "ready_replicas": rs.status.ready_replicas or 0,
                    "available_replicas": rs.status.available_replicas or 0,
                    "revision": (rs.metadata.annotations or {}).get(
                        "deployment.kubernetes.io/revision"
                    ),
                    "created_at": rs.metadata.creation_timestamp,
                    "images": [
                        redact_text(container.image, max_length=300)
                        for container in rs.spec.template.spec.containers
                    ],
                }
                for rs in replica_sets
            ],
        }
    except ApiException as error:
        return _api_error(error)


def get_kubernetes_events(
    namespace: str, workload: str | None = None
) -> dict[str, Any]:
    _scope(namespace, workload)
    _load_k8s_config()
    try:
        events = _core().list_namespaced_event(namespace).items
        if workload:
            pods = _pods_for_deployment(namespace, workload)
            object_names = {pod.metadata.name for pod in pods}
            object_names.update(
                owner.name
                for pod in pods
                for owner in (pod.metadata.owner_references or [])
                if owner.kind == "ReplicaSet"
            )
            object_names.add(workload)
            events = [
                event for event in events
                if event.involved_object.name in object_names
            ]
        result = [
            {
                "time": str(event.last_timestamp or event.event_time or event.first_timestamp or ""),
                "type": event.type,
                "reason": redact_text(event.reason or "", max_length=100),
                "message": redact_text(event.message or "", max_length=1000),
                "object": f"{event.involved_object.kind}/{event.involved_object.name}",
                "count": event.count,
            }
            for event in events if event.type == "Warning"
        ]
        result.sort(key=lambda item: item["time"], reverse=True)
        return {
            "namespace": namespace,
            "warning_event_count": len(result),
            "events": result[:20],
        }
    except ApiException as error:
        return _api_error(error)
    except ValueError as error:
        return {"error": str(error)}


def get_recent_rollout(namespace: str, deployment: str) -> dict[str, Any]:
    result = get_replicaset_status(namespace, deployment)
    if "error" in result:
        return result
    replica_sets = result["replica_sets"]
    replica_sets.sort(key=lambda rs: str(rs["created_at"] or ""), reverse=True)
    deployment_status = get_deployment_status(namespace, deployment)
    return {
        "namespace": namespace,
        "deployment": deployment,
        "current_revision": deployment_status.get("revision"),
        "replica_sets": replica_sets[:10],
    }


def describe_workload(namespace: str, workload: str) -> dict[str, Any]:
    deployment = get_deployment_status(namespace, workload)
    if "error" in deployment:
        return deployment
    pods = get_pods(namespace, workload)
    return {
        "deployment": deployment,
        "pods": pods.get("pods", []),
        "replica_sets": get_replicaset_status(namespace, workload).get(
            "replica_sets", []
        ),
    }


def _safe_logs(
    namespace: str,
    pod: str,
    container: str | None,
    tail_lines: int,
    previous: bool,
) -> dict[str, Any]:
    _scope(namespace)
    validate_pod_name(pod)
    if not isinstance(tail_lines, int) or not 1 <= tail_lines <= _MAX_LOG_LINES:
        raise ValueError(f"tail_lines must be between 1 and {_MAX_LOG_LINES}")
    if container is not None and (
        not isinstance(container, str)
        or len(container) > 63
        or not container.replace("-", "").isalnum()
    ):
        raise ValueError("Invalid container name")
    resource = _allowed_pod(namespace, pod)
    containers = {item.name for item in resource.spec.containers}
    if container and container not in containers:
        raise ValueError("Container does not belong to the selected pod")
    try:
        text = _core().read_namespaced_pod_log(
            name=pod,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
            previous=previous,
            timestamps=True,
        )
    except ApiException as error:
        return _api_error(error)
    lines = text.splitlines()
    clipped = lines[-_MAX_RETURNED_LOG_LINES:]
    return {
        "namespace": namespace,
        "pod": pod,
        "container": container,
        "previous": previous,
        "returned_lines": len(clipped),
        "truncated": len(lines) > len(clipped),
        "logs": [redact_text(line, max_length=1000) for line in clipped],
    }


def get_pod_logs(
    namespace: str, pod: str, container: str | None = None, tail_lines: int = 200
) -> dict[str, Any]:
    try:
        return _safe_logs(namespace, pod, container, tail_lines, False)
    except (ApiException, ValueError) as error:
        return _api_error(error) if isinstance(error, ApiException) else {"error": str(error)}


def get_previous_pod_logs(
    namespace: str, pod: str, container: str | None = None, tail_lines: int = 200
) -> dict[str, Any]:
    try:
        return _safe_logs(namespace, pod, container, tail_lines, True)
    except (ApiException, ValueError) as error:
        return _api_error(error) if isinstance(error, ApiException) else {"error": str(error)}


def search_pod_logs(
    namespace: str,
    workload: str,
    patterns: list[str],
    tail_lines: int = 500,
) -> dict[str, Any]:
    _scope(namespace, workload)
    if (
        not isinstance(patterns, list)
        or not 1 <= len(patterns) <= 5
        or any(not isinstance(item, str) or not 1 <= len(item) <= 100 for item in patterns)
    ):
        raise ValueError("patterns must contain between 1 and 5 non-empty strings")
    pods = get_pods(namespace, workload)
    if "error" in pods:
        return pods
    matches = []
    errors = []
    for pod in pods["pods"]:
        result = get_pod_logs(namespace, pod["name"], tail_lines=tail_lines)
        if "error" in result:
            errors.append({"pod": pod["name"], "error": result["error"]})
            continue
        for line in result["logs"]:
            if any(pattern.casefold() in line.casefold() for pattern in patterns):
                matches.append({"pod": pod["name"], "line": line})
                if len(matches) >= 100:
                    break
        if len(matches) >= 100:
            break
    return {
        "namespace": namespace,
        "workload": workload,
        "patterns": [redact_text(pattern, max_length=100) for pattern in patterns],
        "matches": matches,
        "errors": errors,
        "truncated": len(matches) >= 100,
    }


def check_application_endpoint(
    namespace: str,
    endpoint: str = "/health",
    workload: str = "fastapi-dev-deployment",
) -> dict[str, Any]:
    _scope(namespace, workload)
    if endpoint not in _ENDPOINTS:
        raise ValueError(f"endpoint must be one of: {', '.join(sorted(_ENDPOINTS))}")
    config_path = os.environ.get(
        "MCP_CONFIG_PATH",
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml")
        ),
    )
    try:
        with open(config_path, encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}
        service_url = (
            config.get("application_services", {})
            .get(namespace, {})
            .get(workload)
        )
    except (OSError, yaml.YAMLError) as error:
        return {"error": f"Unable to load approved application endpoint configuration: {error}"}
    if not isinstance(service_url, str):
        return {"error": "No approved endpoint is configured for this workload"}
    parsed_url = urlsplit(service_url)
    if (
        parsed_url.scheme != "http"
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
        or not parsed_url.hostname.endswith(".svc.cluster.local")
        or parsed_url.path not in {"", "/"}
        or parsed_url.query
        or parsed_url.fragment
    ):
        return {"error": "Configured application endpoint is not an approved cluster service URL"}
    started = time.monotonic()
    try:
        with httpx.Client(timeout=3.0, follow_redirects=False) as http:
            response = http.get(f"{service_url}{endpoint}")
        return {
            "namespace": namespace,
            "workload": workload,
            "endpoint": endpoint,
            "status_code": response.status_code,
            "healthy": response.status_code == 200,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
        }
    except httpx.HTTPError as error:
        return {
            "namespace": namespace,
            "workload": workload,
            "endpoint": endpoint,
            "error": redact_text(str(error), max_length=300),
        }

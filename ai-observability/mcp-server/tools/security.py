"""Input validation and output sanitization for observability tools."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit


_K8S_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_POD_NAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")
_SECRET_PATTERNS = (
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(?i)(authorization|x-api-key|api[_-]?key|password|passwd|secret|token)"
            r"(\s*[:=]\s*)([^\s,;]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@"),
        r"\1[REDACTED]@",
    ),
    (
        re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
        "[REDACTED_SLACK_WEBHOOK]",
    ),
    (
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b"),
        "[REDACTED_CREDENTIAL]",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\b"),
        "[REDACTED_JWT]",
    ),
)


def allowed_namespaces() -> frozenset[str]:
    configured = os.environ.get("OBSERVABILITY_ALLOWED_NAMESPACES", "dev")
    values = frozenset(part.strip() for part in configured.split(",") if part.strip())
    if "prod" in values and os.environ.get("ENABLE_PROD_TROUBLESHOOTING", "").lower() != "true":
        values = values - {"prod"}
    return values


def allowed_workloads() -> frozenset[str]:
    configured = os.environ.get(
        "OBSERVABILITY_ALLOWED_WORKLOADS", "fastapi-dev-deployment"
    )
    return frozenset(part.strip() for part in configured.split(",") if part.strip())


def workload_aliases() -> dict[str, str]:
    configured = os.environ.get(
        "OBSERVABILITY_WORKLOAD_ALIASES",
        "fastapi-dev-service=fastapi-dev-deployment",
    )
    aliases: dict[str, str] = {}
    for pair in configured.split(","):
        source, separator, target = pair.partition("=")
        if separator and source.strip() and target.strip():
            aliases[source.strip()] = target.strip()
    return aliases


def validate_namespace(namespace: str) -> str:
    if not isinstance(namespace, str) or not _K8S_NAME.fullmatch(namespace):
        raise ValueError(f"Invalid Kubernetes namespace: {namespace!r}")
    if namespace not in allowed_namespaces():
        raise ValueError(f"Namespace is not enabled for observability: {namespace}")
    return namespace


def validate_workload(workload: str) -> str:
    if not isinstance(workload, str) or not _K8S_NAME.fullmatch(workload):
        raise ValueError(f"Invalid Kubernetes workload: {workload!r}")
    if workload not in allowed_workloads():
        raise ValueError(f"Workload is not enabled for observability: {workload}")
    return workload


def validate_pod_name(pod: str) -> str:
    if not isinstance(pod, str) or not _POD_NAME.fullmatch(pod):
        raise ValueError(f"Invalid Kubernetes pod name: {pod!r}")
    return pod


def validate_alert_name(alert_name: str) -> str:
    if not isinstance(alert_name, str) or not re.fullmatch(
        r"[A-Za-z0-9_:][A-Za-z0-9_:.-]{0,127}", alert_name
    ):
        raise ValueError(f"Invalid alert name: {alert_name!r}")
    return alert_name


def redact_text(value: str, *, max_length: int = 1000) -> str:
    text = value[:max_length]
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_mapping(values: dict[str, object]) -> dict[str, str]:
    return {
        redact_text(str(key), max_length=100): redact_text(str(value))
        for key, value in values.items()
        if not re.search(r"(?i)(token|secret|password|authorization|api[_-]?key)", str(key))
    }


def approved_service_url(environment_variable: str, default: str) -> str:
    """Load a configured service URL while rejecting credentials and URL paths."""
    candidate = os.environ.get(environment_variable, default)
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{environment_variable} must be a base HTTP(S) service URL")
    return candidate.rstrip("/")

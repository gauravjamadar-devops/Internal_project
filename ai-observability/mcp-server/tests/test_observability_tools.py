from types import SimpleNamespace
import os
import tempfile
import unittest
from unittest.mock import patch

from tools import (
    alert_tools,
    incident_state,
    incident_workflow,
    kubernetes_tools,
    prometheus_tools,
    security,
)


class PrometheusToolsTests(unittest.TestCase):
    @staticmethod
    def query_result(value: float) -> dict:
        return {"status": "success", "result": [{"value": ["0", str(value)]}]}

    @patch("tools.prometheus_tools._query")
    def test_get_error_rate_returns_rates_and_percentage(self, query_mock):
        query_mock.side_effect = [
            self.query_result(2),
            self.query_result(10),
            self.query_result(1),
        ]

        result = prometheus_tools.get_error_rate("dev", "5m")

        self.assertEqual(result["http_5xx_rate_per_sec"], 2)
        self.assertEqual(result["total_request_rate_per_sec"], 10)
        self.assertEqual(result["error_percentage"], "20.00%")
        self.assertEqual(result["simulated_errors_in_window"], 1)
        self.assertIn('namespace="dev"', query_mock.call_args_list[0].args[0])

    @patch("tools.prometheus_tools._query")
    def test_get_error_rate_reports_query_errors(self, query_mock):
        query_mock.side_effect = [
            {"error": "Prometheus unavailable"},
            self.query_result(10),
            self.query_result(1),
        ]

        result = prometheus_tools.get_error_rate("dev")

        self.assertEqual(result["error"], "One or more Prometheus queries failed")
        self.assertEqual(
            result["query_errors"]["http_5xx_rate_per_sec"],
            "Prometheus unavailable",
        )

    @patch("tools.prometheus_tools._query")
    def test_invalid_namespace_is_rejected_before_query(self, query_mock):
        with self.assertRaises(ValueError):
            prometheus_tools.get_error_rate('dev"} or up', "5m")

        query_mock.assert_not_called()

    @patch("tools.prometheus_tools._query")
    def test_invalid_window_is_rejected_before_query(self, query_mock):
        with self.assertRaises(ValueError):
            prometheus_tools.get_error_rate("dev", "5m] or up")

        query_mock.assert_not_called()

    @patch("tools.prometheus_tools._query")
    def test_workload_selectors_are_valid_prometheus_regexes(self, query_mock):
        query_mock.return_value = {"status": "success", "result": []}

        prometheus_tools.get_application_health(
            "dev", "fastapi-dev-deployment"
        )
        self.assertIn(
            'pod=~"fastapi-dev-deployment-.*"',
            query_mock.call_args_list[0].args[0],
        )
        self.assertNotIn(r"\-", query_mock.call_args_list[0].args[0])

        query_mock.reset_mock()
        prometheus_tools.get_pod_cpu("dev")
        self.assertIn(
            'pod=~"fastapi-dev-deployment-.*"',
            query_mock.call_args.args[0],
        )
        self.assertNotIn(r"\-", query_mock.call_args.args[0])


class KubernetesToolsTests(unittest.TestCase):
    @patch("tools.kubernetes_tools._load_k8s_config")
    @patch("tools.kubernetes_tools._pod_deployment", return_value="fastapi-dev-deployment")
    @patch(
        "tools.kubernetes_tools._pods_for_deployment",
        return_value=[
            SimpleNamespace(
                metadata=SimpleNamespace(name="fastapi-dev-deployment-api-123"),
                spec=SimpleNamespace(
                    containers=[SimpleNamespace(name="api")],
                    node_name="minikube",
                ),
                status=SimpleNamespace(
                    phase="Running",
                    container_statuses=[
                        SimpleNamespace(ready=True, restart_count=2)
                    ],
                ),
            )
        ],
    )
    def test_get_pods_summarizes_readiness_and_restarts(
        self, pods_mock, _deployment_mock, load_config_mock
    ):
        result = kubernetes_tools.get_pods("dev")

        self.assertEqual(result["pod_count"], 1)
        self.assertEqual(result["pods"][0]["ready"], "1/1")
        self.assertEqual(result["pods"][0]["restarts"], 2)
        pods_mock.assert_called_once_with("dev", "fastapi-dev-deployment")
        _deployment_mock.assert_called_once_with(pods_mock.return_value[0])
        load_config_mock.assert_called_once()

    @patch("tools.kubernetes_tools._load_k8s_config")
    def test_invalid_namespace_is_rejected_before_api_call(
        self, load_config_mock
    ):
        with self.assertRaises(ValueError):
            kubernetes_tools.get_pods("dev;prod")

        load_config_mock.assert_not_called()


class SecurityTests(unittest.TestCase):
    def test_default_namespace_and_workload_are_dev_only(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(security.validate_namespace("dev"), "dev")
            with self.assertRaises(ValueError):
                security.validate_namespace("prod")

    def test_prod_requires_explicit_enablement(self):
        with patch.dict(
            os.environ,
            {
                "OBSERVABILITY_ALLOWED_NAMESPACES": "dev,prod",
                "ENABLE_PROD_TROUBLESHOOTING": "false",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError):
                security.validate_namespace("prod")
        with patch.dict(
            os.environ,
            {
                "OBSERVABILITY_ALLOWED_NAMESPACES": "dev,prod",
                "ENABLE_PROD_TROUBLESHOOTING": "true",
            },
            clear=True,
        ):
            self.assertEqual(security.validate_namespace("prod"), "prod")

    def test_redaction_removes_bearer_password_and_webhook_values(self):
        value = (
            "Authorization: Bearer abcdef password=supersecret "
            "https://hooks.slack.com/services/T000/B000/SECRET"
        )
        redacted = security.redact_text(value)
        self.assertNotIn("abcdef", redacted)
        self.assertNotIn("supersecret", redacted)
        self.assertNotIn("T000/B000/SECRET", redacted)

    def test_arbitrary_service_urls_are_rejected(self):
        with patch.dict(
            os.environ,
            {"ALERTMANAGER_URL": "http://user:password@example.com/api"},
        ):
            with self.assertRaises(ValueError):
                security.approved_service_url("ALERTMANAGER_URL", "http://localhost")


class AlertToolsTests(unittest.TestCase):
    def test_alertmanager_failure_is_returned_as_an_error(self):
        with patch(
            "tools.alert_tools._request",
            side_effect=alert_tools.httpx.ConnectError("service unavailable"),
        ):
            result = alert_tools.get_active_alerts()

        self.assertIn("error", result)
        self.assertIn("Unable to retrieve active alerts", result["error"])

    def test_active_alerts_exclude_out_of_scope_namespaces(self):
        alert = {
            "labels": {
                "alertname": "FastAPIHigh5xxRate",
                "severity": "warning",
                "namespace": "prod",
                "job": "fastapi-dev-service",
            },
            "status": {"state": "active"},
        }
        with (
            patch("tools.alert_tools._request", return_value=[alert]),
            patch("tools.alert_tools.allowed_namespaces", return_value={"dev"}),
            patch(
                "tools.alert_tools.allowed_workloads",
                return_value={"fastapi-dev-deployment"},
            ),
            patch(
                "tools.alert_tools.workload_aliases",
                return_value={"fastapi-dev-service": "fastapi-dev-deployment"},
            ),
        ):
            result = alert_tools.get_active_alerts()

        self.assertEqual(result["alerts"], [])

    def test_alertmanager_response_is_normalized_and_secrets_redacted(self):
        alert = {
            "fingerprint": "abc123",
            "labels": {
                "alertname": "FastAPIHigh5xxRate",
                "severity": "warning",
                "namespace": "dev",
                "job": "fastapi-dev-service",
                "pod": "fastapi-dev-deployment-abc123",
            },
            "annotations": {
                "summary": "Error rate is high",
                "description": "token=abc123",
            },
            "status": {"state": "active", "silencedBy": [], "inhibitedBy": []},
            "startsAt": "2026-10-27T00:00:00Z",
            "generatorURL": "http://prometheus.example/graph?g0.expr=up",
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("tools.alert_tools._request", return_value=[alert]),
        ):
            result = alert_tools.get_active_alerts()
        self.assertEqual(result["count"], 1)
        normalized = result["alerts"][0]
        self.assertEqual(normalized["alert_name"], "FastAPIHigh5xxRate")
        self.assertEqual(normalized["workload"], "fastapi-dev-deployment")
        self.assertEqual(normalized["severity"], "warning")
        self.assertNotIn("abc123", normalized["description"])
        self.assertEqual(normalized["state"], "ACTIVE")

    def test_silence_output_excludes_comments_and_created_by(self):
        with patch(
            "tools.alert_tools._request",
            return_value=[
                {
                    "id": "silence-1",
                    "status": {"state": "active"},
                    "comment": "private text",
                    "createdBy": "operator",
                    "matchers": [{"name": "alertname", "value": "FastAPIHigh5xxRate"}],
                }
            ],
        ):
            result = alert_tools.get_silenced_alerts()
        self.assertEqual(result["count"], 1)
        self.assertNotIn("comment", result["silences"][0])
        self.assertNotIn("createdBy", result["silences"][0])


class IncidentWorkflowTests(unittest.TestCase):
    def test_alert_classification_preserves_alertmanager_severity(self):
        result = incident_workflow.classify_alert(
            {
                "alert_name": "FastAPIHigh5xxRate",
                "namespace": "dev",
                "workload": "fastapi-dev-deployment",
                "severity": "warning",
            }
        )
        self.assertEqual(result["category"], "http_5xx")
        self.assertEqual(result["ownership"], "application")
        self.assertEqual(result["severity"], "warning")

    def test_crashloop_selects_targeted_kubernetes_tools(self):
        plan = incident_workflow._CATEGORY_TOOLS["crash_loop"]
        self.assertIn("get_previous_pod_logs_tool", plan)
        self.assertIn("get_kubernetes_events_tool", plan)
        self.assertNotIn("query_prometheus_tool", plan)


class IncidentStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_directory.name, "incidents.sqlite3")
        self.environment = patch.dict(os.environ, {"INCIDENT_DB_PATH": self.db_path})
        self.environment.start()
        incident_state.close_state_store()

    def tearDown(self):
        incident_state.close_state_store()
        self.environment.stop()
        self.temp_directory.cleanup()

    def test_same_fingerprint_deduplicates_incident(self):
        alert = {
            "fingerprint": "stable-fingerprint",
            "alert_name": "FastAPIHigh5xxRate",
            "namespace": "dev",
            "workload": "fastapi-dev-deployment",
            "severity": "warning",
        }
        first = incident_state.register_incident(alert)
        second = incident_state.register_incident(alert)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertFalse(first["duplicate_active"])
        self.assertTrue(second["duplicate_active"])
        self.assertEqual(
            first["incident"]["incident_id"], second["incident"]["incident_id"]
        )

    def test_recovered_fingerprint_reactivates_without_duplicate_flag(self):
        alert = {
            "fingerprint": "reactivation-fingerprint",
            "alert_name": "FastAPIHigh5xxRate",
            "namespace": "dev",
            "workload": "fastapi-dev-deployment",
        }
        incident = incident_state.register_incident(alert)["incident"]
        incident_state.update_incident(incident["incident_id"], "RECOVERED")

        result = incident_state.register_incident(alert)

        self.assertTrue(result["reactivated"])
        self.assertFalse(result["duplicate_active"])
        self.assertEqual(result["incident"]["status"], "DETECTED")

    def test_incident_state_validates_transitions_and_redacts_values(self):
        incident = incident_state.register_incident(
            {
                "fingerprint": "status-test",
                "alert_name": "FastAPIHigh5xxRate",
                "namespace": "dev",
                "workload": "fastapi-dev-deployment",
            }
        )["incident"]
        result = incident_state.update_incident(
            incident["incident_id"],
            "INVESTIGATING",
            probable_cause="password=secret123 in log",
        )
        self.assertNotIn("secret123", result["probable_cause"])
        with self.assertRaises(ValueError):
            incident_state.update_incident(incident["incident_id"], "UNKNOWN")


class RecoveryValidationTests(unittest.TestCase):
    @patch("tools.prometheus_tools.get_application_health")
    @patch("tools.kubernetes_tools.check_application_endpoint")
    @patch("tools.kubernetes_tools.get_pod_restarts")
    @patch("tools.kubernetes_tools.get_deployment_status")
    @patch("tools.alert_tools.get_active_alerts")
    def test_recovery_requires_all_checks(
        self, alerts, deployment, restarts, endpoint, health
    ):
        alerts.return_value = {"alerts": []}
        deployment.return_value = {
            "desired_replicas": 2,
            "available_replicas": 2,
        }
        restarts.return_value = {"total_restarts": 0}
        endpoint.return_value = {"status_code": 200}
        health.return_value = {
            "all_targets_healthy": True,
            "prometheus_health": "HEALTHY",
        }
        result = incident_workflow.validate_recovery(
            "dev", "fastapi-dev-deployment"
        )
        self.assertEqual(result["status"], "RECOVERED")

    @patch("tools.prometheus_tools.get_application_health")
    @patch("tools.kubernetes_tools.check_application_endpoint")
    @patch("tools.kubernetes_tools.get_pod_restarts")
    @patch("tools.kubernetes_tools.get_deployment_status")
    @patch("tools.alert_tools.get_active_alerts")
    def test_active_alert_prevents_recovered_status(
        self, alerts, deployment, restarts, endpoint, health
    ):
        alerts.return_value = {
            "alerts": [
                {
                    "namespace": "dev",
                    "workload": "fastapi-dev-deployment",
                    "alert_name": "FastAPIHigh5xxRate",
                }
            ]
        }
        deployment.return_value = {
            "desired_replicas": 2,
            "available_replicas": 2,
        }
        restarts.return_value = {"total_restarts": 0}
        endpoint.return_value = {"status_code": 200}
        health.return_value = {
            "all_targets_healthy": True,
            "prometheus_health": "HEALTHY",
        }
        result = incident_workflow.validate_recovery(
            "dev", "fastapi-dev-deployment"
        )
        self.assertEqual(result["status"], "STILL_ACTIVE")


if __name__ == "__main__":
    unittest.main()

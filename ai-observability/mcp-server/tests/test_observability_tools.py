from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import kubernetes_tools, prometheus_tools


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


class KubernetesToolsTests(unittest.TestCase):
    @patch("tools.kubernetes_tools._load_k8s_config")
    @patch("tools.kubernetes_tools.client.CoreV1Api")
    def test_get_pods_summarizes_readiness_and_restarts(
        self, api_mock, load_config_mock
    ):
        container_status = SimpleNamespace(ready=True, restart_count=2)
        pod = SimpleNamespace(
            metadata=SimpleNamespace(name="api-123"),
            spec=SimpleNamespace(
                containers=[SimpleNamespace(name="api")],
                node_name="minikube",
            ),
            status=SimpleNamespace(
                phase="Running",
                container_statuses=[container_status],
            ),
        )
        api_mock.return_value.list_namespaced_pod.return_value = SimpleNamespace(
            items=[pod]
        )

        result = kubernetes_tools.get_pods("dev")

        self.assertEqual(result["pod_count"], 1)
        self.assertEqual(result["pods"][0]["ready"], "1/1")
        self.assertEqual(result["pods"][0]["restarts"], 2)
        load_config_mock.assert_called_once()

    @patch("tools.kubernetes_tools._load_k8s_config")
    @patch("tools.kubernetes_tools.client.CoreV1Api")
    def test_invalid_namespace_is_rejected_before_api_call(
        self, api_mock, load_config_mock
    ):
        with self.assertRaises(ValueError):
            kubernetes_tools.get_pods("dev;prod")

        load_config_mock.assert_not_called()
        api_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

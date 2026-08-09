"""Root preflight behavior without contacting a real model server."""

import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from ...run import engine, preflight
from ...run.failure import WorkflowFailure
from ...adapters import gopher


_WORKFLOW = {'workflow': {'steps': []}, 'actionSets': {}}


class LLMPreflightTest(unittest.TestCase):

    def _response(self, status):
        response = MagicMock()
        response.__enter__.return_value.status = status
        return response

    @patch('clay.run.preflight.gopher.resolve_endpoint', return_value='http://127.0.0.1:8080')
    @patch('clay.run.preflight.urllib.request.urlopen')
    def test_ready_llama_server_passes(self, urlopen, endpoint):
        urlopen.return_value = self._response(200)
        self.assertIsNone(preflight.check_llm_endpoint(_WORKFLOW))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:8080/health')
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 2)

    @patch('clay.run.preflight.gopher.resolve_endpoint', return_value='http://127.0.0.1:8080/v1')
    @patch('clay.run.preflight.urllib.request.urlopen')
    def test_v1_endpoint_uses_server_root_health_route(self, urlopen, endpoint):
        urlopen.return_value = self._response(200)
        self.assertIsNone(preflight.check_llm_endpoint(_WORKFLOW))
        self.assertEqual(urlopen.call_args.args[0].full_url,
                         'http://127.0.0.1:8080/health')

    @patch('clay.run.preflight.gopher.resolve_endpoint', return_value='http://127.0.0.1:8080')
    @patch('clay.run.preflight.urllib.request.urlopen')
    def test_missing_health_route_still_proves_server_is_reachable(self, urlopen, endpoint):
        urlopen.side_effect = urllib.error.HTTPError(
            'http://127.0.0.1:8080/health', 404, 'missing', {}, None)
        self.assertIsNone(preflight.check_llm_endpoint(_WORKFLOW))

    @patch('clay.run.preflight.app_config.get_default_model',
           return_value='owner/model-GGUF:Q4_K_M')
    @patch('clay.run.preflight.gopher.resolve_endpoint', return_value='http://127.0.0.1:8080')
    @patch('clay.run.preflight.urllib.request.urlopen',
           side_effect=urllib.error.URLError(ConnectionRefusedError()))
    def test_connection_failure_explains_exact_llama_start_command(
            self, urlopen, endpoint, default_model):
        problem = preflight.check_llm_endpoint(_WORKFLOW)
        self.assertIn('LLM preflight failed', problem)
        self.assertIn('llama-server --hf-repo owner/model-GGUF:Q4_K_M', problem)
        self.assertIn('curl --fail http://127.0.0.1:8080/health', problem)
        self.assertIn('GOPHER_URL', problem)

    @patch('clay.run.preflight.gopher.resolve_endpoint', return_value='http://127.0.0.1:8080')
    @patch('clay.run.preflight.urllib.request.urlopen')
    def test_loading_server_fails_before_actions(self, urlopen, endpoint):
        urlopen.side_effect = urllib.error.HTTPError(
            'http://127.0.0.1:8080/health', 503, 'loading', {}, None)
        with patch.object(preflight, 'CHECKS',
                          (preflight.check_llm_endpoint,)):
            with self.assertRaisesRegex(WorkflowFailure, 'still loading'):
                preflight.run_checks(_WORKFLOW)

    @patch('clay.run.preflight.gopher.resolve_endpoint', return_value='not a url')
    def test_invalid_endpoint_is_actionable_failure(self, endpoint):
        problem = preflight.check_llm_endpoint(_WORKFLOW)
        self.assertIn('configured endpoint is invalid', problem)

    @patch('clay.run.preflight.gopher.resolve_endpoint', return_value='http://127.0.0.1:8080')
    @patch('clay.run.preflight.urllib.request.urlopen')
    def test_authentication_failure_names_http_status(self, urlopen, endpoint):
        urlopen.side_effect = urllib.error.HTTPError(
            'http://127.0.0.1:8080/health', 401, 'unauthorized', {}, None)
        problem = preflight.check_llm_endpoint(_WORKFLOW)
        self.assertIn('HTTP 401', problem)

    @patch('clay.run.preflight.gopher.resolve_endpoint', return_value='http://127.0.0.1:8080')
    @patch('clay.run.preflight.urllib.request.urlopen')
    def test_server_failure_names_http_status(self, urlopen, endpoint):
        urlopen.side_effect = urllib.error.HTTPError(
            'http://127.0.0.1:8080/health', 500, 'failed', {}, None)
        problem = preflight.check_llm_endpoint(_WORKFLOW)
        self.assertIn('HTTP 500', problem)


class EndpointResolutionTest(unittest.TestCase):

    @patch('clay.adapters.gopher.app_config.get_provider_url',
           return_value='http://configured:9000')
    def test_environment_overrides_configured_provider(self, provider_url):
        with patch.dict(os.environ, {'GOPHER_URL': 'http://override:7000'}):
            self.assertEqual(gopher.resolve_endpoint(), 'http://override:7000')

    @patch('clay.adapters.gopher.app_config.get_provider_url',
           return_value='http://configured:9000')
    def test_configured_provider_overrides_builtin_default(self, provider_url):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gopher.resolve_endpoint(), 'http://configured:9000')


class RootPreflightIntegrationTest(unittest.TestCase):

    def test_root_run_checks_once_before_processing_actions(self):
        order = []
        with patch('clay.run.engine.preflight.run_checks',
                   side_effect=lambda workflow: order.append('preflight')), \
                patch('clay.run.engine.process_steps',
                      side_effect=lambda *args, **kwargs: order.append('actions') or {}):
            engine.run_from_data(_WORKFLOW, label='preflight-order')
        self.assertEqual(order, ['preflight', 'actions'])

    def test_failed_preflight_does_not_process_actions(self):
        with patch('clay.run.engine.preflight.run_checks',
                   side_effect=WorkflowFailure('offline')), \
                patch('clay.run.engine.process_steps') as process_steps:
            with self.assertRaisesRegex(WorkflowFailure, 'offline'):
                engine.run_from_data(_WORKFLOW, label='preflight-failure')
        process_steps.assert_not_called()


if __name__ == '__main__':
    unittest.main()

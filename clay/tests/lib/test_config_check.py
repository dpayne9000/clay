import json
import os
import unittest
import urllib.error
import tempfile
from unittest.mock import patch

from clay.lib import config_check


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class ConfigurationProblemTest(unittest.TestCase):

    def check(self, config, payload, *, environment=None):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config',
                             return_value=config), \
                patch.object(config_check.urllib.request, 'urlopen',
                             return_value=_Response(payload)), \
                patch.dict(os.environ, environment or {}, clear=True):
            return config_check.configuration_problem()

    def test_every_configured_profile_must_be_served(self):
        problem = self.check(
            {'provider': {'url': 'http://localhost:8080'},
             'models': {'default': 'model-a', 'code': 'model-b'}},
            {'data': [{'id': 'model-a'}]},
        )
        self.assertIn('code=model-b', problem)

    def test_all_profiles_present_is_healthy(self):
        problem = self.check(
            {'provider': {'url': 'http://localhost:8080'},
             'models': {'default': 'model-a', 'code': 'model-b'}},
            {'data': [{'id': 'model-b'}, {'id': 'model-a'}]},
        )
        self.assertIsNone(problem)

    def test_hugging_face_cache_path_identifies_repository_exactly(self):
        served_path = (
            '/Users/user/.cache/huggingface/hub/'
            'models--mradermacher--DeepSeek-R1-GGUF/snapshots/abc/'
            'DeepSeek-R1.Q4_K_M.gguf')
        problem = self.check(
            {'provider': {'url': 'http://localhost:8080'},
             'models': {
                 'default': 'mradermacher/DeepSeek-R1-GGUF:Q4_K_M',
                 'chat': 'unsloth/Qwen3-GGUF:Q6_K',
             }},
            {'data': [{'id': served_path}]},
        )
        self.assertNotIn('default=', problem)
        self.assertIn('chat=unsloth/Qwen3-GGUF:Q6_K', problem)
        self.assertIn('loaded: mradermacher/DeepSeek-R1-GGUF', problem)
        self.assertNotIn('/Users/user', problem)

    def test_cache_path_requires_hugging_face_snapshot_structure(self):
        problem = self.check(
            {'provider': {'url': 'http://localhost:8080'},
             'models': {'default': 'owner/repository:Q4'}},
            {'data': [{'id': '/tmp/models--owner--repository/model.gguf'}]},
        )
        self.assertIn('default=owner/repository:Q4', problem)

    def test_mismatch_status_requires_confirmation(self):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config', return_value={
                    'provider': {'url': 'http://localhost:8080'},
                    'models': {'default': 'owner/configured:Q4'},
                }), patch.object(config_check.urllib.request, 'urlopen',
                                 return_value=_Response({'data': [{'id': 'other'}]})), \
                patch.dict(os.environ, {}, clear=True):
            status = config_check.configuration_status()
        self.assertTrue(status.model_mismatch)

    def test_only_requested_profiles_are_checked(self):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config', return_value={
                    'provider': {'url': 'http://localhost:8080'},
                    'models': {'default': 'served', 'code': 'served',
                               'chat': 'not-served'},
                }), patch.object(config_check.urllib.request, 'urlopen',
                                 return_value=_Response({'data': [{'id': 'served'}]})), \
                patch.dict(os.environ, {}, clear=True):
            status = config_check.configuration_status({'code'})
        self.assertIsNone(status.problem)

    def test_requested_profile_must_exist_in_config(self):
        config = {
            'provider': {'url': 'http://localhost:8080'},
            'models': {'default': 'served'},
        }
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config',
                             return_value=config), \
                patch.object(config_check.urllib.request, 'urlopen') as opened, \
                patch.dict(os.environ, {}, clear=True):
            status = config_check.configuration_status({'code'})
        self.assertIn('code', status.problem)
        opened.assert_not_called()

    def test_workflow_profiles_include_static_children(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = os.path.join(directory, 'main.json')
            child = os.path.join(directory, 'child.json')
            with open(parent, 'w', encoding='utf-8') as output:
                json.dump({'actionSets': {'run': [
                    {'type': 'scramda2', 'modelProfile': 'chat'},
                    {'type': 'workflow', 'file': './child.json'},
                ]}}, output)
            with open(child, 'w', encoding='utf-8') as output:
                json.dump({'actionSets': {'run': [
                    {'type': 'scramda2', 'modelProfile': 'reports'},
                ]}}, output)

            self.assertEqual({'chat', 'reports'},
                             config_check.model_profiles_in_workflow(parent))

    def test_empty_model_listing_is_not_success(self):
        problem = self.check(
            {'provider': {'url': 'http://localhost:8080'},
             'models': {'default': 'model-a'}},
            {'data': []},
        )
        self.assertIn('advertises no models', problem)

    def test_malformed_model_listing_is_not_success(self):
        problem = self.check(
            {'provider': {'url': 'http://localhost:8080'},
             'models': {'default': 'model-a'}},
            {'models': ['model-a']},
        )
        self.assertIn('invalid /v1/models response', problem)

    def test_blank_profile_value_is_reported_before_network_success(self):
        problem = self.check(
            {'provider': {'url': 'http://localhost:8080'},
             'models': {'default': 'model-a', 'code': ''}},
            {'data': [{'id': 'model-a'}]},
        )
        self.assertIn('code', problem)

    def test_environment_override_is_the_endpoint_that_is_checked(self):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config', return_value={
                    'provider': {'url': 'http://configured:8080'},
                    'models': {'default': 'model-a'},
                }), \
                patch.object(config_check.urllib.request, 'urlopen',
                             return_value=_Response({'data': [{'id': 'model-a'}]})) \
                as opened, \
                patch.dict(os.environ, {'GOPHER_URL': 'http://effective:9090'},
                           clear=True):
            self.assertIsNone(config_check.configuration_problem())
        self.assertEqual(
            'http://effective:9090/v1/models', opened.call_args.args[0].full_url)

    def test_missing_config_stops_before_loading_or_network(self):
        with patch.object(config_check.os.path, 'exists', return_value=False), \
                patch.object(config_check.app_config, 'load_config') as load, \
                patch.object(config_check.urllib.request, 'urlopen') as opened:
            self.assertEqual('no configuration found',
                             config_check.configuration_problem())
        load.assert_not_called()
        opened.assert_not_called()

    def test_missing_provider_url_stops_before_network(self):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config',
                             return_value={'models': {'default': 'model-a'}}), \
                patch.object(config_check.urllib.request, 'urlopen') as opened, \
                patch.dict(os.environ, {}, clear=True):
            problem = config_check.configuration_problem()
        self.assertIn('no provider.url', problem)
        opened.assert_not_called()

    def test_invalid_provider_url_stops_before_network(self):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config', return_value={
                    'provider': {'url': 'localhost:8080'},
                    'models': {'default': 'model-a'},
                }), patch.object(config_check.urllib.request, 'urlopen') as opened, \
                patch.dict(os.environ, {}, clear=True):
            problem = config_check.configuration_problem()
        self.assertIn('provider.url is invalid', problem)
        opened.assert_not_called()

    def test_no_models_stops_before_network(self):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config', return_value={
                    'provider': {'url': 'http://localhost:8080'}, 'models': {},
                }), patch.object(config_check.urllib.request, 'urlopen') as opened, \
                patch.dict(os.environ, {}, clear=True):
            problem = config_check.configuration_problem()
        self.assertEqual('no models configured', problem)
        opened.assert_not_called()

    def test_transport_failure_is_an_advisory_problem(self):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config', return_value={
                    'provider': {'url': 'http://localhost:8080'},
                    'models': {'default': 'model-a'},
                }), patch.object(config_check.urllib.request, 'urlopen',
                                 side_effect=urllib.error.URLError('offline')), \
                patch.dict(os.environ, {}, clear=True):
            problem = config_check.configuration_problem()
        self.assertIn('not reachable', problem)

    def test_invalid_json_is_not_misreported_as_a_transport_failure(self):
        response = _Response({})
        response.read = lambda: b'not json'
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config', return_value={
                    'provider': {'url': 'http://localhost:8080'},
                    'models': {'default': 'model-a'},
                }), patch.object(config_check.urllib.request, 'urlopen',
                                 return_value=response), \
                patch.dict(os.environ, {}, clear=True):
            problem = config_check.configuration_problem()
        self.assertIn('invalid JSON', problem)
        self.assertNotIn('not reachable', problem)

    def test_completion_endpoint_is_reduced_to_server_root(self):
        with patch.object(config_check.os.path, 'exists', return_value=True), \
                patch.object(config_check.app_config, 'load_config', return_value={
                    'provider': {'url': 'http://localhost:8080/v1/chat/completions'},
                    'models': {'default': 'model-a'},
                }), patch.object(config_check.urllib.request, 'urlopen',
                                 return_value=_Response({'data': [{'id': 'model-a'}]})) \
                as opened, patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(config_check.configuration_problem())
        self.assertEqual('http://localhost:8080/v1/models',
                         opened.call_args.args[0].full_url)


if __name__ == '__main__':
    unittest.main()

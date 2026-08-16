"""Integration tests for _load_config() in clay/cli.py.

_load_config() seeds every workflow run with:
  - '__config__' : parsed clay/configs/default.json (or {} if missing/invalid)
  - '__schema__' : JSON string from the action registry

Both keys are seeded into initial_data. Actions must list them in includedData
to receive them — the engine does NOT auto-inject (Flow A).
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from clay.cli import _load_config
from clay.lib import config as lib_config
from clay.run import io as run_io


class _ApprovingIO:
    """Answers every prompt 'y'. `python` is a required gate (573aee4) and
    reaches this test's terminal for real without a scripted channel."""

    def prompt(self, prompt_id, text):
        return 'y'


class TestLoadConfigStructure(unittest.TestCase):

    def test_returns_dict_with_config_key(self):
        result = _load_config()
        self.assertIn('__config__', result)

    def test_returns_dict_with_schema_key(self):
        result = _load_config()
        self.assertIn('__schema__', result)

    def test_config_value_is_dict(self):
        result = _load_config()
        self.assertIsInstance(result['__config__'], dict)

    def test_schema_value_is_string(self):
        result = _load_config()
        self.assertIsInstance(result['__schema__'], str)

    def test_schema_value_is_valid_json(self):
        result = _load_config()
        parsed = json.loads(result['__schema__'])
        self.assertIsNotNone(parsed)


class TestLoadConfigSelfHealing(unittest.TestCase):
    """The user config is self-healing (create_user_config): a missing file is
    created from the baked-in configs/default.json; a corrupt one is recreated
    from those defaults with a stdout message. Never an empty-dict fallback."""

    def setUp(self):
        lib_config.reload_config()

    def tearDown(self):
        lib_config.reload_config()

    def _patched_paths(self, tmpdir):
        return (patch('clay.lib.config._CONFIG_PATH', os.path.join(tmpdir, 'config.json')),
                patch('clay.lib.config._SCHEMA_PATH', os.path.join(tmpdir, 'schema.json')))

    def _baked_in_defaults(self):
        with open(lib_config._BASE_CONFIG_PATH) as f:
            return json.load(f)

    def test_missing_config_created_from_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_patch, schema_patch = self._patched_paths(d)
            with cfg_patch, schema_patch:
                result = _load_config()
                self.assertTrue(os.path.exists(os.path.join(d, 'config.json')),
                                "user config was not auto-created")
        self.assertEqual(result['__config__'], self._baked_in_defaults())

    def test_corrupt_config_recreated_with_stdout_message(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, 'config.json')
            with open(cfg, 'w') as f:
                f.write('{broken json')
            cfg_patch, schema_patch = self._patched_paths(d)
            buf = io.StringIO()
            with cfg_patch, schema_patch, contextlib.redirect_stdout(buf):
                result = _load_config()
        self.assertIn('recreating', buf.getvalue())
        self.assertEqual(result['__config__'], self._baked_in_defaults())

    def test_non_object_config_recreated_from_defaults(self):
        # Valid JSON but a list — thin validation requires a JSON object.
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, 'config.json')
            with open(cfg, 'w') as f:
                json.dump([1, 2, 3], f)
            cfg_patch, schema_patch = self._patched_paths(d)
            with cfg_patch, schema_patch, contextlib.redirect_stdout(io.StringIO()):
                result = _load_config()
        self.assertEqual(result['__config__'], self._baked_in_defaults())

    def test_valid_config_gains_new_managed_defaults_without_losing_values(self):
        fake_config = {"models": {"fast": "llama-3-8b"}, "env": "test"}
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, 'config.json')
            with open(cfg, 'w') as f:
                json.dump(fake_config, f)
            cfg_patch, schema_patch = self._patched_paths(d)
            with cfg_patch, schema_patch:
                result = _load_config()
                with open(cfg) as f:
                    updated = json.load(f)
        self.assertEqual(updated['models'], fake_config['models'])
        self.assertEqual(updated['env'], 'test')
        self.assertEqual(updated['maxTokens'], lib_config.DEFAULT_MAX_TOKENS)
        self.assertEqual(result['__config__'], updated)

    def test_existing_max_tokens_is_preserved(self):
        fake_config = {"maxTokens": 12345, "models": {"default": "model"}}
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, 'config.json')
            with open(cfg, 'w') as f:
                json.dump(fake_config, f)
            cfg_patch, schema_patch = self._patched_paths(d)
            with cfg_patch, schema_patch:
                result = _load_config()
        self.assertEqual(result['__config__']['maxTokens'], 12345)


class TestLoadConfigContent(unittest.TestCase):

    def test_schema_contains_action_type_names(self):
        """Schema JSON should reference at least some action types."""
        result = _load_config()
        schema_text = result['__schema__']
        # Action types present in the registry
        self.assertIn("scramda2", schema_text)
        self.assertIn("humanDecision", schema_text)


class TestLoadConfigRunIntegration(unittest.TestCase):
    """Verify that __config__ + __schema__ are available inside a live workflow run."""

    def test_config_persists_through_workflow(self):
        """__config__ from _load_config() survives in step_output throughout the run."""
        from clay.run import engine
        seed = _load_config()
        wf = {
            "workflow": {"steps": ["run"]},
            "actionSets": {"run": [
                {"id": "marker", "type": "python", "code": "print('ok')"},
            ]},
        }
        with patch.object(run_io, 'get', return_value=_ApprovingIO()):
            result = engine.run_from_data(wf, initial_data=seed, auto=True)
        self.assertIn('__config__', result)
        self.assertIsInstance(result['__config__'], dict)

    def test_schema_accessible_when_listed_in_included_data(self):
        """__schema__ is no longer RESERVED — transformData can find it when no includedData filter."""
        from clay.run import engine
        # With no includedData, all keys pass through including __schema__.
        # transformData finds the source and stores the result under "checker".
        wf = {
            "workflow": {"steps": ["run"]},
            "actionSets": {"run": [
                {"id": "checker", "type": "transformData",
                 "source": "__schema__", "method": "parseLines"},
            ]},
        }
        seed = _load_config()
        result = engine.run_from_data(wf, initial_data=seed, auto=True)
        self.assertIn("checker", result)


if __name__ == '__main__':
    unittest.main()

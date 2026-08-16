"""Tests for the workflow linter: includedData scope and unknown-field detection."""
import json
import os
import tempfile
import unittest
from typing import Optional

from clay.lint import lint_file, lint_dir


def _write(d: dict, tmpdir: str, name: str = "wf.json") -> str:
    path = os.path.join(tmpdir, name)
    with open(path, "w") as f:
        json.dump(d, f)
    return path


def _workflow(steps: list, action_sets: dict, defaults: Optional[dict] = None) -> dict:
    d: dict = {"workflow": {"steps": steps}, "actionSets": action_sets}
    if defaults:
        d["defaults"] = defaults
    return d


class TestIncludedDataScope(unittest.TestCase):
    """_lint_included_data_scope via lint_file."""

    def test_key_produced_by_preceding_action_is_ok(self):
        wf = _workflow(
            ["a", "b"],
            {
                "a": [{"id": "value", "type": "humanDecision", "prompt": "x"}],
                "b": [{"id": "out", "type": "humanDecision", "prompt": "x",
                       "includedData": ["value"]}],
            },
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_key_from_same_step_earlier_action_is_ok(self):
        wf = _workflow(
            ["run"],
            {
                "run": [
                    {"id": "first", "type": "humanDecision", "prompt": "x"},
                    {"id": "second", "type": "humanDecision", "prompt": "x",
                     "includedData": ["first"]},
                ],
            },
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_key_from_later_step_is_error(self):
        """Using an id that is only produced in a later step must be flagged."""
        wf = _workflow(
            ["a", "b"],
            {
                "a": [{"id": "early", "type": "humanDecision", "prompt": "x",
                       "includedData": ["late"]}],
                "b": [{"id": "late", "type": "humanDecision", "prompt": "x"}],
            },
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(len(scope_errors), 1)
        self.assertIn("'late'", scope_errors[0])

    def test_key_from_defaults_is_ok(self):
        wf = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["seed"]}]},
            defaults={"seed": "hello"},
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_system_keys_are_always_ok(self):
        wf = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["__config__", "__schema__"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_iteration_key_is_always_ok(self):
        """'iteration' is injected by the loop engine so never needs a producer."""
        wf = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["iteration"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_alias_entry_root_is_checked(self):
        """'alias=missing_key.sub' should flag 'missing_key' as not in scope."""
        wf = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["result=missing_key.sub"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(len(scope_errors), 1)
        self.assertIn("'missing_key'", scope_errors[0])

    def test_dot_path_root_is_checked(self):
        """'key.subkey' should only verify 'key' is in scope."""
        wf = _workflow(
            ["a", "b"],
            {
                "a": [{"id": "data", "type": "humanDecision", "prompt": "x"}],
                "b": [{"id": "out", "type": "humanDecision", "prompt": "x",
                       "includedData": ["data.nested_field"]}],
            },
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_completely_unknown_key_is_error(self):
        wf = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["ghost_key"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(len(scope_errors), 1)
        self.assertIn("ghost_key", scope_errors[0])


class TestExternalKeys(unittest.TestCase):
    """Cross-file scope: keys passed via parent workflow/loop includedData."""

    def test_key_from_parent_workflow_includedData_is_ok(self):
        """Sub-workflow receives external_key via parent's includedData."""
        sub = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["external_key"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            sub_path = _write(sub, d, "sub.json")
            parent = _workflow(
                ["call"],
                {"call": [{"id": "result", "type": "workflow",
                           "file": "sub.json",
                           "includedData": ["external_key"],
                           "_note": "external_key produced earlier in parent"}]},
            )
            _write(parent, d, "parent.json")
            results = lint_dir(d)
        sub_result = next(r for r in results if r.path == sub_path)
        scope_errors = [e for e in sub_result.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_key_not_passed_by_parent_is_error(self):
        """If the parent's includedData doesn't include the key, it's an error."""
        sub = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["needed_key"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            sub_path = _write(sub, d, "sub.json")
            parent = _workflow(
                ["call"],
                {"call": [{"id": "result", "type": "workflow",
                           "file": "sub.json",
                           "includedData": ["other_key"]}]},
            )
            _write(parent, d, "parent.json")
            results = lint_dir(d)
        sub_result = next(r for r in results if r.path == sub_path)
        scope_errors = [e for e in sub_result.errors if "includedData" in e]
        self.assertEqual(len(scope_errors), 1)
        self.assertIn("needed_key", scope_errors[0])

    def test_parent_alias_exposes_alias_to_child(self):
        """The child sees the alias, not the parent's source-key name."""
        sub = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["child_name"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            sub_path = _write(sub, d, "sub.json")
            parent = _workflow(
                ["make", "call"],
                {
                    "make": [{"id": "parent_value", "type": "humanDecision",
                              "prompt": "x"}],
                    "call": [{"id": "result", "type": "workflow",
                              "file": "sub.json",
                              "includedData": ["child_name=parent_value"]}],
                },
            )
            _write(parent, d, "parent.json")
            results = lint_dir(d)
        sub_result = next(r for r in results if r.path == sub_path)
        self.assertEqual(
            [e for e in sub_result.errors if "includedData" in e], []
        )

    def test_parent_dot_path_exposes_leaf_name_to_child(self):
        """Without an alias, build_ctx names a selected dot path by its leaf."""
        sub = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["final"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            sub_path = _write(sub, d, "sub.json")
            parent = _workflow(
                ["make", "call"],
                {
                    "make": [{"id": "result", "type": "humanDecision",
                              "prompt": "x"}],
                    "call": [{"id": "nested", "type": "workflow",
                              "file": "sub.json",
                              "includedData": ["result.final"]}],
                },
            )
            _write(parent, d, "parent.json")
            results = lint_dir(d)
        sub_result = next(r for r in results if r.path == sub_path)
        self.assertEqual(
            [e for e in sub_result.errors if "includedData" in e], []
        )


class TestDataFiles(unittest.TestCase):
    def test_nested_context_objects_are_valid(self):
        with tempfile.TemporaryDirectory() as d:
            result = lint_file(_write({"training": {"examples": [1]}}, d))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])

    def test_loop_iteration_gets_own_ids_from_prev_iteration(self):
        """Loop iterations can reference their own action ids (prev iteration outputs)."""
        iteration = _workflow(
            ["step_a", "step_b"],
            {
                "step_a": [{"id": "produced_last_iter", "type": "humanDecision",
                            "prompt": "x"}],
                # step_b references produced_last_iter which runs AFTER it in order
                # but is valid because it comes from the previous iteration
                "step_b": [{"id": "out", "type": "humanDecision", "prompt": "x",
                            "includedData": ["produced_last_iter"]}],
            },
        )
        with tempfile.TemporaryDirectory() as d:
            iter_path = _write(iteration, d, "iteration.json")
            parent = _workflow(
                ["run"],
                {"run": [{"id": "log", "type": "loop",
                          "file": "iteration.json",
                          "includedData": ["seed"]}]},
            )
            _write(parent, d, "parent.json")
            results = lint_dir(d)
        iter_result = next(r for r in results if r.path == iter_path)
        scope_errors = [e for e in iter_result.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_unconstrained_caller_skips_scope_check(self):
        """If a parent calls a sub-workflow with no includedData, scope is
        unverifiable and the check is skipped (no false positives)."""
        sub = _workflow(
            ["run"],
            {"run": [{"id": "out", "type": "humanDecision", "prompt": "x",
                      "includedData": ["anything_at_all"]}]},
        )
        with tempfile.TemporaryDirectory() as d:
            sub_path = _write(sub, d, "sub.json")
            parent = _workflow(
                ["call"],
                # No includedData → full ctx passes through
                {"call": [{"id": "result", "type": "workflow", "file": "sub.json"}]},
            )
            _write(parent, d, "parent.json")
            results = lint_dir(d)
        sub_result = next(r for r in results if r.path == sub_path)
        scope_errors = [e for e in sub_result.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])


class TestLoadContextExpandsScope(unittest.TestCase):
    """loadContext merges a file's keys into scope for subsequent actions."""

    def test_loadContext_keys_available_after_action(self):
        with tempfile.TemporaryDirectory() as d:
            ctx_path = os.path.join(d, "ctx.json")
            with open(ctx_path, "w") as f:
                json.dump({"injected_key": "hello"}, f)

            wf = _workflow(
                ["load", "use"],
                {
                    "load": [{"id": "ctx", "type": "loadContext", "file": ctx_path}],
                    "use": [{"id": "out", "type": "humanDecision", "prompt": "x",
                             "includedData": ["injected_key"]}],
                },
            )
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(scope_errors, [])

    def test_loadContext_key_not_yet_available_before_it_runs(self):
        """A key from loadContext is NOT in scope before the loadContext action."""
        with tempfile.TemporaryDirectory() as d:
            ctx_path = os.path.join(d, "ctx.json")
            with open(ctx_path, "w") as f:
                json.dump({"injected_key": "hello"}, f)

            wf = _workflow(
                ["use", "load"],
                {
                    # Uses injected_key BEFORE loadContext runs
                    "use": [{"id": "out", "type": "humanDecision", "prompt": "x",
                             "includedData": ["injected_key"]}],
                    "load": [{"id": "ctx", "type": "loadContext", "file": ctx_path}],
                },
            )
            r = lint_file(_write(wf, d))
        scope_errors = [e for e in r.errors if "includedData" in e]
        self.assertEqual(len(scope_errors), 1)
        self.assertIn("injected_key", scope_errors[0])


class TestUnknownFieldDetection(unittest.TestCase):
    """Fields not declared by an action type are ignored at runtime.

    Nothing catches them otherwise: registry.validate() only checks that
    required fields are present, never that the action's own keys are real.
    """

    @staticmethod
    def _unknown_warnings(result) -> list[str]:
        return [w for w in result.warnings if "unknown field" in w]

    def _lint_action(self, action: dict):
        wf = _workflow(["run"], {"run": [action]})
        with tempfile.TemporaryDirectory() as d:
            return lint_file(_write(wf, d))

    def test_undeclared_field_is_warned(self):
        r = self._lint_action(
            {"id": "out", "type": "shell", "command": "ls", "cwd": "/tmp"}
        )
        warnings = self._unknown_warnings(r)
        self.assertEqual(len(warnings), 1)
        self.assertIn("'cwd'", warnings[0])
        self.assertIn("'shell'", warnings[0])

    def test_warning_lists_the_valid_field_names(self):
        r = self._lint_action(
            {"id": "out", "type": "shell", "command": "ls", "cwd": "/tmp"}
        )
        warning = self._unknown_warnings(r)[0]
        for name in ("id", "command", "timeout"):
            self.assertIn(name, warning)

    def test_undeclared_field_is_never_an_error(self):
        """Warning only — the emitted JSON Schema allows additionalProperties."""
        r = self._lint_action(
            {"id": "out", "type": "shell", "command": "ls", "cwd": "/tmp"}
        )
        self.assertEqual(r.errors, [])
        self.assertTrue(r.ok)

    def test_declared_optional_field_is_not_warned(self):
        r = self._lint_action(
            {"id": "out", "type": "shell", "command": "ls", "timeout": 5}
        )
        self.assertEqual(self._unknown_warnings(r), [])

    def test_case_mismatch_is_caught(self):
        """scramda2 declares max_tokens; maxTokens is silently dropped."""
        r = self._lint_action(
            {"id": "out", "type": "scramda2", "prompt": "x", "maxTokens": 100}
        )
        warnings = self._unknown_warnings(r)
        self.assertEqual(len(warnings), 1)
        self.assertIn("'maxTokens'", warnings[0])

    def test_declared_snake_case_field_is_accepted(self):
        r = self._lint_action(
            {"id": "out", "type": "scramda2", "prompt": "x", "max_tokens": 100}
        )
        self.assertEqual(self._unknown_warnings(r), [])

    def test_includedData_is_never_flagged(self):
        r = self._lint_action(
            {"id": "out", "type": "shell", "command": "ls", "includedData": []}
        )
        self.assertEqual(self._unknown_warnings(r), [])

    def test_outputKey_is_never_flagged(self):
        r = self._lint_action(
            {"id": "out", "type": "shell", "command": "ls",
             "outputKey": "alias"}
        )
        self.assertEqual(self._unknown_warnings(r), [])

    def test_underscore_prefixed_keys_are_never_flagged(self):
        r = self._lint_action(
            {"id": "out", "type": "shell", "command": "ls",
             "_comment": "explanatory note"}
        )
        self.assertEqual(self._unknown_warnings(r), [])

    def test_unknown_action_type_produces_no_field_warnings(self):
        """No schema to compare against — the type warning stands alone."""
        r = self._lint_action(
            {"id": "out", "type": "notARealType", "whatever": 1}
        )
        self.assertEqual(self._unknown_warnings(r), [])
        self.assertTrue(any("unknown action type" in w for w in r.warnings))

    def test_multiple_undeclared_fields_each_warn(self):
        r = self._lint_action(
            {"id": "out", "type": "shell", "command": "ls",
             "cwd": "/tmp", "shell": True}
        )
        self.assertEqual(len(self._unknown_warnings(r)), 2)

    def test_readFile_fields_are_declared(self):
        """readFile was absent from the registry until this check landed."""
        r = self._lint_action(
            {"id": "out", "type": "readFile", "file": "notes.txt",
             "root": "output", "encoding": "utf-8", "maxBytes": 1024}
        )
        self.assertEqual(self._unknown_warnings(r), [])
        self.assertEqual(
            [w for w in r.warnings if "unknown action type" in w], []
        )

    def test_writeFile_handler_fields_are_declared(self):
        """All seven options write_file.handler reads must be in the schema."""
        r = self._lint_action(
            {"id": "out", "type": "writeFile", "file": "a.txt",
             "content": "src", "root": "output", "encoding": "utf-8",
             "append": True, "createParent": True, "stripCodeFence": False,
             "requireCodeFence": False, "ensureFinalNewline": True}
        )
        self.assertEqual(self._unknown_warnings(r), [])


if __name__ == "__main__":
    unittest.main()

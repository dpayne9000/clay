"""Tests for clay.lib.context.build_ctx.

Covers:
  - No includedData → full pass-through (backward-compat)
  - includedData present → ONLY listed keys in ctx (no leakage)
  - Dot-path resolution ("a.b", "alias=a.b.c")
  - PASSTHROUGH_KEYS → documents engine-seeded globals (__config__, __schema__)
    but does NOT auto-inject them (Flow A: must be listed in includedData)
  - RESERVED_KEYS is now empty — nothing is auto-stripped
  - Edge cases: missing keys, empty lists, alias collisions
"""

import unittest

from ...lib.context import build_ctx, RESERVED_KEYS, PASSTHROUGH_KEYS


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _action(included=None):
    """Build a minimal action dict for build_ctx."""
    a = {}
    if included is not None:
        a['includedData'] = included
    return a


# ─────────────────────────────────────────────────────────────────────────────
# No includedData — backward-compat full pass-through
# ─────────────────────────────────────────────────────────────────────────────

class TestNoIncludedData(unittest.TestCase):

    def test_returns_all_keys_when_no_included_data(self):
        source = {"a": 1, "b": 2, "c": 3}
        ctx = build_ctx(source, _action())
        self.assertEqual(ctx, {"a": 1, "b": 2, "c": 3})
        self.assertIsNot(ctx, source)

    def test_unfiltered_action_cannot_mutate_accumulated_context(self):
        source = {"a": 1, "b": 2}
        ctx = build_ctx(source, _action())
        ctx["a"] = 99
        ctx["new"] = 3
        self.assertEqual(source, {"a": 1, "b": 2})

    def test_empty_step_output_returns_empty(self):
        self.assertEqual(build_ctx({}, _action()), {})

    def test_schema_key_passes_through_without_filter(self):
        # RESERVED_KEYS is now empty; __schema__ is no longer stripped
        ctx = build_ctx({"a": 1, "__schema__": "schema-data"}, _action())
        self.assertIn("a", ctx)
        self.assertIn("__schema__", ctx)

    def test_passthrough_keys_not_special_without_included_data(self):
        """PASSTHROUGH_KEYS have no special effect when includedData is absent — everything already passes."""
        ctx = build_ctx({"a": 1, "__config__": {"x": 1}}, _action())
        self.assertEqual(ctx, {"a": 1, "__config__": {"x": 1}})


# ─────────────────────────────────────────────────────────────────────────────
# Leakage — with includedData only listed keys must appear
# ─────────────────────────────────────────────────────────────────────────────

class TestLeakage(unittest.TestCase):
    """Explicit checks that unlisted keys do NOT appear in ctx."""

    STEP = {
        "goal": "build an API",
        "__config__": {"env": "prod"},
        "secret_token": "abc123",
        "credentials": {"user": "admin", "pass": "hunter2"},
        "internal_state": {"iteration": 5},
        "output": "some result",
    }

    def test_unlisted_key_does_not_leak(self):
        ctx = build_ctx(self.STEP, _action(included=["goal"]))
        self.assertNotIn("secret_token", ctx)
        self.assertNotIn("credentials", ctx)
        self.assertNotIn("internal_state", ctx)
        self.assertNotIn("output", ctx)

    def test_only_listed_key_present_no_auto_inject(self):
        # __config__ is NOT auto-injected in Flow A — must be listed in includedData
        ctx = build_ctx(self.STEP, _action(included=["goal"]))
        self.assertIn("goal", ctx)
        self.assertNotIn("__config__", ctx)

    def test_multiple_listed_keys_no_extras(self):
        ctx = build_ctx(self.STEP, _action(included=["goal", "output"]))
        self.assertNotIn("secret_token", ctx)
        self.assertNotIn("credentials", ctx)
        self.assertNotIn("internal_state", ctx)
        self.assertNotIn("__config__", ctx)  # not listed
        self.assertIn("goal", ctx)
        self.assertIn("output", ctx)

    def test_empty_included_data_produces_empty_ctx(self):
        """An explicit empty includedData list returns an empty ctx — no auto-inject."""
        ctx = build_ctx(self.STEP, _action(included=[]))
        self.assertEqual(ctx, {})

    def test_nonexistent_key_in_included_data_silently_skipped(self):
        ctx = build_ctx(self.STEP, _action(included=["goal", "does_not_exist"]))
        self.assertIn("goal", ctx)
        self.assertNotIn("does_not_exist", ctx)

    def test_schema_key_accessible_when_listed(self):
        # __schema__ is no longer RESERVED; listing it in includedData delivers it
        step = {**self.STEP, "__schema__": "accessible-now"}
        ctx = build_ctx(step, _action(included=["__schema__", "goal"]))
        self.assertIn("__schema__", ctx)
        self.assertIn("goal", ctx)


# ─────────────────────────────────────────────────────────────────────────────
# Dot-path resolution
# ─────────────────────────────────────────────────────────────────────────────

class TestDotPaths(unittest.TestCase):

    STEP = {
        "loop_result": {"summary": "iteration done", "score": 42},
        "workflow_out": {"nested": {"deep": "found it"}},
        "flat": "plain value",
    }

    def test_dot_path_uses_leaf_as_key(self):
        ctx = build_ctx(self.STEP, _action(included=["loop_result.summary"]))
        self.assertEqual(ctx["summary"], "iteration done")

    def test_dot_path_alias_overrides_leaf_name(self):
        ctx = build_ctx(self.STEP, _action(included=["result=loop_result.summary"]))
        self.assertEqual(ctx["result"], "iteration done")

    def test_three_level_dot_path(self):
        ctx = build_ctx(self.STEP, _action(included=["val=workflow_out.nested.deep"]))
        self.assertEqual(ctx["val"], "found it")

    def test_flat_key_alongside_dot_path(self):
        ctx = build_ctx(self.STEP, _action(included=["flat", "loop_result.score"]))
        self.assertIn("flat", ctx)
        self.assertIn("score", ctx)

    def test_missing_dot_path_silently_skipped(self):
        ctx = build_ctx(self.STEP, _action(included=["loop_result.missing_key"]))
        self.assertNotIn("missing_key", ctx)

    def test_dot_path_into_non_dict_silently_skipped(self):
        ctx = build_ctx(self.STEP, _action(included=["flat.nonexistent"]))
        self.assertNotIn("nonexistent", ctx)

    def test_dot_path_parent_missing_silently_skipped(self):
        ctx = build_ctx(self.STEP, _action(included=["no_such_parent.key"]))
        self.assertNotIn("key", ctx)

    def test_dot_path_does_not_leak_sibling_keys(self):
        """Extracting one key from a dict must not expose the rest of that dict."""
        ctx = build_ctx(self.STEP, _action(included=["loop_result.summary"]))
        self.assertNotIn("loop_result", ctx)
        self.assertNotIn("score", ctx)


# ─────────────────────────────────────────────────────────────────────────────
# PASSTHROUGH_KEYS — documents engine globals, NOT auto-injected (Flow A)
# ─────────────────────────────────────────────────────────────────────────────

class TestEnginePassthroughKeys(unittest.TestCase):

    STEP = {
        "__config__": {"env": "prod", "model": "claude"},
        "goal": "build API",
        "secret": "do-not-share",
    }

    def test_passthrough_key_not_auto_injected(self):
        # Flow A: __config__ must be listed in includedData to appear in ctx
        ctx = build_ctx(self.STEP, _action(included=["goal"]))
        self.assertNotIn("__config__", ctx)
        self.assertIn("goal", ctx)

    def test_non_passthrough_key_still_blocked(self):
        ctx = build_ctx(self.STEP, _action(included=["goal"]))
        self.assertNotIn("secret", ctx)

    def test_passthrough_key_absent_from_step_output_silently_skipped(self):
        step = {"goal": "build API", "secret": "nope"}
        ctx = build_ctx(step, _action(included=["goal"]))
        self.assertNotIn("__config__", ctx)

    def test_passthrough_key_accessible_when_listed_in_included_data(self):
        ctx = build_ctx(self.STEP, _action(included=["__config__"]))
        self.assertIn("__config__", ctx)
        self.assertEqual(ctx["__config__"], {"env": "prod", "model": "claude"})

    def test_passthrough_keys_constant_is_frozenset(self):
        self.assertIsInstance(PASSTHROUGH_KEYS, frozenset)

    def test_config_is_in_passthrough_keys(self):
        self.assertIn("__config__", PASSTHROUGH_KEYS)

    def test_schema_is_in_passthrough_keys(self):
        self.assertIn("__schema__", PASSTHROUGH_KEYS)

    def test_schema_accessible_when_listed_in_included_data(self):
        step = {**self.STEP, "__schema__": "schema-data"}
        ctx = build_ctx(step, _action(included=["__schema__"]))
        self.assertIn("__schema__", ctx)
        self.assertEqual(ctx["__schema__"], "schema-data")


# ─────────────────────────────────────────────────────────────────────────────
# RESERVED_KEYS — now empty
# ─────────────────────────────────────────────────────────────────────────────

class TestReservedKeys(unittest.TestCase):

    def test_reserved_keys_set_is_empty(self):
        """RESERVED_KEYS is now empty — nothing is auto-blocked."""
        self.assertEqual(RESERVED_KEYS, frozenset())

    def test_schema_key_accessible_without_filter(self):
        """__schema__ is no longer reserved; it passes through when no includedData."""
        ctx = build_ctx({"__schema__": "value", "a": 1}, _action())
        self.assertIn("__schema__", ctx)

    def test_schema_key_accessible_when_listed_in_included_data(self):
        """Actions can receive __schema__ by listing it in includedData."""
        ctx = build_ctx({"__schema__": "x", "a": 1}, _action(included=["__schema__"]))
        self.assertIn("__schema__", ctx)
        self.assertEqual(ctx["__schema__"], "x")

    def test_non_reserved_double_underscore_allowed(self):
        """All __ keys are accessible (RESERVED_KEYS is empty)."""
        ctx = build_ctx({"__version__": "1.0", "a": 1}, _action())
        self.assertIn("__version__", ctx)


if __name__ == '__main__':
    unittest.main()

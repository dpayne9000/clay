"""Invariant tests for clay/actions/registry.py and its consumer dispatcher.py.

These assert the structural property that would have caught the readFile bug:
a type present in _HANDLERS but absent from _REGISTRY (or vice versa) is a
schema/handler mismatch, not a "missing test coverage" gap.
"""

import unittest

from ...actions import registry
from ...run.dispatcher import dispatch

# Types dispatch() routes through explicit branches (extra engine arguments)
# rather than the generic handler = handler_for_type(action_type) lookup.
_SPECIAL_TYPES = frozenset({
    'scramda2', 'humanDecision', 'workflow', 'loop', 'humanShell', 'loadContext',
})


class TestRegistryHandlerInvariant(unittest.TestCase):

    def setUp(self):
        registry.discover()

    def test_every_registered_type_has_a_handler(self):
        missing = set(registry._REGISTRY) - set(registry._HANDLERS)
        self.assertEqual(missing, set(), f"types with a schema but no handler: {missing}")

    def test_every_handler_has_a_registered_type(self):
        missing = set(registry._HANDLERS) - set(registry._REGISTRY)
        self.assertEqual(missing, set(), f"types with a handler but no schema: {missing}")

    def test_dispatch_routable_set_matches_registry(self):
        # Every non-special type must resolve through handler_for_type() —
        # this is exactly the lookup the generic branch of dispatch() uses.
        generic_types = set(registry._REGISTRY) - _SPECIAL_TYPES
        unroutable = {t for t in generic_types if registry.handler_for_type(t) is None}
        self.assertEqual(unroutable, set())

    def test_special_types_are_registered(self):
        # The six extra-argument branches in dispatch() reference these types
        # by name; if one drops out of the registry, dispatch() silently no-ops.
        missing = _SPECIAL_TYPES - set(registry._REGISTRY)
        self.assertEqual(missing, set(), f"special types missing from registry: {missing}")

    def test_every_handler_takes_action_and_ctx(self):
        # A @handler_for decorator sits on the line above its function, so a
        # helper inserted between the two silently steals the registration and
        # the real handler loses it. Presence tests above still pass — the type
        # has *a* handler — and it fails only when a live run calls it with
        # (action, ctx). Checking the signature is what distinguishes "some
        # callable is registered" from "the handler is registered".
        import inspect

        wrong = {}
        for type_name, func in registry._HANDLERS.items():
            params = list(inspect.signature(func).parameters.values())
            names = [p.name for p in params[:2]]
            extras_optional = all(p.default is not inspect.Parameter.empty
                                  for p in params[2:])
            if names != ['action', 'ctx'] or not extras_optional:
                wrong[type_name] = f'{func.__name__}{inspect.signature(func)}'
        self.assertEqual(wrong, {}, f"handlers not callable as (action, ctx): {wrong}")


class TestDiscoveryOrderStable(unittest.TestCase):

    def test_repeated_discovery_yields_same_order(self):
        # discover() walks modules in sorted name order, not filesystem order,
        # so repeated (forced) discovery must produce identical registration
        # order regardless of machine or directory-listing order.
        registry.discover(force=True)
        first = list(registry._REGISTRY)
        registry.discover(force=True)
        second = list(registry._REGISTRY)
        self.assertEqual(first, second)

    def test_order_is_alphabetical_by_module(self):
        # Cross-check discover()'s own contract: modules are walked via
        # sorted(pkgutil.walk_packages(...)), so re-deriving that sorted
        # module list independently must reproduce the same order discover()
        # used, not just be stable run-to-run.
        import importlib
        import pkgutil

        package = importlib.import_module('clay.actions')
        expected_modules = sorted(
            info.name
            for info in pkgutil.walk_packages(package.__path__, package.__name__ + ".")
        )

        registry.discover(force=True)
        seen_modules = []
        for type_name, cls in registry._REGISTRY.items():
            module = cls.__module__
            if module not in seen_modules:
                seen_modules.append(module)

        # Every module that registered a type must appear in the same
        # relative order as expected_modules (module-walk order).
        filtered_expected = [m for m in expected_modules if m in seen_modules]
        self.assertEqual(seen_modules, filtered_expected)

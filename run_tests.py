#!/usr/bin/env python3
"""
clay workflow integration test runner
────────────────────────────────────────
Each test class runs one workflow JSON from clay/data/workflows/test/ end-to-end and
asserts on the returned step_output dict.  This exercises the real execution
path — file I/O, shell actions, context filtering, loop/sub-workflow wiring —
without mocking the engine internals.

Usage:
    python run_tests.py          # all workflow tests
    python run_tests.py -v       # verbose (show each test name)
    python run_tests.py -f       # stop on first failure
    python run_tests.py context  # filter by class name keyword
"""

import contextlib
import io
import os
import sys
import time
import traceback
import unittest
from collections import defaultdict

from clay.run import engine
from clay.cli import _load_config

from clay.lib import config

WORKFLOW_DIR = config.data_path('workflows', 'test')

# Seed every test workflow the same way the CLI does: __config__ + __schema__.
_CLI_SEED = _load_config()


# ── workflow runner ────────────────────────────────────────────────────────────

def _run_workflow(filename, initial_data=None):
    """Run a test workflow, suppressing all stdout. Returns step_output (never None).

    Seeds with the same _load_config() the CLI uses so context filtering tests
    reflect real runtime behavior, not a stripped-down mock environment.
    """
    path = os.path.join(WORKFLOW_DIR, filename)
    seed = {**_CLI_SEED, **(initial_data or {})}
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        result = engine.run(path, initial_data=seed)
    return result or {}


# ── base test class ────────────────────────────────────────────────────────────

class _WorkflowTest(unittest.TestCase):
    """Run WORKFLOW once in setUpClass; every test method reads cls.result."""
    WORKFLOW = None

    @classmethod
    def setUpClass(cls):
        if cls.WORKFLOW:
            cls.result = _run_workflow(cls.WORKFLOW)

    def _get(self, key, default=''):
        return self.result.get(key, default)


# ── test classes ───────────────────────────────────────────────────────────────

class ShellWorkflowTests(_WorkflowTest):
    WORKFLOW = 'test-shell.json'

    def test_echo_produces_output(self):
        self.assertIn('hello-from-shell', self._get('echo_result'))

    def test_variable_substituted_from_defaults(self):
        self.assertIn('shell-test', self._get('subst_result'))

    def test_chained_variable_from_prior_step(self):
        self.assertIn('date-was-', self._get('subst_chained'))

    def test_compound_command_both_parts_present(self):
        out = self._get('compound_result')
        self.assertIn('part-one', out)
        self.assertIn('part-two', out)


class LoadContextWorkflowTests(_WorkflowTest):
    WORKFLOW = 'test-loadContext.json'

    def test_string_key_loaded(self):
        self.assertEqual(self._get('test_string'), 'hello world')

    def test_number_key_loaded(self):
        self.assertEqual(self._get('test_number'), '42')

    def test_multiline_key_loaded(self):
        self.assertIn('line one', self._get('test_multiline'))

    def test_workflow_continues_after_missing_file(self):
        self.assertIn('workflow-continued', self._get('continue_after_missing'))


class TransformDataWorkflowTests(_WorkflowTest):
    WORKFLOW = 'test-transformData.json'

    def test_parse_lines_returns_dict(self):
        self.assertIsInstance(self.result.get('parsed_result'), dict)

    def test_missing_source_not_stored(self):
        self.assertIsNone(self.result.get('missing_src_result'))

    def test_unknown_method_not_stored(self):
        self.assertIsNone(self.result.get('unknown_method_result'))


class PythonWorkflowTests(_WorkflowTest):
    WORKFLOW = 'test-python.json'

    def test_assert_error_returns_error_string(self):
        self.assertIn('[error:', self._get('py_error'))

    def test_syntax_error_returns_error_string(self):
        self.assertIn('[error:', self._get('py_syntax_error'))

    def test_workflow_continues_after_empty_code(self):
        self.assertIn('workflow-continued', self._get('after_empty'))


class WriteFileWorkflowTests(_WorkflowTest):
    WORKFLOW = 'test-writeFile.json'

    def test_write_returns_resolved_path(self):
        self.assertIn('plain-output.txt', self._get('write_result'))

    def test_templated_path_contains_run_label(self):
        self.assertIn('testrun', self._get('write_result_templated'))


class LoopWorkflowTests(_WorkflowTest):
    WORKFLOW = 'test-loop.json'

    def test_early_stop_result_is_full_dict(self):
        self.assertIsInstance(self.result.get('early_stop_log'), dict)

    def test_fixed_iterations_result_is_full_dict(self):
        self.assertIsInstance(self.result.get('fixed_loop_log'), dict)

    def test_loop_result_has_iteration_output_key(self):
        self.assertIn('iteration_output', self.result.get('early_stop_log', {}))

    def test_loop_returns_last_iteration_output(self):
        # fixed_loop_log ran 2 iterations; the loop returns the LAST iteration's
        # step_output. loop_history is written to the run log only, not the
        # returned context (see loop_actions handler docstring), so the carried
        # outputKey reflects iteration 2.
        loop = self.result.get('fixed_loop_log', {})
        self.assertIn('iteration-2', loop.get('iteration_output', ''))

    def test_workflow_continues_after_loops(self):
        self.assertIn('loop-outputs-stored', self._get('loop_verify'))


class WorkflowWorkflowTests(_WorkflowTest):
    WORKFLOW = 'test-workflow.json'

    def test_sub_workflow_result_is_dict(self):
        self.assertIsInstance(self.result.get('sub_result'), dict)

    def test_sub_workflow_result_contains_action_output_keys(self):
        sub = self.result.get('sub_result', {})
        self.assertIn('sub_shell', sub)
        self.assertIn('final', sub)

    def test_seeded_sub_workflow_result_is_dict(self):
        self.assertIsInstance(self.result.get('seeded_sub_result'), dict)

    def test_seeded_sub_workflow_received_seed_value(self):
        # sub-workflow was seeded with seed_value; it appears in its step_output
        sub = self.result.get('seeded_sub_result', {})
        self.assertIn('seed_value', sub)

    def test_dot_extraction_step_ran(self):
        self.assertIn('dot-extraction-worked', self._get('extracted'))


class ContextWorkflowTests(_WorkflowTest):
    """
    Verifies that build_ctx enforces includedData — no keys leak to handlers
    that aren't listed.  Also verifies that engine globals (__config__,
    __schema__) are only delivered when explicitly listed in includedData
    (Flow A: no auto-inject).

    Detection method: shell action `echo blocked={secret}` outputs the literal
    string '{secret}' when 'secret' is absent from ctx (because _SafeMap leaves
    unknown placeholders unchanged).  If the output contains 'LEAKED' instead,
    the key escaped the filter.
    """
    WORKFLOW = 'test-context.json'

    # ── includedData filtering ────────────────────────────────────────────────

    def test_listed_key_is_substituted(self):
        self.assertIn('allowed=data-payload', self._get('filter_result'))

    def test_engine_passthrough_config_substituted_in_filter_step(self):
        # __config__ is listed in includedData so it is substituted.
        out = self._get('filter_result')
        self.assertNotIn('{__config__}', out)

    def test_unlisted_secret_not_substituted(self):
        out = self._get('filter_result')
        self.assertIn('{secret}', out)
        self.assertNotIn('LEAKED', out)

    # ── engine globals accessible when listed ─────────────────────────────────

    def test_passthrough_key_is_substituted(self):
        # __config__ is listed in includedData so it must be substituted.
        self.assertNotIn('{__config__}', self._get('passthrough_result'))

    def test_non_passthrough_secret_still_blocked(self):
        out = self._get('passthrough_result')
        self.assertIn('{secret}', out)
        self.assertNotIn('LEAKED', out)

    # ── dot-notation extraction ───────────────────────────────────────────────

    def test_dot_path_leaf_extracted(self):
        self.assertIn('leaf=found-it', self._get('dot_result'))

    def test_dot_path_sibling_not_leaked(self):
        out = self._get('dot_result')
        self.assertIn('{sibling}', out)
        self.assertNotIn('also-here', out)

    def test_dot_path_secret_not_leaked(self):
        out = self._get('dot_result')
        self.assertIn('{secret}', out)
        self.assertNotIn('LEAKED', out)

    # ── loop result + dot extraction ──────────────────────────────────────────

    def test_loop_result_is_full_dict_not_scalar(self):
        self.assertIsInstance(self.result.get('loop_data'), dict)

    def test_loop_dict_contains_iteration_keys(self):
        loop = self.result.get('loop_data', {})
        self.assertIn('iteration_output', loop)
        self.assertIn('iteration', loop)

    def test_dot_extraction_from_loop_result(self):
        # runCode received the scalar iteration_output via dot-notation,
        # not the raw dict; it returns 'ok' when 'iteration-' is in the value
        self.assertIn('ok', self._get('loop_check'))


# ── test registry ──────────────────────────────────────────────────────────────

WORKFLOW_TESTS = [
    ShellWorkflowTests,
    LoadContextWorkflowTests,
    TransformDataWorkflowTests,
    PythonWorkflowTests,
    WriteFileWorkflowTests,
    LoopWorkflowTests,
    WorkflowWorkflowTests,
    ContextWorkflowTests,
]


# ── ANSI colours ───────────────────────────────────────────────────────────────

def _ansi(code):
    return f'\033[{code}m' if sys.stdout.isatty() else ''

RESET  = _ansi('0')
BOLD   = _ansi('1')
DIM    = _ansi('2')
GREEN  = _ansi('32')
RED    = _ansi('31')
YELLOW = _ansi('33')


# ── result collector ───────────────────────────────────────────────────────────

class _Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.by_class  = defaultdict(lambda: {'pass': [], 'fail': [], 'error': [], 'skip': []})
        self.timings   = {}
        self._start    = {}
        self.all_tests = []

    def startTest(self, test):
        super().startTest(test)
        self._start[test] = time.perf_counter()

    def stopTest(self, test):
        super().stopTest(test)
        elapsed = time.perf_counter() - self._start.pop(test, time.perf_counter())
        self.timings[_key(test)] = elapsed

    def addSuccess(self, test):
        super().addSuccess(test)
        self.by_class[_class(test)]['pass'].append(test)
        self.all_tests.append(('pass', test, None))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.by_class[_class(test)]['fail'].append((test, err))
        self.all_tests.append(('fail', test, err))

    def addError(self, test, err):
        super().addError(test, err)
        self.by_class[_class(test)]['error'].append((test, err))
        self.all_tests.append(('error', test, err))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.by_class[_class(test)]['skip'].append((test, reason))
        self.all_tests.append(('skip', test, reason))


def _class(test): return type(test).__name__
def _key(test):   return f"{type(test).__name__}.{test._testMethodName}"
def _method(test): return test._testMethodName

def _short_err(err):
    lines = traceback.format_exception(*err)
    meaningful = [l.strip() for l in lines if l.strip() and not l.startswith('  File')]
    return meaningful[-1] if meaningful else str(err[1])

def _full_err(err):
    return ''.join(traceback.format_exception(*err)).rstrip()


# ── printer ────────────────────────────────────────────────────────────────────

def _divider(char='─', width=70):
    return char * width

def _print_class_block(class_name, buckets, timings, verbose):
    passes = buckets['pass'];  fails  = buckets['fail']
    errors = buckets['error']; skips  = buckets['skip']
    total  = len(passes) + len(fails) + len(errors) + len(skips)

    if fails or errors:
        col, char = RED,    '✗'
    elif skips and not passes:
        col, char = YELLOW, '~'
    else:
        col, char = GREEN,  '✓'

    p, f, e, s = len(passes), len(fails), len(errors), len(skips)
    counts = (
        f"{GREEN}{p} pass{RESET}"
        + (f"  {RED}{f} fail{RESET}"    if f else '')
        + (f"  {RED}{e} error{RESET}"   if e else '')
        + (f"  {YELLOW}{s} skip{RESET}" if s else '')
    )
    class_time = sum(v for k, v in timings.items() if k.startswith(class_name + '.'))
    print(f"\n  {col}{BOLD}{char} {class_name}{RESET}  {DIM}({total} tests  {class_time:.2f}s){RESET}")
    print(f"    {counts}")

    if verbose:
        for t in passes:
            print(f"    {GREEN}  ✓{RESET} {_method(t)}  {DIM}{timings.get(_key(t), 0)*1000:.0f}ms{RESET}")
        for t, _ in skips:
            print(f"    {YELLOW}  ~ {_method(t)}{RESET}")
        for t, err in fails + errors:
            label = '' if (t, err) in fails else '  [ERROR]'
            print(f"    {RED}  ✗ {_method(t)}{label}{RESET}  {DIM}{timings.get(_key(t), 0)*1000:.0f}ms{RESET}")
            print(f"      {DIM}{_short_err(err)}{RESET}")

def _print_failures_detail(result):
    issues = [(k, t, e) for k, t, e in result.all_tests if k in ('fail', 'error')]
    if not issues:
        return
    print(f"\n{_divider('═')}")
    print(f"{BOLD}{RED}  FAILURES & ERRORS{RESET}")
    print(_divider('═'))
    for i, (kind, test, err) in enumerate(issues, 1):
        label = 'FAIL' if kind == 'fail' else 'ERROR'
        print(f"\n  {RED}{BOLD}[{i}] {label}: {_class(test)}.{_method(test)}{RESET}")
        print(f"  {_divider()}")
        for line in _full_err(err).splitlines():
            print(f"  {line}")

def _print_summary(result, elapsed, n_classes):
    total  = result.testsRun
    fails  = len(result.failures)
    errors = len(result.errors)
    skips  = len(result.skipped)
    passes = total - fails - errors - skips

    print(f"\n{_divider('═')}")
    if fails or errors:
        print(f"{BOLD}{RED}  FAILED{RESET}  {DIM}({total} tests in {elapsed:.2f}s){RESET}")
    else:
        print(f"{BOLD}{GREEN}  ALL PASS{RESET}  {DIM}({total} tests in {elapsed:.2f}s){RESET}")
    print(_divider('═'))
    col_w = 14
    print(f"  {'Passed':<{col_w}} {GREEN}{BOLD}{passes}{RESET}")
    if fails:  print(f"  {'Failed':<{col_w}} {RED}{BOLD}{fails}{RESET}")
    if errors: print(f"  {'Errors':<{col_w}} {RED}{BOLD}{errors}{RESET}")
    if skips:  print(f"  {'Skipped':<{col_w}} {YELLOW}{skips}{RESET}")
    print(f"  {'Total':<{col_w}} {BOLD}{total}{RESET}")
    print(f"  {'Workflows':<{col_w}} {DIM}{n_classes}{RESET}")
    print(_divider('═'))
    print()


# ── discovery ──────────────────────────────────────────────────────────────────

def _load_suite(keyword=None):
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    loaded = []
    for cls in WORKFLOW_TESTS:
        if keyword and keyword.lower() not in cls.__name__.lower():
            continue
        suite.addTests(loader.loadTestsFromTestCase(cls))
        loaded.append(cls.__name__)
    return suite, loaded


# ── entry point ────────────────────────────────────────────────────────────────

def main():
    args     = sys.argv[1:]
    verbose  = '-v' in args
    failfast = '-f' in args
    keyword  = next((a for a in args if not a.startswith('-')), None)

    print(f"\n{_divider('═')}")
    print(f"{BOLD}  clay workflow tests{RESET}")
    if keyword:
        print(f"  {DIM}filter: {keyword}{RESET}")
    print(_divider('═'))

    suite, loaded = _load_suite(keyword)

    if not loaded:
        print(f"{RED}  No test classes matched.{RESET}\n")
        sys.exit(1)

    print(f"\n  {DIM}Running {suite.countTestCases()} tests across {len(loaded)} workflow(s)…{RESET}")

    result          = _Result()
    result.failfast = failfast

    t0 = time.perf_counter()
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        suite.run(result)
    elapsed = time.perf_counter() - t0

    print(f"\n{_divider('─')}")
    print(f"{BOLD}  Results by workflow{RESET}")
    print(_divider('─'))

    for class_name in sorted(result.by_class.keys()):
        _print_class_block(class_name, result.by_class[class_name], result.timings, verbose)

    _print_failures_detail(result)
    _print_summary(result, elapsed, len(loaded))

    sys.exit(1 if (result.failures or result.errors) else 0)


if __name__ == '__main__':
    main()

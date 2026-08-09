"""Unit-test entry point: stock unittest output plus a compact failure list.

Usage (from the repo root):
    python3 -m clay.tests        # all unit tests
    python3 -m clay.tests -v     # verbose (one line per test)

Equivalent to `python3 -m unittest discover -s clay/tests -t .`, with a
"Failed tests" list at the bottom: one line per failure/error with the test id
and the final line of its traceback. Full tracebacks still print above as
usual. Exits 1 if anything failed.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import patch


def _successful_preflight(workflow):
    """Network-free successful prerequisite for unrelated engine tests."""
    return None


def _last_line(tb: str) -> str:
    lines = [l for l in tb.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ''


def main() -> None:
    verbosity = 2 if '-v' in sys.argv[1:] else 1
    suite = unittest.defaultTestLoader.discover('clay/tests', top_level_dir='.')
    # Unit tests must never depend on or contact a developer's live model
    # server. Keep the real run_checks loop and replace only its ordered check
    # list; dedicated tests restore the production check locally.
    with patch('clay.run.preflight.CHECKS', (_successful_preflight,)):
        result = unittest.TextTestRunner(verbosity=verbosity).run(suite)

    issues = ([('FAIL', t, tb) for t, tb in result.failures]
              + [('ERROR', t, tb) for t, tb in result.errors])
    if issues:
        print(f'\nFailed tests ({len(issues)}):')
        for kind, test, tb in issues:
            print(f'  {kind:5}  {test.id()}')
            print(f'         {_last_line(tb)}')
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()

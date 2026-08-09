"""Regression tests for root-run cleanup after execution escapes.

These tests preserve the pre-fix reproductions and prove F-04 now brackets root
execution with guaranteed cleanup in ``clay.run.engine._execute``.
"""

import unittest
from unittest.mock import patch

from clay.run import engine, events, logger


_WORKFLOW = {
    'workflow': {'steps': ['run']},
    'actionSets': {'run': []},
}


class _RunLog:
    """In-memory RunLogger substitute with observable ownership cleanup."""

    def __init__(self, label):
        self.path = f'{label}.log'
        self.closed = False

    def log(self, line):
        pass

    def log_event(self, event):
        pass

    def close(self):
        self.closed = True


class RootLifecycleFailureTest(unittest.TestCase):

    def setUp(self):
        # Make each reproduction independent even when an earlier assertion
        # demonstrated the leak this suite is intended to expose.
        logger.stop()

    def tearDown(self):
        logger.stop()

    @patch('clay.run.engine.process_steps', side_effect=RuntimeError('broken'))
    def test_raising_run_releases_active_logger(self, process_steps):
        recorded = []
        logger.add_listener(recorded.append)
        self.addCleanup(logger.remove_listener, recorded.append)
        with patch('clay.run.logger.RunLogger', return_value=_RunLog('failed')):
            with self.assertRaisesRegex(RuntimeError, 'broken'):
                engine.run_from_data(_WORKFLOW, label='failed-run')

            self.assertIsNone(
                logger.get(),
                'a root execution exception must release the active logger',
            )
        self.assertIn(events.RUN_ERROR,
                      [event['type'] for event in recorded])
        self.assertNotIn(events.RUN_COMPLETE,
                         [event['type'] for event in recorded])

    @patch('clay.run.engine.process_steps', side_effect=RuntimeError('broken'))
    def test_raising_run_closes_its_log_file(self, process_steps):
        failed_log = _RunLog('failed')
        with patch('clay.run.logger.RunLogger', return_value=failed_log):
            with self.assertRaisesRegex(RuntimeError, 'broken'):
                engine.run_from_data(_WORKFLOW, label='failed-run')

        self.assertTrue(
            failed_log.closed,
            'a root execution exception must close its log file',
        )

    def test_run_after_failure_gets_a_fresh_root_lifecycle(self):
        recorded = []
        logger.add_listener(recorded.append)
        self.addCleanup(logger.remove_listener, recorded.append)

        outcomes = [RuntimeError('first run failed'), {'second': 'ran'}]
        run_logs = [_RunLog('failed'), _RunLog('clean')]
        with patch('clay.run.logger.RunLogger', side_effect=run_logs), \
                patch('clay.run.engine.process_steps', side_effect=outcomes):
            with self.assertRaisesRegex(RuntimeError, 'first run failed'):
                engine.run_from_data(_WORKFLOW, label='failed-run')

            result = engine.run_from_data(_WORKFLOW, label='clean-run')

        self.assertEqual(result, {'second': 'ran'})
        starts = [event.get('label') for event in recorded
                  if event.get('type') == events.RUN_START]
        completes = [event.get('label') for event in recorded
                     if event.get('type') == events.RUN_COMPLETE]
        self.assertEqual(starts, ['failed-run', 'clean-run'])
        self.assertEqual(completes, ['clean-run'])
        self.assertIsNone(logger.get())

    def test_control_flow_exceptions_release_active_logger(self):
        for exception in (KeyboardInterrupt(), SystemExit(2)):
            with self.subTest(exception=type(exception).__name__), \
                    patch('clay.run.logger.RunLogger',
                          return_value=_RunLog('interrupted')), \
                    patch('clay.run.engine.process_steps',
                          side_effect=exception):
                try:
                    with self.assertRaises(type(exception)):
                        engine.run_from_data(_WORKFLOW, label='interrupted-run')
                    self.assertIsNone(logger.get())
                finally:
                    # Keeps subtests independent if lifecycle regresses.
                    logger.stop()


if __name__ == '__main__':
    unittest.main()

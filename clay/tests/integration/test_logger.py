"""Integration tests for RunLogger and the logger module.

RunLogger:
  - Creates logs/ directory if absent
  - File name format: logs/{YYYY-MM-DD_HH-MM-SS}_{name}.log
  - Each log() call writes "[+{elapsed}s] {indent}{line}"
  - Depth indentation: 2 spaces per depth level
  - start() / get() / stop() module singleton
"""

import os
import re
import tempfile
import time
import unittest

from clay.run import logger as logger
from clay.run.logger import RunLogger


class TestRunLogger(unittest.TestCase):

    def setUp(self):
        # Each test gets its own temp dir as cwd so logs/ is isolated
        self._orig_dir = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._orig_dir)
        self._tmp.cleanup()
        # Clean up singleton if a test left it open
        if logger.get():
            logger.stop()

    def test_creates_logs_directory(self):
        rl = RunLogger("workflow.json")
        rl.close()
        self.assertTrue(os.path.isdir("logs"))

    def test_log_file_created(self):
        rl = RunLogger("workflow.json")
        rl.close()
        logs = os.listdir("logs")
        self.assertEqual(len(logs), 1)

    def test_log_filename_format(self):
        rl = RunLogger("my_workflow.json")
        rl.close()
        fname = os.listdir("logs")[0]
        # e.g. 2026-03-17_12-34-56_my_workflow.log
        self.assertRegex(fname, r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_my_workflow\.log$')

    def test_log_file_name_strips_directory_and_extension(self):
        rl = RunLogger("workflows/sub/my_flow.json")
        rl.close()
        fname = os.listdir("logs")[0]
        self.assertIn("my_flow", fname)
        self.assertNotIn("workflows", fname)
        self.assertNotIn(".json", fname)

    def test_log_writes_elapsed_timestamp(self):
        rl = RunLogger("w.json")
        rl.log("test line")
        rl.close()
        content = open(rl.path).read()
        self.assertRegex(content, r'\[\+[\d\.]+s\]')

    def test_log_writes_line_content(self):
        rl = RunLogger("w.json")
        rl.log("hello world")
        rl.close()
        content = open(rl.path).read()
        self.assertIn("hello world", content)

    def test_depth_zero_no_indentation(self):
        rl = RunLogger("w.json")
        rl.depth = 0
        rl.log("flat")
        rl.close()
        line = open(rl.path).read().strip()
        # After timestamp, no leading spaces before "flat"
        after_bracket = line.split("] ", 1)[1]
        self.assertEqual(after_bracket, "flat")

    def test_depth_one_two_space_indent(self):
        rl = RunLogger("w.json")
        rl.depth = 1
        rl.log("indented")
        rl.close()
        line = open(rl.path).read().strip()
        after_bracket = line.split("] ", 1)[1]
        self.assertEqual(after_bracket, "  indented")

    def test_depth_two_four_space_indent(self):
        rl = RunLogger("w.json")
        rl.depth = 2
        rl.log("deep")
        rl.close()
        line = open(rl.path).read().strip()
        after_bracket = line.split("] ", 1)[1]
        self.assertEqual(after_bracket, "    deep")

    def test_multiple_lines_written(self):
        rl = RunLogger("w.json")
        rl.log("line one")
        rl.log("line two")
        rl.close()
        lines = open(rl.path).read().splitlines()
        self.assertEqual(len(lines), 2)

    def test_elapsed_increases_over_time(self):
        rl = RunLogger("w.json")
        rl.log("first")
        time.sleep(0.05)
        rl.log("second")
        rl.close()
        lines = open(rl.path).read().splitlines()
        t1 = float(re.search(r'\+([\d\.]+)s', lines[0]).group(1))
        t2 = float(re.search(r'\+([\d\.]+)s', lines[1]).group(1))
        self.assertGreater(t2, t1)


class TestRunLoggerSingleton(unittest.TestCase):

    def setUp(self):
        self._orig_dir = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._orig_dir)
        self._tmp.cleanup()
        if logger.get():
            logger.stop()

    def test_get_returns_none_before_start(self):
        logger._active = None  # ensure clean state
        self.assertIsNone(logger.get())

    def test_start_returns_logger(self):
        rl = logger.start("w.json")
        self.assertIsInstance(rl, RunLogger)

    def test_get_returns_active_logger(self):
        rl = logger.start("w.json")
        self.assertIs(logger.get(), rl)

    def test_stop_clears_singleton(self):
        logger.start("w.json")
        logger.stop()
        self.assertIsNone(logger.get())

    def test_stop_closes_file(self):
        rl = logger.start("w.json")
        path = rl.path
        logger.stop()
        # File should be closed — writing to it should fail
        self.assertTrue(rl._fh.closed)

    def test_stop_when_none_does_not_raise(self):
        logger._active = None
        logger.stop()  # should not raise


if __name__ == '__main__':
    unittest.main()

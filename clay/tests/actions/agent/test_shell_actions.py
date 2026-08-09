"""Unit and workflow-layer tests for shell_actions."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import shell_actions
from ....actions.agent.shell_actions import (
    ALLOWED_COMMANDS,
    BLOCKED_ARGUMENTS,
    _blocked_arguments_in,
    _executables_in,
    _interpolate,
    execute,
    parse_commands,
    refusal_for,
)
from ....run import approval, engine, io
from ..fixtures import write_workflow, simple_workflow
from ...test_core import _EventLog


class _ApprovingIO:
    """Answers every prompt 'y'. A whitelisted command still reaches
    approval.confirm() (required=True, 573aee4) even when the handler is
    called directly, so it has to reach something other than the terminal."""

    def prompt(self, prompt_id, text):
        return 'y'


class TestShellActionsUnit(unittest.TestCase):

    def setUp(self):
        self._io_patch = patch.object(io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def test_whitelisted_command_runs(self):
        result = shell_actions.handler({"id": "out", "command": "echo hello"}, {})
        self.assertIsNotNone(result)
        self.assertIn("hello", result["data"])

    def test_blocked_command_returns_none(self):
        with patch('builtins.print'):
            result = shell_actions.handler({"id": "out", "command": "rm -rf /"}, {})
        self.assertIsNone(result)

    def test_missing_command_returns_none(self):
        with patch('builtins.print'):
            result = shell_actions.handler({"id": "out"}, {})
        self.assertIsNone(result)

    def test_variable_substitution(self):
        result = shell_actions.handler(
            {"id": "out", "command": "echo {msg}"},
            {"msg": "world"}
        )
        self.assertIn("world", result["data"])

    def test_injection_chars_stripped_from_variable(self):
        # Semicolons in AI-supplied values are stripped before substitution.
        result = shell_actions.handler(
            {"id": "out", "command": "echo {msg}"},
            {"msg": "safe; echo HACKED"}
        )
        self.assertIsNotNone(result)
        lines = [l for l in result["data"].splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"Expected 1 line, got: {result['data']!r}")

    def test_whitelist_is_frozenset(self):
        self.assertIsInstance(ALLOWED_COMMANDS, frozenset)

    def test_whitelist_cannot_be_extended_via_action(self):
        with patch('builtins.print'):
            result = shell_actions.handler(
                {"id": "out", "command": "rm -rf /", "whitelist": ["rm"]}, {}
            )
        self.assertIsNone(result)

    def test_compound_command_all_whitelisted(self):
        result = shell_actions.handler(
            {"id": "out", "command": "echo a && echo b"}, {}
        )
        self.assertIsNotNone(result)

    def test_compound_command_one_blocked(self):
        with patch('builtins.print'):
            result = shell_actions.handler(
                {"id": "out", "command": "echo hello && rm -rf /"}, {}
            )
        self.assertIsNone(result)

    def test_timeout_returns_timeout_message(self):
        import subprocess
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("cmd", 1)), \
             patch('builtins.print'):
            result = shell_actions.handler(
                {"id": "out", "command": "echo hi", "timeout": 1}, {}
            )
        self.assertIsNotNone(result)
        self.assertIn("timeout", result["data"])

    def test_id_preserved_in_result(self):
        result = shell_actions.handler({"id": "my_out", "command": "echo x"}, {})
        self.assertEqual(result["id"], "my_out")


class TestExecutablesIn(unittest.TestCase):

    def test_single_command(self):
        self.assertEqual(_executables_in("ping 8.8.8.8"), ["ping"])

    def test_compound_and(self):
        names = _executables_in("ifconfig && arp -a")
        self.assertIn("ifconfig", names)
        self.assertIn("arp", names)

    def test_compound_semicolon(self):
        names = _executables_in("echo a; echo b")
        self.assertEqual(names.count("echo"), 2)

    def test_pipe(self):
        names = _executables_in("cat /etc/hosts | grep local")
        self.assertIn("cat", names)
        self.assertIn("grep", names)


class TestBlockedArguments(unittest.TestCase):
    """`find` is whitelisted, so the flags that let it run other commands
    must not be. _executables_in only inspects the first token of each
    segment, so `find . -exec rm -rf {} ;` would otherwise present `find` and
    hide `rm`."""

    def setUp(self):
        self._io_patch = patch.object(io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def test_find_listing_is_allowed(self):
        result = shell_actions.handler(
            {"id": "out", "command": "find . -maxdepth 1 -type f"}, {})
        self.assertIsNotNone(result)

    def test_find_exec_is_blocked(self):
        with patch('builtins.print'):
            result = shell_actions.handler(
                {"id": "out", "command": "find . -exec rm -rf {} ;"}, {})
        self.assertIsNone(result)

    def test_find_delete_is_blocked(self):
        with patch('builtins.print'):
            result = shell_actions.handler(
                {"id": "out", "command": "find . -name '*.py' -delete"}, {})
        self.assertIsNone(result)

    def test_execdir_and_ok_and_fprint_are_blocked(self):
        for flag in ("-execdir", "-ok", "-okdir", "-fprint", "-fls"):
            with self.subTest(flag=flag), patch('builtins.print'):
                result = shell_actions.handler(
                    {"id": "out", "command": f"find . {flag} x"}, {})
                self.assertIsNone(result)

    def test_blocked_flag_arriving_through_a_placeholder_is_caught(self):
        with patch('builtins.print'):
            result = shell_actions.handler(
                {"id": "out", "command": "find . {flag} rm"},
                {"flag": "-exec"})
        self.assertIsNone(result)

    def test_detects_the_flag_anywhere_in_the_command(self):
        self.assertEqual(_blocked_arguments_in("find . -type f"), [])
        self.assertEqual(_blocked_arguments_in("find . -exec ls {} ;"), ["-exec"])

    def test_blocked_arguments_is_frozenset(self):
        self.assertIsInstance(BLOCKED_ARGUMENTS, frozenset)


class TestInterpolation(unittest.TestCase):
    """Shell syntax is full of braces that are not placeholders. str.format_map
    raises ValueError on `{}`, which would kill the run rather than refuse the
    command — `find . -exec rm -rf {} ;` must reach the guard to be blocked."""

    def setUp(self):
        self._io_patch = patch.object(io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def test_empty_braces_survive_interpolation(self):
        self.assertEqual(_interpolate("find . -exec ls {} ;", {}),
                         "find . -exec ls {} ;")

    def test_shell_expansions_survive(self):
        for text in ("echo ${HOME}", "echo {1..3}", "echo {a,b}"):
            with self.subTest(text=text):
                self.assertEqual(_interpolate(text, {}), text)

    def test_named_placeholder_substituted_and_quoted(self):
        self.assertEqual(_interpolate("echo {msg}", {"msg": "a b"}),
                         "echo 'a b'")

    def test_unquoted_mode_passes_the_value_through(self):
        self.assertEqual(_interpolate("{dir}", {"dir": "out/x"}, quote=False),
                         "out/x")

    def test_unknown_key_is_left_as_written(self):
        self.assertEqual(_interpolate("echo {nope}", {}), "echo {nope}")

    def test_braces_in_a_command_do_not_crash_the_handler(self):
        result = shell_actions.handler(
            {"id": "out", "command": "echo {} done"}, {})
        self.assertIsNotNone(result)
        self.assertIn("{}", result["data"])


class TestRefusalFor(unittest.TestCase):
    """The single gate. Both the `shell` action and runReplyCommands go
    through it, so a command refused for one is refused for the other."""

    def test_whitelisted_command_is_allowed(self):
        self.assertIsNone(refusal_for("echo hello"))

    def test_unlisted_command_names_itself(self):
        self.assertIn("rm", refusal_for("rm -rf /"))

    def test_empty_command_is_refused(self):
        self.assertIsNotNone(refusal_for("   "))

    def test_blocked_argument_is_refused_even_on_a_listed_command(self):
        self.assertIn("-exec", refusal_for("find . -exec ls {} ;"))

    def test_dev_toolchain_is_allowed(self):
        for command in ("python3 hello.py", "python hello.py", "node app.js",
                        "pytest -q", "npm test", "make build", "git status"):
            with self.subTest(command=command):
                self.assertIsNone(refusal_for(command))


class TestExecute(unittest.TestCase):

    def test_stdout_is_returned(self):
        self.assertIn("hi", execute("echo hi"))

    def test_nonzero_exit_is_marked_not_raised(self):
        with patch('builtins.print'):
            output = execute("ls /definitely/not/a/real/path")
        self.assertIn("[exit code:", output)

    def test_include_stderr_folds_the_error_stream_in(self):
        with patch('builtins.print'):
            output = execute("ls /definitely/not/a/real/path", include_stderr=True)
        self.assertIn("/definitely/not/a/real/path", output)

    def test_cwd_is_honoured(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, 'marker.txt'), 'w').close()
            output = execute("ls", cwd=d)
        self.assertIn("marker.txt", output)


class TestParseCommands(unittest.TestCase):

    def test_no_fence_yields_nothing(self):
        self.assertEqual(parse_commands("just prose about bash"), [])

    def test_single_bash_fence(self):
        text = "Here's the command to execute it:\n\n```bash\npython3 hello.py\n```\n"
        self.assertEqual(parse_commands(text), ["python3 hello.py"])

    def test_other_fence_languages(self):
        for lang in ("sh", "shell", "zsh", "console"):
            with self.subTest(lang=lang):
                self.assertEqual(
                    parse_commands(f"```{lang}\nls\n```"), ["ls"])

    def test_python_fence_is_not_a_command(self):
        self.assertEqual(parse_commands("```python\nprint('hi')\n```"), [])

    def test_one_command_per_line(self):
        self.assertEqual(
            parse_commands("```bash\nls\ncat a.txt\n```"),
            ["ls", "cat a.txt"])

    def test_comments_and_blank_lines_dropped(self):
        self.assertEqual(
            parse_commands("```bash\n# run it\n\nls\n```"), ["ls"])

    def test_backslash_continuation_is_one_command(self):
        self.assertEqual(
            parse_commands("```bash\nfind . \\\n  -type f\n```"),
            ["find . -type f"])

    def test_multiple_fences_in_order(self):
        text = "first\n```bash\nls\n```\nthen\n```bash\ndate\n```"
        self.assertEqual(parse_commands(text), ["ls", "date"])

    def test_none_reply_is_safe(self):
        self.assertEqual(parse_commands(None), [])


class TestRunReplyCommands(unittest.TestCase):

    def setUp(self):
        self._io_patch = patch.object(io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def _run(self, action, ctx):
        with patch('builtins.print'):
            return shell_actions.run_reply_commands_handler(action, ctx)

    def test_a_gated_command_that_is_rejected_does_not_run(self):
        approval.reset()
        self.addCleanup(approval.reset)
        approval.set_manual(True)
        approval.set_gate('commands', True)

        class _Answer:
            def __init__(self, text):
                self.text = text
                self.prompts = []

            def prompt(self, prompt_id, text):
                self.prompts.append(text)
                return self.text

        channel = _Answer('1')
        with patch.object(io, 'get', return_value=channel):
            result = self._run(
                {"id": "out", "reply": "r"},
                {"r": "```bash\necho first\necho second\n```"})

        # In the transcript, not dropped: the next pass reads this, and a
        # command that vanished would have it conclude the check passed.
        self.assertIn("[skipped: not approved]", result["data"])
        self.assertNotIn("first\n", result["data"].replace("$ echo first", ""))
        self.assertIn("second", result["data"])
        # A command already blocked is shown as blocked at the moment somebody
        # is reading the list, rather than hidden.
        self.assertIn("echo first", channel.prompts[0])

    def test_reply_without_commands_returns_empty(self):
        result = self._run({"id": "out", "reply": "r"}, {"r": "no fences here"})
        self.assertEqual(result["data"], "")

    def test_command_runs_and_output_is_labelled(self):
        result = self._run(
            {"id": "out", "reply": "r"}, {"r": "```bash\necho hello\n```"})
        self.assertIn("$ echo hello", result["data"])
        self.assertIn("hello", result["data"])

    def test_unlisted_command_is_refused_not_run(self):
        result = self._run(
            {"id": "out", "reply": "r"}, {"r": "```bash\nrm -rf /\n```"})
        self.assertIn("[refused:", result["data"])
        self.assertIn("rm", result["data"])

    def test_a_refusal_does_not_stop_later_commands(self):
        result = self._run(
            {"id": "out", "reply": "r"},
            {"r": "```bash\nrm -rf /\necho survived\n```"})
        self.assertIn("[refused:", result["data"])
        self.assertIn("survived", result["data"])

    def test_max_commands_refuses_the_whole_block(self):
        reply = "```bash\n" + "\n".join(["echo x"] * 6) + "\n```"
        result = self._run(
            {"id": "out", "reply": "r", "maxCommands": 5}, {"r": reply})
        self.assertIn("limit is 5", result["data"])
        self.assertNotIn("$ echo x", result["data"])

    def test_cwd_placeholder_is_interpolated_unquoted(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, 'marker.txt'), 'w').close()
            result = self._run(
                {"id": "out", "reply": "r", "cwd": "{workspace}"},
                {"r": "```bash\nls\n```", "workspace": d})
        self.assertIn("marker.txt", result["data"])

    def test_missing_cwd_is_reported_not_run_elsewhere(self):
        result = self._run(
            {"id": "out", "reply": "r", "cwd": "/no/such/dir"},
            {"r": "```bash\nls\n```"})
        self.assertIn("does not exist", result["data"])

    def test_id_preserved_in_result(self):
        result = self._run({"id": "cmd_out", "reply": "r"}, {"r": ""})
        self.assertEqual(result["id"], "cmd_out")

    def test_command_and_every_output_line_reach_the_event_bus(self):
        # The front-ends draw what they receive, so output that only lands in
        # the returned data is output nobody watching the run ever sees.
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'lines.txt'), 'w') as handle:
                handle.write('one\ntwo\nthree\n')
            with _EventLog() as log:
                self._run({"id": "out", "reply": "r", "cwd": d},
                          {"r": "```bash\ncat lines.txt\n```"})
        logged = '\n'.join(log.outputs('command'))
        self.assertIn("$ cat lines.txt", logged)
        for line in ('one', 'two', 'three'):
            self.assertIn(line, logged)

    def test_a_command_and_its_output_arrive_as_one_event(self):
        # Two commands back to back must not interleave, so each command and
        # the lines it printed are a single message.
        reply = "```bash\necho first\necho second\n```"
        with _EventLog() as log:
            self._run({"id": "out", "reply": "r"}, {"r": reply})
        self.assertEqual(log.outputs('command'),
                         ['$ echo first\nfirst', '$ echo second\nsecond'])

    def test_a_silent_command_logs_the_command_alone(self):
        # No trailing blank line for a command that printed nothing.
        with _EventLog() as log:
            self._run({"id": "out", "reply": "r"}, {"r": "```bash\necho\n```"})
        self.assertEqual(log.outputs('command'), ['$ echo'])


class TestShellWorkflowLayer(unittest.TestCase):

    def setUp(self):
        self._io_patch = patch.object(io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def test_output_stored_by_action_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "greeting", "type": "shell", "command": "echo hello_world"}
            ]}))
            data = engine.run(path)
        self.assertIn("greeting", data)
        self.assertIn("hello_world", data["greeting"])

    def test_blocked_command_not_stored(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "danger", "type": "shell", "command": "rm -rf /"}
            ]}))
            with patch('builtins.print'):
                data = engine.run(path)
        self.assertNotIn("danger", data)

    def test_variable_substituted_from_context(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "out", "type": "shell", "command": "echo {msg}"}
            ]}))
            data = engine.run(path, initial_data={"msg": "substituted"})
        self.assertIn("substituted", data["out"])

    def test_output_flows_to_next_action(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, {
                "workflow": {"steps": ["s1", "s2"]},
                "actionSets": {
                    "s1": [{"id": "raw", "type": "shell", "command": "echo 99"}],
                    "s2": [{"id": "processed", "type": "runCode", "language": "python",
                             "source": "import sys; v=sys.stdin.read().strip(); print(int(v)+1)",
                             "stdin": "raw"}]
                }
            })
            data = engine.run(path)
        self.assertIn("100", data["processed"])


if __name__ == '__main__':
    unittest.main()

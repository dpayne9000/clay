"""Cooperative cancellation for in-process workflow runs.

In-process runners (e.g. the Qt UI worker thread) call request_cancel() to
stop a run at the next action boundary. engine.process_steps checks the flag,
so nested sub-workflows and loops stop too. The flag is cleared at the start
of each root run. The daemon path stops workflows via process signals and does
not rely on this.
"""
import threading

_cancel_event = threading.Event()


def request_cancel():
    """Signal the running workflow to stop at the next action/step boundary."""
    _cancel_event.set()


def clear_cancel():
    """Reset the cancellation flag before a root run."""
    _cancel_event.clear()


def is_cancelled():
    """Return whether the current run has received a stop request."""
    return _cancel_event.is_set()

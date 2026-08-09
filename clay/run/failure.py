"""The one explicit control-flow signal for a known workflow failure."""


class WorkflowFailure(RuntimeError):
    """A workflow cannot continue as written; callers may report it cleanly."""

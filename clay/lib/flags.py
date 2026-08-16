"""Interpret control-flow values consistently across the engine.

Both loop continueKey and action `when` evaluate values from earlier actions.
They share this function so values such as `"0"` and `"done"` have identical
control-flow meaning.

This is not a general truthiness test. Unrecognized values are true because
only explicit false values should stop execution.
"""

#: Explicit false values after whitespace removal and lowercase conversion.
FALSY_WORDS = ('false', 'done', '0', 'no', 'stop', '')


def is_truthy(value) -> bool:
    """Return false only for recognized false values.

    None, empty strings, and whitespace are false. Boolean values retain their
    native meaning.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in FALSY_WORDS

"""One reading of "does this string mean yes".

Two places in the engine ask that question of a value that came out of a
previous action: `loop`'s `continueKey`, which decides whether to go round
again, and `when`, which decides whether an action runs at all. Both are
usually answered by a model replying YES or NO in a single word, and both
would be quietly wrong in different ways if they disagreed about `"0"` or
`"done"`. They share this function so they cannot drift.

The vocabulary is deliberately small and literal. It is not a general truthy
test: `"maybe"` is true here, because the only safe reading of a word we do
not recognise is "not one of the ways of saying no".
"""

#: Values that mean no. Compared lower-cased and stripped. This is exactly the
#: list `loop` has always used, moved here rather than rewritten — widening it
#: would change when existing loops stop, which is not what this is for.
FALSY_WORDS = ('false', 'done', '0', 'no', 'stop', '')


def is_truthy(value) -> bool:
    """True unless `value` is one of the recognised ways of saying no.

    `None`, a missing key's empty string, and whitespace are all no. A real
    bool answers for itself — a JSON `false` must not be read as the truthy
    string "False".
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in FALSY_WORDS

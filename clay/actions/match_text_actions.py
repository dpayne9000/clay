"""A literal, local answer to a yes/no question about a string.

Workflows ask small closed questions all the time — did the user say quit, is
this key one of three known values — and until now the only thing that could
answer one was a model. That is the wrong tool for an exact-match question on
three counts: it costs a call, it costs the latency of a call, and it is wrong
in ways a list of literal strings cannot be. `system/coding3` asked a model
every single turn whether the user had said quit, and a model replying "NO."
with a full stop reads as **yes** through `is_truthy`, because the vocabulary
in clay/lib/flags.py is deliberately literal and "no." is not "no".

Matching is whole-string, stripped and lower-cased. Substring matching was
considered and left out: a `values` list holding "no" would fire on "no, make
it blue", and a gate that guesses is worse than one that asks. A source that
does not match exactly is a miss, and for a continue-gate a miss means carry
on — the direction that is always recoverable.
"""

from ..run import logger
from .registry import action, req, opt, handler_for


@action('matchText', skeleton=False)
class MatchText:
    id:      str = req("Output key for the onMatch or onMiss string")
    source:  str = req("Context key holding the text to test")
    values:  list = req("Literal strings that count as a match, compared stripped and lower-cased")
    onMatch: str = opt("Emitted when the source equals one of `values`", "yes")
    onMiss:  str = opt("Emitted when it does not", "no")


@handler_for('matchText')
def handler(action, ctx):
    source_key = action.get('source')
    values = action.get('values')

    if not source_key:
        logger.error("matchText: no 'source' key given")
        return None
    if not isinstance(values, list) or not values:
        logger.error(f"matchText: 'values' must be a non-empty list "
                     f"(got {type(values).__name__})")
        return None

    # Read through .get, not a required lookup: a key nothing has produced yet
    # is a legitimate miss. Gating on an action that has not run is a workflow
    # error the dispatcher already warns about, and duplicating it here would
    # turn a soft branch into a dead run.
    raw = ctx.get(source_key)

    # Fetched rather than defaulted through .get(key, default) so a workflow can
    # emit the empty string deliberately — '' is how is_truthy spells "no", and
    # that is exactly what a continue-gate wants on a match.
    on_match = action.get('onMatch')
    on_miss = action.get('onMiss')
    on_match = 'yes' if on_match is None else str(on_match)
    on_miss = 'no' if on_miss is None else str(on_miss)

    needle = str(raw if raw is not None else '').strip().lower()
    wanted = {str(value).strip().lower() for value in values}
    matched = needle in wanted

    logger.debug(f"matchText: '{needle[:40]}' "
                 f"{'matched' if matched else 'did not match'} "
                 f"{sorted(wanted)}")
    return {"id": action.get("id"), "data": on_match if matched else on_miss}

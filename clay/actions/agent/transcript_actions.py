"""appendTranscript — fold one conversation turn into a rolling transcript.

The loop action deliberately carries only one iteration of memory
(loop_actions.py: prev_result_data), so a conversational workflow needs an
action that accumulates turns into a single key that rides that memory
forward. Store the result under the same id each iteration and the loop does
the rest.

The transcript is capped at maxChars, trimmed from the front at a turn
boundary — old turns fall away whole, the context window stays bounded.
"""

from ..registry import action, req, opt, handler_for


@action('appendTranscript', skeleton=False)
class AppendTranscript:
    id:            str  = req("Output key for the updated transcript. Use the same key every iteration so the loop carries it forward")
    entries:       list = req('Turn lines as "Label=ctxKey" (bare "ctxKey" uses the key as the label). Entries whose value is empty are skipped')
    transcriptKey: str  = opt("Context key holding the prior transcript. Defaults to id", None)
    maxChars:      int  = opt("Cap on transcript length; oldest turns are dropped at turn boundaries", 8000)


_TURN_SEPARATOR = '\n\n'


def _turn_lines(specs, ctx):
    """Resolve "Label=ctxKey" specs to "Label: value" lines, skipping empties."""
    lines = []
    for spec in specs or []:
        label, sep, key = str(spec).partition('=')
        if sep:
            label, key = label.strip(), key.strip()
        else:
            label = key = label.strip()
        value = ctx.get(key)
        if value is None or not str(value).strip():
            continue
        lines.append(f'{label}: {str(value).strip()}')
    return lines


def _trim(transcript: str, max_chars: int) -> str:
    """Cut to max_chars, then drop the leading partial turn."""
    if not max_chars or len(transcript) <= max_chars:
        return transcript
    cut = transcript[-max_chars:]
    boundary = cut.find(_TURN_SEPARATOR)
    if boundary != -1:
        cut = cut[boundary + len(_TURN_SEPARATOR):]
    return cut


@handler_for('appendTranscript')
def handler(action, ctx):
    out_key = action.get('id')
    prior_key = action.get('transcriptKey') or out_key
    prior = str(ctx.get(prior_key) or '').strip()

    lines = _turn_lines(action.get('entries'), ctx)
    if not lines:
        return {"id": out_key, "data": prior}

    turn = '\n'.join(lines)
    transcript = f'{prior}{_TURN_SEPARATOR}{turn}' if prior else turn

    try:
        max_chars = int(action.get('maxChars', 8000) or 0)
    except (TypeError, ValueError):
        max_chars = 8000

    return {"id": out_key, "data": _trim(transcript, max_chars)}

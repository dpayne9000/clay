"""Shared formatting for engine events.

Every front-end announces a starting action the same way — what is starting,
plus the one or two fields that identify this particular instance of it. Only
the drawing differs, so the field selection lives here and neither renderer
owns it. A copy per renderer would drift, and a field added to one would go
missing from the other with nothing to catch it.
"""

from ...lib import config


def payload_lines(event: dict, indent: str = '  ') -> str:
    """An action.output drawn as indented text: header, then every body line.

    For the front-ends that render into a scrolling text area — `clay attach`
    and the three Qt surfaces (panels, manager, dashboard). A body is routinely
    many lines (a file's contents, a command's output), and indenting only the
    first leaves the rest in column zero, which is how this looked before it
    was one shared function.

    Bodies are cut here, so every surface that draws payloads this way honours
    the settings without repeating the check — a `kind == 'prompt'` body to
    display.promptMaxChars, everything else to its action's entry in
    display.payloadMaxChars. The terminal does not double-cut: it returns at
    kind 'prompt' before reaching this, and cuts on its own path into the
    prompt box.
    """
    label = event.get('label') or ''
    text = event.get('text') or ''
    if event.get('kind') == 'prompt':
        text = prompt_body(text)
    else:
        text = payload_body(event)
    body = f'{label}\n{text}' if text else label
    return '\n'.join(f'{indent}{line}' for line in body.split('\n'))


def _cut(body: str, limit: int, what: str) -> str:
    """`body` cut to `limit`, with a tail saying what is missing and where.

    The tail is literal: logger.output writes to the log file before any
    renderer sees the event, so every one of these hides text from a screen
    and never from the record.
    """
    if limit <= 0 or len(body) <= limit:
        return body
    return (f'{body[:limit]}\n'
            f'… {len(body) - limit} more characters — full {what} in the run log')


def payload_body(event: dict) -> str:
    """An action's payload body, cut to its display.payloadMaxChars entry.

    Per action type, not per `kind`: `kind` says what a payload *is* — a file,
    a listing — and several actions share each one. What earns a cap is an
    action that quotes something already on disk back at you, which is a fact
    about the action, not about the shape of its payload.

    So a memory entry, a skill file and a set of files served to a model are
    cut, and the same 'file' kind coming from applyFileWrites is not: the file
    a turn just wrote is the turn's result, and the reasoning that leaves a
    model's answer uncapped applies to it too. An action with no entry in the
    table is drawn whole.
    """
    body = str(event.get('text') or '')
    limit = config.get_payload_max_chars(event.get('action_type') or '')
    return _cut(body, limit, 'text')


def prompt_body(text: str) -> str:
    """An outgoing model prompt, cut to config.json's display.promptMaxChars.

    Shared by the terminal and the chat renderer so a prompt is cut in one
    place, to one number, from one file. Both surfaces used to carry their own
    knob — PROMPT_BOX_MAX_CHARS in the theme and PROMPT_PREVIEW here — which
    meant setting a limit was two edits in two formats and drifting was silent.

    Only the prompt is cut. A model's answer travels on action.complete and is
    drawn whole by every front-end. The full prompt is always in the run log:
    logger.output writes to the log file before any renderer sees the event,
    so this hides text from a screen and never from the record.
    """
    return _cut(str(text or ''), config.get_prompt_max_chars(), 'prompt')


def skipped_reason(event: dict) -> str:
    """Why a `when` gate closed, as one short phrase: `files_written=''`.

    Every surface draws a skipped action, and every one of them wants the same
    sentence, so the sentence is written once. `value` arrives already cut by
    the dispatcher; newlines are flattened because this goes on a single line
    next to the action id.
    """
    key = str(event.get('key') or '').strip()
    value = str(event.get('value') or '').strip().replace('\n', ' ')
    if not key:
        return 'gated'
    return f'{key}={value!r}' if value else f'no {key}'


def busy_label(event: dict, limit: int = 0) -> str:
    """What a busy indicator should say, for any surface that draws one.

    Three fallbacks, narrowing as information runs out: the resolved prompt
    preview, then the action type, then a bare word. The dispatcher raises the
    indicator before the handler runs and so has only the type; the preview
    arrives on a second busy once the prompt resolves, which is why both cases
    have to read well.

    `limit` cuts the whole label for a surface that draws it on one line. The
    terminal spinner redraws with '\\r', so a label long enough to wrap leaves
    the previous frame stranded on screen; passing 0 leaves it uncut.
    """
    label = (str(event.get('preview') or '').strip()
             or str(event.get('action_type') or '').strip()
             or 'working')
    if 0 < limit < len(label):
        return label[:limit] + '…'
    return label


#: Long free text (a shell command) is cut to this before it reaches a single
#: display line. This is the *summary* line only — a model call's prompt is
#: printed in its own block right after, uncapped, by each renderer from the
#: action.output event. Raising this number widens the summary line; it is not
#: the knob for how much of a prompt you see.
MAX_FIELD = 80


def action_detail(event: dict) -> str:
    """Format the identifying fields of an action.start event as one line.

    No prompt, and no `omit` parameter to suppress one. action.start does not
    carry a prompt for any action type — it is emitted before the handler
    runs, so the value there was always the unsubstituted template. The text
    that was really sent or really asked arrives on its own event
    (action.output, or input.request), which is where a renderer draws it.
    """
    parts = []
    if event.get('model'):
        parts.append(f'model="{event["model"]}"')
    if event.get('file'):
        parts.append(f'file="{event["file"]}"')
    if event.get('action_type') == 'loop':
        parts.append(f'iterations={event.get("iterations", 10)}')
    if event.get('command'):
        command = event['command']
        parts.append(f'cmd="{command[:MAX_FIELD]}"'
                     + ('...' if len(command) > MAX_FIELD else ''))
    if event.get('content'):
        parts.append(f'content="{event["content"]}"')
    if event.get('included'):
        parts.append(f'included=[{", ".join(event["included"])}]')
    return '  '.join(parts)

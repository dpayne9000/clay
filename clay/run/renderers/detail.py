"""Provide shared formatting for engine events.

Front-ends display the same identifying fields for an action but render them
differently. Centralizing field selection prevents renderers from diverging.
"""

from ...lib import config


def payload_lines(event: dict, indent: str = '  ') -> str:
    """Format an action.output header and body as indented text.

    Scrolling terminal and Qt surfaces use this function for multiline file and
    command output. Every body line receives the same indentation.

    This function applies display.promptMaxChars to prompts and the action's
    display.payloadMaxChars setting to other payloads. The terminal handles
    prompt boxes separately.
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
    """Truncate `body` and append the omitted length and log location.

    logger.output records the complete event before rendering, so truncation
    affects only the display.
    """
    if limit <= 0 or len(body) <= limit:
        return body
    return (f'{body[:limit]}\n'
            f'… {len(body) - limit} more characters — full {what} in the run log')


def payload_body(event: dict) -> str:
    """Apply an action's display.payloadMaxChars limit to its payload body.

    Limits belong to action types because several actions can emit the same
    payload kind. Actions without a configured limit display the complete body.
    """
    body = str(event.get('text') or '')
    limit = config.get_payload_max_chars(event.get('action_type') or '')
    return _cut(body, limit, 'text')


def prompt_body(text: str) -> str:
    """Apply config.json's display.promptMaxChars limit to a model prompt.

    Terminal and chat renderers share this limit. Model answers remain complete,
    and logger.output records the full prompt before display truncation.
    """
    return _cut(str(text or ''), config.get_prompt_max_chars(), 'prompt')


def skipped_reason(event: dict) -> str:
    """Format the reason a gate closed as a one-line phrase.

    The dispatcher has already truncated `value`. Replace newlines because the
    result appears beside the action ID.
    """
    key = str(event.get('key') or '').strip()
    value = str(event.get('value') or '').strip().replace('\n', ' ')
    if not key:
        return 'gated'
    return f'{key}={value!r}' if value else f'no {key}'


def busy_label(event: dict, limit: int = 0) -> str:
    """Format a busy indicator label for any rendering surface.

    Prefer the resolved prompt preview, then the action type, then `working`.
    The dispatcher initially has only the type; a handler may later add a prompt.

    `limit` prevents one-line indicators from wrapping. Zero disables the limit.
    """
    label = (str(event.get('preview') or '').strip()
             or str(event.get('action_type') or '').strip()
             or 'working')
    if 0 < limit < len(label):
        return label[:limit] + '…'
    return label


#: Maximum free-text length in a one-line summary. Prompts use their own limit.
MAX_FIELD = 80


def action_detail(event: dict) -> str:
    """Format the identifying fields of an action.start event as one line.

    action.start excludes prompts because handlers have not yet resolved their
    templates. Renderers receive final text through action.output or input.request.
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

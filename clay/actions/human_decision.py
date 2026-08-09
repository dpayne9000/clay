from ..run import io, logger
from .registry import action, req, handler_for


@action('humanDecision')
class HumanDecision:
    id:     str = req("Output key for the typed response")
    prompt: str = req("Text shown to the human. Supports {placeholder} interpolation")


class _SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'


@handler_for('humanDecision')
def handler(action, ctx, auto=False, auto_context=None):
    prompt = action.get('prompt') or ''
    resolved_prompt = prompt.format_map(_SafeMap(ctx))
    if not resolved_prompt:
        return None

    if auto:
        parts = []
        if auto_context:
            parts.append(auto_context)
        if ctx:
            context_lines = "\n".join(f"  {k}: {str(v)[:200]}" for k, v in ctx.items())
            parts.append(f"Accumulated context:\n{context_lines}")
        parts.append(resolved_prompt)
        full_prompt = "\n\n".join(parts)

        # A real dispatch, so the model call is on the bus like any other.
        # full_prompt is finished text, but the scramda2 handler always runs
        # format_map on its prompt — brace-escape so context values containing
        # { } (JSON, code) pass through as-is instead of being re-interpolated
        # or crashing the format parser.
        from ..run import dispatcher
        result = dispatcher.dispatch(
            {'type': 'scramda2', 'id': action.get('id', ''),
             'prompt': full_prompt.replace('{', '{{').replace('}', '}}')},
            {}, auto=auto)
        answer = (result or {}).get('data')
        logger.debug(f"[AUTO] {resolved_prompt} → {answer}")
        return {"id": action.get("id"), "data": answer}

    # Terminal when run directly, relayed through clayd when daemon-managed.
    user_input = io.get().prompt(action.get("id", ""), resolved_prompt)
    return {"id": action.get("id"), "data": user_input}

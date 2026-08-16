import time
from ..run import logger
from ..adapters import gopher
from ..lib import config as app_config
from .registry import action, req, opt, handler_for


@action('scramda2')
class Scramda2:
    id:           str  = req("Output key for the AI response text")
    prompt:       str  = req("Prompt sent to the AI. Supports {placeholder} interpolation")
    model:        str  = opt("Literal model ID to use for this call", None)
    modelProfile: str  = opt("Named alias resolved from config.models[modelProfile] in context. Overrides model", None)
    max_tokens:   int  = opt("Cap on response length in tokens", None)
    examples:     list = opt("Few-shot examples as [{\"input\": ..., \"output\": ...}]", None)


class _SafeMap(dict):
    """Leave unresolved {placeholders} in place instead of raising KeyError."""
    def __missing__(self, key):
        return f'{{{key}}}'

@handler_for('scramda2')
def handler(action, ctx):
    prompt = action.get('prompt') or ''
    if not prompt:
        return None

    resolved_prompt = prompt.format_map(_SafeMap(ctx))

    models = app_config.get_models()

    model_name = action.get('model')
    model_profile_name = action.get('modelProfile')
    # modelProfile → lookup in config.models (None if profile name not found)
    # model        → literal string on the action
    # fallback     → config.models["default"]
    resolved_model = models.get(model_profile_name) if model_profile_name else None
    model = resolved_model or model_name or models.get('default')
    action_max_tokens = action.get('max_tokens')
    max_tokens = (action_max_tokens if action_max_tokens is not None
                  else app_config.get_max_tokens())
    # The resolved prompt, not the template on the action. Until now nothing
    # showed it: dispatcher._action_fields copies action['prompt'] onto
    # action.start, which happens before this handler runs, so every prompt in
    # every front-end was the raw json with {workspace_files} and {transcript}
    # still literal. It only exists here, so it can only be emitted here.
    logger.output(action, 'prompt', model or '', resolved_prompt)

    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            text = gopher.fire(
                resolved_prompt,
                examples=action.get('examples') or [],
                model=model,
                max_tokens=max_tokens,
            )
            break
        except (gopher.GopherConnectionError, gopher.GopherTimeoutError) as e:
            logger.warn(f"scramda2: could not reach gopher ({e}), retry {attempt}/{max_retries}...")
            if attempt == max_retries:
                logger.error(f"scramda2: giving up after {max_retries} retries")
                return {"id": action.get("id"), "data": None, "error": f"scramda2: gopher unreachable after {max_retries} retries: {e}"}
            time.sleep(5)
        except Exception as e:
            logger.error(f"scramda2: unexpected error: {e}")
            return {"id": action.get("id"), "data": None, "error": f"scramda2: {e}"}

    return {"id": action.get("id"), "data": text}

import os
import re
from ...lib import config
from ...run import approval, logger
from ..registry import action as _action_decorator, req, handler_for


@_action_decorator('createAgentAction', skeleton=False)
class CreateAgentAction:
    id:         str = req("Output key for the created file path")
    actionName: str = req("kebab-case or snake_case name matching [a-z][a-z0-9_-]{1,39}")
    content:    str = req("Context key holding the Python source for the new action module")


# Generated source belongs to user data, never the installed package.
_AGENT_DIR = config.user_path('actions')

# Only allow safe identifiers as action names — no path traversal.
_SAFE_NAME_RE = re.compile(r'^[a-z][a-z0-9_-]{1,39}$')


@handler_for('createAgentAction')
def handler(action, ctx):
    """
    Write a new agent action module to the agent/ folder.

    Action fields:
      actionName  — snake_case or kebab-case name, e.g. "dns-resolver" → dns_resolver_actions.py
      content     — key in ctx containing the Python source to write
    """
    action_name = (action.get('actionName') or '').strip()
    content_key = action.get('content')

    if not action_name:
        logger.error("createAgentAction: missing 'actionName'")
        return None
    if not _SAFE_NAME_RE.match(action_name):
        logger.error(f"createAgentAction: invalid actionName '{action_name}' (must match [a-z][a-z0-9_-]{{1,39}})")
        return None
    if not content_key:
        logger.error("createAgentAction: missing 'content' field")
        return None

    source = ctx.get(content_key)
    if source is None:
        logger.error(f"createAgentAction: no data for content key '{content_key}'")
        return None

    try:
        compile(str(source), f'{action_name}_actions.py', 'exec')
    except SyntaxError as exc:
        return {"id": action.get("id"), "data": None,
                "error": f"createAgentAction: invalid Python source: {exc}"}

    safe_name = action_name.replace('-', '_')
    filename = f"{safe_name}_actions.py"
    path = os.path.join(_AGENT_DIR, filename)

    decision = approval.confirm(
        'fileWrites', 'createAgentAction wants to save generated Python:',
        [(path, str(source))], prompt_id=f'{action.get("id", "")}.approve',
        required=True)
    if not decision:
        return {"id": action.get("id"), "data": None,
                "error": "createAgentAction: generated source was not approved"}

    os.makedirs(_AGENT_DIR, mode=0o700, exist_ok=True)
    with open(path, 'w') as f:
        f.write(str(source))

    logger.debug(f"agent action created: {path}")
    return {"id": action.get("id"), "data": path}

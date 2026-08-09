import io
import contextlib
from ..run import approval
from .registry import action as _action_decorator, req, handler_for


@_action_decorator('python', skeleton=False)
class Python:
    id:   str = req("Output key for the captured stdout")
    code: str = req("Python source to execute after explicit human approval; not a security sandbox")


@handler_for('python')
def handler(action, ctx, daemon=False):
    code = action.get('code')
    if not code:
        return None

    decision = approval.confirm(
        'commands', 'python wants to execute workflow-supplied source:',
        [('python', code)], prompt_id=f'{action.get("id", "")}.approve',
        required=True)
    if not decision:
        return {"id": action.get("id"), "data": None,
                "error": "python: source was not approved"}

    output_capture = io.StringIO()
    with contextlib.redirect_stdout(output_capture):
        try:
            # This is an execution convenience, not a sandbox. Authorization
            # above is the security boundary.
            exec(code, {"__builtins__": {}})
        except Exception as e:
            return {"id": action.get("id"), "data": f"[error: {e}]"}

    output = output_capture.getvalue()
    return {"id": action.get("id"), "data": output}

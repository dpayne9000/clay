import re
from ...run import logger
from ...actions.core import write_file
from ...run.workspaces import DEFAULT_ROOT
from ..registry import action, req, opt, handler_for


@action('writeCode', skeleton=False)
class WriteCode:
    id:         str = req("Output key for the written file path")
    contentKey: str = req("Context key holding AI-generated content (code fences stripped automatically)")
    file:       str = req("Output file path. Supports {placeholder} interpolation")
    root:       str = opt("Approved workspace root containing the relative output path", DEFAULT_ROOT)


_FENCE_RE = re.compile(r'^```[a-zA-Z]*\n([\s\S]*?)\n```$', re.MULTILINE)


class _SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'


def _strip_fences(text):
    """
    Remove markdown code fences from AI-generated content.
    Handles ```python ... ```, ```json ... ```, ``` ... ```, etc.
    Falls back to the original text if no fence is found.
    """
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1)
    # Partial fence: opening without closing (AI got cut off)
    partial = re.sub(r'^```[a-zA-Z]*\n', '', text)
    if partial != text:
        return partial.rstrip('`').strip()
    return text


@handler_for('writeCode')
def handler(action, ctx):
    """
    writeCode — strip markdown code fences from AI-generated content,
    then write the result to a file path.

    Action fields:
      contentKey   key in ctx holding the AI-generated content
      file         output file path (supports {placeholder} interpolation)
    """
    content_key = action.get('contentKey')
    file_template = action.get('file') or ''

    if not content_key:
        logger.error("writeCode: missing 'contentKey'")
        return None
    if not file_template:
        logger.error("writeCode: missing 'file'")
        return None

    raw = ctx.get(content_key)
    if raw is None:
        logger.error(f"writeCode: no data for key '{content_key}'")
        return None

    content = _strip_fences(str(raw))
    delegated = {
        "id": action.get("id"),
        "file": file_template,
        "content": "__write_code_content__",
        "root": action.get("root") or DEFAULT_ROOT,
        "stripCodeFence": False,
    }
    delegated_ctx = dict(ctx)
    delegated_ctx["__write_code_content__"] = content
    # The delegated writeFile handler resolves the path and owns the single
    # mandatory approval.  Keeping the gate there prevents writeCode and future
    # wrappers from accidentally implementing weaker or duplicate policies.
    return write_file.handler(delegated, delegated_ctx)

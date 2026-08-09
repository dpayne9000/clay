import os
from ..run import logger

class _SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'

    def __getitem__(self, key):
        raw = super().__getitem__(key)
        # Strip path-traversal sequences from any context value substituted into a path.
        # Replace backslashes and remove all '..' components after splitting on '/'.
        parts = str(raw).replace('\\', '/').split('/')
        safe_parts = [p for p in parts if p not in ('..', '.', '')]
        return '/'.join(safe_parts)

def _err(action, msg):
    logger.error(msg)
    return {"id": action.get("id"), "data": None, "error": msg}


def handler(action, ctx):
    file_template = action.get('file') or ''
    content_key = action.get('content')

    if not file_template:
        return _err(action, "writeFile: missing 'file' field")
    if not content_key:
        return _err(action, "writeFile: missing 'content' field")

    content = ctx.get(content_key)
    if content is None:
        return _err(action, f"writeFile: no data for content key '{content_key}'")

    output_path = file_template.format_map(_SafeMap(ctx))
    dirname = os.path.dirname(output_path)

    try:
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(str(content))
    except OSError as e:
        return _err(action, f"writeFile: could not write '{output_path}': {e}")

    logger.debug(f"writeFile: saved {output_path}")
    return {"id": action.get("id"), "data": output_path}

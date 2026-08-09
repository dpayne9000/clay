"""Legacy data transformations retained for workflow compatibility.

``transformData`` is not used by the shipped application workflows. Its
existing operations remain registered so older user workflows do not change
meaning during an unrelated cleanup.
"""

from ..run import logger
from .registry import action, req, handler_for


@action('transformData', skeleton=False)
class TransformData:
    id:     str = req("Output key for the transformed result")
    source: str = req("Context key holding the data to transform")
    method: str = req("Legacy transformation method: parseLines or map")


def _custom_map(func, iterable, *args, **kwargs):
    return [func(item, *args, **kwargs) for item in iterable]


def _multiply_by(item, factor):
    return item * factor


def _text_to_dict(text):
    lines = text.split('\n')
    return {index: line for index, line in enumerate(lines, start=1)}


@handler_for('transformData')
def handler(action, ctx):
    method = action.get('method')
    source_key = action.get('source')
    data = ctx.get(source_key) if source_key else None

    if data is None:
        logger.error(f"transformData: no data for source key '{source_key}'")
        return None

    output = None
    if method == 'map':
        # TODO(transformData-map): replace the hard-coded multiply-by-two only
        # after choosing a useful declarative contract, such as named safe
        # transforms or field/path selection.
        # TODO(transformData-map): add schema validation for that contract and
        # migration guidance before changing this compatibility behavior.
        output = _custom_map(_multiply_by, data, factor=2)
    elif method == 'parseLines':
        output = _text_to_dict(str(data))
    else:
        logger.error(f"transformData: unknown method '{method}'")
        return None

    logger.debug(f"transformData: {method} → {str(output)[:80]}")
    return {"id": action.get("id"), "data": output}

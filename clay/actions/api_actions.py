from ..lib.network_policy import (
    NetworkPolicyError, request,
)
from ..run import logger
from .registry import action as _action_decorator, req, opt, handler_for


@_action_decorator('API', skeleton=False)
class API:
    id:       str  = req("Output key for the response body (parsed JSON or raw text)")
    endpoint: str  = req("Full URL of the API endpoint")
    method:   str  = opt("HTTP method: get, post, put, patch, delete", "get")
    params:   dict = opt("URL query parameters as a JSON object", None)
    headers:  dict = opt("HTTP headers as a JSON object", None)
    data:     dict = opt("Request body, sent as JSON", None)


@handler_for('API')
def handler(action, ctx):
    endpoint = action.get('endpoint')
    if not endpoint:
        logger.error("API: missing 'endpoint'")
        return None

    _methods = {'get', 'post', 'put', 'patch', 'delete'}
    method = action.get('method', 'get').lower()
    params = action.get('params', {})
    headers = action.get('headers', {})
    data = action.get('data', {})

    if method not in _methods:
        logger.error(f"API: unsupported method '{method}'")
        return None

    try:
        response = request(
            method, endpoint, params=params, headers=headers, json=data,
            allow_loopback_http=True)
        logger.debug(f"API: {method.upper()} {endpoint} → {response.status_code}")
        try:
            result = response.json()
        except ValueError:
            result = response.text
        return {"id": action.get("id"), "data": result}
    except (OSError, NetworkPolicyError) as e:
        logger.warn(f"API error: {e}")
        return {"id": action.get("id"), "data": f"[error: {e}]"}

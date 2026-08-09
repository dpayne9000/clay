import json
import os
import time
import urllib.request
from ...run import logger
from ...lib import config as app_config
from ..registry import action, req, opt, handler_for


@action('sendAlert', skeleton=False)
class SendAlert:
    id:      str = req("Output key for alert delivery confirmation")
    channel: str = req("Delivery channel: email, webhook, or file")
    message: str = req("Context key or literal text. Supports {placeholder}")
    level:   str = opt("Alert level: info, warning, or critical", "info")
    to:      str = opt("Override recipient for email channel. Supports {placeholder}", None)
    url:     str = opt("Override URL for webhook channel. Supports {placeholder}", None)


CONFIG_PATH = app_config.resource('configs', 'alerts.json')


class _SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'


def _load_config():
    """Load alert channel config from configs/alerts.json."""
    if not os.path.exists(CONFIG_PATH):
        return {'channels': {}}
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception as e:
        logger.warn(f"sendAlert: could not read {CONFIG_PATH}: {e}")
        return {'channels': {}}


def _send_email_alert(message, level, action, ctx):
    from . import email_actions
    to = (action.get('to') or '').format_map(_SafeMap(ctx))
    if not to:
        email_cfg = email_actions._load_config()
        to = email_cfg.get('from_email', '')  # self-notify as fallback
    if not to:
        logger.error("sendAlert(email): no recipient — set 'to' in action or from_email in configs/email.json")
        return "[error: no email recipient]"

    subject = f"[{level.upper()}] Alert"
    try:
        email_actions.send_email(to, subject, message)
        return f"email sent to {to}"
    except Exception as e:
        logger.warn(f"sendAlert(email): {e}")
        return f"[error: {e}]"


def _send_webhook_alert(message, level, action, ctx):
    cfg = _load_config()
    url = (action.get('url') or '').format_map(_SafeMap(ctx))
    if not url:
        url = cfg.get('channels', {}).get('webhook', {}).get('url', '')
    if not url:
        logger.error("sendAlert(webhook): no URL — set 'url' in action or configs/alerts.json")
        return "[error: no webhook URL]"

    payload = json.dumps({
        'message': message,
        'level': level,
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }).encode('utf-8')

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return f"webhook {resp.status}"
    except Exception as e:
        logger.warn(f"sendAlert(webhook): {e}")
        return f"[error: {e}]"


def _send_file_alert(message, level, action, ctx):
    cfg = _load_config()
    log_path = cfg.get('channels', {}).get('file', {}).get('path', 'logs/alerts.log')

    # Relative alert logs belong to the user's Clay data, never site-packages.
    if not os.path.isabs(log_path):
        log_path = app_config.user_path(log_path)

    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        line = f"{timestamp} [{level.upper()}] {message}\n"
        with open(log_path, 'a') as f:
            f.write(line)
        return f"logged to {log_path}"
    except Exception as e:
        logger.warn(f"sendAlert(file): {e}")
        return f"[error: {e}]"


_CHANNEL_HANDLERS = {
    'email': _send_email_alert,
    'webhook': _send_webhook_alert,
    'file': _send_file_alert,
}


@handler_for('sendAlert')
def handler(action, ctx):
    channel = action.get('channel', '')
    message_key = action.get('message', '')
    message = ctx.get(message_key, message_key)
    message = str(message).format_map(_SafeMap(ctx))
    level = action.get('level', 'info')

    if not channel:
        logger.error("sendAlert: missing 'channel' field")
        return None

    cfg = _load_config()
    channel_cfg = cfg.get('channels', {}).get(channel, {})
    if channel_cfg.get('enabled') is False:
        logger.debug(f"sendAlert: channel '{channel}' is disabled in config")
        return {"id": action.get("id"), "data": f"[skipped: {channel} disabled]"}

    dispatch = _CHANNEL_HANDLERS.get(channel)
    if not dispatch:
        logger.error(f"sendAlert: unknown channel '{channel}' — use email, webhook, or file")
        return None

    result = dispatch(message, level, action, ctx)
    return {"id": action.get("id"), "data": result}

import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from ...run import logger
from ...lib import config as app_config
from ..registry import action, req, opt, handler_for


@action('sendEmail', skeleton=False)
class SendEmail:
    id:      str = req("Output key for the send confirmation")
    to:      str = req("Recipient email address. Supports {placeholder}")
    body:    str = req("Context key or literal text for email body. Supports {placeholder}")
    subject: str = opt("Subject line. Supports {placeholder}", "No Subject")
    format:  str = opt("Email body format: 'plain' or 'html'", "plain")


CONFIG_PATH = app_config.resource('configs', 'email.json')


class _SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'


def _load_config():
    """Load SMTP config from configs/email.json, falling back to env vars."""
    cfg = {}

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
        except Exception as e:
            logger.warn(f"sendEmail: could not read {CONFIG_PATH}: {e}")

    return {
        'smtp_server':   cfg.get('smtp_server')   or os.environ.get('CLAY_SMTP_SERVER', ''),
        'smtp_port':     cfg.get('smtp_port')      or int(os.environ.get('CLAY_SMTP_PORT', '587')),
        'smtp_username': cfg.get('smtp_username')  or os.environ.get('CLAY_SMTP_USERNAME', ''),
        'smtp_password': cfg.get('smtp_password')  or os.environ.get('CLAY_SMTP_PASSWORD', ''),
        'from_email':    cfg.get('from_email')     or os.environ.get('CLAY_FROM_EMAIL', ''),
    }


def send_email(to, subject, body, fmt='plain', config=None):
    """Send an email. Reusable by other modules (e.g. alert_actions)."""
    cfg = config or _load_config()

    if not all([cfg['smtp_server'], cfg['smtp_username'], cfg['smtp_password'], cfg['from_email']]):
        raise ValueError('Incomplete email config — fill configs/email.json or set CLAY_SMTP_* env vars')

    msg = MIMEMultipart()
    msg['From'] = cfg['from_email']
    msg['To'] = to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, fmt))

    server = smtplib.SMTP(cfg['smtp_server'], int(cfg['smtp_port']))
    server.starttls()
    server.login(cfg['smtp_username'], cfg['smtp_password'])
    server.sendmail(cfg['from_email'], to, msg.as_string())
    server.quit()


@handler_for('sendEmail')
def handler(action, ctx):
    to = (action.get('to') or '').format_map(_SafeMap(ctx))
    subject = (action.get('subject') or 'No Subject').format_map(_SafeMap(ctx))
    body_key = action.get('body', '')
    body = ctx.get(body_key, body_key)  # resolve as context key first, literal fallback
    body = str(body).format_map(_SafeMap(ctx))
    fmt = action.get('format', 'plain')

    if not to:
        logger.error("sendEmail: missing 'to' field")
        return None

    try:
        send_email(to, subject, body, fmt)
        logger.debug(f"sendEmail: sent to {to}")
        return {"id": action.get("id"), "data": f"sent to {to}"}
    except Exception as e:
        logger.warn(f"sendEmail: failed: {e}")
        return {"id": action.get("id"), "data": f"[error: {e}]"}

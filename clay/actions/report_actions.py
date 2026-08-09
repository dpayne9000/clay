import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from ..run import logger
from .registry import action, req, opt, handler_for


@action('report', skeleton=False)
class Report:
    id:            str = req("Output key for the send confirmation string")
    body:          str = req("Context key holding the email body, or a literal string")
    to_email:      str = req("Recipient email address")
    from_email:    str = req("Sender email address")
    smtp_server:   str = req("SMTP server hostname")
    smtp_port:     int = req("SMTP server port (typically 587 for STARTTLS)")
    smtp_username: str = req("SMTP login username")
    smtp_password: str = req("SMTP login password")
    subject:       str = opt("Email subject line", "No Subject")


def _send_email(subject, body, to_email, from_email, smtp_server, smtp_port, smtp_username, smtp_password):
    message = MIMEMultipart()
    message['From'] = from_email
    message['To'] = to_email
    message['Subject'] = subject
    message.attach(MIMEText(body, 'plain'))

    server = smtplib.SMTP(smtp_server, smtp_port)
    server.starttls()
    server.login(smtp_username, smtp_password)
    server.sendmail(from_email, to_email, message.as_string())
    server.quit()


@handler_for('report')
def handler(action, ctx):
    subject = action.get('subject', 'No Subject')
    body_key = action.get('body', '')
    body = ctx.get(body_key, body_key)  # resolve as key or use literal
    to_email = action.get('to_email')
    from_email = action.get('from_email')
    smtp_server = action.get('smtp_server')
    smtp_port = action.get('smtp_port')
    smtp_username = action.get('smtp_username')
    smtp_password = action.get('smtp_password')

    if not all([to_email, from_email, smtp_server, smtp_port, smtp_username, smtp_password]):
        logger.error("report: missing email configuration parameters")
        return None

    try:
        _send_email(subject, body, to_email, from_email, smtp_server, smtp_port, smtp_username, smtp_password)
        logger.debug(f"report: email sent to {to_email}")
        return {"id": action.get("id"), "data": f"sent to {to_email}"}
    except Exception as e:
        logger.warn(f"report: failed to send email: {e}")
        return {"id": action.get("id"), "data": f"[error: {e}]"}

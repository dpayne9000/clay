# report

Sends an email via SMTP. Used to deliver workflow results, alerts, or summaries to an email address.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the send confirmation under |
| `subject` | no | string | Email subject line. Defaults to `"No Subject"` |
| `body` | yes | string | Key in `previous_data` holding the email body text, OR a literal string |
| `to_email` | yes | string | Recipient email address |
| `from_email` | yes | string | Sender email address |
| `smtp_server` | yes | string | SMTP server hostname |
| `smtp_port` | yes | number | SMTP server port (typically `587` for TLS) |
| `smtp_username` | yes | string | SMTP login username |
| `smtp_password` | yes | string | SMTP login password |

## How it works

`body` is first looked up as a key in `previous_data`. If found, that value is used as the body text. If not found as a key, the literal value of `body` is used directly.

Connects to the SMTP server with STARTTLS, authenticates, sends the message as plain text, and disconnects. Returns `"sent to {to_email}"` on success.

## Examples

### Send a research summary
```json
{
  "id": "email_sent",
  "type": "report",
  "subject": "Research complete",
  "body": "final_summary",
  "to_email": "team@example.com",
  "from_email": "bot@example.com",
  "smtp_server": "smtp.example.com",
  "smtp_port": 587,
  "smtp_username": "bot@example.com",
  "smtp_password": "secret"
}
```

### Load credentials from config then send
```json
{ "id": "_", "type": "loadContext", "file": "config/email.json" },
{
  "id": "email_sent",
  "type": "report",
  "subject": "Daily report",
  "body": "report_text",
  "to_email": {"override": "email_recipient"},
  "from_email": {"override": "email_sender"},
  "smtp_server": {"override": "smtp_host"},
  "smtp_port": {"override": "smtp_port"},
  "smtp_username": {"override": "smtp_user"},
  "smtp_password": {"override": "smtp_pass"}
}
```

`config/email.json` holds all the SMTP credentials; `{"override": "key"}` injects them.

## Notes

- All SMTP fields are required — a missing field causes the action to return `None` without sending
- Credentials in workflow JSON are plaintext — use `loadContext` from a gitignored config file to keep secrets out of version control
- Sends plain text only — no HTML, no attachments

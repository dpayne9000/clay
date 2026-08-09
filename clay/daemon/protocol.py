"""JSON-line protocol between clayd and its clients.

Every message is a single JSON object terminated by newline.

Client → Server (commands):
    {"cmd": "start",  "workflow": "path/to/wf.json", "auto": true, "daemon": true}
    {"cmd": "start-json", "data": {...}, "label": "name", "auto": true}
    {"cmd": "stop",   "id": "wf-0001"}
    {"cmd": "kill",   "id": "wf-0001"}
    {"cmd": "list"}
    {"cmd": "info",   "id": "wf-0001"}
    {"cmd": "input",  "id": "wf-0001", "text": "user response"}
    {"cmd": "subscribe", "id": "wf-0001"}   # stream events for one workflow
    {"cmd": "subscribe-all"}                 # stream events for all workflows
    {"cmd": "unsubscribe"}
    {"cmd": "tail",   "id": "wf-0001", "lines": 50}  # last N stdout lines
    {"cmd": "ping"}
    {"cmd": "shutdown"}

Server → Client (responses):
    {"ok": true, "id": "wf-0001", ...}
    {"ok": false, "error": "message"}

Server → Client (streamed events, only after subscribe):
    {"event": "stdout",    "id": "wf-0001", "line": "..."}
    {"event": "stderr",    "id": "wf-0001", "line": "..."}
    {"event": "workflow",  "id": "wf-0001", "data": {...}}  # engine event
    {"event": "prompt",    "id": "wf-0001", "prompt_id": "...", "text": "..."}
    {"event": "started",   "id": "wf-0001", "pid": 1234}
    {"event": "finished",  "id": "wf-0001", "exit_code": 0}
    {"event": "error",     "id": "wf-0001", "message": "..."}
    {"event": "status",    "id": "wf-0001", "status": "running", ...}

Server → Client (unsolicited, broadcast to all connected):
    {"event": "daemon-stopping"}
"""

import json

MAX_FRAME_BYTES = 1024 * 1024


def encode(obj):
    """Encode a message dict to a JSON line (bytes)."""
    if not isinstance(obj, dict):
        raise TypeError("daemon protocol messages must be JSON objects")
    frame = (json.dumps(obj, default=str) + '\n').encode('utf-8')
    if len(frame) > MAX_FRAME_BYTES:
        raise ValueError("daemon protocol message exceeds 1 MiB")
    return frame


def decode_line(line):
    """Decode a JSON line string to a dict. Returns None on failure."""
    line = line.strip()
    if not line:
        return None
    try:
        value = json.loads(line)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None

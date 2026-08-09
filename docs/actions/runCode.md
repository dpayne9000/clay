# runCode

Executes a code string in a temporary file and captures stdout. Supports Python, Bash, Node, and sh.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store stdout under |
| `language` | no | string | `python` (default), `bash`, `node`, or `sh` |
| `source` | no | string | Inline source code (literal string in JSON) |
| `sourceKey` | no | string | Key in `previous_data` holding the source code. Takes precedence over `source` |
| `stdin` | no | string | Key in `previous_data` to pipe as stdin to the process |
| `timeout` | no | number | Seconds before the process is killed. Defaults to `30` |

One of `source` or `sourceKey` is required.

## How it works

The source is written to a temp file with the appropriate extension (`.py`, `.sh`, `.js`), executed with the matching interpreter, and the temp file is deleted afterward. Stdout is returned. Stderr is not captured to the result but non-zero exit codes append `\n[exit code: N]` to the output.

## Examples

### Run inline Python
```json
{
  "id": "output",
  "type": "runCode",
  "language": "python",
  "source": "print('hello')"
}
```

### Run AI-generated code
```json
{ "id": "script", "type": "scramda2", "prompt": "Write a Python script that prints system info." },
{
  "id": "output",
  "type": "runCode",
  "language": "python",
  "sourceKey": "script"
}
```

When using AI-generated code via `sourceKey`, the AI should output plain Python — not markdown-fenced. If the AI wraps output in ` ```python ``` ` fences, use `writeCode` to strip them before passing to `runCode`.

### Pipe data as stdin
```json
{
  "id": "result",
  "type": "runCode",
  "language": "bash",
  "source": "sort | uniq -c | sort -rn",
  "stdin": "raw_data"
}
```

### Run a Node script with a longer timeout
```json
{
  "id": "output",
  "type": "runCode",
  "language": "node",
  "sourceKey": "generated_js",
  "timeout": 60
}
```

## Notes

- Code runs with full system access — there is no sandbox. Only run trusted, reviewed code
- For AI-generated code that may contain markdown fences, use `writeCode` to write to disk first, then use `humanShell` to run it with human approval — this is safer than executing fenced output directly
- The `python` action (`type: python`) runs inline code in an `exec()` sandbox with no builtins. `runCode` with `language: python` uses a real subprocess — prefer `runCode` when you need imports or access to the filesystem

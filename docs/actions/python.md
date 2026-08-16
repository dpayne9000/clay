# python

Executes approved inline Python and captures standard output.

## Fields

| Field | Required | Type | Description |
|---|---:|---|---|
| `id` | yes | string | Result key |
| `code` | yes | string | Python source |

The action always uses the required `commands` approval gate. It calls
`exec(code, {"__builtins__": {}})` and captures stdout. Empty builtins limit
ordinary convenience functions, but they are not a security sandbox.

Workflow context is not injected into the execution scope. Errors are returned
as `[error: ...]`.

Use `runCode` when the source needs a normal interpreter, imports, filesystem
access, or stdin. Both actions execute code and require informed approval.

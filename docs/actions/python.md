# python

Executes a small inline Python snippet inside a restricted `exec()` sandbox and captures its stdout. Builtins are disabled — use for pure computation only.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the captured stdout under |
| `code` | yes | string | Python source code to execute (inline string in JSON) |

## How it works

The `code` string is executed via `exec(code, {"__builtins__": {}})`. Stdout is captured via `contextlib.redirect_stdout`. The captured output is returned.

Because `__builtins__` is empty, most standard library functions are unavailable. No imports, no file access, no network access. This is suitable only for isolated transformations on literal values.

## Examples

### Simple arithmetic
```json
{
  "id": "result",
  "type": "python",
  "code": "print(42 * 7)"
}
```

### String manipulation
```json
{
  "id": "upper",
  "type": "python",
  "code": "print('hello world'.upper())"
}
```

Note: `previous_data` is not accessible inside the sandbox. The code must be fully self-contained.

## Notes

- `previous_data` values are **not** injected into the execution scope — the code cannot access workflow context
- For code that needs imports, filesystem access, or workflow data, use `runCode` (subprocess) instead
- Errors in the snippet return `[error: ExceptionType: message]` rather than failing the workflow
- This action is a basic escape hatch for simple one-off computations. For anything beyond trivial math/string ops, use `runCode`

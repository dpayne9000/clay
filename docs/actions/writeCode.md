# writeCode

Strips markdown code fences from AI-generated content and writes the clean result to a file. This is the correct way to materialize AI-generated code files — AI output often wraps code in ` ```python ``` ` blocks which must not reach the filesystem verbatim.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the written file path under |
| `contentKey` | yes | string | Key in `previous_data` holding the AI-generated content |
| `file` | yes | string | Output file path. Supports `{placeholder}` interpolation |

## How it works

Reads `previous_data[contentKey]`, strips any surrounding markdown code fence (` ```python `, ` ```json `, ` ``` `, etc.), then writes the clean content to the path. Creates parent directories if needed.

Fence stripping handles:
- Full fence: ` ```python\n...\n``` ` → inner content only
- Partial fence (AI got cut off): ` ```python\n... ` → content after opening line, trailing backticks removed

If no fence is found, the content is written as-is.

Returns the written file path.

## Examples

### Write AI-generated Python to a file
```json
{ "id": "code", "type": "scramda2", "prompt": "Write a Python module that does X." },
{
  "id": "file_path",
  "type": "writeCode",
  "contentKey": "code",
  "file": "output/module.py"
}
```

### Use a dynamic file path
```json
{ "id": "filename", "type": "scramda2", "prompt": "What should this file be called (e.g. scaffold.py)?" },
{
  "id": "file_path",
  "type": "writeCode",
  "contentKey": "generated_code",
  "file": "output/{filename}"
}
```

### Write then run with human approval
```json
{ "id": "code", "type": "scramda2", "prompt": "Write a script to initialize the project." },
{ "id": "file_path", "type": "writeCode", "contentKey": "code", "file": "scripts/init.py" },
{ "id": "run_result", "type": "humanShell", "command": "python3 {file_path}" }
```

This is the recommended pattern for executing AI-generated code — write it to disk first (with fence stripping), then run it via `humanShell` so a human approves the execution.

## Notes

- Use this instead of `writeFile` when the source is AI-generated code. `writeFile` writes raw content with no processing
- The fence stripping is designed specifically for AI model output — it handles the most common wrapping patterns
- After `writeCode`, use `humanShell` rather than `runCode` to execute the file — the human can review what was written before running it

# writeFile

Writes a raw string value from `previous_data` to a file path. No processing — what's in the data key goes directly to disk.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the written file path under |
| `file` | yes | string | Output file path. Supports `{placeholder}` interpolation |
| `content` | yes | string | Key in `previous_data` holding the content to write |

## How it works

Resolves the `file` path via `{placeholder}` interpolation, creates any missing parent directories, then writes `str(previous_data[content])` to the file. Returns the file path.

## Examples

### Write a report to disk
```json
{
  "id": "report_path",
  "type": "writeFile",
  "file": "reports/output.txt",
  "content": "report_text"
}
```

### Use a dynamic file path
```json
{ "id": "filename", "type": "humanDecision", "prompt": "Output filename:" },
{
  "id": "saved_path",
  "type": "writeFile",
  "file": "output/{filename}",
  "content": "result"
}
```

### Save structured JSON output
```json
{
  "id": "config_path",
  "type": "writeFile",
  "file": "config/settings.json",
  "content": "generated_config"
}
```

If `generated_config` contains valid JSON as a string, it will be written verbatim. No serialization is performed — ensure the data is already in the desired format.

## Notes

- Content is written as-is — no fence stripping, no formatting. For AI-generated code, use `writeCode` instead
- The `content` field references a key in `previous_data`, not a literal string. To write a literal string, either set it in `defaults` first or store it via a prior action
- Overwrites any existing file at the path without confirmation

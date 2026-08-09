# writeSkill

Writes a file to a skill set directory at `clay/skills/{skillset}/`. Skills are executable artifacts — Python scripts, shell scripts, JSON configs — meant to be run later via `runCode` or `humanShell`.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the written file path under |
| `skillset` | yes | string | Subdirectory under `skills/` (e.g. `developer`, `system-editor`) |
| `name` | yes | string | Filename without extension. Supports `{placeholder}` interpolation |
| `content` | yes | string | Key in `previous_data` holding the file content |
| `extension` | no | string | File extension. Defaults to `"py"`. Allowed: `py`, `json`, `txt`, `sh` |
| `skipValue` | no | string | If the resolved `name` equals this value, the write is skipped |

## How it works

Resolves the `name` field via `{placeholder}` interpolation, then writes `previous_data[content]` to `skills/{skillset}/{name}.{extension}`. Creates the directory if it doesn't exist.

Returns the absolute file path on success, or `"[skipped]"` if skipped.

## Examples

### Write a Python skill from AI output
```json
{
  "id": "skill_path",
  "type": "writeSkill",
  "skillset": "developer",
  "name": "express-app-scaffold",
  "content": "generated_code",
  "extension": "py"
}
```

### Use a dynamic name from previous output
```json
{ "id": "skill_name", "type": "scramda2", "prompt": "Name this skill (kebab-case, no extension):" },
{
  "id": "skill_path",
  "type": "writeSkill",
  "skillset": "developer",
  "name": "{skill_name}",
  "content": "generated_code"
}
```

### Skip if AI returned a sentinel value
```json
{
  "id": "skill_path",
  "type": "writeSkill",
  "skillset": "developer",
  "name": "{skill_name}",
  "content": "generated_code",
  "skipValue": "NONE"
}
```

If the AI set `skill_name` to `"NONE"`, the write is skipped without error.

### Write a shell script
```json
{
  "id": "skill_path",
  "type": "writeSkill",
  "skillset": "ops",
  "name": "deploy-staging",
  "content": "deploy_script",
  "extension": "sh"
}
```

## Notes

- Allowed extensions: `py`, `json`, `txt`, `sh` — any other extension is rejected
- Skills are executable artifacts, not documentation. For reference text, use `writeMemory`
- `listSkills` surfaces skills with tags derived from the filename — use descriptive hyphenated names (e.g. `auth-token-refresh.py`) for better discoverability
- Writing with the same name overwrites the existing file

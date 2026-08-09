# removeSkill

Deletes a skill file from a skill set directory.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the deleted file path under |
| `skillset` | yes | string | Skill set directory under `skills/` |
| `name` | yes | string | Filename without extension. Supports `{placeholder}` interpolation |
| `extension` | no | string | File extension. Defaults to `"py"` |

## How it works

Resolves `name` via `{placeholder}` interpolation, then deletes `skills/{skillset}/{name}.{extension}`. If the file doesn't exist, logs a message but does not fail. Always returns the target file path.

## Examples

### Remove a specific skill
```json
{
  "id": "removed",
  "type": "removeSkill",
  "skillset": "developer",
  "name": "old-scaffold",
  "extension": "py"
}
```

### Remove a skill chosen by the user
```json
{ "id": "skill_to_remove", "type": "humanDecision", "prompt": "Which skill should be deleted? (name only, no extension)" },
{
  "id": "removed",
  "type": "removeSkill",
  "skillset": "developer",
  "name": "{skill_to_remove}"
}
```

## Notes

- Deletion is immediate and permanent — no confirmation prompt is built in. Add a `humanDecision` gate before this action if the workflow is running in `--auto` mode
- If the file does not exist, the action still returns successfully (idempotent)

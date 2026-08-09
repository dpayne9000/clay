# writeMemory

Persists a string value to a named namespace in the memory store at `clay/memory/{namespace}/`. Each entry is saved as a JSON file, tagged for later retrieval by `searchMemory` or `readMemory`.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the returned entry ID under |
| `namespace` | yes | string | Directory namespace to write into (e.g. `developer`, `system-editor`) |
| `content` | yes | string | Key in `previous_data` holding the text content to save |
| `tagsKey` | no | string | Key in `previous_data` holding a comma-separated tag string. If absent, tags are auto-derived from content |
| `entryId` | no | string | Override the generated entry ID. If absent, ID is built from top tags + timestamp |
| `source` | no | string | Metadata field recorded in the JSON entry. Defaults to `"workflow"` |
| `skillset` | no | string | If set, also saves the content as a skill file in the named skillset |
| `skillExtension` | no | string | Extension for the dual-written skill file. Defaults to `"py"` |

## How it works

The content at `previous_data[content]` is written as a JSON object:

```json
{
  "id": "tag1-tag2-tag3-12345",
  "content": "...",
  "tags": ["tag1", "tag2", "tag3"],
  "created": "2026-03-16",
  "source": "workflow"
}
```

Tags are sourced from `tagsKey` if provided, otherwise auto-derived from the content using `deriveTags` (frequency + positional weighting, stopwords removed). The entry ID is `<top3-tags>-<timestamp_suffix>` unless overridden with `entryId`.

The action returns the entry ID so downstream steps can reference it.

## Examples

### Save AI output with auto-derived tags
```json
{
  "id": "memory_saved",
  "type": "writeMemory",
  "namespace": "developer",
  "content": "summary"
}
```

### Save with explicit tags from a previous step
```json
{
  "id": "memory_saved",
  "type": "writeMemory",
  "namespace": "developer",
  "content": "analysis",
  "tagsKey": "derived_tags"
}
```

`deriveTags` followed by `writeMemory` is a common pattern — run `deriveTags` on the content first, then pass the result via `tagsKey`.

### Save with a fixed entry ID (for updatable records)
```json
{
  "id": "memory_saved",
  "type": "writeMemory",
  "namespace": "project",
  "content": "status_report",
  "entryId": "current-status"
}
```

Writing the same `entryId` again overwrites the previous file.

### Dual-write: memory + skill
```json
{
  "id": "memory_saved",
  "type": "writeMemory",
  "namespace": "developer",
  "content": "generated_script",
  "skillset": "developer",
  "skillExtension": "py"
}
```

Saves the content as both a memory entry and a runnable skill file.

## Notes

- Memory is stored in `clay/memory/{namespace}/` — one `.json` file per entry
- If `content` key resolves to an empty string, the write is skipped
- Tags drive `searchMemory` — more specific tags improve retrieval quality
- Use `deriveTags` before `writeMemory` when content tags need to be reused elsewhere

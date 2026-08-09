# readMemory

Reads a single memory entry by its exact ID from a namespace. Returns the full formatted content including header, date, and tags.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the retrieved entry under |
| `namespace` | yes | string | Namespace to read from (e.g. `developer`, `project`) |
| `entryId` | yes | string | Exact ID of the entry to read |

## How it works

Looks up `memory/{namespace}/{entryId}.json` and returns the entry formatted as:

```
[entry-id]  2026-03-16  tags: tag1, tag2, tag3
Content text of the entry...
```

Returns an empty string if the file does not exist.

## Examples

### Read a known entry
```json
{
  "id": "entry_content",
  "type": "readMemory",
  "namespace": "developer",
  "entryId": "auth-design-notes-91234"
}
```

### Read an entry ID chosen by the user
```json
{ "id": "memory_index", "type": "listMemory", "namespace": "developer" },
{ "id": "chosen_id", "type": "humanDecision", "prompt": "Entries:\n{memory_index}\n\nEnter entry ID:" },
{ "id": "entry_content", "type": "readMemory", "namespace": "developer", "entryId": {"override": "chosen_id"} }
```

The `{"override": "chosen_id"}` resolves `entryId` to the string the user typed, not a literal.

### Read and inject into a prompt
```json
{ "id": "entry_content", "type": "readMemory", "namespace": "project", "entryId": "current-status" },
{ "id": "analysis", "type": "scramda2", "prompt": "Current status:\n{entry_content}\n\nWhat should we do next?" }
```

## Notes

- `entryId` is a literal string — it will not resolve `{placeholder}` syntax. Use `{"override": "key"}` to pass a dynamic value
- Entry IDs are available from `listMemory` or from the return value of `writeMemory`
- Returns empty string (not an error) when the entry is not found

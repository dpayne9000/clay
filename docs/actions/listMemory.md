# listMemory

Lists all entry IDs and their tags in a memory namespace. Returns a compact index, not the full entry content.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the listing under |
| `namespace` | yes | string | Namespace to list (e.g. `developer`, `project`) |

## How it works

All `.json` files in `memory/{namespace}/` are read. For each entry, one line is produced:

```
entry-id  [tags: tag1, tag2, tag3]
```

Entries with no tags show `[tags: —]`. The full listing is returned as a single newline-separated string.

Returns an empty string if the namespace does not exist or has no entries.

## Examples

### List all developer memory
```json
{ "id": "memory_index", "type": "listMemory", "namespace": "developer" }
```

### Show the index to the user
```json
{ "id": "memory_index", "type": "listMemory", "namespace": "developer" },
{ "id": "choice", "type": "humanDecision", "prompt": "Memory entries:\n{memory_index}\n\nWhich would you like to read?" }
```

### Use the index to guide a search
```json
{ "id": "memory_index", "type": "listMemory", "namespace": "developer" },
{ "id": "query", "type": "humanDecision", "prompt": "Available memory:\n{memory_index}\n\nWhat do you want to look up?" },
{ "id": "result", "type": "searchMemory", "namespace": "developer", "queryKey": "query" }
```

## Notes

- Returns tag index only — no content. Use `readMemory` or `searchMemory` to fetch content
- The entry IDs in the listing are valid values for `readMemory`'s `entryId` field
- Files are listed in alphabetical order (sorted by filename on disk)

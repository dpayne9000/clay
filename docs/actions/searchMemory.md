# searchMemory

Searches a memory namespace and returns the most relevant entries ranked by keyword match. Tag matches score 3× higher than content matches.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the retrieved text under |
| `namespace` | yes | string | Namespace to search (e.g. `developer`, `system-editor`) |
| `queryKey` | no | string | Key in `previous_data` holding the search query string |
| `query` | no | string | Inline query string. Used if `queryKey` is absent |
| `maxResults` | no | number | Maximum entries to return. Defaults to `5` |

One of `queryKey` or `query` should be provided. If neither is given, all entries are returned up to `maxResults`.

## How it works

Every JSON file in `memory/{namespace}/` is loaded and scored against the query. Scoring:

- Each query word found in tags: **+3 points**
- Each query word found in content: **+1 point**

Entries with a score of 0 are excluded. The top `maxResults` entries are returned, formatted as:

```
[entry-id]  2026-03-16  tags: tag1, tag2, tag3
Content text of the entry...

[entry-id-2]  2026-03-15  tags: other, tags
Another entry content...
```

If the namespace has no entries, an empty string is returned.

## Examples

### Search with a previous AI response as query
```json
{
  "id": "relevant_memory",
  "type": "searchMemory",
  "namespace": "developer",
  "queryKey": "user_input"
}
```

### Search with an inline query
```json
{
  "id": "auth_notes",
  "type": "searchMemory",
  "namespace": "project",
  "query": "authentication login session",
  "maxResults": 3
}
```

### Search and inject into a downstream prompt
```json
{ "id": "context", "type": "searchMemory", "namespace": "developer", "queryKey": "task" },
{ "id": "response", "type": "scramda2", "prompt": "Context:\n{context}\n\nTask: {task}" }
```

The retrieved memory text lands in `{context}` for the AI to use.

## Notes

- Query scoring is word-level, not semantic — use specific technical terms for best results
- Tag matches outweigh content matches 3:1, so well-tagged entries surface first
- Returns an empty string (not `null`) when no matches are found, making it safe to use in `{placeholder}` interpolation without breaking the workflow

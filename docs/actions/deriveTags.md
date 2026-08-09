# deriveTags

Extracts keyword tags from text using a frequency + positional scoring algorithm. No AI call required — runs entirely in Python.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the comma-separated tag string under |
| `contentKey` | no | string | Key in `previous_data` holding the main text to analyze |
| `content` | no | string | Inline fallback text if `contentKey` is absent or resolves to empty |
| `contextKey` | no | string | Key in `previous_data` for secondary/supporting text (weighted 40% vs main) |
| `maxTags` | no | number | Maximum tags to return. Defaults to `6` |

At least one of `contentKey` or `content` must produce a non-empty string.

## How it works

The algorithm:

1. Tokenises text (splits on whitespace, punctuation, hyphens, underscores, camelCase)
2. Removes stopwords and tokens shorter than 3 characters
3. Scores each unique token: positional decay rewards tokens that appear earlier (title/heading words matter more)
4. Returns the top `maxTags` tokens, joined as a comma-separated string

Secondary text from `contextKey` is included at 40% weight — useful for letting surrounding context influence tags without overriding the primary content.

## Examples

### Auto-tag a summary before saving to memory
```json
{ "id": "summary", "type": "scramda2", "prompt": "Summarize the findings." },
{ "id": "tags", "type": "deriveTags", "contentKey": "summary" },
{ "id": "saved", "type": "writeMemory", "namespace": "research", "content": "summary", "tagsKey": "tags" }
```

The `deriveTags` → `writeMemory` pattern ensures tags reflect the actual content.

### Tag content with context boost
```json
{
  "id": "tags",
  "type": "deriveTags",
  "contentKey": "article_body",
  "contextKey": "article_title",
  "maxTags": 8
}
```

The title words score at 40% on top of the body analysis, nudging important terms up the ranking.

### Inline content tagging
```json
{
  "id": "tags",
  "type": "deriveTags",
  "content": "Express.js REST API with JWT authentication and MongoDB",
  "maxTags": 5
}
```

Returns something like: `express, rest, authentication, mongodb, jwt`

## Notes

- camelCase identifiers are split: `writeMemory` → `write`, `memory`
- Hyphenated names are split: `auth-token-refresh` → `auth`, `token`, `refresh`
- Output is a comma-separated string (e.g. `"express, api, auth, mongodb"`) suitable for the `tagsKey` field of `writeMemory`
- `deriveTags` is also used internally by `writeMemory` (when `tagsKey` is not provided) and by `searchSkills` (to extract keywords from the query)

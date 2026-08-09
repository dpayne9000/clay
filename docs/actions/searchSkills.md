# searchSkills

Searches a skill set by keyword relevance. Skills are ranked by how many query keywords appear in the filename.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the results under |
| `skillset` | yes | string | Subdirectory under `skills/` to search |
| `queryKey` | no | string | Key in `previous_data` holding the search query |
| `query` | no | string | Inline query string. Used if `queryKey` is absent |

One of `queryKey` or `query` should be provided. If neither is given, all files in the skillset are returned unsorted.

## How it works

The query is run through `derive_tags` to extract keywords. Each skill filename is split on hyphens/underscores and scored by the number of keywords that overlap. Files with zero overlap are excluded. Results are returned as a newline-separated list of matched filenames, ranked best-first.

## Examples

### Find skills relevant to a user task
```json
{
  "id": "relevant_skills",
  "type": "searchSkills",
  "skillset": "developer",
  "queryKey": "user_input"
}
```

### Search with an inline query
```json
{
  "id": "relevant_skills",
  "type": "searchSkills",
  "skillset": "developer",
  "query": "authentication session token"
}
```

### Full pattern: search → select → run
```json
{ "id": "task", "type": "humanDecision", "prompt": "What do you want to do?" },
{ "id": "relevant_skills", "type": "searchSkills", "skillset": "developer", "queryKey": "task" },
{ "id": "skill_choice", "type": "scramda2", "prompt": "Relevant skills:\n{relevant_skills}\n\nTask: {task}\n\nWhich skill file should we run, or NONE?" },
{ "id": "run_result", "type": "humanShell", "command": "python3 skills/developer/{skill_choice}", "skipValue": "NONE" }
```

## Notes

- Scoring is purely filename-based — skills with descriptive hyphenated names (e.g. `express-api-scaffold.py`) surface much better than vague names like `script1.py`
- Returns filenames only, no content. Pass the filename to `runCode` or `humanShell` to execute
- Returns all files unsorted when no query is provided, equivalent to `listSkills` output without tags

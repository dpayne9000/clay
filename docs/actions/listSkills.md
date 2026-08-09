# listSkills

Lists all files in a skill set directory, with tags derived from each filename.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the listing under |
| `skillset` | yes | string | Subdirectory under `skills/` to list (e.g. `developer`) |

## How it works

Lists all non-hidden files in `skills/{skillset}/`, sorted alphabetically. For each file, tags are derived by splitting the filename on hyphens, underscores, and dots, then filtering stopwords. Output format:

```
express-app-scaffold.py  [tags: express, app, scaffold]
auth-token-refresh.py  [tags: auth, token, refresh]
deploy-staging.sh  [tags: deploy, staging]
```

Returns an empty string if the skillset directory does not exist.

## Examples

### List available skills
```json
{ "id": "skills_index", "type": "listSkills", "skillset": "developer" }
```

### Show to the user for selection
```json
{ "id": "skills_index", "type": "listSkills", "skillset": "developer" },
{ "id": "skill_choice", "type": "humanDecision", "prompt": "Available skills:\n{skills_index}\n\nWhich skill should we run?" }
```

### Guide a search with the index
```json
{ "id": "skills_index", "type": "listSkills", "skillset": "developer" },
{ "id": "task", "type": "humanDecision", "prompt": "What do you want to build?" },
{ "id": "relevant_skills", "type": "searchSkills", "skillset": "developer", "queryKey": "task" }
```

## Notes

- Tags come from the filename, not the file content — name skills descriptively
- Returns a flat list (filename + tags), not content. To run a skill, pass its filename to `runCode` or `humanShell`
- Use `searchSkills` when you need relevance-ranked results rather than the full list

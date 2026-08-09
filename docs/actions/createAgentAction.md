# createAgentAction

Writes a new Python action module to the `actions/agent/` directory, making it available as a new action type in future workflow runs. This is the platform's self-extension mechanism.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the created file path under |
| `actionName` | yes | string | Name for the action in kebab-case or snake_case (e.g. `dns-resolver`). Must match `[a-z][a-z0-9_-]{1,39}` |
| `content` | yes | string | Key in `previous_data` holding the Python source code for the new action module |

## How it works

`actionName` is normalized (hyphens → underscores) and `_actions.py` is appended to form the filename. The source from `previous_data[content]` is written to `clay/actions/agent/{actionName}_actions.py`. Returns the created file path.

**The new action is not registered automatically** — a developer must add a dispatch branch in `runWorkflow.py` to wire it up. This is intentional: new action types require code review before becoming active.

## Examples

### Generate and write a new action from AI
```json
{ "id": "user_request", "type": "humanDecision", "prompt": "Describe the new action you want to create:" },
{
  "id": "action_code",
  "type": "scramda2",
  "prompt": "Write a Python action module for: {user_request}\n\nThe module must have a handler(action, previous_data) function that returns {\"id\": action.get(\"id\"), \"data\": result}."
},
{ "id": "action_name", "type": "scramda2", "prompt": "Give this action a kebab-case name (e.g. dns-resolver):" },
{
  "id": "created_path",
  "type": "createAgentAction",
  "actionName": {"override": "action_name"},
  "content": "action_code"
}
```

### Write a specific action inline
```json
{
  "id": "created_path",
  "type": "createAgentAction",
  "actionName": "csv-parser",
  "content": "csv_module_source"
}
```

Results in `clay/actions/agent/csv_parser_actions.py`.

## Notes

- `actionName` validation rejects path traversal attempts (`../`, absolute paths, spaces)
- The module is written as plain text — if the AI wraps the code in markdown fences, use `writeCode` first to strip them, then use `createAgentAction` with the cleaned content
- After creating the module, update `runWorkflow.py` to add the dispatch branch and `cli.py` to register the type name
- This action is intended for use by the system-editor workflow and developer agents building new capabilities

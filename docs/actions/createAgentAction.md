# createAgentAction

Writes reviewed Python source to the user's Clay action directory.

## Fields

| Field | Required | Type | Description |
|---|---:|---|---|
| `id` | yes | string | Result key for the written path |
| `actionName` | yes | string | Name matching `[a-z][a-z0-9_-]{1,39}` |
| `content` | yes | string | Context key containing Python source |

The action validates the name, compiles the source to catch syntax errors,
asks through the `fileWrites` gate, and writes
`~/.clay/actions/<normalized_name>_actions.py`.

Writing the file does not load or register it. Clay discovers built-in action
modules under `clay.actions`; user action loading is not currently implemented.
Treat the output as generated source for review, not as an active extension.

# humanDecision

Presents a prompt to the human and waits for typed input. In `--auto` mode, the AI answers instead using the full accumulated context.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the response under |
| `prompt` | yes | string | Text shown to the human. Supports `{placeholder}` interpolation |

## How it works

In normal mode the prompt is printed and the workflow pauses until the human types a response and hits enter. Whatever they type is stored under `id`.

In `--auto` mode the call is forwarded to the AI with:
- The `autoContext` string from the workflow (if set)
- Every key in `previous_data` serialised as `key: value` (truncated at 200 chars each)
- The resolved prompt

This makes `humanDecision` the primary human gate — place it before any destructive or expensive step to require explicit approval before proceeding.

## Examples

### Simple input gate
```json
{ "id": "topic", "type": "humanDecision", "prompt": "What should I research?" }
```

### Approval gate before a build step
```json
{
  "id": "approved",
  "type": "humanDecision",
  "prompt": "────────────────────────\nPlan:\n{plan}\n────────────────────────\nType APPROVE to continue or describe changes:"
}
```

### Collecting structured input across multiple steps
```json
{ "id": "name",     "type": "humanDecision", "prompt": "Your name:" },
{ "id": "role",     "type": "humanDecision", "prompt": "Your role:" },
{ "id": "goal",     "type": "humanDecision", "prompt": "What do you want to build?" }
```

Each response is stored separately and can be referenced as `{name}`, `{role}`, `{goal}` in downstream prompts.

## Notes

- In web/API mode the prompt is emitted as a JSON marker on stdout and the response is read back from stdin — the frontend handles the exchange
- The human's response is always stored as a plain string
- There is no validation — downstream actions should handle unexpected input gracefully

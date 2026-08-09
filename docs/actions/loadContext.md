# loadContext

Reads a JSON file and merges all its top-level keys directly into the workflow context. Used to inject configuration, training data, or external state at the start of a workflow.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Stored but not meaningful — all keys merge into context directly |
| `file` | yes | string | Path to a JSON file containing a top-level object |

## How it works

The JSON file must contain a single object at the top level. Each key is merged directly into `previous_data`, making them available as `{placeholder}` values and `{"override": "key"}` references for all downstream actions.

This is different from every other action — instead of storing a single value under `id`, it unpacks multiple keys into the context at once.

## Examples

### Load training examples for a scramda2 call
```json
{ "id": "_", "type": "loadContext", "file": "training/fewshot.json" },
{
  "id": "result",
  "type": "scramda2",
  "prompt": "Classify this: {input}",
  "examples": {"override": "training_examples"}
}
```

`fewshot.json`:
```json
{
  "training_examples": [
    {"input": "buy now", "output": "spam"},
    {"input": "meeting at 3pm", "output": "calendar"}
  ]
}
```

The `{"override": "training_examples"}` pattern resolves the `examples` field to the loaded array — this is the canonical way to inject training data.

### Load environment config
```json
{ "id": "_", "type": "loadContext", "file": "config/env.json" }
```

`env.json`:
```json
{
  "api_base": "https://api.example.com",
  "api_key": "sk-...",
  "environment": "staging"
}
```

All three keys become available as `{api_base}`, `{api_key}`, `{environment}` in downstream actions.

### Load user profile at workflow boot
```json
{
  "actionSets": {
    "boot": [
      { "id": "_", "type": "loadContext", "file": "config/user.json" },
      { "id": "greeting", "type": "scramda2", "prompt": "Hello {user_name}! How can I help?" }
    ]
  }
}
```

## Notes

- The file must be a JSON object `{}` — arrays and primitives at the top level are rejected
- Keys from the file overwrite any existing keys in `previous_data` with the same name
- `loadContext` is typically used in the first step of a workflow. For values set at workflow start, use `defaults` in the workflow JSON instead
- The `id` field is required but ignored for merging purposes. Convention is to use `"_"` as a placeholder

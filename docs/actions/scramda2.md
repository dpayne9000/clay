# scramda2

Sends a prompt to a local OpenAI-compatible model server (via the bundled **Gopher** adapter, `clay/adapters/gopher.py`) and returns the response as text. The primary way workflows invoke the AI.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the response under |
| `prompt` | yes | string | The prompt. Supports `{placeholder}` interpolation from context |
| `examples` | no | array | Few-shot examples as `[{"question": "...", "answer": "..."}]` |
| `model` | no | string | Literal model ID to use for this call |
| `modelProfile` | no | string | Named alias resolved from `config.models[modelProfile]`. Takes precedence over `model` if both are set |
| `max_tokens` | no | int | Cap on response length. Overrides `config.json`'s `maxTokens` default |

## Placeholder interpolation

Any `{key}` in `prompt` is replaced with the matching value from the workflow context before the call is made. Unresolved placeholders are left as-is.

```json
{
  "id": "summary",
  "type": "scramda2",
  "prompt": "Summarise this in 3 bullets:\n{research}"
}
```

## Training injection

Training examples loaded via `loadContext` can be appended inline to the prompt, or bound directly to the `examples` field using `override`:

```json
{
  "id": "result",
  "type": "scramda2",
  "prompt": "Generate queries for {topic}\n\n{training_generate_queries}"
}
```

```json
{
  "id": "result",
  "type": "scramda2",
  "prompt": "Generate queries for {topic}",
  "examples": { "override": "my_loaded_examples" }
}
```

The first approach appends the training text inline to the prompt. The second binds a loaded array directly to the `examples` field via the `override` mechanism.

## Examples

### Basic call
```json
{
  "id": "draft",
  "type": "scramda2",
  "prompt": "Write a one-paragraph summary of {topic} for {audience}."
}
```

### Collecting user input to fill prompt variables

Use `humanDecision` steps before the `scramda2` call to populate the placeholders:

```json
{ "id": "topic",    "type": "humanDecision", "prompt": "What topic should the report cover?" },
{ "id": "audience", "type": "humanDecision", "prompt": "Who is the target audience?" },
{
  "id": "draft",
  "type": "scramda2",
  "prompt": "Write a report on {topic} for {audience}."
}
```

`{topic}` and `{audience}` resolve to whatever the user typed.

### Injecting training examples via override

Load a training file at boot with `loadContext`, then bind it to `examples`:

```json
{ "id": "_training", "type": "loadContext", "file": "workflows/myapp/training.json" }
```

`training.json`:
```json
{
  "query_examples": [
    { "question": "Generate queries for: climate change", "answer": "1. What are current CO2 levels?\n2. Which countries emit the most carbon?" }
  ]
}
```

Then in the action:
```json
{
  "id": "queries",
  "type": "scramda2",
  "prompt": "Generate 5 research queries for: {topic}",
  "examples": { "override": "query_examples" }
}
```

The `override` replaces the `examples` field at runtime with the loaded array — no hardcoding in the workflow JSON.

### Inline training text in the prompt

Alternatively, store training as a raw `Example\nInput:...\nOutput:...` string and append it directly to the prompt:

`training.json`:
```json
{
  "training_queries": "Example\nInput: Generate queries for: climate change\nOutput: 1. What are current CO2 levels?\n2. Which countries emit the most carbon?"
}
```

```json
{
  "id": "queries",
  "type": "scramda2",
  "prompt": "Generate 5 research queries for: {topic}\n\n{training_queries}"
}
```

### With model and token override
```json
{
  "id": "spec",
  "type": "scramda2",
  "prompt": "Write a detailed technical spec for {feature}",
  "model": "claude-opus-4-6",
  "max_tokens": 4000
}
```

### With modelProfile — named model alias from config
```json
{ "id": "_", "type": "loadContext", "file": "config/models.json" },
{
  "id": "spec",
  "type": "scramda2",
  "prompt": "Write a detailed technical spec for {feature}",
  "modelProfile": "heavy"
}
```

`config/models.json`:
```json
{
  "models": {
    "fast":  "claude-haiku-4-5-20251001",
    "heavy": "claude-opus-4-6"
  }
}
```

`modelProfile: "heavy"` resolves to `"claude-opus-4-6"` via the loaded map. This lets you change model assignments in one config file rather than editing every workflow step.

## Model resolution

Each call resolves its model in priority order:

1. **`modelProfile`** — looked up in `config.models[modelProfile]`, else
2. **`model`** — a literal model id on the action, else
3. **fallback** — `config.models["default"]`.

`config.models` comes from the engine-seeded `__config__` when the action
receives it, otherwise from `configs/default.json` directly via
`clay/lib/config.py`. This means the **default model always resolves**, even
for actions that filter their context with `includedData` (which would
otherwise strip `__config__`). An unknown `modelProfile` falls through to
`model`, then to the default — it is not passed through as a literal id.

## Notes

- Model server URL defaults to `http://127.0.0.1:8080`, overridable via the `GOPHER_URL` environment variable
- Retries up to 10 times on connection/timeout failure, 5 seconds between attempts, then returns an error result
- Returns `null` if `prompt` is empty — always provide a prompt

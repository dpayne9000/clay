# workflow

Executes another workflow JSON file and stores its complete final context under
the workflow action's `id`.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the sub-workflow's output under. If absent, the result is discarded |
| `file` | yes | string | Path to the workflow JSON file to run |
| `includedData` | no | array | Parent-context values passed into the sub-workflow. When absent, the complete accumulated parent context is passed |
| `outputKey` | no | string | Compatibility field currently ignored; the complete sub-workflow context is stored |

## How it works

The dispatcher applies `includedData` before invoking the sub-workflow. When
the field is absent, the complete accumulated parent context is passed. When it
is present, only its named values are passed.

The complete final sub-workflow context is stored under `id`; it is not
flattened into the parent. Downstream actions select a child value with a
dictionary dot path such as `research_result.summary`.

`outputKey` currently has no runtime effect. It is accepted for compatibility
with existing workflow files.

## Examples

### Delegate to a sub-workflow and capture its output
```json
{
  "id": "research_result",
  "type": "workflow",
  "file": "workflows/research/main.json",
  "includedData": ["topic"]
}
```

Use one child value downstream:

```json
{
  "id": "draft",
  "type": "scramda2",
  "prompt": "Draft from {summary}",
  "includedData": ["summary=research_result.summary"]
}
```

### Chain multiple sub-workflows
```json
{ "id": "draft", "type": "workflow", "file": "workflows/draft.json" },
{ "id": "review", "type": "workflow", "file": "workflows/review.json", "includedData": ["draft"] },
{ "id": "final", "type": "workflow", "file": "workflows/finalize.json", "includedData": ["review"] }
```

The first sub-workflow receives the full accumulated context because it omits
`includedData`. The later calls explicitly receive only their named inputs.

### Use a sub-workflow as a reusable helper
```json
{
  "id": "validated_input",
  "type": "workflow",
  "file": "workflows/helpers/validate-input.json",
  "includedData": ["raw_input"]
}
```

Sub-workflows are the primary reuse mechanism — extract repeated multi-step patterns into their own workflow files.

## Notes

- For repeated execution, use `loop` instead
- `outputKey` does not extract or discard any child values
- The parent workflow's `autoContext` propagates into the sub-workflow. A
  sub-workflow's own `autoContext` is appended after the inherited instructions
  so both apply
- Engine-seeded `__config__`, `__schema__`, and `__workflow_template__` values
  are reseeded into the sub-workflow even when this action's `includedData`
  filters ordinary parent variables
- Cycle detection currently warns but does not refuse recursion; see F-07

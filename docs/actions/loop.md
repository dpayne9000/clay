# loop

Runs a sub-workflow repeatedly. Each iteration receives the immediately
previous iteration's complete context, and the loop stores the complete final
iteration context under its `id`.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the final iteration's output under |
| `file` | yes | string | Path to the sub-workflow JSON file to execute each iteration |
| `iterations` | no | number | Maximum number of iterations. `0` or absent = infinite |
| `continueKey` | no | string | Key in the sub-workflow's output to check for a stop signal |
| `outputKey` | no | string | Key whose value is previewed in the run log after each iteration. It does not change stored context |
| `includedData` | no | array | Parent-context values passed into the loop. When absent, the complete accumulated parent context is passed |
| `merge` | no | boolean | If true, shallowly publish the final iteration context into the parent instead of nesting it under `id` |

If `iterations` is `0` or absent, `continueKey` is required — without it, a safety cap of 1000 iterations is applied.

## How it works

Each iteration of the sub-workflow receives:
- The loop action's input context: all accumulated parent context when
  `includedData` is absent, or only the explicitly selected values
- The complete result from the immediately previous iteration, overlaid on the
  parent input
- `iteration`: the current iteration number as a string (`"1"`, `"2"`, ...)

After each iteration, the value at `outputKey` may be previewed in the run log.
It is not added to executable context as `loop_history`.

If `continueKey` is set and the sub-workflow returns a false-like value for
that key (`false`, `done`, `0`, `no`, `stop`, or empty string), the loop stops
early.

The complete final iteration context is stored under the loop action's `id`.
Downstream actions reference a child action as `loop_id.action_id` in
`includedData`.

## Examples

### Fixed iterations — research pipeline
```json
{
  "id": "research_output",
  "type": "loop",
  "file": "workflows/research/iteration.json",
  "iterations": 5,
  "includedData": ["topic"]
}
```

Use the final iteration's summary downstream:

```json
{
  "includedData": ["summary=research_output.iteration_summary"]
}
```

### Infinite loop with user-controlled stop
```json
{
  "id": "session_output",
  "type": "loop",
  "file": "workflows/chatbot/iteration.json",
  "continueKey": "keep_going"
}
```

The sub-workflow must return a key `keep_going`. When it returns `"false"`, `"done"`, `"stop"`, etc., the loop ends.

### AI decides whether to continue
Inside the sub-workflow, a `scramda2` step evaluates whether to continue:

```json
{
  "id": "keep_going",
  "type": "scramda2",
  "prompt": "User said: {user_input}\n\nShould we continue? Reply 'true' to continue or 'false' to stop."
}
```

### Refer to the previous iteration
The complete previous iteration result is overlaid into the next iteration, so
the same action ids are directly available:

```json
{
  "id": "analysis",
  "type": "scramda2",
  "prompt": "Previous response: {response}\nIteration {iteration}: analyze {current_target}",
  "includedData": ["response", "iteration", "current_target"]
}
```

## Notes

- Earlier iterations are not retained in executable context; only the
  immediately previous result is carried forward
- Omitting `includedData` passes the entire accumulated parent context
- `outputKey` is log-only; `continueKey` controls termination
- Parent `autoContext` and engine-seeded config/schema/template values propagate
  into every iteration; an iteration workflow's own `autoContext` is appended
  after the inherited instructions
- Use `workflow` for a single sub-workflow invocation; use `loop` when you need repeated execution

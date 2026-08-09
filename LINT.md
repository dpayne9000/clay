# clay lint

Static analysis for workflow and data JSON files. Catches schema errors, broken references, and structural problems before you run anything.

```bash
python clay.py lint                          # lint your workflow folder ($CLAY_HOME/workflows)
python clay.py lint templates research       # lint one workflow, named as segments
python clay.py lint ./scratch/shell.json     # an existing path on disk wins over a name
python clay.py lint --verbose                # show clean files too
```

Exit code `0` = all clean. Exit code `1` = one or more errors.

---

## What it checks

The linter auto-detects each file's role from its structure and applies the appropriate rules.

### Role detection

| Role | Condition | Example files |
|---|---|---|
| `workflow` | Has `workflow` + `actionSets` keys | `main.json`, `iteration.json` |
| `data` | Everything else | `goal.json`, `training.json`, `context.json` |

No markers or naming conventions required — the shape of the JSON determines the role.

---

### Workflow checks

**Structure**
- Every step listed in `workflow.steps` has a matching key in `actionSets` — error if missing
- Every key in `actionSets` is referenced in `workflow.steps` — warning if orphaned (dead action set)
- `workflow.steps` is not empty — warning if it is

**Actions**
- Every action has a `type` field — error if missing
- Action `type` is a known registered type — warning if unknown (allows forward-compatible workflows)
- Every required field for the action type is present — error if missing (validated against the schema registry)

**File references**
- Actions with a `file` field (`workflow`, `loop`, `loadContext`) reference a path that exists on disk — warning if not found

### Data checks

- Top-level value is a JSON object — error if not
- Top-level values are not nested objects — warning if they are (usually means a workflow accidentally saved as a data file)

---

## Output format

```
✗  dev/developer/main.json  [workflow ]
   ✗ [build][2] 'shell' missing required field 'command'
   △ actionSet 'debug' is not referenced in workflow.steps

△  templates/chatbot/training.json  [data    ]
   △ key 'examples' is a nested object — did you mean this to be a workflow?

────────────────────────────────────────────────────
  48 files  ·  46 clean  ·  2 with errors
  2 data  ·  1 invalid  ·  45 workflow
```

- `✗` error — the workflow will fail or behave incorrectly
- `△` warning — suspicious but may be intentional
- `✓` clean (shown with `--verbose`)

---

## Schema registry

Action field requirements come from `clay/actions/registry.py` — the single source of truth for all action types. Adding a new action type there automatically makes `lint` aware of it.

To inspect the schema for a specific action type:

```bash
python -m clay.actions.registry shell        # JSON Schema for one type
python -m clay.actions.registry              # combined schema for all types
```

---

## Running in CI

```bash
cd clay
python clay.py lint clay/data/workflows/
echo "Exit: $?"
```

The linter imports nothing from the AI service and requires no environment variables — it runs fully offline.

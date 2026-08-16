# Action registry

`clay/actions/registry.py` is the source of truth for action schemas and
handlers.

## Registration

Each action module declares a schema and handler:

```python
@action('example')
class Example:
    id: str = req('Result key')
    value: str = opt('Optional value', '')

@handler_for('example')
def handler(action, ctx):
    return {'id': action['id'], 'data': action.get('value', '')}
```

`discover()` imports every module below `clay.actions` in stable sorted order.
There is no dispatcher `if/elif` list to update. `handler_for_type()` returns
the registered callable.

## Validation and schema export

- `validate(action)` reports missing required fields.
- Unknown action types are reported by the dispatcher.
- `schema(type_name)` returns one action's JSON Schema.
- `all_schemas()` returns the combined schema.
- `export_json()` serializes that schema.
- `export=False` hides an action or field from exported schema.
- `skeleton=False` hides an action or field from generated workflow skeletons.

Universal fields such as `outputKey`, `visible`, `when`, and `whenNot` are
defined once in the combined schema instead of repeated for every action.

`outputKey` is a secondary storage alias. After a normal action returns, the
engine stores the identical result under both `id` and `outputKey`. It does not
rename the result, remove `id`, or extract a nested field. Actions returning
`merge: true` flatten their dictionary instead and create neither storage key.

Run `clay build` in a source checkout to rebuild generated schema artifacts.
Run `clay docs` to rebuild the HTML and JSON action reference.

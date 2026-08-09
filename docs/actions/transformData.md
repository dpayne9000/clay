# transformData

Applies a built-in transformation to a value in `previous_data`. Currently supports two methods: multiplying list items by a factor, and splitting text into a line-indexed dictionary.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the transformed output under |
| `source` | yes | string | Key in `previous_data` holding the data to transform |
| `method` | yes | string | Transformation to apply: `map` or `parseLines` |

## Methods

### `parseLines`
Splits a string on newlines and returns a dictionary mapping 1-based line numbers to line strings.

Input: `"alpha\nbeta\ngamma"`
Output: `{1: "alpha", 2: "beta", 3: "gamma"}`

### `map`
Multiplies each item in a list by a factor of 2. (This is a basic placeholder method.)

## Examples

### Split a multi-line AI response into indexed lines
```json
{ "id": "ai_output", "type": "scramda2", "prompt": "List 5 ideas, one per line." },
{
  "id": "ideas_dict",
  "type": "transformData",
  "source": "ai_output",
  "method": "parseLines"
}
```

`ideas_dict` becomes `{1: "First idea", 2: "Second idea", ...}`.

## Notes

- `transformData` has a small built-in method set — it is not a general-purpose data processor
- For complex transformations, use `python` (inline `exec`-based execution) or `runCode` (subprocess)
- `parseLines` is the most practically useful method for splitting AI-generated lists into indexable structures

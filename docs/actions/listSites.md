# listSites

Lists all saved web site profiles in `clay/webactions/`.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the listing under |

## How it works

Lists all `.json` files in the `webactions/` directory, alphabetically sorted. Returns a newline-separated list of filenames. Returns an empty string if the directory does not exist or is empty.

Site profiles are created by `browseWeb` when the `siteKey` field is set.

## Examples

### List saved sites
```json
{ "id": "saved_sites", "type": "listSites" }
```

### Show sites to the user and load one
```json
{ "id": "saved_sites", "type": "listSites" },
{ "id": "site_choice", "type": "humanDecision", "prompt": "Saved sites:\n{saved_sites}\n\nWhich site key to load?" },
{ "id": "site_data", "type": "loadSite", "siteKey": {"override": "site_choice"} }
```

## Notes

- Returns filenames including `.json` extension (e.g. `example-api-status.json`)
- The `siteKey` for `loadSite` is the filename without `.json` (e.g. `example-api-status`)
- Site profiles contain the URL and a 500-character content preview, not the full page

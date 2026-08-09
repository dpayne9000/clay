# loadSite

Loads a previously saved web site profile from `clay/webactions/`. Returns the stored URL and content preview without making a network request.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the site profile JSON under |
| `siteKey` | yes | string | Name of the saved site (filename without `.json`) |

## How it works

Reads `webactions/{siteKey}.json` and returns its contents as a formatted JSON string. Returns an empty string if the file does not exist. Site profiles are created by `browseWeb` when its `siteKey` field is set.

A saved profile contains at minimum:
```json
{
  "url": "https://example.com/page",
  "preview": "First 500 chars of extracted page text..."
}
```

## Examples

### Load a known saved profile
```json
{
  "id": "api_docs",
  "type": "loadSite",
  "siteKey": "example-api-docs"
}
```

### Load a profile chosen at runtime
```json
{ "id": "saved_sites", "type": "listSites" },
{ "id": "site_key", "type": "humanDecision", "prompt": "Saved sites:\n{saved_sites}\n\nEnter site key:" },
{ "id": "site_data", "type": "loadSite", "siteKey": {"override": "site_key"} }
```

### Save then load pattern
```json
{ "id": "page", "type": "browseWeb", "url": "https://example.com", "siteKey": "example-home" },
{ "id": "cached", "type": "loadSite", "siteKey": "example-home" }
```

## Notes

- `loadSite` returns a snapshot — it does not re-fetch the page. Use `browseWeb` with the same `siteKey` to update the profile
- The preview is capped at 500 characters by `browseWeb` — it is a reference point, not the full content
- `siteKey` is a literal string. Use `{"override": "key"}` to load a dynamically determined site key

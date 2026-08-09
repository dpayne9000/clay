# browseWeb

Fetches a URL, strips HTML tags, and returns the visible text content. Optionally saves a site profile for later retrieval via `loadSite`.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the extracted page text under |
| `url` | yes | string | URL to fetch. Supports `{placeholder}` interpolation. Must be `http://` or `https://` |
| `maxChars` | no | number | Maximum characters of text to return. Defaults to `4000` |
| `siteKey` | no | string | If set, saves the URL and a 500-char preview to `webactions/{siteKey}.json` |

## How it works

Fetches the URL with a 15-second timeout using `clay/1.0` as the User-Agent. For HTML responses, script/style/head tags are stripped and visible text is extracted. Non-HTML responses are returned as raw text. Output is truncated at `maxChars` with a notice appended.

Only `http` and `https` schemes are allowed. `file://`, `ftp://`, and internal schemes are rejected.

## Examples

### Fetch a page
```json
{
  "id": "page_content",
  "type": "browseWeb",
  "url": "https://example.com/docs"
}
```

### Use a URL from previous output
```json
{ "id": "search_results", "type": "searchWeb", "query": "Python asyncio tutorial" },
{ "id": "page_text", "type": "browseWeb", "url": "{first_url}", "maxChars": 8000 }
```

### Save a site profile for reuse
```json
{
  "id": "page_content",
  "type": "browseWeb",
  "url": "https://api.example.com/status",
  "siteKey": "example-api-status"
}
```

The profile is saved and can be retrieved later without re-fetching:
```json
{ "id": "cached_content", "type": "loadSite", "siteKey": "example-api-status" }
```

## Notes

- HTML extraction preserves text but loses structure (tables, lists become flat text)
- Use `maxChars` to control context size — large pages can exceed model token limits
- Errors (network failure, timeout) are returned as `[error: ...]` strings rather than failing the workflow
- For structured API responses, prefer the `API` action which handles JSON natively

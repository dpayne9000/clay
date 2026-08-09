# searchWeb

Searches the web and returns a numbered list of results (title, URL, snippet). Supports DuckDuckGo (no key required), Google Custom Search, and Bing.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the formatted result list under |
| `query` | no | string | Search query string. Supports `{placeholder}` interpolation |
| `queryKey` | no | string | Key in `previous_data` holding the query. Takes precedence over `query` |
| `engine` | no | string | `duckduckgo` (default), `google`, or `bing` |
| `maxResults` | no | number | Maximum results to return. Defaults to `5` |
| `apiKey` | no | string | Required for `google` and `bing` engines |
| `cx` | no | string | Custom Search Engine ID. Required for `google` engine |

One of `query` or `queryKey` is required.

## Output format

```
1. Page Title Here
   https://example.com/page
   Brief snippet of text from the page...

2. Another Result
   https://other.com
   Another snippet...
```

## Examples

### Search with DuckDuckGo (no API key)
```json
{
  "id": "search_results",
  "type": "searchWeb",
  "query": "Python asyncio best practices",
  "maxResults": 5
}
```

### Search using input from previous step
```json
{ "id": "user_query", "type": "humanDecision", "prompt": "What should I research?" },
{ "id": "search_results", "type": "searchWeb", "queryKey": "user_query", "maxResults": 8 }
```

### Search and browse the top result
```json
{ "id": "results", "type": "searchWeb", "query": "openai function calling docs" },
{ "id": "best_url", "type": "scramda2", "prompt": "Results:\n{results}\n\nWhich URL is most relevant? Return just the URL." },
{ "id": "page_text", "type": "browseWeb", "url": "{best_url}" }
```

### Use Google Custom Search
```json
{
  "id": "search_results",
  "type": "searchWeb",
  "query": "site:docs.example.com {topic}",
  "engine": "google",
  "apiKey": "YOUR_GOOGLE_API_KEY",
  "cx": "YOUR_SEARCH_ENGINE_ID",
  "maxResults": 10
}
```

### Use Bing
```json
{
  "id": "search_results",
  "type": "searchWeb",
  "queryKey": "research_topic",
  "engine": "bing",
  "apiKey": "YOUR_BING_API_KEY"
}
```

## Notes

- DuckDuckGo uses the Instant Answers API — works best for well-known topics; may return fewer results for obscure queries
- Google and Bing require API keys stored in the workflow JSON or loaded via `loadContext`
- Errors are returned as `[error: ...]` strings rather than failing the workflow
- Follow up `searchWeb` with `browseWeb` to fetch full page content from a specific result

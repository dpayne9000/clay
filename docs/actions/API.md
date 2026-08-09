# API

Makes an HTTP request to an external API endpoint and returns the response body. Supports GET, POST, PUT, PATCH, and DELETE.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the response under |
| `endpoint` | yes | string | Full URL of the API endpoint |
| `method` | no | string | HTTP method: `get` (default), `post`, `put`, `patch`, `delete` |
| `params` | no | object | URL query parameters as a JSON object |
| `headers` | no | object | HTTP headers as a JSON object |
| `data` | no | object | Request body, sent as JSON |

## How it works

Uses the `requests` library to call the endpoint. If the response body is valid JSON, it is returned as a parsed object. Otherwise the raw text is returned. HTTP errors and network failures return an error string rather than failing the workflow.

## Examples

### GET request
```json
{
  "id": "weather",
  "type": "API",
  "endpoint": "https://api.openweathermap.org/data/2.5/weather",
  "params": { "q": "London", "appid": "YOUR_API_KEY" }
}
```

### POST with JSON body and auth header
```json
{
  "id": "api_response",
  "type": "API",
  "endpoint": "https://api.example.com/v1/items",
  "method": "post",
  "headers": { "Authorization": "Bearer YOUR_TOKEN", "Content-Type": "application/json" },
  "data": { "name": "new item", "active": true }
}
```

### Load credentials via loadContext then call the API
```json
{ "id": "_", "type": "loadContext", "file": "config/api-keys.json" },
{
  "id": "response",
  "type": "API",
  "endpoint": "https://api.example.com/data",
  "headers": { "Authorization": "Bearer {api_key}" }
}
```

Note: `{placeholder}` interpolation is not applied to `headers`, `params`, or `data` — these are plain JSON objects. Load values into context first and use the `{"override": "key"}` mechanism if you need dynamic values in these fields.

## Notes

- `params`, `headers`, and `data` are static JSON objects defined in the workflow file. For dynamic values in these fields, use `{"override": "key"}` to substitute from `previous_data`
- The response is stored as a Python dict/list (if JSON) or a string (if not JSON)
- Uses the `requests` library — must be installed in the environment

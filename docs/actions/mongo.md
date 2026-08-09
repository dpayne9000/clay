# mongo

Retrieves all documents from a MongoDB collection and returns them as a list.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the retrieved documents under |
| `url` | yes | string | MongoDB connection URI (e.g. `mongodb://localhost:27017`) |
| `db` | yes | string | Database name |
| `collection` | yes | string | Collection name |

## How it works

Connects to MongoDB using the `pymongo` library, runs `collection.find()`, returns all documents as a Python list, then closes the connection.

If `pymongo` is not installed, the action logs a message and returns `None` without failing the workflow.

## Examples

### Fetch all records from a collection
```json
{
  "id": "users",
  "type": "mongo",
  "url": "mongodb://localhost:27017",
  "db": "myapp",
  "collection": "users"
}
```

### Load credentials from config
```json
{ "id": "_", "type": "loadContext", "file": "config/db.json" },
{
  "id": "records",
  "type": "mongo",
  "url": {"override": "mongo_url"},
  "db": {"override": "mongo_db"},
  "collection": "events"
}
```

`config/db.json`:
```json
{
  "mongo_url": "mongodb://localhost:27017",
  "mongo_db": "analytics"
}
```

## Notes

- `collection.find()` fetches **all documents** — there is no query filter or projection. For large collections this may return a very large payload
- `pymongo` must be installed (`pip install pymongo`). The action degrades gracefully if it is missing
- MongoDB `ObjectId` values are not serialized to strings automatically — they may cause issues when passed to JSON-based downstream actions

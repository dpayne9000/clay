try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None
from ..run import logger
from .registry import action, req, handler_for


@action('mongo', skeleton=False)
class Mongo:
    id:         str = req("Output key for the list of retrieved documents")
    url:        str = req("MongoDB connection URI (e.g. mongodb://localhost:27017)")
    db:         str = req("Database name")
    collection: str = req("Collection name")


@handler_for('mongo')
def handler(action, ctx):
    """
    Connects to MongoDB based on the details in 'action', retrieves data,
    and returns it along with the action's 'id'.

    Args:
    action (dict): Details for the MongoDB action, including connection info and collection name.
    previous_data (dict): Data from previous actions, not used in this function but can be utilized if needed.

    Returns:
    dict: A dictionary containing the action's 'id' and the retrieved data.
    """
    logger.debug("mongo: handling action")

    # Extract MongoDB details from the action
    url = action.get('url')
    db_name = action.get('db')
    collection_name = action.get('collection')

    if not (url and db_name and collection_name):
        logger.error("mongo: missing required parameters (url, db, collection)")
        return None

    if MongoClient is None:
        logger.error("mongo: pymongo is not installed")
        return None

    client = None
    try:
        client = MongoClient(url, serverSelectionTimeoutMS=10000)
        db = client[db_name]
        collection = db[collection_name]
        data = list(collection.find())
        return {"id": action.get("id"), "data": data}
    except Exception as e:
        logger.warn(f"mongo: error: {e}")
        return None
    finally:
        if client:
            client.close()
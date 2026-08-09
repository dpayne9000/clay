"""Unit tests for api_actions (API) handler."""

import unittest
from unittest.mock import patch, MagicMock

from ...actions import api_actions


def _mock_response(status_code=200, json_data=None, text="ok"):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json.return_value = json_data
    else:
        mock_resp.json.side_effect = ValueError("no json")
    mock_resp.text = text
    return mock_resp


def _request_patch(response=None, side_effect=None):
    return patch.object(
        api_actions, "request", return_value=response, side_effect=side_effect)


class TestApiActions(unittest.TestCase):

    def test_missing_endpoint_returns_none(self):
        with patch('builtins.print'):
            result = api_actions.handler({"id": "out", "method": "get"}, {})
        self.assertIsNone(result)

    def test_get_request_made(self):
        with _request_patch(_mock_response(json_data={"k": "v"})) as mock_get:
            result = api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/data", "method": "get"},
                {}
            )
        mock_get.assert_called_once()
        self.assertEqual(result["data"], {"k": "v"})

    def test_post_request_made(self):
        with _request_patch(_mock_response(json_data={"id": 1})) as mock_post:
            result = api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/items",
                 "method": "post", "data": {"name": "x"}},
                {}
            )
        mock_post.assert_called_once()
        self.assertIsNotNone(result)

    def test_put_request_made(self):
        with _request_patch(_mock_response(json_data={})) as mock_put:
            result = api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/item/1", "method": "put"},
                {}
            )
        mock_put.assert_called_once()

    def test_patch_request_made(self):
        with _request_patch(_mock_response(json_data={})) as mock_patch:
            result = api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/item/1", "method": "patch"},
                {}
            )
        mock_patch.assert_called_once()

    def test_delete_request_made(self):
        with _request_patch(_mock_response(json_data={})) as mock_delete:
            result = api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/item/1", "method": "delete"},
                {}
            )
        mock_delete.assert_called_once()

    def test_default_method_is_get(self):
        with _request_patch(_mock_response(json_data={})) as mock_get:
            api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/x"},
                {}
            )
        mock_get.assert_called_once()

    def test_unsupported_method_returns_none(self):
        with patch('builtins.print'):
            result = api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/x", "method": "head"},
                {}
            )
        self.assertIsNone(result)

    def test_non_json_response_falls_back_to_text(self):
        with _request_patch(_mock_response(text="plain text response")):
            result = api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/x", "method": "get"},
                {}
            )
        self.assertEqual(result["data"], "plain text response")

    def test_request_exception_returns_error_string(self):
        with _request_patch(side_effect=OSError("timeout")), \
             patch('builtins.print'):
            result = api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/x"},
                {}
            )
        self.assertIn("error", result["data"])

    def test_id_preserved_in_result(self):
        with _request_patch(_mock_response(json_data={})):
            result = api_actions.handler(
                {"id": "my_result", "endpoint": "https://api.example.com/x"},
                {}
            )
        self.assertEqual(result["id"], "my_result")

    def test_headers_forwarded(self):
        with _request_patch(_mock_response(json_data={})) as mock_get:
            api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/x",
                 "headers": {"Authorization": "Bearer token"}},
                {}
            )
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer token"})

    def test_params_forwarded(self):
        with _request_patch(_mock_response(json_data={})) as mock_get:
            api_actions.handler(
                {"id": "out", "endpoint": "https://api.example.com/search",
                 "params": {"q": "python"}},
                {}
            )
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"], {"q": "python"})


if __name__ == '__main__':
    unittest.main()

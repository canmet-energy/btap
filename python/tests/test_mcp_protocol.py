"""Protocol tests for btap._mcp — JSON-RPC, SSE decoding, X-API-Key, retries.

Deterministic mocked tests needing no key: request shape, SSE frame parsing,
auth header presence, exponential backoff timing. These verify the CLIENT
implementation without touching the network.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

PYTHON_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PYTHON_ROOT))

from btap._mcp import MCPClient, MCPError  # noqa: E402


class MockHTTPResponse:
    """Minimal http.client.HTTPResponse mock for urllib."""

    def __init__(self, data: bytes, code: int = 200):
        self.data = data
        self.code = code
        self.status = code

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestMCPClient(unittest.TestCase):
    """Protocol tests: request shape, SSE decoding, auth, retries."""

    def test_request_shape(self):
        """JSON-RPC request has correct structure and headers."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            # Mock successful SSE response
            sse_data = 'data: {"result": {"content": [{"text": "{\\"result\\": \\"ok\\"}"}]}}\n'
            mock_urlopen.return_value = MockHTTPResponse(sse_data.encode("utf-8"))

            client = MCPClient("test-server", endpoint="https://test.example.com/mcp", api_key="test-key")
            client.call("test_tool", {"arg": "value"})

            # Verify request
            request = mock_urlopen.call_args[0][0]
            self.assertEqual(request.get_full_url(), "https://test.example.com/mcp")
            self.assertEqual(request.get_header("X-api-key"), "test-key")
            self.assertEqual(request.get_header("Content-type"), "application/json")
            self.assertIn("text/event-stream", request.get_header("Accept"))

            # Verify JSON-RPC body
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body["jsonrpc"], "2.0")
            self.assertEqual(body["method"], "tools/call")
            self.assertEqual(body["params"]["name"], "test_tool")
            self.assertEqual(body["params"]["arguments"], {"arg": "value"})

    def test_sse_decoding(self):
        """SSE stream is correctly parsed to extract tool result."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            # Multi-line SSE with event types and data frames
            sse_stream = (
                "event: message\n"
                'data: {"id": 1}\n'
                "\n"
                'data: {"result": {"content": [{"text": "{\\"status\\": \\"success\\"}"}]}}\n'
                "\n"
            )
            mock_urlopen.return_value = MockHTTPResponse(sse_stream.encode("utf-8"))

            client = MCPClient("test", endpoint="https://test.example.com/mcp", api_key="key")
            result = client.call("tool", {})

            self.assertEqual(result, {"status": "success"})

    def test_plain_json_fallback(self):
        """Non-SSE plain JSON response is also supported."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            plain_json = {"result": {"content": [{"text": '{"value": 42}'}]}}
            mock_urlopen.return_value = MockHTTPResponse(json.dumps(plain_json).encode("utf-8"))

            client = MCPClient("test", endpoint="https://test.example.com/mcp", api_key="key")
            result = client.call("tool", {})

            self.assertEqual(result, {"value": 42})

    def test_rpc_error_handling(self):
        """JSON-RPC error responses raise MCPError."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            error_response = {
                "error": {"code": -32600, "message": "Invalid request"}
            }
            sse = f'data: {json.dumps(error_response)}\n'
            mock_urlopen.return_value = MockHTTPResponse(sse.encode("utf-8"))

            client = MCPClient("test", endpoint="https://test.example.com/mcp", api_key="key")

            with self.assertRaises(MCPError) as cm:
                client.call("tool", {})
            self.assertIn("RPC error", str(cm.exception))

    def test_http_4xx_fails_fast(self):
        """4xx errors fail immediately without retry."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "https://test.example.com/mcp", 404, "Not Found", {}, None
            )

            client = MCPClient("test", endpoint="https://test.example.com/mcp", api_key="key")

            with self.assertRaises(MCPError) as cm:
                client.call("tool", {})

            # Should fail immediately
            self.assertEqual(mock_urlopen.call_count, 1)
            self.assertIn("HTTP 404", str(cm.exception))

    def test_http_5xx_retries_with_backoff(self):
        """5xx and 429 errors retry with exponential backoff."""
        with patch("urllib.request.urlopen") as mock_urlopen, \
             patch("time.sleep") as mock_sleep:

            # Fail twice, then succeed
            mock_urlopen.side_effect = [
                HTTPError("url", 503, "Service Unavailable", {}, None),
                HTTPError("url", 503, "Service Unavailable", {}, None),
                MockHTTPResponse(b'data: {"result": {"content": [{"text": "{\\"ok\\": true}"}]}}\n')
            ]

            client = MCPClient("test", endpoint="https://test.example.com/mcp", api_key="key")
            result = client.call("tool", {}, attempts=3)

            self.assertEqual(result, {"ok": True})
            self.assertEqual(mock_urlopen.call_count, 3)

            # Verify exponential backoff: 2^0=1, 2^1=2
            self.assertEqual(mock_sleep.call_count, 2)
            self.assertEqual(mock_sleep.call_args_list[0][0][0], 1)
            self.assertEqual(mock_sleep.call_args_list[1][0][0], 2)

    def test_retry_exhaustion(self):
        """After N failed attempts, raise with attempt count."""
        with patch("urllib.request.urlopen") as mock_urlopen, \
             patch("time.sleep"):

            mock_urlopen.side_effect = HTTPError("url", 500, "Error", {}, None)

            client = MCPClient("test", endpoint="https://test.example.com/mcp", api_key="key")

            with self.assertRaises(MCPError) as cm:
                client.call("tool", {}, attempts=3)

            self.assertIn("after 3 attempts", str(cm.exception))

    def test_env_var_expansion(self):
        """${VAR} and ${VAR:-default} placeholders are expanded."""
        with patch.dict("os.environ", {"TEST_VAR": "expanded_value"}):
            client = MCPClient("test", endpoint="https://test.example.com/mcp", api_key="key")

            # Direct value
            self.assertEqual(client._expand_vars("${TEST_VAR}"), "expanded_value")

            # With default (unused because var is set)
            self.assertEqual(client._expand_vars("${TEST_VAR:-fallback}"), "expanded_value")

            # Unset var with default
            self.assertEqual(client._expand_vars("${UNSET:-fallback}"), "fallback")

            # Unset var without default returns None
            self.assertIsNone(client._expand_vars("${UNSET}"))

    def test_missing_api_key_raises(self):
        """Client raises clear error when API key is unavailable."""
        with patch.dict("os.environ", {}, clear=True), \
             patch("pathlib.Path.is_file", return_value=False):

            with self.assertRaises(MCPError) as cm:
                MCPClient("test-server", endpoint="https://test.example.com/mcp")

            self.assertIn("no test-server API key", str(cm.exception))
            self.assertIn("HBIX_API_KEY", str(cm.exception))

    def test_missing_endpoint_raises(self):
        """Client raises clear error when endpoint is unavailable."""
        with patch.dict("os.environ", {"HBIX_API_KEY": "test-key"}, clear=True), \
             patch("pathlib.Path.is_file", return_value=False):

            with self.assertRaises(MCPError) as cm:
                MCPClient("test-server")

            self.assertIn("no test-server MCP url", str(cm.exception))
            self.assertIn("HBIX_MCP_BASE_URL", str(cm.exception))

    def test_base_url_construction(self):
        """Base URL + server name builds correct endpoint."""
        client = MCPClient(
            "my-server",
            base_url="https://api.example.com/prod",
            api_key="key"
        )
        self.assertEqual(client._endpoint, "https://api.example.com/prod/my-server/mcp")

    def test_mcp_config_parsing(self):
        """Load .mcp.json and extract server config."""
        mock_config = {
            "mcpServers": {
                "test-server": {
                    "url": "https://configured.example.com/test-server/mcp",
                    "headers": {"X-API-Key": "configured-key"}
                }
            }
        }

        patches = (
            patch.dict("os.environ", {}, clear=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.read_text", return_value=json.dumps(mock_config)),
        )
        with patches[0], patches[1], patches[2]:
            client = MCPClient("test-server")

            self.assertEqual(client._endpoint, "https://configured.example.com/test-server/mcp")
            self.assertEqual(client._api_key, "configured-key")

    def test_mcp_config_with_env_expansion(self):
        """${VAR} placeholders in .mcp.json are expanded from env."""
        mock_config = {
            "mcpServers": {
                "test-server": {
                    "url": "${BASE_URL}/test-server/mcp",
                    "headers": {"X-API-Key": "${API_KEY}"}
                }
            }
        }

        env = {"BASE_URL": "https://env.example.com", "API_KEY": "env-key"}
        patches = (
            patch.dict("os.environ", env, clear=True),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.read_text", return_value=json.dumps(mock_config)),
        )
        with patches[0], patches[1], patches[2]:
            client = MCPClient("test-server")

            self.assertEqual(client._endpoint, "https://env.example.com/test-server/mcp")
            self.assertEqual(client._api_key, "env-key")


if __name__ == "__main__":
    unittest.main()

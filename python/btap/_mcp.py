"""Minimal JSON-RPC MCP client for HBIX HTTP servers.

Stateless client: one POST per call, no session, no initialize handshake.
SSE response decoding, X-API-Key auth, exponential backoff retries.

MCP access is a MAINTAINER operation (fetching Section 8.4 text and
building-stock bulk work), never part of ordinary compliance runtime. This
stdlib-only helper lives at package root so repository scripts work from a
checkout and installed maintainer commands can share the same protocol code.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class MCPError(Exception):
    """MCP client errors: auth, network, protocol, or tool result."""
    pass


class MCPClient:
    """Minimal JSON-RPC client for NRCan HTTP MCP servers.

    Args:
        server: Server name (appended to base URL as ``/<server>/mcp``)
        endpoint: Full MCP endpoint URL (overrides base + server)
        api_key: X-API-Key value (overrides env)
        base_url: Base URL for all servers (env: HBIX_MCP_BASE_URL)
        timeout: Read timeout in seconds

    Auth resolution order (first wins):
        1. ``api_key`` argument
        2. ``HBIX_API_KEY`` environment variable
        3. ``.mcp.json`` headers.X-API-Key (with ${VAR} expansion)
        4. Raise MCPError

    URL resolution order:
        1. ``endpoint`` argument
        2. ``base_url`` (or env HBIX_MCP_BASE_URL) + server name
        3. ``.mcp.json`` url (with ${VAR} expansion)
        4. Raise MCPError
    """

    def __init__(
        self,
        server: str,
        endpoint: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 60
    ):
        self.server = server
        self.timeout = timeout

        # URL resolution
        if endpoint:
            self._endpoint = endpoint
        elif base_url or os.getenv("HBIX_MCP_BASE_URL"):
            base = (base_url or os.getenv("HBIX_MCP_BASE_URL", "")).rstrip("/")
            self._endpoint = f"{base}/{server}/mcp"
        else:
            config = self._load_mcp_config()
            expanded = self._expand_vars(config.get("url", ""))
            if not expanded:
                raise MCPError(
                    f"no {server} MCP url: set HBIX_MCP_BASE_URL "
                    "(see .env.example) or install .mcp.json"
                )
            self._endpoint = expanded

        # API key resolution
        if api_key:
            self._api_key = api_key
        elif os.getenv("HBIX_API_KEY"):
            self._api_key = os.getenv("HBIX_API_KEY")
        else:
            config = self._load_mcp_config()
            expanded = self._expand_vars(config.get("headers", {}).get("X-API-Key", ""))
            if not expanded:
                raise MCPError(
                    f"no {server} API key: set HBIX_API_KEY (see .env.example)"
                )
            self._api_key = expanded

    def call(self, tool: str, arguments: dict[str, Any], attempts: int = 3) -> Any:
        """Make one JSON-RPC tools/call request.

        Args:
            tool: Tool name to call
            arguments: Tool arguments dict
            attempts: Retry attempts (exponential backoff on 429/5xx)

        Returns:
            Parsed tool result (the content[0].text JSON unwrapped)

        Raises:
            MCPError: On auth, network, protocol, or tool errors
        """
        request_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}
        }

        response = None
        last_error = None

        for attempt in range(attempts):
            try:
                req = urllib.request.Request(
                    self._endpoint,
                    data=json.dumps(request_body).encode("utf-8"),
                    headers={
                        "X-API-Key": self._api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    }
                )

                with urllib.request.urlopen(req, timeout=self.timeout) as res:
                    response = res.read().decode("utf-8")
                    break  # success

            except urllib.error.HTTPError as e:
                last_error = e
                # Back off on throttling and transient server faults; fail fast on 4xx
                if e.code not in [429, 500, 502, 503, 504]:
                    raise MCPError(f"{tool}: HTTP {e.code}") from e
                if attempt < attempts - 1:
                    time.sleep(2 ** attempt)
            except Exception as e:
                raise MCPError(f"{tool}: network error: {e}") from e

        if response is None:
            raise MCPError(
                f"{tool}: HTTP {last_error.code if last_error else 'error'} "
                f"after {attempts} attempts"
            )

        return self._unwrap_response(response, tool)

    def _unwrap_response(self, body: str, tool: str) -> Any:
        """Decode SSE stream or plain JSON, extract tool result."""
        # Try SSE first (look for "data: " lines)
        data_lines = [line for line in body.splitlines() if line.startswith("data: ")]
        if data_lines:
            # Parse each data line as JSON, find the one with result/error
            payload = None
            for line in data_lines:
                try:
                    frame = json.loads(line.removeprefix("data: "))
                    if "result" in frame or "error" in frame:
                        payload = frame
                        break
                except json.JSONDecodeError:
                    continue

            if payload is None:
                raise MCPError(f"{tool}: no JSON-RPC frame in SSE response")
        else:
            # Not SSE, try plain JSON
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as e:
                raise MCPError(f"{tool}: response is not valid JSON") from e

        # Check for JSON-RPC error
        if "error" in payload:
            error = payload["error"]
            raise MCPError(f"{tool}: RPC error {error}")

        # Extract result
        if "result" not in payload:
            raise MCPError(f"{tool}: no result in response")

        result = payload["result"]
        content = result.get("content", [])
        if not content:
            raise MCPError(f"{tool}: empty result content")

        text = content[0].get("text")
        if text is None:
            raise MCPError(f"{tool}: no text in result content[0]")

        # The text itself is often JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _load_mcp_config(self) -> dict:
        """Load .mcp.json defensively (it may not exist or be invalid)."""
        repo_root = Path(__file__).resolve().parents[2]
        mcp_path = repo_root / ".mcp.json"

        if not mcp_path.is_file():
            return {}

        try:
            config = json.loads(mcp_path.read_text(encoding="utf-8"))
            return config.get("mcpServers", {}).get(self.server, {})
        except (json.JSONDecodeError, KeyError):
            return {}

    def _expand_vars(self, value: str) -> str | None:
        """Expand ${VAR} and ${VAR:-default} placeholders from environment.

        Returns None if any placeholder cannot be resolved (no value, no default).
        """
        if not value:
            return None

        import re

        def replacer(match):
            var_name = match.group(1)
            default = match.group(2)
            env_value = os.getenv(var_name)
            if env_value:
                return env_value
            if default is not None:
                return default
            return "\x00"  # sentinel for unresolvable

        result = re.sub(r'\$\{(\w+)(?::-([^}]*))?\}', replacer, value)
        return None if "\x00" in result else result

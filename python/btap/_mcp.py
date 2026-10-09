"""mcp_client.py — stdlib-only Python client for the hbix MCP (JSON-RPC) endpoints.

Each hbix service exposes its MCP server over streamable HTTP at
``/<service>/mcp``. The servers run stateless (``stateless_http=True``), so a
single ``POST`` per ``tools/call`` works — no ``initialize`` handshake, no
``Mcp-Session-Id``. Responses come back SSE-framed (``data: {...}`` lines)
even for a single reply; this client unwraps both SSE and plain JSON.

No third-party dependencies — only ``urllib.request``/``json``/``hashlib``
from the standard library.

Auth
----
Pass ``api_key=...`` or set the ``HBIX_API_KEY`` environment variable.
Keys are sent as the ``X-API-Key`` header (Bearer tokens also work against
the servers, but this client speaks X-API-Key).

Navigation
----------
Don't memorize tool names — ask the server:

    MCPClient("codes").list_tools()

or read ``GET <base>/<service>/llms.txt`` for a human-readable list.

Usage
-----
    from mcp_client import MCPClient

    codes = MCPClient("codes")  # reads HBIX_API_KEY / HBIX_API_URL from env
    section = codes.call("get_section", {"number": "3.2.2.2", "edition": "2025"})

Updates
-------
This file is served by the deployed gateway at ``GET <base>/mcp_client.py``.
It never checks for updates on its own — run ``python mcp_client.py
--check-update`` (or call :func:`check_for_update`) to compare this copy
against the served one, and re-curl to refresh. Suitable as an opt-in CI
staleness guard: exit code 1 means a newer file is being served.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

__version__ = "1.0.0"  # bump on behavior changes; --check-update compares content, not this
__released__ = "2026-09-04"

# Services run as Lambdas behind API Gateway, whose integration timeout is 29s.
# A request that exceeds it comes back as a gateway 5xx — so the client timeout
# must sit ABOVE 29s, or urllib raises its own socket timeout first and the
# caller sees a connection error instead of the status the server actually sent.
DEFAULT_TIMEOUT = 35.0

# Transient by nature: throttling (429), and the gateway 5xx family a Lambda
# cold start can produce when it blows the 29s ceiling. Other 4xx is never
# retried — it means the request itself is wrong.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

DEFAULT_MAX_RETRIES = 2  # i.e. up to 3 attempts
DEFAULT_BACKOFF = 0.5  # seconds; doubles each attempt (0.5s, then 1.0s)

DEFAULT_BASE_URL = "https://3ucoopudrb.execute-api.ca-central-1.amazonaws.com/prod"

# The MCP streamable-HTTP SDK validates this Accept header; omitting the
# event-stream half gets a 406 before the request reaches any tool.
_ACCEPT = "application/json, text/event-stream"

__all__ = ["MCPClient", "MCPError", "check_for_update"]


class MCPError(Exception):
    """MCP client errors: auth, network, protocol, or tool-result failures.

    Attributes:
        status: HTTP status code, or 0 if the request never reached the server.
        body: Response body (or reason string) for debugging.
    """

    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


# =============================================================================
# Client
# =============================================================================


class MCPClient:
    """Minimal JSON-RPC client for one hbix MCP server.

    Args:
        server: Service name, appended to the base URL as ``/<server>/mcp``
            (one of: codes, geocoding, weather, building-stock, modelling,
            simulation).
        endpoint: Full MCP endpoint URL (overrides base_url + server).
        api_key: X-API-Key value (overrides the HBIX_API_KEY env var).
        base_url: Gateway base URL including stage, e.g.
            ``https://.../prod`` (overrides env).
        timeout: Read timeout in seconds. Keep it above 29 — see
            DEFAULT_TIMEOUT.

    Resolution order (first wins):
        base URL:  ``endpoint`` arg > ``base_url`` arg > ``HBIX_API_URL`` env
                   > ``HBIX_MCP_BASE_URL`` env (compat) > built-in prod URL
        API key:   ``api_key`` arg > ``HBIX_API_KEY`` env > raise on first call

    Unlike earlier consumer-repo forks, this client reads no ``.mcp.json`` —
    configuration is explicit arguments or environment variables only.
    """

    def __init__(
        self,
        server: str,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
    ):
        self.server = server
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        base = (
            base_url
            or os.getenv("HBIX_API_URL")
            or os.getenv("HBIX_MCP_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.endpoint = endpoint or f"{base}/{server}/mcp"
        self._api_key = api_key or os.getenv("HBIX_API_KEY")

    # -- public API -----------------------------------------------------------

    def call(
        self,
        tool: str,
        arguments: Optional[dict[str, Any]] = None,
        attempts: Optional[int] = None,
    ) -> Any:
        """Invoke one tool via JSON-RPC ``tools/call`` and return its result.

        The result is ``content[0].text`` parsed as JSON when possible,
        otherwise the raw text. All current hbix tools are read-only queries,
        so transient failures (429/5xx) are retried by default — unlike REST
        POSTs, a re-sent tools/call cannot create duplicate work.

        Args:
            tool: Tool name (see :meth:`list_tools`).
            arguments: Tool arguments dict.
            attempts: Total attempts including the first (default:
                ``max_retries + 1``).

        Raises:
            MCPError: on auth, network, protocol, or tool-result errors.
        """
        payload = self._rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments or {}},
            },
            attempts=attempts,
            context=tool,
        )
        result = payload["result"]
        if result.get("isError"):
            raise MCPError(f"{tool}: tool returned an error: {result}", body=str(result))
        content = result.get("content") or []
        if not content:
            raise MCPError(f"{tool}: empty result content", body=str(result))
        text = content[0].get("text")
        if text is None:
            raise MCPError(f"{tool}: no text in result content[0]", body=str(result))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def list_tools(self, attempts: Optional[int] = None) -> list[dict]:
        """Return the server's tool list (name, description, inputSchema)."""
        payload = self._rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            attempts=attempts,
            context="tools/list",
        )
        return payload["result"].get("tools", [])

    # -- transport ------------------------------------------------------------

    def _require_key(self) -> str:
        if not self._api_key:
            raise MCPError(
                "No API key configured. Pass api_key=... to MCPClient(), or set "
                "the HBIX_API_KEY environment variable."
            )
        return self._api_key

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._require_key(),
            "Content-Type": "application/json",
            "Accept": _ACCEPT,
        }

    def _rpc(
        self,
        request_body: dict,
        attempts: Optional[int] = None,
        context: str = "rpc",
    ) -> dict:
        """POST one JSON-RPC request, retrying transient failures; return the
        decoded JSON-RPC payload (guaranteed to contain ``result``)."""
        total = attempts if attempts is not None else self.max_retries + 1
        data = json.dumps(request_body).encode("utf-8")
        headers = self._headers()
        last_error: Optional[MCPError] = None

        for attempt in range(total):
            try:
                req = urllib.request.Request(self.endpoint, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as res:
                    body = res.read().decode("utf-8")
                return self._unwrap(body, context)
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", "replace")[:500]
                except Exception:  # pragma: no cover - best-effort body capture
                    pass
                last_error = MCPError(
                    f"{context}: HTTP {e.code}: {err_body}", status=e.code, body=err_body
                )
                if e.code not in RETRY_STATUSES:
                    raise last_error from e
            except urllib.error.URLError as e:
                last_error = MCPError(
                    f"{context}: network error: {e.reason}", status=0, body=str(e.reason)
                )
            if attempt < total - 1:
                time.sleep(self.backoff * (2**attempt))

        assert last_error is not None
        raise MCPError(
            f"{context}: failed after {total} attempt(s): {last_error}",
            status=last_error.status,
            body=last_error.body,
        )

    @staticmethod
    def _unwrap(body: str, context: str = "rpc") -> dict:
        """Decode an SSE stream or plain JSON body into the JSON-RPC payload."""
        payload = None
        data_lines = [ln for ln in body.splitlines() if ln.startswith("data: ")]
        if data_lines:
            for line in data_lines:
                try:
                    frame = json.loads(line[len("data: ") :])
                except json.JSONDecodeError:
                    continue
                if isinstance(frame, dict) and ("result" in frame or "error" in frame):
                    payload = frame
                    break
            if payload is None:
                raise MCPError(f"{context}: no JSON-RPC frame in SSE response", body=body[:500])
        else:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as e:
                raise MCPError(f"{context}: response is not valid JSON", body=body[:500]) from e

        if "error" in payload:
            raise MCPError(f"{context}: RPC error: {payload['error']}", body=str(payload["error"]))
        if "result" not in payload:
            raise MCPError(f"{context}: no result in response", body=str(payload)[:500])
        return payload

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"MCPClient(server={self.server!r}, endpoint={self.endpoint!r}, "
            f"api_key={'set' if self._api_key else None!r})"
        )


# =============================================================================
# Update check (explicit — this module never phones home on its own)
# =============================================================================


def check_for_update(base_url: Optional[str] = None, timeout: float = 10.0) -> dict:
    """Compare this file against the copy served at ``<base>/mcp_client.py``.

    Content-hash comparison (sha256), so there is no version bookkeeping to
    go stale. Network access happens only when this function is called.

    Returns:
        ``{"up_to_date": bool, "local_sha256": str, "remote_sha256": str,
        "url": str}``
    """
    base = (
        base_url
        or os.getenv("HBIX_API_URL")
        or os.getenv("HBIX_MCP_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")
    url = f"{base}/mcp_client.py"
    local = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"Accept": "text/x-python"}),
            timeout=timeout,
        ) as res:
            remote = hashlib.sha256(res.read()).hexdigest()
    except Exception as e:
        raise MCPError(f"check_for_update: could not fetch {url}: {e}") from e
    return {
        "up_to_date": local == remote,
        "local_sha256": local,
        "remote_sha256": remote,
        "url": url,
    }


# =============================================================================
# Self-test (offline) and CLI
# =============================================================================


def _selftest() -> None:
    """Offline sanity checks — no network access."""
    c = MCPClient("codes", api_key="mk_test", base_url="https://example.com/prod")
    assert c.endpoint == "https://example.com/prod/codes/mcp", c.endpoint
    h = c._headers()
    assert h["Accept"] == "application/json, text/event-stream"
    assert h["X-API-Key"] == "mk_test"
    assert DEFAULT_TIMEOUT > 29, "timeout must exceed the API Gateway 29s ceiling"

    # SSE unwrap
    sse = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    assert MCPClient._unwrap(sse)["result"] == {"ok": True}
    # plain JSON unwrap
    assert MCPClient._unwrap('{"jsonrpc":"2.0","id":1,"result":{}}')["result"] == {}
    # RPC error raises
    try:
        MCPClient._unwrap('{"jsonrpc":"2.0","id":1,"error":{"code":-32601}}')
        raise AssertionError("expected MCPError")
    except MCPError:
        pass
    # no-key client raises with guidance
    k = MCPClient("codes", base_url="https://example.com/prod")
    k._api_key = None
    try:
        k._headers()
        raise AssertionError("expected MCPError")
    except MCPError as e:
        assert "HBIX_API_KEY" in str(e)

    print(f"selftest OK: mcp_client {__version__}, endpoint/header/unwrap verified.")


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        _selftest()
    elif "--check-update" in sys.argv:
        info = check_for_update()
        if info["up_to_date"]:
            print(f"up to date ({info['local_sha256'][:12]})")
        else:
            print(
                "update available — refresh with:\n"
                f"  curl {info['url']} -o mcp_client.py"
            )
            sys.exit(1)
    else:
        client = MCPClient(sys.argv[1] if len(sys.argv) > 1 else "codes")
        try:
            tools = client.list_tools()
            print(f"{client.server}: {len(tools)} tools")
            for t in tools:
                print(f"  {t['name']}: {(t.get('description') or '').splitlines()[0][:80]}")
        except Exception as e:  # pragma: no cover - best-effort smoke print
            print(f"discovery failed: {e}")

"""Transport-level WebSocket client used by the whole test suite.

Design goals
------------
* **Thin.** It wraps `websocket-client` (the permitted basic protocol library) and
  adds only the conveniences the tests actually need: JSON send/receive, a bounded
  message *collector*, and robust timeout handling.
* **Deterministic under test.** Network feeds are asynchronous and noisy. Every
  receive operation is time-bounded so a stalled feed turns into a clear
  `WSTimeout` instead of a hanging test.
* **Version-agnostic.** This layer knows nothing about Kraken v1 vs v2 semantics.
  The per-version helpers in `v1.py` / `v2.py` build the payloads and interpret the
  decoded messages; this class only moves JSON in and out of the socket.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable, Optional

# `websocket-client` exposes the low-level `create_connection` factory and the
# `WebSocketTimeoutException` we translate into our own error type.
from websocket import WebSocket, WebSocketTimeoutException, create_connection


class WSTimeout(TimeoutError):
    """Raised when an expected message does not arrive within the deadline.

    We use a dedicated exception (subclassing the stdlib ``TimeoutError``) so tests
    and fixtures can distinguish "the feed went quiet" from genuine protocol errors.
    """


# A predicate decides whether a decoded message is "the one we are waiting for".
# It receives the already-JSON-decoded message (dict or list) and returns a bool.
Predicate = Callable[[Any], bool]


class KrakenWSClient:
    """A minimal, well-behaved JSON-over-WebSocket client.

    Typical usage::

        with KrakenWSClient("wss://ws.kraken.com/v2") as ws:
            ws.send_json({"method": "subscribe", "params": {...}})
            snapshot = ws.wait_for(lambda m: m.get("type") == "snapshot")
    """

    def __init__(
        self,
        url: str,
        *,
        open_timeout: float = 10.0,
        recv_timeout: float = 10.0,
        parse_float: Optional[Callable[[str], Any]] = None,
    ):
        """Open a connection to ``url``.

        Parameters
        ----------
        url:
            The WebSocket endpoint (e.g. ``wss://ws.kraken.com`` for v1).
        open_timeout:
            Seconds to wait for the TCP/TLS/WebSocket handshake to complete.
        recv_timeout:
            Default per-``recv`` socket timeout. Individual calls may override the
            overall deadline via their own ``timeout`` argument.
        parse_float:
            Optional hook passed straight through to ``json.loads``. Order-book
            checksum validation needs the *exact* decimal digits Kraken sent on the
            wire, which are lost once a JSON number is turned into a binary float.
            Passing ``decimal.Decimal`` here preserves them.
        """
        self.url = url
        self.recv_timeout = recv_timeout
        self._parse_float = parse_float
        # `create_connection` performs the blocking handshake. We set a socket-level
        # timeout so a single recv() never blocks forever.
        self._ws: WebSocket = create_connection(url, timeout=open_timeout)
        self._ws.settimeout(recv_timeout)

    # -- context manager plumbing -------------------------------------------------
    def __enter__(self) -> "KrakenWSClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- sending ------------------------------------------------------------------
    def send_json(self, payload: dict) -> None:
        """Serialize ``payload`` to JSON and send it as a text frame."""
        self._ws.send(json.dumps(payload))

    # -- receiving ----------------------------------------------------------------
    def recv_json(self, timeout: Optional[float] = None) -> Any:
        """Receive a single frame and JSON-decode it.

        Non-JSON frames (Kraken never sends these on public feeds, but we stay
        defensive) are skipped and the next frame is read, still respecting the
        overall deadline.
        """
        deadline = time.monotonic() + (timeout if timeout is not None else self.recv_timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WSTimeout(f"No JSON frame received within timeout from {self.url}")
            # Shrink the socket timeout to the remaining budget so recv() cannot
            # overshoot the caller's deadline.
            self._ws.settimeout(remaining)
            try:
                raw = self._ws.recv()
            except WebSocketTimeoutException as exc:
                raise WSTimeout(f"recv timed out after waiting on {self.url}") from exc
            if raw is None or raw == "":
                # Empty keep-alive frame; keep waiting within the budget.
                continue
            try:
                return json.loads(raw, parse_float=self._parse_float)
            except (json.JSONDecodeError, TypeError):
                # Ignore anything that is not valid JSON and try the next frame.
                continue

    def wait_for(self, predicate: Predicate, *, timeout: float = 15.0) -> Any:
        """Return the first decoded message for which ``predicate`` is true.

        Messages that do not match are discarded. Raises :class:`WSTimeout` if no
        matching message arrives before ``timeout`` seconds elapse.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WSTimeout("Predicate not satisfied before timeout")
            msg = self.recv_json(timeout=remaining)
            if predicate(msg):
                return msg

    def collect(
        self,
        predicate: Predicate,
        *,
        count: int,
        timeout: float = 20.0,
    ) -> list:
        """Collect up to ``count`` messages matching ``predicate``.

        This is the workhorse for tests that need to observe a feed over time
        (e.g. "the order book is never crossed across N updates"). Collection stops
        as soon as either ``count`` matches are gathered or ``timeout`` is reached.

        Returns whatever was collected so far (possibly fewer than ``count``); the
        caller decides whether a short read is acceptable or should be skipped.
        """
        deadline = time.monotonic() + timeout
        collected: list = []
        while len(collected) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                msg = self.recv_json(timeout=remaining)
            except WSTimeout:
                break
            if predicate(msg):
                collected.append(msg)
        return collected

    def drain(self, *, for_seconds: float) -> list:
        """Read and return every message seen during a fixed window.

        Useful for negative tests (e.g. "after unsubscribe, no more data frames
        arrive") where we want to inspect *all* traffic rather than filter it.
        """
        deadline = time.monotonic() + for_seconds
        messages: list = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return messages
            try:
                messages.append(self.recv_json(timeout=remaining))
            except WSTimeout:
                return messages

    # -- teardown -----------------------------------------------------------------
    def close(self) -> None:
        """Close the underlying socket, swallowing errors during teardown."""
        try:
            self._ws.close()
        except Exception:
            # Teardown must never mask the real test result.
            pass


def any_of(*predicates: Predicate) -> Predicate:
    """Combine predicates with logical OR (handy for 'match error OR success')."""
    return lambda msg: any(p(msg) for p in predicates)

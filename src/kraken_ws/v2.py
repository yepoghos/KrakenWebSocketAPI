"""Kraken WebSocket **v2** helpers (endpoint: ``wss://ws.kraken.com/v2``).

This module builds request payloads and classifies/parses the JSON objects the v2
API returns. Keeping this protocol knowledge in one place means the tests can read
almost like plain English (``v2.is_channel_data(msg, "ticker")``) and any future
protocol tweak is a one-line change here rather than a hunt through the suite.

v2 message shapes (the ones we rely on)
---------------------------------------
* Status (sent once on connect)::

      {"channel": "status", "type": "update",
       "data": [{"system": "online", "api_version": "v2", ...}]}

* Subscribe/unsubscribe ack (one per symbol)::

      {"method": "subscribe", "success": true, "result": {...}, ...}
      {"method": "subscribe", "success": false, "error": "...", ...}

* Channel data::

      {"channel": "ticker", "type": "snapshot"|"update", "data": [ {...} ]}

* Heartbeat (low-traffic keep-alive)::

      {"channel": "heartbeat"}
"""

from __future__ import annotations

from typing import Any, Iterable

URL = "wss://ws.kraken.com/v2"

# A liquid pair guarantees a steady flow of data so time-bounded tests are reliable.
DEFAULT_SYMBOL = "BTC/USD"


# --------------------------------------------------------------------------- #
# Request builders
# --------------------------------------------------------------------------- #
def subscribe(channel: str, symbols: Iterable[str], **params: Any) -> dict:
    """Build a ``subscribe`` request for ``channel`` on ``symbols``.

    Extra channel-specific options (``depth``, ``interval``, ``snapshot`` ...) are
    passed through ``params`` and merged into ``params`` object of the request.
    """
    body: dict[str, Any] = {"channel": channel, "symbol": list(symbols)}
    body.update(params)
    return {"method": "subscribe", "params": body}


def unsubscribe(channel: str, symbols: Iterable[str], **params: Any) -> dict:
    """Build an ``unsubscribe`` request for ``channel`` on ``symbols``."""
    body: dict[str, Any] = {"channel": channel, "symbol": list(symbols)}
    body.update(params)
    return {"method": "unsubscribe", "params": body}


# --------------------------------------------------------------------------- #
# Message classifiers (predicates for client.wait_for / client.collect)
# --------------------------------------------------------------------------- #
def is_status(msg: Any) -> bool:
    """True for the connection ``status`` message."""
    return isinstance(msg, dict) and msg.get("channel") == "status"


def is_heartbeat(msg: Any) -> bool:
    """True for a heartbeat frame."""
    return isinstance(msg, dict) and msg.get("channel") == "heartbeat"


def is_ack(msg: Any, method: str = "subscribe") -> bool:
    """True for a subscribe/unsubscribe acknowledgement (success or failure)."""
    return isinstance(msg, dict) and msg.get("method") == method and "success" in msg


def is_channel_data(msg: Any, channel: str, *, type_: str | None = None) -> bool:
    """True for a data message on ``channel`` (optionally of a given ``type``).

    ``type_`` may be ``"snapshot"`` or ``"update"``; ``None`` matches either.
    """
    if not isinstance(msg, dict) or msg.get("channel") != channel:
        return False
    if "data" not in msg:
        return False
    return type_ is None or msg.get("type") == type_


# --------------------------------------------------------------------------- #
# Small accessors
# --------------------------------------------------------------------------- #
def first_data(msg: dict) -> dict:
    """Return the first element of a channel message's ``data`` list.

    Most v2 single-symbol channels wrap their payload in a one-element list; this
    helper keeps the tests tidy.
    """
    return msg["data"][0]

"""Kraken WebSocket **v1** helpers (endpoint: ``wss://ws.kraken.com``).

The v1 protocol is noticeably different from v2:

* Control messages are JSON **objects** keyed by ``event``
  (``systemStatus``, ``subscriptionStatus``, ``heartbeat``).
* Market data arrives as JSON **arrays**::

      [channelID, <payload>, channelName, pair]

  e.g. ``[0, {"b": [...], "a": [...]}, "ticker", "XBT/USD"]`` or
       ``[42, [[price, vol, time, side, ordType, misc]], "trade", "XBT/USD"]``.

This module hides those quirks behind builders and predicates that mirror ``v2.py``
so the tests for both versions stay symmetrical and readable.
"""

from __future__ import annotations

from typing import Any, Iterable

URL = "wss://ws.kraken.com"

# v1 uses Kraken's internal asset code ``XBT`` (rather than ``BTC``) for bitcoin.
DEFAULT_PAIR = "XBT/USD"


# --------------------------------------------------------------------------- #
# Request builders
# --------------------------------------------------------------------------- #
def subscribe(name: str, pairs: Iterable[str], **subscription: Any) -> dict:
    """Build a ``subscribe`` request for channel ``name`` on ``pairs``.

    Channel-specific options such as ``depth`` (book) or ``interval`` (ohlc) go into
    the nested ``subscription`` object alongside ``name``.
    """
    sub: dict[str, Any] = {"name": name}
    sub.update(subscription)
    return {"event": "subscribe", "pair": list(pairs), "subscription": sub}


def unsubscribe(name: str, pairs: Iterable[str], **subscription: Any) -> dict:
    """Build an ``unsubscribe`` request for channel ``name`` on ``pairs``."""
    sub: dict[str, Any] = {"name": name}
    sub.update(subscription)
    return {"event": "unsubscribe", "pair": list(pairs), "subscription": sub}


# --------------------------------------------------------------------------- #
# Message classifiers
# --------------------------------------------------------------------------- #
def is_event(msg: Any, event: str) -> bool:
    """True if ``msg`` is a control object with ``event`` == the given name."""
    return isinstance(msg, dict) and msg.get("event") == event


def is_system_status(msg: Any) -> bool:
    """True for the one-off ``systemStatus`` message sent on connect."""
    return is_event(msg, "systemStatus")


def is_heartbeat(msg: Any) -> bool:
    """True for a ``heartbeat`` control message."""
    return is_event(msg, "heartbeat")


def is_subscription_status(msg: Any) -> bool:
    """True for a ``subscriptionStatus`` ack (either ``subscribed`` or ``error``)."""
    return is_event(msg, "subscriptionStatus")


def is_channel_data(msg: Any, channel_name: str | None = None) -> bool:
    """True for a data array; optionally require a specific channel name.

    v1 data frames are lists shaped ``[channelID, payload, channelName, pair]``.
    Because book updates can carry an extra element, the channel name is always the
    *second-to-last* item and the pair is the last.
    """
    if not isinstance(msg, list) or len(msg) < 4:
        return False
    if channel_name is None:
        return True
    # channelName may be suffixed (e.g. "book-10", "ohlc-1"), so match on prefix.
    name = msg[-2]
    return isinstance(name, str) and name.split("-")[0] == channel_name.split("-")[0]


# --------------------------------------------------------------------------- #
# Small accessors
# --------------------------------------------------------------------------- #
def payload(msg: list) -> Any:
    """Return the payload element of a v1 data array (index 1)."""
    return msg[1]


def pair(msg: list) -> str:
    """Return the trading pair of a v1 data array (last element)."""
    return msg[-1]

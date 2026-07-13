"""Ticker channel tests (v1 and v2).

The ticker is level-1 market data: best bid/ask plus rolling stats. We validate the
schema and two invariants that must hold for *any* sane quote:
  * the spread is non-negative (best bid <= best ask), and
  * prices/volumes are positive.
"""

import pytest

from kraken_ws import v1, v2
from kraken_ws.validation import (
    require_keys,
    as_number,
    is_positive,
    is_non_negative,
)

pytestmark = pytest.mark.live


# --------------------------------------------------------------------------- #
# v2 ticker
# --------------------------------------------------------------------------- #
@pytest.fixture
def v2_ticker_snapshot(v2_client):
    """Subscribe to the v2 ticker and return the first snapshot's data object."""
    v2_client.send_json(v2.subscribe("ticker", [v2.DEFAULT_SYMBOL]))
    ack = v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    assert ack.get("success") is True, f"ticker subscribe failed: {ack.get('error')!r}"
    snap = v2_client.wait_for(
        lambda m: v2.is_channel_data(m, "ticker", type_="snapshot"), timeout=15
    )
    return v2.first_data(snap)


@pytest.mark.v2
@pytest.mark.ticker
def test_v2_ticker_schema(v2_ticker_snapshot):
    """TC5: v2 ticker snapshot exposes the documented level-1 fields with numbers."""
    data = v2_ticker_snapshot
    require_keys(
        data,
        ["symbol", "bid", "bid_qty", "ask", "ask_qty", "last", "high", "low", "volume"],
        where="v2 ticker",
    )
    assert data["symbol"] == v2.DEFAULT_SYMBOL
    for field in ["bid", "bid_qty", "ask", "ask_qty", "last", "high", "low", "volume"]:
        as_number(data[field], where=f"v2 ticker.{field}")


@pytest.mark.v2
@pytest.mark.ticker
def test_v2_ticker_spread_non_negative(v2_ticker_snapshot):
    """TC6: best ask >= best bid (the market is not crossed at level 1)."""
    bid = as_number(v2_ticker_snapshot["bid"], where="v2 ticker.bid")
    ask = as_number(v2_ticker_snapshot["ask"], where="v2 ticker.ask")
    assert ask >= bid, f"crossed ticker: ask {ask} < bid {bid}"


@pytest.mark.v2
@pytest.mark.ticker
def test_v2_ticker_prices_positive(v2_ticker_snapshot):
    """TC7: bid/ask prices and quantities are strictly positive."""
    for field in ["bid", "ask", "bid_qty", "ask_qty", "last"]:
        is_positive(v2_ticker_snapshot[field], where=f"v2 ticker.{field}")


# --------------------------------------------------------------------------- #
# v1 ticker
# --------------------------------------------------------------------------- #
@pytest.fixture
def v1_ticker_payload(v1_client):
    """Subscribe to the v1 ticker and return its payload dict.

    v1 ticker payload keys: a=ask, b=bid, c=last close, v=volume, p=vwap,
    t=trade count, l=low, h=high, o=open. Each value is an array of strings.
    """
    v1_client.wait_for(v1.is_system_status, timeout=10)
    v1_client.send_json(v1.subscribe("ticker", [v1.DEFAULT_PAIR]))
    data = v1_client.wait_for(lambda m: v1.is_channel_data(m, "ticker"), timeout=15)
    return v1.payload(data)


@pytest.mark.v1
@pytest.mark.ticker
def test_v1_ticker_schema(v1_ticker_payload):
    """TC8: v1 ticker payload has the expected compact keys with numeric heads."""
    p = v1_ticker_payload
    require_keys(p, ["a", "b", "c", "v", "p", "t", "l", "h", "o"], where="v1 ticker")
    # The first element of each array is the primary quote/price value.
    for key in ["a", "b", "c", "l", "h", "o"]:
        assert isinstance(p[key], list) and p[key], f"v1 ticker.{key} should be a non-empty array"
        as_number(p[key][0], where=f"v1 ticker.{key}[0]")


@pytest.mark.v1
@pytest.mark.ticker
def test_v1_ticker_spread_non_negative(v1_ticker_payload):
    """TC9: v1 best ask (a[0]) >= best bid (b[0])."""
    ask = as_number(v1_ticker_payload["a"][0], where="v1 ticker.a[0]")
    bid = as_number(v1_ticker_payload["b"][0], where="v1 ticker.b[0]")
    assert ask >= bid, f"crossed v1 ticker: ask {ask} < bid {bid}"
    # Volume-weighted average price and 24h volume must be non-negative.
    is_non_negative(v1_ticker_payload["v"][0], where="v1 ticker.v[0]")

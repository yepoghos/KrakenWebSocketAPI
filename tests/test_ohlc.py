"""OHLC (candlestick) channel tests for v1 and v2.

Candles have strong internal invariants that make excellent regression checks:
  * high is the max and low is the min of the {open, high, low, close} set, and
  * successive candle interval timestamps never move backwards.
We also validate the schema of each version's differently-shaped payload.
"""

from datetime import datetime

import pytest

from kraken_ws import v1, v2
from kraken_ws.validation import require_keys, expect_sequence, as_number, is_positive
from conftest import require

pytestmark = pytest.mark.live

INTERVAL = 1  # 1-minute candles: frequent enough to observe several updates quickly.


def _parse_rfc3339(value: str) -> datetime:
    """Parse Kraken's RFC3339 timestamps (``...Z``) into aware datetimes."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# v2 OHLC
# --------------------------------------------------------------------------- #
@pytest.fixture
def v2_ohlc_candle(v2_client):
    """Subscribe to v2 OHLC and return the first candle data object."""
    v2_client.send_json(v2.subscribe("ohlc", [v2.DEFAULT_SYMBOL], interval=INTERVAL))
    ack = v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    assert ack.get("success") is True, f"ohlc subscribe failed: {ack.get('error')!r}"
    snap = v2_client.wait_for(lambda m: v2.is_channel_data(m, "ohlc"), timeout=15)
    return v2.first_data(snap)


@pytest.mark.v2
@pytest.mark.ohlc
def test_v2_ohlc_schema(v2_ohlc_candle):
    """TC15: v2 candle carries OHLC/vwap/volume fields with the right types."""
    c = v2_ohlc_candle
    require_keys(
        c,
        ["symbol", "open", "high", "low", "close", "vwap", "trades", "volume", "interval", "interval_begin"],
        where="v2 ohlc",
    )
    for field in ["open", "high", "low", "close", "vwap", "volume"]:
        as_number(c[field], where=f"v2 ohlc.{field}")
    assert isinstance(c["trades"], int) and c["trades"] >= 0
    assert c["interval"] == INTERVAL


@pytest.mark.v2
@pytest.mark.ohlc
def test_v2_ohlc_invariants(v2_ohlc_candle):
    """TC16: high == max(o,h,l,c) and low == min(o,h,l,c); prices are positive."""
    c = v2_ohlc_candle
    o, h, l, cl = (as_number(c[k], where=f"v2 ohlc.{k}") for k in ("open", "high", "low", "close"))
    for v in (o, h, l, cl):
        assert v > 0, "candle prices must be positive"
    assert h >= max(o, l, cl), f"high {h} not the maximum of the candle"
    assert l <= min(o, h, cl), f"low {l} not the minimum of the candle"


@pytest.mark.v2
@pytest.mark.ohlc
def test_v2_ohlc_interval_non_decreasing(v2_client):
    """TC17: candle `interval_begin` timestamps never decrease across updates."""
    v2_client.send_json(v2.subscribe("ohlc", [v2.DEFAULT_SYMBOL], interval=INTERVAL))
    v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    msgs = v2_client.collect(lambda m: v2.is_channel_data(m, "ohlc"), count=8, timeout=25)
    require(msgs, 2, "not enough v2 ohlc updates")

    times = [_parse_rfc3339(v2.first_data(m)["interval_begin"]) for m in msgs]
    for earlier, later in zip(times, times[1:]):
        assert later >= earlier, f"candle interval went backwards: {later} < {earlier}"


# --------------------------------------------------------------------------- #
# v1 OHLC
# --------------------------------------------------------------------------- #
@pytest.mark.v1
@pytest.mark.ohlc
def test_v1_ohlc_schema_and_invariants(v1_client):
    """TC18: v1 OHLC array [time, etime, open, high, low, close, vwap, vol, count].

    Validates the positional schema and the same high/low candle invariants.
    """
    v1_client.wait_for(v1.is_system_status, timeout=10)
    v1_client.send_json(v1.subscribe("ohlc", [v1.DEFAULT_PAIR], interval=INTERVAL))
    data = v1_client.wait_for(lambda m: v1.is_channel_data(m, "ohlc"), timeout=15)
    candle = v1.payload(data)
    expect_sequence(candle, where="v1 ohlc", min_len=9)

    time, etime = as_number(candle[0], where="v1 ohlc.time"), as_number(candle[1], where="v1 ohlc.etime")
    assert etime >= time, "candle end time precedes start time"
    o = is_positive(candle[2], where="v1 ohlc.open")
    h = is_positive(candle[3], where="v1 ohlc.high")
    l = is_positive(candle[4], where="v1 ohlc.low")
    cl = is_positive(candle[5], where="v1 ohlc.close")
    assert h >= max(o, l, cl), f"v1 high {h} not the maximum"
    assert l <= min(o, h, cl), f"v1 low {l} not the minimum"

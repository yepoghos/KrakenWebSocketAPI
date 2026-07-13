"""Trade channel tests for v1 and v2.

Trades are the ground-truth transaction feed. We check the schema, that each trade is
economically sane (known side, positive price and quantity), and that trade timestamps
are monotonically non-decreasing within a batch — a common expectation downstream
consumers rely on for ordering.
"""

from datetime import datetime

import pytest

from kraken_ws import v1, v2
from kraken_ws.validation import require_keys, expect_sequence, is_positive, one_of, as_number
from conftest import require

pytestmark = pytest.mark.live


def _parse_rfc3339(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# v2 trade
# --------------------------------------------------------------------------- #
@pytest.fixture
def v2_trades(v2_client):
    """Subscribe to v2 trades and return a flat list of trade objects."""
    v2_client.send_json(v2.subscribe("trade", [v2.DEFAULT_SYMBOL]))
    ack = v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    assert ack.get("success") is True, f"trade subscribe failed: {ack.get('error')!r}"
    msgs = v2_client.collect(lambda m: v2.is_channel_data(m, "trade"), count=5, timeout=25)
    trades = [t for m in msgs for t in m["data"]]
    return trades


@pytest.mark.v2
@pytest.mark.trade
def test_v2_trade_schema(v2_trades):
    """TC19: each v2 trade has symbol/side/price/qty/ord_type/trade_id/timestamp."""
    require(v2_trades, 1, "no v2 trades observed")
    for t in v2_trades:
        require_keys(
            t,
            ["symbol", "side", "price", "qty", "ord_type", "trade_id", "timestamp"],
            where="v2 trade",
        )
        assert t["symbol"] == v2.DEFAULT_SYMBOL
        assert isinstance(t["trade_id"], int)


@pytest.mark.v2
@pytest.mark.trade
def test_v2_trade_values_valid(v2_trades):
    """TC20: side is buy/sell; price and qty are positive; ord_type is known."""
    require(v2_trades, 1, "no v2 trades observed")
    for t in v2_trades:
        one_of(t["side"], ["buy", "sell"], where="v2 trade.side")
        one_of(t["ord_type"], ["limit", "market"], where="v2 trade.ord_type")
        is_positive(t["price"], where="v2 trade.price")
        is_positive(t["qty"], where="v2 trade.qty")


@pytest.mark.v2
@pytest.mark.trade
def test_v2_trade_timestamps_non_decreasing(v2_trades):
    """TC21: trade timestamps within a batch never move backwards."""
    require(v2_trades, 2, "need >=2 v2 trades to compare ordering")
    times = [_parse_rfc3339(t["timestamp"]) for t in v2_trades]
    for earlier, later in zip(times, times[1:]):
        assert later >= earlier, f"v2 trade time regressed: {later} < {earlier}"


# --------------------------------------------------------------------------- #
# v1 trade
# --------------------------------------------------------------------------- #
@pytest.fixture
def v1_trades(v1_client):
    """Subscribe to v1 trades and return a flat list of [price, vol, time, side, ...]."""
    v1_client.wait_for(v1.is_system_status, timeout=10)
    v1_client.send_json(v1.subscribe("trade", [v1.DEFAULT_PAIR]))
    msgs = v1_client.collect(lambda m: v1.is_channel_data(m, "trade"), count=5, timeout=25)
    return [trade for m in msgs for trade in v1.payload(m)]


@pytest.mark.v1
@pytest.mark.trade
def test_v1_trade_schema_and_values(v1_trades):
    """TC22: v1 trade array [price, vol, time, side, ordType, misc] with sane values.

    v1 encodes side as 'b'/'s' and order type as 'm'/'l'.
    """
    require(v1_trades, 1, "no v1 trades observed")
    for tr in v1_trades:
        expect_sequence(tr, where="v1 trade", min_len=6)
        is_positive(tr[0], where="v1 trade.price")
        is_positive(tr[1], where="v1 trade.volume")
        one_of(tr[3], ["b", "s"], where="v1 trade.side")
        one_of(tr[4], ["m", "l"], where="v1 trade.ordType")


@pytest.mark.v1
@pytest.mark.trade
def test_v1_trade_timestamps_non_decreasing(v1_trades):
    """TC23: v1 trade epoch timestamps are non-decreasing within a batch."""
    require(v1_trades, 2, "need >=2 v1 trades to compare ordering")
    times = [as_number(tr[2], where="v1 trade.time") for tr in v1_trades]
    for earlier, later in zip(times, times[1:]):
        assert later >= earlier, f"v1 trade time regressed: {later} < {earlier}"

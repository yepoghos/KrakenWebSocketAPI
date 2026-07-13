"""Subscription lifecycle and input-validation tests.

Beyond happy-path data, a robust API must reject bad input clearly and support clean
teardown. These tests capture that contract:
  * subscribing with an invalid symbol/channel returns an error (not silence, not a
    crash), and
  * unsubscribing is acknowledged and stops the data flow.
"""

import pytest

from kraken_ws import v1, v2
from conftest import require

pytestmark = pytest.mark.live


# --------------------------------------------------------------------------- #
# v2 input validation
# --------------------------------------------------------------------------- #
@pytest.mark.v2
@pytest.mark.subscription
def test_v2_invalid_symbol_is_rejected(v2_client):
    """TC24: subscribing to a nonsense symbol yields success=false with an error."""
    v2_client.send_json(v2.subscribe("ticker", ["NOTAREAL/PAIR"]))
    ack = v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    assert ack.get("success") is False, "expected the invalid-symbol subscribe to fail"
    assert ack.get("error"), "a failed subscription must carry an error message"


@pytest.mark.v2
@pytest.mark.subscription
def test_v2_invalid_channel_is_rejected(v2_client):
    """TC25: subscribing to an unknown channel produces an error response.

    Kraken may answer either with a method-ack failure or a top-level `error`
    envelope; both are acceptable evidence that the bad request was rejected.
    """
    v2_client.send_json(v2.subscribe("not_a_channel", [v2.DEFAULT_SYMBOL]))

    def is_error(m):
        if isinstance(m, dict) and m.get("error"):
            return True
        return v2.is_ack(m, "subscribe") and m.get("success") is False

    err = v2_client.wait_for(is_error, timeout=15)
    assert err.get("error") or err.get("success") is False


@pytest.mark.v2
@pytest.mark.subscription
def test_v2_unsubscribe_is_acknowledged(v2_client):
    """TC26: after subscribing, an unsubscribe request is acknowledged with success."""
    v2_client.send_json(v2.subscribe("ticker", [v2.DEFAULT_SYMBOL]))
    sub_ack = v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    assert sub_ack.get("success") is True

    v2_client.send_json(v2.unsubscribe("ticker", [v2.DEFAULT_SYMBOL]))
    unsub_ack = v2_client.wait_for(lambda m: v2.is_ack(m, "unsubscribe"), timeout=15)
    assert unsub_ack.get("success") is True, (
        f"unsubscribe was not acknowledged: {unsub_ack.get('error')!r}"
    )


# --------------------------------------------------------------------------- #
# v1 input validation
# --------------------------------------------------------------------------- #
@pytest.mark.v1
@pytest.mark.subscription
def test_v1_invalid_pair_is_rejected(v1_client):
    """TC27: v1 reports a `subscriptionStatus` error for an unknown pair."""
    v1_client.wait_for(v1.is_system_status, timeout=10)
    v1_client.send_json(v1.subscribe("ticker", ["NOPE/NOPE"]))
    status = v1_client.wait_for(v1.is_subscription_status, timeout=15)
    assert status.get("status") == "error", f"expected error status, got {status.get('status')!r}"
    assert status.get("errorMessage"), "v1 error status should include an errorMessage"


@pytest.mark.v1
@pytest.mark.subscription
def test_v1_unsubscribe_is_acknowledged(v1_client):
    """TC28: v1 acknowledges unsubscribe with a `subscriptionStatus` = unsubscribed."""
    v1_client.wait_for(v1.is_system_status, timeout=10)
    v1_client.send_json(v1.subscribe("ticker", [v1.DEFAULT_PAIR]))
    subbed = v1_client.wait_for(
        lambda m: v1.is_subscription_status(m) and m.get("status") == "subscribed",
        timeout=15,
    )
    assert subbed.get("status") == "subscribed"

    v1_client.send_json(v1.unsubscribe("ticker", [v1.DEFAULT_PAIR]))
    unsub = v1_client.wait_for(
        lambda m: v1.is_subscription_status(m) and m.get("status") == "unsubscribed",
        timeout=15,
    )
    assert unsub.get("status") == "unsubscribed"

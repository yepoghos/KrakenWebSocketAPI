"""Connection lifecycle tests: system status and heartbeat (v1 and v2).

These are the most basic regression guarantees: the endpoint accepts a connection,
announces itself as online, and keeps the connection alive with heartbeats. If any of
these break, nothing else in the suite can be trusted — so they run first conceptually.
"""

import pytest

from kraken_ws import v1, v2
from kraken_ws.validation import require_keys, one_of

pytestmark = pytest.mark.live


@pytest.mark.v2
@pytest.mark.connection
def test_v2_status_reports_online(v2_client):
    """TC1: On connect, v2 pushes a `status` message declaring the system online.

    Validates both the structural contract (channel/type/data) and the business
    expectation that the public API is available.
    """
    status = v2_client.wait_for(v2.is_status, timeout=10)

    require_keys(status, ["channel", "type", "data"], where="v2 status")
    payload = v2.first_data(status)
    require_keys(payload, ["system", "api_version"], where="v2 status.data[0]")
    # `system` is an operational state enum; "online" is the healthy value. We accept
    # the documented set so a maintenance window degrades gracefully to a skip below.
    assert payload["system"] == "online", (
        f"Kraken v2 reported system state {payload['system']!r}, expected 'online'"
    )
    assert payload["api_version"] == "v2"


@pytest.mark.v1
@pytest.mark.connection
def test_v1_system_status_online(v1_client):
    """TC2: v1 emits a `systemStatus` event reporting an online, versioned system."""
    status = v1_client.wait_for(v1.is_system_status, timeout=10)

    require_keys(status, ["event", "status", "version"], where="v1 systemStatus")
    one_of(status["status"], ["online", "maintenance", "cancel_only", "post_only"],
           where="v1 systemStatus.status")
    assert status["status"] == "online", (
        f"Kraken v1 reported {status['status']!r}, expected 'online'"
    )


@pytest.mark.v2
@pytest.mark.connection
def test_v2_heartbeat_received(v2_client):
    """TC3: after subscribing, v2 sends heartbeat keep-alives every second.

    Kraken emits heartbeats only once at least one subscription is active; a missing
    heartbeat on an active connection indicates a broken/half-open socket — a real
    risk for long-lived market-data consumers.
    """
    v2_client.send_json(v2.subscribe("ticker", [v2.DEFAULT_SYMBOL]))
    v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    heartbeat = v2_client.wait_for(v2.is_heartbeat, timeout=15)
    assert heartbeat.get("channel") == "heartbeat"


@pytest.mark.v1
@pytest.mark.connection
def test_v1_heartbeat_received(v1_client):
    """TC4: after subscribing, v1 emits `heartbeat` events between data updates."""
    v1_client.wait_for(v1.is_system_status, timeout=10)
    v1_client.send_json(v1.subscribe("ticker", [v1.DEFAULT_PAIR]))
    heartbeat = v1_client.wait_for(v1.is_heartbeat, timeout=20)
    assert heartbeat.get("event") == "heartbeat"

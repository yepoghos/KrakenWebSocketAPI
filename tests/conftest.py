"""Shared pytest fixtures and helpers for the Kraken WebSocket test suite.

Everything that touches the network lives here so the individual test modules stay
focused on *behaviour* (invariants, schemas) rather than plumbing.

Key ideas
---------
* **Fresh connection per test.** Each fixture yields a brand-new client and closes it
  on teardown. WebSocket feeds are stateful (a subscription mutates the connection),
  so sharing a socket across tests would create ordering/coupling bugs — exactly the
  kind of flakiness a regression suite must avoid.
* **Network resilience.** :func:`require` turns "the market/feed was silent" into a
  ``pytest.skip`` instead of a false failure, while genuine invariant violations still
  fail loudly. This matches the assessment's "capture existing behaviour" goal: we
  assert hard on correctness, softly on data availability.
* **Slow/network tests are marked ``live``** so they can be selected or excluded
  (``pytest -m "not live"``).
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from kraken_ws import KrakenWSClient
from kraken_ws import v1 as _v1
from kraken_ws import v2 as _v2

# Re-export the adapters so tests can do `from conftest import v1, v2` if preferred,
# though importing from the package directly works too.
v1 = _v1
v2 = _v2

# Allow CI to dial timeouts up/down without editing code (e.g. slower shared runners).
DEFAULT_TIMEOUT = float(os.environ.get("KRAKEN_WS_TIMEOUT", "20"))


# --------------------------------------------------------------------------- #
# Connection fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def v2_client():
    """A connected v2 client (BTC/USD friendly). Closed automatically on teardown."""
    client = KrakenWSClient(v2.URL, recv_timeout=DEFAULT_TIMEOUT)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def v2_client_decimal():
    """A v2 client that decodes JSON numbers as ``Decimal``.

    Required only by the order-book checksum test, which needs the exact wire digits.
    """
    client = KrakenWSClient(v2.URL, recv_timeout=DEFAULT_TIMEOUT, parse_float=Decimal)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def v1_client():
    """A connected v1 client (XBT/USD friendly). Closed automatically on teardown."""
    client = KrakenWSClient(v1.URL, recv_timeout=DEFAULT_TIMEOUT)
    try:
        yield client
    finally:
        client.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def require(collection, minimum: int, reason: str):
    """Skip the test if fewer than ``minimum`` messages/samples were gathered.

    This is the guardrail that keeps the suite trustworthy on a live exchange: absence
    of data is an environmental condition (quiet market, throttled runner), not a
    product defect, so we skip rather than fail. When data *is* present, the caller
    goes on to assert the real invariants.
    """
    if len(collection) < minimum:
        pytest.skip(f"{reason}: got {len(collection)} of {minimum} required samples")


def subscribe_and_wait_v2(client, request_builder, data_predicate, *, timeout=DEFAULT_TIMEOUT):
    """Send a v2 subscribe request, assert the ack succeeded, and return first data.

    Centralises the common "subscribe → check ack → await first data" flow so each
    test does not repeat it.
    """
    client.send_json(request_builder)
    ack = client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=timeout)
    assert ack.get("success") is True, f"v2 subscribe failed: {ack.get('error')!r}"
    return client.wait_for(data_predicate, timeout=timeout)

"""kraken_ws - a small, from-scratch client toolkit for Kraken's public WebSocket API.

This package deliberately contains *only* thin, well-documented helpers built on top
of the `websocket-client` library and the Python standard library. It is not a
full-featured Kraken SDK; it exists purely to make the regression test suite in
`tests/` clear, deterministic, and maintainable.

Modules
-------
client      : transport-level wrapper (connect / send / receive / collect).
v1          : Kraken WebSocket API v1 helpers (subscribe payloads + message parsing).
v2          : Kraken WebSocket API v2 helpers (subscribe payloads + message parsing).
validation  : stdlib-only schema / type / predicate validators.
checksum    : CRC32 order-book checksum computation (v1 and v2).
"""

from .client import KrakenWSClient, WSTimeout

__all__ = ["KrakenWSClient", "WSTimeout"]

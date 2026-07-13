"""CRC32 order-book checksum computation for Kraken WebSocket v1 and v2.

Both API versions publish a CRC32 checksum with every order-book message so a client
can prove its locally maintained book is byte-for-byte in sync with the exchange.
Reproducing that checksum is one of the strongest correctness tests we can run
against the book feed, so it lives in its own module.

The two versions share the same core idea but differ in the raw shape of the data:

* **v2** delivers bids/asks as dicts ``{"price": ..., "qty": ...}`` and the checksum
  covers the top 10 levels: asks (price low→high) then bids (price high→low).
* **v1** delivers bids/asks as ``[price, volume, timestamp, ...]`` arrays and uses
  the same ordering and formatting rules.

Formatting rule for every price/qty (per Kraken's guide):
    1. Take the value's *exact* decimal string (why we parse with ``Decimal``).
    2. Remove the decimal point.
    3. Remove leading zeros.
Concatenate all formatted asks then all formatted bids, CRC32 the ASCII bytes, and
compare against the unsigned 32-bit ``checksum`` from the message.
"""

from __future__ import annotations

import zlib
from decimal import Decimal
from typing import Sequence


def _format_token(value: object) -> str:
    """Return Kraken's checksum token for a single price or quantity.

    ``value`` should be a ``Decimal`` (or a string) carrying the exact digits Kraken
    sent. Using a binary ``float`` here would silently corrupt the checksum, so we
    normalise via ``Decimal`` and avoid scientific notation.
    """
    # `Decimal` -> fixed-point string without exponent (e.g. "0.00100000").
    text = format(Decimal(str(value)), "f")
    # Remove the decimal point, then strip leading zeros. `lstrip("0")` on a value
    # like "000100000" yields "100000"; an all-zero value collapses to "" which is
    # the correct Kraken representation for a zero token.
    digits = text.replace(".", "").lstrip("0")
    return digits


def _crc32_of(payload: str) -> int:
    """CRC32 of an ASCII string as an unsigned 32-bit integer."""
    return zlib.crc32(payload.encode("ascii")) & 0xFFFFFFFF


def crc32_v2(asks_top10: Sequence[dict], bids_top10: Sequence[dict]) -> int:
    """Compute the v2 book checksum.

    Parameters
    ----------
    asks_top10:
        Up to 10 ask levels ``{"price": ..., "qty": ...}`` sorted price low→high.
    bids_top10:
        Up to 10 bid levels sorted price high→low.
    """
    parts: list[str] = []
    for level in asks_top10:
        parts.append(_format_token(level["price"]))
        parts.append(_format_token(level["qty"]))
    for level in bids_top10:
        parts.append(_format_token(level["price"]))
        parts.append(_format_token(level["qty"]))
    return _crc32_of("".join(parts))


def crc32_v1(asks_top10: Sequence[Sequence], bids_top10: Sequence[Sequence]) -> int:
    """Compute the v1 book checksum.

    v1 levels are arrays ``[price, volume, timestamp, ...]``; only the first two
    fields participate in the checksum. Ordering matches v2 (asks low→high, then
    bids high→low).
    """
    parts: list[str] = []
    for level in asks_top10:
        parts.append(_format_token(level[0]))  # price
        parts.append(_format_token(level[1]))  # volume
    for level in bids_top10:
        parts.append(_format_token(level[0]))
        parts.append(_format_token(level[1]))
    return _crc32_of("".join(parts))

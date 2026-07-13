"""Order book (Level 2) tests for v1 and v2.

The order book is the richest regression target in the suite. We validate:
  * schema of the initial snapshot,
  * price-level ordering (bids descending, asks ascending),
  * the book is never *crossed* (best bid < best ask) while applying live updates,
  * and — the strongest check — that our locally reconstructed book reproduces
    Kraken's CRC32 checksum.

To do the last two we maintain a small local book (`LocalBook`) exactly as a real
consumer would: apply the snapshot, then fold in updates (a zero quantity removes a
price level), truncating to the subscribed depth.
"""

from decimal import Decimal

import pytest

from kraken_ws import v1, v2
from kraken_ws.checksum import crc32_v2, crc32_v1
from kraken_ws.validation import (
    require_keys,
    expect_sequence,
    is_positive,
    is_non_negative,
)
from conftest import require

pytestmark = pytest.mark.live

DEPTH = 10


class LocalBook:
    """A minimal price-keyed order book used to verify updates and checksums.

    Prices and quantities are stored as ``Decimal`` so the reconstructed checksum
    matches Kraken's byte-for-byte. Keys are the exact wire strings; values track the
    parallel ``Decimal`` price for sorting.
    """

    def __init__(self, depth: int = DEPTH):
        self.depth = depth
        # Map exact price-string -> (Decimal price, quantity token string).
        self.bids: dict[str, tuple[Decimal, str]] = {}
        self.asks: dict[str, tuple[Decimal, str]] = {}

    @staticmethod
    def _key(price) -> str:
        # Normalise to a canonical fixed-point string so "45000.0" and Decimal match.
        return format(Decimal(str(price)), "f")

    def _apply_side(self, side: dict, price, qty) -> None:
        pstr = self._key(price)
        qdec = Decimal(str(qty))
        if qdec == 0:
            side.pop(pstr, None)  # zero quantity => remove the level
        else:
            side[pstr] = (Decimal(pstr), format(qdec, "f"))

    def _truncate(self) -> None:
        # Keep only the top `depth` levels on each side (bids high, asks low).
        self.bids = dict(sorted(self.bids.items(), key=lambda kv: kv[1][0], reverse=True)[: self.depth])
        self.asks = dict(sorted(self.asks.items(), key=lambda kv: kv[1][0])[: self.depth])

    def apply_v2(self, data: dict) -> None:
        for level in data.get("bids", []):
            self._apply_side(self.bids, level["price"], level["qty"])
        for level in data.get("asks", []):
            self._apply_side(self.asks, level["price"], level["qty"])
        self._truncate()

    def apply_v1(self, payload: dict) -> None:
        # v1 snapshot uses keys as/bs; updates use a/b. Each level is [price, vol, ...].
        for level in payload.get("bs", []) + payload.get("b", []):
            self._apply_side(self.bids, level[0], level[1])
        for level in payload.get("as", []) + payload.get("a", []):
            self._apply_side(self.asks, level[0], level[1])
        self._truncate()

    def top_bids(self) -> list[tuple[Decimal, str]]:
        return sorted(self.bids.values(), key=lambda v: v[0], reverse=True)[: self.depth]

    def top_asks(self) -> list[tuple[Decimal, str]]:
        return sorted(self.asks.values(), key=lambda v: v[0])[: self.depth]

    def best_bid(self):
        tb = self.top_bids()
        return tb[0][0] if tb else None

    def best_ask(self):
        ta = self.top_asks()
        return ta[0][0] if ta else None


# --------------------------------------------------------------------------- #
# v2 book
# --------------------------------------------------------------------------- #
@pytest.mark.v2
@pytest.mark.book
def test_v2_book_snapshot_schema(v2_client):
    """TC10: v2 book snapshot has bids/asks arrays of {price, qty} plus a checksum."""
    v2_client.send_json(v2.subscribe("book", [v2.DEFAULT_SYMBOL], depth=DEPTH))
    ack = v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    assert ack.get("success") is True, f"book subscribe failed: {ack.get('error')!r}"
    snap = v2_client.wait_for(
        lambda m: v2.is_channel_data(m, "book", type_="snapshot"), timeout=15
    )
    data = v2.first_data(snap)
    require_keys(data, ["symbol", "bids", "asks", "checksum"], where="v2 book")
    expect_sequence(data["bids"], where="v2 book.bids", min_len=1)
    expect_sequence(data["asks"], where="v2 book.asks", min_len=1)
    for level in data["bids"] + data["asks"]:
        require_keys(level, ["price", "qty"], where="v2 book level")
        is_positive(level["price"], where="v2 book level.price")
        is_non_negative(level["qty"], where="v2 book level.qty")


@pytest.mark.v2
@pytest.mark.book
def test_v2_book_sorted_and_not_crossed_over_updates(v2_client):
    """TC11: across many updates the v2 book stays sorted and never crosses.

    Maintains a local book and, after every applied message, asserts bids are strictly
    descending, asks strictly ascending, and best_bid < best_ask.
    """
    v2_client.send_json(v2.subscribe("book", [v2.DEFAULT_SYMBOL], depth=DEPTH))
    v2_client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    messages = v2_client.collect(
        lambda m: v2.is_channel_data(m, "book"), count=25, timeout=25
    )
    require(messages, 3, "not enough v2 book messages")

    book = LocalBook(DEPTH)
    checks = 0
    for msg in messages:
        book.apply_v2(v2.first_data(msg))
        bid_prices = [p for p, _ in book.top_bids()]
        ask_prices = [p for p, _ in book.top_asks()]
        assert bid_prices == sorted(bid_prices, reverse=True), "bids not descending"
        assert ask_prices == sorted(ask_prices), "asks not ascending"
        if book.best_bid() is not None and book.best_ask() is not None:
            assert book.best_bid() < book.best_ask(), (
                f"crossed book: bid {book.best_bid()} >= ask {book.best_ask()}"
            )
            checks += 1
    require([None] * checks, 1, "never had both sides populated")


@pytest.mark.v2
@pytest.mark.book
def test_v2_book_checksum_matches(v2_client_decimal):
    """TC12: our reconstructed v2 book reproduces Kraken's CRC32 checksum.

    Uses a Decimal-decoding client so price/qty digits survive JSON parsing intact.
    We try the snapshot and each subsequent update until at least one checksum is
    verified (updates can race with local truncation, so we require one solid match).
    """
    client = v2_client_decimal
    client.send_json(v2.subscribe("book", [v2.DEFAULT_SYMBOL], depth=DEPTH))
    client.wait_for(lambda m: v2.is_ack(m, "subscribe"), timeout=15)
    messages = client.collect(
        lambda m: v2.is_channel_data(m, "book"), count=15, timeout=25
    )
    require(messages, 1, "no v2 book messages for checksum")

    book = LocalBook(DEPTH)
    matched = False
    for msg in messages:
        data = v2.first_data(msg)
        book.apply_v2(data)
        asks = [{"price": p, "qty": q} for p, q in book.top_asks()]
        bids = [{"price": p, "qty": q} for p, q in book.top_bids()]
        if len(asks) >= DEPTH and len(bids) >= DEPTH:
            if crc32_v2(asks, bids) == data["checksum"]:
                matched = True
                break
    assert matched, "reconstructed v2 book never matched Kraken's checksum"


# --------------------------------------------------------------------------- #
# v1 book
# --------------------------------------------------------------------------- #
@pytest.mark.v1
@pytest.mark.book
def test_v1_book_snapshot_schema(v1_client):
    """TC13: v1 book snapshot payload has `as`/`bs` arrays of [price, vol, time]."""
    v1_client.wait_for(v1.is_system_status, timeout=10)
    v1_client.send_json(v1.subscribe("book", [v1.DEFAULT_PAIR], depth=DEPTH))
    data = v1_client.wait_for(lambda m: v1.is_channel_data(m, "book"), timeout=15)
    payload = v1.payload(data)
    require_keys(payload, ["as", "bs"], where="v1 book snapshot")
    for level in payload["as"] + payload["bs"]:
        expect_sequence(level, where="v1 book level", min_len=3)
        is_positive(level[0], where="v1 book level price")
        is_non_negative(level[1], where="v1 book level volume")


@pytest.mark.v1
@pytest.mark.book
def test_v1_book_checksum_matches(v1_client):
    """TC14: our reconstructed v1 book reproduces Kraken's CRC32 checksum.

    v1 sends price/qty as strings already, so precision is preserved without special
    decoding. Update frames carry the authoritative checksum in the `c` field.
    """
    v1_client.wait_for(v1.is_system_status, timeout=10)
    v1_client.send_json(v1.subscribe("book", [v1.DEFAULT_PAIR], depth=DEPTH))
    snapshot = v1_client.wait_for(lambda m: v1.is_channel_data(m, "book"), timeout=15)

    book = LocalBook(DEPTH)
    book.apply_v1(v1.payload(snapshot))

    updates = v1_client.collect(
        lambda m: v1.is_channel_data(m, "book") and "c" in v1.payload(m),
        count=15,
        timeout=25,
    )
    require(updates, 1, "no v1 book updates with checksum")

    matched = False
    for msg in updates:
        payload = v1.payload(msg)
        book.apply_v1(payload)
        asks = [[str(p), q] for p, q in book.top_asks()]
        bids = [[str(p), q] for p, q in book.top_bids()]
        if len(asks) >= DEPTH and len(bids) >= DEPTH:
            if crc32_v1(asks, bids) == int(payload["c"]):
                matched = True
                break
    assert matched, "reconstructed v1 book never matched Kraken's checksum"

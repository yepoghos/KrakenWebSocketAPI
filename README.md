# Kraken WebSocket API — QA Automation Test Suite

A from-scratch, `pytest`-based regression suite that exercises Kraken's **public**
WebSocket API. It covers **both** protocol versions:

* **v1** — `wss://ws.kraken.com`
* **v2** — `wss://ws.kraken.com/v2`

No Kraken account or API key is required: only public market-data feeds are used.

## What it tests

28 test cases across 6 areas and both API versions:

| Area | Representative checks |
|------|-----------------------|
| Connection / status | system reports `online`; heartbeats arrive on active subscriptions |
| Ticker | schema; best bid ≤ best ask; prices/volumes positive |
| Book (L2) | snapshot schema; bids desc / asks asc; **never crossed** across live updates; **CRC32 checksum reconstruction** |
| OHLC | schema; `high == max`, `low == min`; interval timestamps non-decreasing |
| Trade | schema; side ∈ {buy/sell}; positive price/qty; timestamps non-decreasing |
| Subscription / input validation | invalid symbol/channel rejected with error; clean unsubscribe |

See `NOTES.txt` for the full strategy and rationale.

## Project layout

```
.
├─ src/kraken_ws/          # from-scratch client toolkit (no third-party Kraken client)
│  ├─ client.py            # thin wrapper over websocket-client (connect/recv/collect)
│  ├─ v1.py / v2.py        # per-version subscribe payloads + message parsing
│  ├─ validation.py        # stdlib-only schema/type validators
│  └─ checksum.py          # CRC32 order-book checksum (v1 & v2)
├─ tests/                  # pytest suite (conftest.py + one module per channel)
├─ Dockerfile             # builds a ready-to-run test image
├─ requirements.txt        # pytest + websocket-client only
└─ pytest.ini             # CI-style verbose output + markers
```

## Running with Docker (recommended)

The image runs the whole suite and exits non-zero on any failure, exactly as a CI
step would. It needs outbound network access to the Kraken endpoints at run time.

```bash
docker build -t kraken-ws-tests .
docker run --rm kraken-ws-tests
```

You can forward pytest arguments after the image name, e.g. run only v2 ticker tests:

```bash
docker run --rm kraken-ws-tests -m "v2 and ticker"
```

## Running locally

Requires Python 3.11+ and network access.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate
pip install -r requirements.txt
pytest
```

`pytest.ini` sets `pythonpath = src`, so `import kraken_ws` works without installing
the package.

## Useful invocations

```bash
pytest -m v2                     # only v2 API tests
pytest -m "book or ticker"       # only book/ticker channels
pytest -m "not live"             # skip anything needing the network (collects only)
pytest tests/test_book.py -v     # a single module
```

Markers are declared in `pytest.ini`: `live`, `v1`, `v2`, `book`, `ohlc`, `ticker`,
`trade`, `connection`, `subscription`.

## Configuration

* `KRAKEN_WS_TIMEOUT` (seconds, default `20`) — receive timeout for the collectors.
  Increase it on slow/shared CI runners:

  ```bash
  KRAKEN_WS_TIMEOUT=40 pytest
  ```

## Network resilience

Every receive is time-bounded. When a feed is legitimately quiet (thin market, throttled
runner) a test **skips** rather than fails, while genuine invariant violations (crossed
book, bad schema, checksum mismatch) **fail** loudly. This keeps the suite trustworthy
against a live exchange.

# Kraken WebSocket QA test suite — container image.
#
# The image builds a ready-to-run test environment. Its entry-point executes the
# pytest suite against Kraken's *public* WebSocket API and exits non-zero on any
# failure, so it behaves correctly as a CI step:
#
#   docker build -t kraken-ws-tests .
#   docker run --rm kraken-ws-tests
#
# Note: the tests hit the live public API, so the container needs outbound network
# access to wss://ws.kraken.com and wss://ws.kraken.com/v2 at run time.

# Pinned, slim base keeps the image small and reproducible.
FROM python:3.12-slim

# Standard Python container hygiene:
#   PYTHONDONTWRITEBYTECODE - no .pyc clutter in the image layers.
#   PYTHONUNBUFFERED        - stream test output live to the CI log (no buffering).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (separate layer) so code changes don't bust the pip
# cache and rebuilds stay fast.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project (source, tests, pytest config).
COPY . .

# `pytest.ini` sets `pythonpath = src`, so `import kraken_ws` resolves without an
# editable install. Run as a non-root user (good practice for CI images) and give it
# ownership of /app so pytest can write its cache without permission warnings.
RUN useradd --create-home --uid 1000 tester && chown -R tester /app
USER tester

# Entry-point: run the suite. Any test failure -> non-zero exit -> failed pipeline.
# Extra arguments passed to `docker run` are forwarded to pytest, e.g.
#   docker run --rm kraken-ws-tests -m "v2 and ticker"
ENTRYPOINT ["python", "-m", "pytest"]
CMD []

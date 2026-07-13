"""Standard-library-only validation helpers.

The assessment restricts third-party dependencies to a WebSocket library and a test
framework, so we deliberately do **not** use `jsonschema`. Instead this module offers
a few small, composable validators that give clear, assertion-friendly error messages.

They are intentionally permissive about *extra* fields: Kraken occasionally adds new
keys, and a regression suite that captures existing behaviour should not break just
because the payload grew. We assert on the fields we care about, not on the absence
of others.
"""

from __future__ import annotations

import numbers
from typing import Any, Iterable, Mapping, Sequence


class SchemaError(AssertionError):
    """Raised when a message fails structural/type validation.

    Subclassing ``AssertionError`` means pytest reports these exactly like a normal
    failed ``assert`` and applies its usual introspection/formatting.
    """


def require_keys(obj: Mapping, keys: Iterable[str], *, where: str = "object") -> None:
    """Assert that ``obj`` is a mapping containing every key in ``keys``."""
    if not isinstance(obj, Mapping):
        raise SchemaError(f"{where}: expected a mapping, got {type(obj).__name__}")
    missing = [k for k in keys if k not in obj]
    if missing:
        raise SchemaError(f"{where}: missing required keys {missing} (present: {sorted(obj)})")


def expect_type(value: Any, types: type | tuple[type, ...], *, where: str) -> Any:
    """Assert ``value`` is an instance of ``types`` and return it unchanged."""
    if not isinstance(value, types):
        names = (
            types.__name__
            if isinstance(types, type)
            else "/".join(t.__name__ for t in types)
        )
        raise SchemaError(f"{where}: expected {names}, got {type(value).__name__} ({value!r})")
    return value


def as_number(value: Any, *, where: str) -> float:
    """Coerce a Kraken numeric field to ``float``.

    Kraken sends numbers either as JSON numbers (v2) or as strings (v1, e.g.
    ``"12345.6"``). Both are valid; booleans are explicitly rejected because in
    Python ``bool`` is a subclass of ``int`` and would otherwise slip through.
    """
    if isinstance(value, bool):
        raise SchemaError(f"{where}: expected a number, got bool {value!r}")
    if isinstance(value, numbers.Number):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise SchemaError(f"{where}: string {value!r} is not numeric") from exc
    raise SchemaError(f"{where}: expected number or numeric string, got {type(value).__name__}")


def is_positive(value: Any, *, where: str) -> float:
    """Assert a numeric field is strictly greater than zero; return it as float."""
    num = as_number(value, where=where)
    if num <= 0:
        raise SchemaError(f"{where}: expected a positive value, got {num}")
    return num


def is_non_negative(value: Any, *, where: str) -> float:
    """Assert a numeric field is >= 0; return it as float."""
    num = as_number(value, where=where)
    if num < 0:
        raise SchemaError(f"{where}: expected a non-negative value, got {num}")
    return num


def expect_sequence(value: Any, *, where: str, min_len: int = 0) -> Sequence:
    """Assert ``value`` is a list/tuple of at least ``min_len`` items."""
    if not isinstance(value, (list, tuple)):
        raise SchemaError(f"{where}: expected a sequence, got {type(value).__name__}")
    if len(value) < min_len:
        raise SchemaError(f"{where}: expected at least {min_len} items, got {len(value)}")
    return value


def one_of(value: Any, allowed: Iterable[Any], *, where: str) -> Any:
    """Assert ``value`` is one of the ``allowed`` options."""
    allowed = list(allowed)
    if value not in allowed:
        raise SchemaError(f"{where}: {value!r} is not one of {allowed}")
    return value

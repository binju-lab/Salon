"""Exact conversion between display prices and database minor units.

The database stores integer minor currency units.  These helpers deliberately
accept decimal strings (and Decimal values), never binary floating point
values, so a form or JSON boundary cannot silently round a price.
"""

from decimal import Decimal, InvalidOperation


# SQLite INTEGER is signed 64-bit.  This is a storage-safety limit, not a new
# commercial price policy; a lower business limit would need team agreement.
MAX_PRICE_MINOR = (1 << 63) - 1
MAX_PRICE = Decimal("92233720368547758.07")


class PriceValidationError(ValueError):
    """Raised when a display price cannot be represented exactly and safely."""


def price_to_minor(value):
    """Convert a non-negative decimal price to integer minor units.

    String input may contain surrounding whitespace and at most two decimal
    places.  The returned value is always an SQLite-compatible ``int``.
    ``float`` is rejected because its binary representation is inexact.
    """
    if isinstance(value, bool) or isinstance(value, float) or value is None:
        raise PriceValidationError("price must be a decimal string with at most two decimal places")
    try:
        text = value.strip() if isinstance(value, str) else value
        amount = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        raise PriceValidationError("price must be a decimal string with at most two decimal places") from None

    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise PriceValidationError("price must be a non-negative amount with at most two decimal places")
    if amount > MAX_PRICE:
        raise PriceValidationError("price exceeds the signed 64-bit minor-unit storage limit")

    minor = amount * 100
    if minor != minor.to_integral_value():
        raise PriceValidationError("price must be exact in minor currency units")
    return int(minor)


def price_from_minor(value):
    """Format a non-negative signed-64-bit integer minor-unit value."""
    if (isinstance(value, bool) or not isinstance(value, int)
            or value < 0 or value > MAX_PRICE_MINOR):
        raise PriceValidationError(
            "minor currency value must be a non-negative signed 64-bit integer"
        )
    units, fraction = divmod(value, 100)
    return f"{units}.{fraction:02d}"

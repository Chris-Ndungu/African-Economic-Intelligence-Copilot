"""The number formatter. Table-driven so #32 can reuse the cases for the PDF."""

import pytest

from copilot_core.formatting import MISSING, format_number

CASES = [
    (None, "%", "—"),
    (None, None, "—"),
    (0, "%", "0.0"),
    (0.0, "USD", "0"),
    (5.234, "%", "5.2"),
    (-5.25, "%", "-5.2"),
    (-0.01, "%", "0.0"),
    (1234.56, "USD_BN", "1,234.6"),
    (1234.5, "MILLIONS", "1,234.5"),
    (1234.5, "USD", "1,234"),
    (12345678901.0, "USD", "12,345,678,901"),
    (1234.5, "z", "1,234.50"),
    (3.14159, None, "3.14"),
]


@pytest.mark.parametrize(("value", "unit", "expected"), CASES)
def test_format_number(value, unit, expected):
    assert format_number(value, unit) == expected


def test_missing_is_a_dash_and_never_zero():
    assert MISSING == "—"
    assert format_number(None) != format_number(0)

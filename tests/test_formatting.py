"""Tests for style and formatting helper functions."""

import pytest


class TestPctStyle:
    """pct_style threshold logic."""

    def test_below_green(self, mod):
        assert mod.pct_style(0) == mod.BAR_GREEN
        assert mod.pct_style(49) == mod.BAR_GREEN

    def test_at_green_boundary(self, mod):
        # round(49.5) == 50 in Python (banker's rounding), so it hits yellow
        assert mod.pct_style(49.4) == mod.BAR_GREEN
        assert mod.pct_style(50) == mod.BAR_YELLOW

    def test_yellow_range(self, mod):
        assert mod.pct_style(50) == mod.BAR_YELLOW
        assert mod.pct_style(79) == mod.BAR_YELLOW

    def test_at_yellow_boundary(self, mod):
        assert mod.pct_style(79.5) == mod.BAR_RED  # rounds to 80 → red
        assert mod.pct_style(80) == mod.BAR_RED

    def test_red_range(self, mod):
        assert mod.pct_style(80) == mod.BAR_RED
        assert mod.pct_style(100) == mod.BAR_RED

    def test_custom_thresholds(self, mod):
        assert mod.pct_style(30, green=30, yellow=60) == mod.BAR_YELLOW
        assert mod.pct_style(60, green=30, yellow=60) == mod.BAR_RED
        assert mod.pct_style(29, green=30, yellow=60) == mod.BAR_GREEN


class TestFormatK:
    """format_k: integer to compact representation."""

    @pytest.mark.parametrize(
        "val, expected",
        [
            (0, "0"),
            (1, "1"),
            (999, "999"),
            (1000, "1k"),
            (1500, "1k"),
            (200000, "200k"),
        ],
    )
    def test_values(self, mod, val, expected):
        assert mod.format_k(val) == expected


class TestFormatTok:
    """format_tok: signed token deltas."""

    @pytest.mark.parametrize(
        "val, expected",
        [
            (0, "+0"),
            (500, "+500"),
            (-500, "-500"),
            (1000, "+1.0k"),
            (1500, "+1.5k"),
            (-1500, "-1.5k"),
            (999, "+999"),
            (-999, "-999"),
        ],
    )
    def test_values(self, mod, val, expected):
        assert mod.format_tok(val) == expected


class TestFormatEma:
    """format_ema: float EMA values."""

    @pytest.mark.parametrize(
        "val, expected",
        [
            (0.0, "0"),
            (42.3, "42"),
            (42.7, "43"),
            (999.9, "1000"),
            (1000.0, "1.0k"),
            (1500.0, "1.5k"),
            (-1500.0, "-1.5k"),
        ],
    )
    def test_values(self, mod, val, expected):
        assert mod.format_ema(val) == expected


class TestFormatCost:
    """format_cost: dollar formatting with precision tiers."""

    @pytest.mark.parametrize(
        "val, expected",
        [
            (0.0, "$0.00"),
            (0.50, "$0.50"),
            (0.999, "$1.00"),
            (1.0, "$1.0"),
            (1.5, "$1.5"),
            (9.99, "$10.0"),
            (10.0, "$10"),
            (10.5, "$10"),
            (100.0, "$100"),
        ],
    )
    def test_values(self, mod, val, expected):
        assert mod.format_cost(val) == expected


class TestFormatTimeDelta:
    """format_time_delta: seconds to human-readable (XdYh, XhYm, Xm)."""

    @pytest.mark.parametrize(
        "secs, expected",
        [
            (0, "0m"),
            (59, "0m"),
            (60, "1m"),
            (3599, "59m"),
            (3600, "1h0m"),
            (3660, "1h1m"),
            (7200, "2h0m"),
            (86400, "1d0h"),
            (90000, "1d1h"),
            (172800, "2d0h"),
            (259200 + 7200, "3d2h"),
        ],
    )
    def test_values(self, mod, secs, expected):
        assert mod.format_time_delta(secs) == expected


class TestFormatDuration:
    """format_duration: milliseconds to human-readable."""

    @pytest.mark.parametrize(
        "ms, expected",
        [
            (0, "0s"),
            (5000, "5s"),
            (59000, "59s"),
            (60000, "1m0s"),
            (90000, "1m30s"),
            (312000, "5m12s"),
            (3600000, "1h0m"),
            (3660000, "1h1m"),
            (7200000, "2h0m"),
            (86400000, "24h0m"),
        ],
    )
    def test_values(self, mod, ms, expected):
        assert mod.format_duration(ms) == expected

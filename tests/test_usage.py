"""Tests for the usage-window display helpers.

The 5h/7d usage metrics are supplied by the Claude Code harness on stdin
(``rate_limits``), so these helpers take an epoch-seconds reset timestamp
directly rather than parsing an API timestamp string.
"""


class TestTimeUntilReset:
    """time_until_reset: human-readable countdown from an epoch timestamp."""

    def test_days_and_hours(self, mod):
        now = 1_000_000.0
        reset = now + (3 * 86400 + 5 * 3600 + 30 * 60)
        result = mod.time_until_reset(reset, now)
        assert result is not None
        assert "d" in result

    def test_hours_and_minutes(self, mod):
        now = 1_000_000.0
        reset = now + (2 * 3600 + 13 * 60)
        assert mod.time_until_reset(reset, now) == "2h13m"

    def test_minutes_only(self, mod):
        now = 1_000_000.0
        reset = now + 45 * 60
        assert mod.time_until_reset(reset, now) == "45m"

    def test_past_time(self, mod):
        now = 1_000_000.0
        assert mod.time_until_reset(now - 3600, now) is None

    def test_missing_timestamp(self, mod):
        # The harness omits resets_at for a window with no active limit.
        assert mod.time_until_reset(None, 1_000_000.0) is None


class TestPacingTarget:
    """pacing_target: percentage of a usage window elapsed."""

    def test_start_of_cycle(self, mod):
        window = 5 * 3600
        now = 1_000_000.0
        reset = now + window  # full window still remaining
        result = mod.pacing_target(reset, window, now)
        assert result is not None
        assert abs(result - 0.0) < 1.0

    def test_middle_of_cycle(self, mod):
        window = 5 * 3600
        now = 1_000_000.0
        reset = now + window / 2  # halfway through
        result = mod.pacing_target(reset, window, now)
        assert result is not None
        assert abs(result - 50.0) < 2.0

    def test_end_of_cycle(self, mod):
        window = 5 * 3600
        now = 1_000_000.0
        reset = now + 60  # one minute remaining
        result = mod.pacing_target(reset, window, now)
        assert result is not None
        assert result > 99.0

    def test_missing_timestamp(self, mod):
        assert mod.pacing_target(None, 86400, 1_000_000.0) is None

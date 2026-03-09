"""Tests for Anthropic OAuth usage functions."""

import json


class TestGetOauthToken:
    """get_oauth_token: reading OAuth token from credentials file."""

    def test_credentials_file_success(self, mod, tmp_path):
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-123"}}))
        assert mod.get_oauth_token(creds_path=creds) == "tok-123"

    def test_credentials_file_missing(self, mod, tmp_path):
        assert mod.get_oauth_token(creds_path=tmp_path / "nope.json") is None

    def test_credentials_file_missing_key(self, mod, tmp_path):
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"other": "data"}))
        assert mod.get_oauth_token(creds_path=creds) is None

    def test_credentials_file_corrupt(self, mod, tmp_path):
        creds = tmp_path / "creds.json"
        creds.write_text("not json")
        assert mod.get_oauth_token(creds_path=creds) is None


class TestFetchUsage:
    """fetch_usage: HTTP call via injected fetcher with structured error returns."""

    def _creds(self, tmp_path):
        """Write a valid credentials file and return its path."""
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-abc"}}))
        return creds

    def test_successful_fetch(self, make_ctx, tmp_path):
        usage_data = {
            "five_hour": {"utilization": 30, "resets_at": "2025-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 50, "resets_at": "2025-01-20T00:00:00+00:00"},
        }
        ctx = make_ctx(
            fetch=lambda u, h, t: json.dumps(usage_data).encode(),
            creds_path=self._creds(tmp_path),
        )
        data, reason = ctx.fetch_usage()
        assert data == usage_data
        assert reason is None
        assert ctx.usage_cache.exists()

    def test_no_auth_token(self, make_ctx, tmp_path):
        ctx = make_ctx(creds_path=tmp_path / "nonexistent.json")
        data, reason = ctx.fetch_usage()
        assert data is None
        assert reason == "no_token"
        assert ctx.usage_cache.exists()  # touched to prevent immediate retry

    def test_network_error(self, make_ctx, tmp_path):
        def bad_fetch(url, headers, timeout):
            raise OSError("timeout")

        ctx = make_ctx(fetch=bad_fetch, creds_path=self._creds(tmp_path))
        data, reason = ctx.fetch_usage()
        assert data is None
        assert reason == "api_err"
        assert ctx.usage_cache.exists()

    def test_missing_usage_keys(self, make_ctx, tmp_path):
        ctx = make_ctx(
            fetch=lambda u, h, t: json.dumps({"other": "data"}).encode(),
            creds_path=self._creds(tmp_path),
        )
        data, reason = ctx.fetch_usage()
        assert data is None
        assert reason == "bad_response"
        assert ctx.usage_cache.exists()


class TestGetUsage:
    """get_usage: caching logic with structured error returns."""

    def test_fresh_cache_hit(self, make_ctx, tmp_path):
        usage_data = {
            "five_hour": {"utilization": 30},
            "seven_day": {"utilization": 50},
        }
        cache = tmp_path / "usage.json"
        cache.write_text(json.dumps(usage_data))

        ctx = make_ctx(now=cache.stat().st_mtime + 10)  # 10s old, within TTL
        data, reason = ctx.get_usage()
        assert data == usage_data
        assert reason is None

    def test_fresh_cache_empty_returns_loading(self, make_ctx, tmp_path):
        """Fresh placeholder (empty file) returns loading reason."""
        cache = tmp_path / "usage.json"
        cache.touch()  # empty placeholder

        ctx = make_ctx(now=cache.stat().st_mtime + 10)  # fresh
        data, reason = ctx.get_usage()
        assert data is None
        assert reason == "loading"

    def test_stale_cache_fallback(self, make_ctx, tmp_path):
        old_data = {"five_hour": {"utilization": 20}, "seven_day": {"utilization": 40}}
        cache = tmp_path / "usage.json"
        cache.write_text(json.dumps(old_data))

        # No auth -> fetch returns (None, "no_token") -> falls back to stale cache
        ctx = make_ctx(
            now=cache.stat().st_mtime + 300,  # stale
            creds_path=tmp_path / "nonexistent.json",
        )
        data, reason = ctx.get_usage()
        assert data == old_data
        assert reason == "no_token"

    def test_no_cache_first_run(self, make_ctx, tmp_path):
        """First run: no cache. Creates placeholder, fetches, returns None."""
        # Remove the default usage.json that make_ctx doesn't create
        cache = tmp_path / "usage.json"
        assert not cache.exists()

        ctx = make_ctx(creds_path=tmp_path / "nonexistent.json")
        data, reason = ctx.get_usage()
        assert data is None
        assert reason == "no_token"
        assert cache.exists()  # placeholder created

    def test_first_run_fetch_succeeds(self, make_ctx, tmp_path):
        """First run: no cache file. Fetches and returns data."""
        new_data = {
            "five_hour": {"utilization": 50, "resets_at": "2025-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 70, "resets_at": "2025-01-20T00:00:00+00:00"},
        }
        ctx = make_ctx(
            fetch=lambda u, h, t: json.dumps(new_data).encode(),
            creds_path=tmp_path / "creds.json",
        )
        # Need a valid creds file for the fetch to proceed
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-abc"}}))

        data, reason = ctx.get_usage()
        assert data == new_data
        assert reason is None

    def test_stale_cache_refreshes(self, make_ctx, tmp_path):
        """When cache is stale, fetch new data."""
        cache = tmp_path / "usage.json"
        old_data = {"five_hour": {"utilization": 10}, "seven_day": {"utilization": 20}}
        cache.write_text(json.dumps(old_data))

        new_data = {
            "five_hour": {"utilization": 50, "resets_at": "2025-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 70, "resets_at": "2025-01-20T00:00:00+00:00"},
        }
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-abc"}}))

        ctx = make_ctx(
            now=cache.stat().st_mtime + 300,  # stale
            fetch=lambda u, h, t: json.dumps(new_data).encode(),
            creds_path=creds,
        )
        data, reason = ctx.get_usage()
        assert data == new_data
        assert reason is None


class TestResetEpoch:
    """_reset_epoch: ISO timestamp parsing."""

    def test_valid_iso(self, mod):
        epoch = mod._reset_epoch("2025-01-15T00:00:00+00:00")
        assert epoch is not None
        assert isinstance(epoch, float)

    def test_invalid_string(self, mod):
        assert mod._reset_epoch("not-a-date") is None

    def test_empty_string(self, mod):
        assert mod._reset_epoch("") is None


class TestTimeUntilReset:
    """time_until_reset: human-readable countdown."""

    def test_days_and_hours(self, mod):
        from datetime import datetime, timedelta, timezone

        future = datetime.now(timezone.utc) + timedelta(days=3, hours=5, minutes=30)
        now = datetime.now(timezone.utc).timestamp()
        result = mod.time_until_reset(future.isoformat(), now)
        assert result is not None
        assert "d" in result

    def test_hours_and_minutes(self, mod):
        now = 1000000.0
        from datetime import datetime, timedelta, timezone

        future = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(
            hours=2, minutes=13
        )
        result = mod.time_until_reset(future.isoformat(), now)
        assert result == "2h13m"

    def test_minutes_only(self, mod):
        now = 1000000.0
        from datetime import datetime, timedelta, timezone

        future = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(minutes=45)
        result = mod.time_until_reset(future.isoformat(), now)
        assert result == "45m"

    def test_past_time(self, mod):
        from datetime import datetime, timedelta, timezone

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        now = datetime.now(timezone.utc).timestamp()
        assert mod.time_until_reset(past.isoformat(), now) is None

    def test_invalid_timestamp(self, mod):
        assert mod.time_until_reset("bad-date", 1000000.0) is None


class TestPacingTarget:
    """pacing_target: percentage of usage window elapsed."""

    def test_start_of_cycle(self, mod):
        from datetime import datetime, timedelta, timezone

        window = 5 * 3600  # 5 hours
        reset = datetime.now(timezone.utc) + timedelta(hours=5)
        now = (reset - timedelta(hours=5)).timestamp()
        result = mod.pacing_target(reset.isoformat(), window, now)
        assert result is not None
        assert abs(result - 0.0) < 1.0

    def test_middle_of_cycle(self, mod):
        from datetime import datetime, timedelta, timezone

        window = 5 * 3600
        reset = datetime.now(timezone.utc) + timedelta(hours=2, minutes=30)
        now = datetime.now(timezone.utc).timestamp()
        result = mod.pacing_target(reset.isoformat(), window, now)
        assert result is not None
        assert abs(result - 50.0) < 2.0

    def test_end_of_cycle(self, mod):
        from datetime import datetime, timedelta, timezone

        window = 5 * 3600
        reset = datetime.now(timezone.utc) + timedelta(minutes=1)
        now = datetime.now(timezone.utc).timestamp()
        result = mod.pacing_target(reset.isoformat(), window, now)
        assert result is not None
        assert result > 99.0

    def test_invalid_timestamp(self, mod):
        assert mod.pacing_target("bad", 86400, 1000000.0) is None

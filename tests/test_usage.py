"""Tests for Anthropic OAuth usage functions."""

import json
from unittest.mock import MagicMock, patch


class TestGetOauthToken:
    """get_oauth_token: reading OAuth token from ~/.claude/.credentials.json."""

    def test_credentials_file_success(self, mod, mock_home):
        creds_file = mock_home / ".claude" / ".credentials.json"
        creds_file.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-123"}}))
        assert mod.get_oauth_token() == "tok-123"

    def test_credentials_file_missing(self, mod, mock_home):
        assert mod.get_oauth_token() is None

    def test_credentials_file_missing_key(self, mod, mock_home):
        creds_file = mock_home / ".claude" / ".credentials.json"
        creds_file.write_text(json.dumps({"other": "data"}))
        assert mod.get_oauth_token() is None

    def test_credentials_file_corrupt(self, mod, mock_home):
        creds_file = mock_home / ".claude" / ".credentials.json"
        creds_file.write_text("not json")
        assert mod.get_oauth_token() is None


class TestFetchUsage:
    """fetch_usage: HTTP call to Anthropic API with structured error returns."""

    def test_successful_fetch(self, mod, mock_home, tmp_path, monkeypatch):
        usage_data = {
            "five_hour": {"utilization": 30, "resets_at": "2025-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 50, "resets_at": "2025-01-20T00:00:00+00:00"},
        }
        response_data = json.dumps(usage_data).encode()

        cache = tmp_path / "usage-cache.json"
        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(mod, "get_oauth_token", return_value="tok-abc"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            data, reason = mod.fetch_usage()

        assert data == usage_data
        assert reason is None
        assert cache.exists()

    def test_no_auth_token(self, mod, mock_home, tmp_path, monkeypatch):
        cache = tmp_path / "usage-cache.json"
        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        with patch.object(mod, "get_oauth_token", return_value=None):
            data, reason = mod.fetch_usage()
        assert data is None
        assert reason == "no_token"
        assert cache.exists()  # touched to prevent immediate retry

    def test_network_error(self, mod, mock_home, tmp_path, monkeypatch):
        cache = tmp_path / "usage-cache.json"
        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        with (
            patch.object(mod, "get_oauth_token", return_value="tok-abc"),
            patch("urllib.request.urlopen", side_effect=OSError("timeout")),
        ):
            data, reason = mod.fetch_usage()
        assert data is None
        assert reason == "api_err"
        assert cache.exists()  # touched to prevent immediate retry

    def test_missing_usage_keys(self, mod, mock_home, tmp_path, monkeypatch):
        cache = tmp_path / "usage-cache.json"
        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"other": "data"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(mod, "get_oauth_token", return_value="tok-abc"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            data, reason = mod.fetch_usage()
        assert data is None
        assert reason == "bad_response"
        assert cache.exists()  # touched to prevent immediate retry


class TestGetUsage:
    """get_usage: caching logic with structured error returns."""

    def _set_cache_path(self, mod, monkeypatch, tmp_path):
        cache = tmp_path / "usage-cache.json"
        monkeypatch.setattr(mod, "USAGE_CACHE", cache)
        return cache

    def test_fresh_cache_hit(self, mod, tmp_path, monkeypatch):
        cache = self._set_cache_path(mod, monkeypatch, tmp_path)
        usage_data = {
            "five_hour": {"utilization": 30},
            "seven_day": {"utilization": 50},
        }
        cache.write_text(json.dumps(usage_data))

        now = cache.stat().st_mtime + 10  # 10s old, within TTL
        data, reason = mod.get_usage(now)
        assert data == usage_data
        assert reason is None

    def test_fresh_cache_empty_returns_loading(self, mod, tmp_path, monkeypatch):
        """Fresh placeholder (empty file) returns loading reason."""
        cache = self._set_cache_path(mod, monkeypatch, tmp_path)
        cache.touch()  # empty placeholder

        with patch.object(mod, "fetch_usage") as mock_fetch:
            now = cache.stat().st_mtime + 10  # fresh
            data, reason = mod.get_usage(now)
        assert data is None
        assert reason == "loading"
        mock_fetch.assert_not_called()

    def test_stale_cache_fallback(self, mod, tmp_path, monkeypatch, mock_home):
        cache = self._set_cache_path(mod, monkeypatch, tmp_path)
        old_data = {"five_hour": {"utilization": 20}, "seven_day": {"utilization": 40}}
        cache.write_text(json.dumps(old_data))

        # No auth → fetch returns (None, "no_token") → falls back to stale cache
        with patch.object(mod, "get_oauth_token", return_value=None):
            now = cache.stat().st_mtime + 300  # 300s old, stale
            data, reason = mod.get_usage(now)
        assert data == old_data
        assert reason == "no_token"  # propagates the fetch failure reason

    def test_no_cache_first_run(self, mod, tmp_path, monkeypatch, mock_home):
        """First run: no cache. Creates placeholder, fetches, returns None."""
        cache = self._set_cache_path(mod, monkeypatch, tmp_path)
        assert not cache.exists()

        with patch.object(mod, "get_oauth_token", return_value=None):
            data, reason = mod.get_usage(1000000.0)
        assert data is None
        assert reason == "no_token"
        assert cache.exists()  # placeholder created

    def test_first_run_fetch_succeeds(self, mod, tmp_path, monkeypatch, mock_home):
        """First run: no cache file. Fetches and returns data."""
        self._set_cache_path(mod, monkeypatch, tmp_path)
        new_data = {
            "five_hour": {"utilization": 50, "resets_at": "2025-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 70, "resets_at": "2025-01-20T00:00:00+00:00"},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(new_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(mod, "get_oauth_token", return_value="tok-abc"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            data, reason = mod.get_usage(1000000.0)
        assert data == new_data
        assert reason is None

    def test_stale_cache_refreshes(self, mod, tmp_path, monkeypatch, mock_home):
        """When cache is stale, fetch new data."""
        cache = self._set_cache_path(mod, monkeypatch, tmp_path)
        old_data = {"five_hour": {"utilization": 10}, "seven_day": {"utilization": 20}}
        cache.write_text(json.dumps(old_data))

        new_data = {
            "five_hour": {"utilization": 50, "resets_at": "2025-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 70, "resets_at": "2025-01-20T00:00:00+00:00"},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(new_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(mod, "get_oauth_token", return_value="tok-abc"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            now = cache.stat().st_mtime + 300  # stale
            data, reason = mod.get_usage(now)
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

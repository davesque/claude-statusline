"""Tests for Anthropic OAuth usage functions."""

import json
import subprocess
from unittest.mock import MagicMock, patch


class TestGetOauthToken:
    """get_oauth_token: reading OAuth token from keychain or credentials file."""

    def test_keychain_success(self, mod, mock_home):
        creds = json.dumps({"claudeAiOauth": {"accessToken": "oauth-tok-123"}})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=creds)
            assert mod.get_oauth_token() == "oauth-tok-123"

    def test_keychain_fails_credentials_file(self, mod, mock_home):
        creds_file = mock_home / ".claude" / ".credentials.json"
        creds_file.write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "file-tok-456"}})
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert mod.get_oauth_token() == "file-tok-456"

    def test_no_credentials_anywhere(self, mod, mock_home):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert mod.get_oauth_token() is None

    def test_keychain_timeout(self, mod, mock_home):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 3)):
            assert mod.get_oauth_token() is None

    def test_keychain_json_corrupt(self, mod, mock_home):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="not json")
            assert mod.get_oauth_token() is None

    def test_credentials_file_missing_key(self, mod, mock_home):
        creds_file = mock_home / ".claude" / ".credentials.json"
        creds_file.write_text(json.dumps({"other": "data"}))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert mod.get_oauth_token() is None


class TestFetchUsage:
    """fetch_usage: HTTP call to Anthropic API."""

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
            result = mod.fetch_usage()

        assert result == usage_data
        assert cache.exists()

    def test_no_auth_token(self, mod, mock_home):
        with patch.object(mod, "get_oauth_token", return_value=None):
            assert mod.fetch_usage() is None

    def test_network_error(self, mod, mock_home, monkeypatch):
        with (
            patch.object(mod, "get_oauth_token", return_value="tok-abc"),
            patch("urllib.request.urlopen", side_effect=Exception("timeout")),
        ):
            assert mod.fetch_usage() is None

    def test_missing_usage_keys(self, mod, mock_home, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "USAGE_CACHE", tmp_path / "usage-cache.json")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"other": "data"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(mod, "get_oauth_token", return_value="tok-abc"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            assert mod.fetch_usage() is None


class TestGetUsage:
    """get_usage: caching logic."""

    def test_fresh_cache_hit(self, mod, tmp_path, monkeypatch):
        cache = tmp_path / "usage-cache.json"
        usage_data = {
            "five_hour": {"utilization": 30},
            "seven_day": {"utilization": 50},
        }
        cache.write_text(json.dumps(usage_data))

        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        now = cache.stat().st_mtime + 10  # 10s old, within 60s
        result = mod.get_usage(now)
        assert result == usage_data

    def test_stale_cache_fallback(self, mod, tmp_path, monkeypatch, mock_home):
        cache = tmp_path / "usage-cache.json"
        old_data = {"five_hour": {"utilization": 20}, "seven_day": {"utilization": 40}}
        cache.write_text(json.dumps(old_data))

        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        # No auth → fetch returns None → falls back to stale cache
        with patch.object(mod, "get_oauth_token", return_value=None):
            now = cache.stat().st_mtime + 120  # 120s old, stale
            result = mod.get_usage(now)
        assert result == old_data

    def test_no_cache(self, mod, tmp_path, monkeypatch, mock_home):
        cache = tmp_path / "nonexistent-cache.json"
        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        with patch.object(mod, "get_oauth_token", return_value=None):
            result = mod.get_usage(1000000.0)
        assert result is None


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

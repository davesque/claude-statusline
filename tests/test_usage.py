"""Tests for Anthropic OAuth usage functions."""

import json
import subprocess
import sys

import pytest


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


class TestReadKeychainCredentials:
    """_read_keychain_credentials: macOS Keychain fallback."""

    def test_returns_token_on_darwin(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        creds_json = json.dumps({"claudeAiOauth": {"accessToken": "kc-tok"}})

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=creds_json, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert mod._read_keychain_credentials() == "kc-tok"

    def test_returns_none_on_linux(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert mod._read_keychain_credentials() is None

    def test_returns_none_on_nonzero_exit(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 44, stdout="", stderr="err")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert mod._read_keychain_credentials() is None

    def test_returns_none_on_bad_json(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout="not json", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert mod._read_keychain_credentials() is None

    def test_returns_none_on_missing_key(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        creds_json = json.dumps({"other": "data"})

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=creds_json, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert mod._read_keychain_credentials() is None

    def test_returns_none_on_timeout(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 5)

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert mod._read_keychain_credentials() is None

    def test_returns_none_on_os_error(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

        def fake_run(*args, **kwargs):
            raise OSError("no such binary")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert mod._read_keychain_credentials() is None


class TestGetOauthTokenKeychainFallback:
    """get_oauth_token: falls back to keychain when no creds_path given."""

    def test_no_file_falls_back_to_keychain(self, mod, monkeypatch):
        """When default creds file missing and on darwin, tries keychain."""
        monkeypatch.setattr(sys, "platform", "darwin")
        creds_json = json.dumps({"claudeAiOauth": {"accessToken": "kc-tok"}})

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=creds_json, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        # creds_path=None triggers default path (~/.claude/.credentials.json)
        # which doesn't exist, so it falls through to keychain
        assert mod.get_oauth_token() == "kc-tok"

    def test_explicit_creds_path_no_fallback(self, mod, tmp_path):
        """When creds_path is explicitly given but missing, no keychain fallback."""
        assert mod.get_oauth_token(creds_path=tmp_path / "nope.json") is None


class TestFetchUsage:
    """fetch_usage: HTTP call via injected fetcher, raises FetchError on failure."""

    def _creds(self, tmp_path):
        """Write a valid credentials file and return its path."""
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-abc"}}))
        return creds

    def test_successful_fetch(self, mod, make_ctx, tmp_path):
        usage_data = {
            "five_hour": {"utilization": 30, "resets_at": "2025-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 50, "resets_at": "2025-01-20T00:00:00+00:00"},
        }
        ctx = make_ctx(
            fetch=lambda u, h, t: json.dumps(usage_data).encode(),
            creds_path=self._creds(tmp_path),
        )
        assert ctx.fetch_usage() == usage_data

    def test_no_auth_token(self, mod, make_ctx, tmp_path):
        ctx = make_ctx(creds_path=tmp_path / "nonexistent.json")
        with pytest.raises(mod.FetchError, match="no OAuth token") as exc_info:
            ctx.fetch_usage()
        assert exc_info.value.reason == "no_token"

    def test_network_error(self, mod, make_ctx, tmp_path):
        def bad_fetch(url, headers, timeout):
            raise OSError("timeout")

        ctx = make_ctx(fetch=bad_fetch, creds_path=self._creds(tmp_path))
        with pytest.raises(mod.FetchError) as exc_info:
            ctx.fetch_usage()
        assert exc_info.value.reason == "api_err"

    def test_missing_usage_keys(self, mod, make_ctx, tmp_path):
        ctx = make_ctx(
            fetch=lambda u, h, t: json.dumps({"other": "data"}).encode(),
            creds_path=self._creds(tmp_path),
        )
        with pytest.raises(mod.FetchError) as exc_info:
            ctx.fetch_usage()
        assert exc_info.value.reason == "bad_response"


class TestUsageCache:
    """UsageCache: file-level cache operations."""

    VALID_DATA = {"five_hour": {"utilization": 30}, "seven_day": {"utilization": 50}}

    def test_exists_false(self, mod, tmp_path):
        cache = mod.UsageCache(tmp_path / "missing.json")
        assert not cache.exists()

    def test_exists_true(self, mod, tmp_path):
        path = tmp_path / "usage.json"
        path.touch()
        assert mod.UsageCache(path).exists()

    def test_touch_creates_file(self, mod, tmp_path):
        cache = mod.UsageCache(tmp_path / "usage.json")
        assert not cache.path.exists()
        cache.touch()
        assert cache.path.exists()

    def test_write_and_read(self, mod, tmp_path):
        cache = mod.UsageCache(tmp_path / "usage.json")
        cache.write(self.VALID_DATA)
        assert cache.read() == self.VALID_DATA

    def test_read_missing_file(self, mod, tmp_path):
        cache = mod.UsageCache(tmp_path / "missing.json")
        assert cache.read() is None

    def test_read_invalid_json(self, mod, tmp_path):
        path = tmp_path / "usage.json"
        path.write_text("not json")
        assert mod.UsageCache(path).read() is None

    def test_read_missing_keys(self, mod, tmp_path):
        path = tmp_path / "usage.json"
        path.write_text(json.dumps({"other": "data"}))
        assert mod.UsageCache(path).read() is None

    def test_is_fresh_within_ttl(self, mod, tmp_path):
        path = tmp_path / "usage.json"
        path.touch()
        now = path.stat().st_mtime + 10
        assert mod.UsageCache(path).is_fresh(now)

    def test_is_fresh_beyond_ttl(self, mod, tmp_path):
        path = tmp_path / "usage.json"
        path.touch()
        now = path.stat().st_mtime + mod.USAGE_CACHE_AGE + 1
        assert not mod.UsageCache(path).is_fresh(now)

    def test_write_is_atomic(self, mod, tmp_path):
        """Write uses a tmp file, so the cache path is never partially written."""
        cache = mod.UsageCache(tmp_path / "usage.json")
        cache.write(self.VALID_DATA)
        assert not cache.path.with_suffix(".tmp").exists()
        assert cache.read() == self.VALID_DATA


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

    def test_stale_cache_fallback(self, mod, make_ctx, tmp_path):
        old_data = {"five_hour": {"utilization": 20}, "seven_day": {"utilization": 40}}
        cache = tmp_path / "usage.json"
        cache.write_text(json.dumps(old_data))

        # No auth -> fetch returns (None, "no_token") -> falls back to stale cache
        ctx = make_ctx(
            now=cache.stat().st_mtime + mod.USAGE_CACHE_AGE + 1,  # stale
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

    def test_stale_cache_refreshes(self, mod, make_ctx, tmp_path):
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
            now=cache.stat().st_mtime + mod.USAGE_CACHE_AGE + 1,  # stale
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

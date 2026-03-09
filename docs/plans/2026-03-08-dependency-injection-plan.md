# Dependency Injection Refactoring — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace module-level state and monkeypatch-heavy tests with a `StatusLineContext` class that holds all injectable dependencies.

**Architecture:** Extract I/O-bearing functions into methods on a `StatusLineContext` class. Pure functions stay as free functions. `main()` becomes a thin shell that reads stdin and delegates to `StatusLineContext.create(raw).run()`. Tests construct contexts with test paths, fake fetchers, and in-memory consoles — no mocking needed.

**Tech Stack:** Python 3.10+, Rich, pytest (no new dependencies)

**Design doc:** `docs/plans/2026-03-08-dependency-injection-design.md`

---

### Task 1: Introduce `StatusLineContext` class and `_default_fetch`

**Files:**
- Modify: `claude-statusline/statusline-command.py`

**Step 1: Add the `Callable` import and `_default_fetch` function**

Add to imports at the top of the file (after `from pathlib import Path`):

```python
from collections.abc import Callable
```

Add `_default_fetch` as a free function right after the style constants block (after line 42, before `DEFAULT_FIGURES`):

```python
def _default_fetch(url: str, headers: dict[str, str], timeout: int) -> bytes:
    """Default HTTP fetcher wrapping urllib."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()
```

**Step 2: Add `get_oauth_token` `creds_path` parameter**

Change `get_oauth_token` signature from:
```python
def get_oauth_token() -> str | None:
    creds_file = Path.home() / ".claude" / ".credentials.json"
```
to:
```python
def get_oauth_token(creds_path: Path | None = None) -> str | None:
    creds_file = creds_path or Path.home() / ".claude" / ".credentials.json"
```

**Step 3: Add the `StatusLineContext` class skeleton**

Insert the class after `_default_fetch` and before `DEFAULT_FIGURES`. It replaces the module-level constants `STATE_DIR`, `CONFIG_PATH`, `USAGE_CACHE`, `DEBUG_LOG` and the module-level logger `_log`. Those module-level definitions should be **removed**.

```python
class StatusLineContext:
    """Holds all injectable dependencies for the status line."""

    def __init__(
        self,
        input_text: str,
        now: float,
        state_dir: Path,
        config_path: Path,
        usage_cache: Path,
        debug_log: Path,
        logger: logging.Logger,
        console: Console,
        fetch: Callable[[str, dict[str, str], int], bytes],
    ) -> None:
        self.input_text = input_text
        self.now = now
        self.state_dir = state_dir
        self.config_path = config_path
        self.usage_cache = usage_cache
        self.debug_log = debug_log
        self.logger = logger
        self.console = console
        self.fetch = fetch

    @classmethod
    def create(cls, input_text: str) -> "StatusLineContext":
        """Build a production context with real paths and I/O."""
        state_dir = Path.home() / ".claude" / "statusline"
        state_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("statusline")
        logger.setLevel(logging.DEBUG)
        # Console width is set later in run() once bar width is computed
        return cls(
            input_text=input_text,
            now=time.time(),
            state_dir=state_dir,
            config_path=state_dir / "config.json",
            usage_cache=state_dir / "usage.json",
            debug_log=state_dir / "debug.log",
            logger=logger,
            console=Console(highlight=False, force_terminal=True),
            fetch=_default_fetch,
        )
```

**Step 4: Run tests to verify nothing is broken yet**

At this point the class exists but nothing uses it. All existing code still works via the old module-level constants (which have NOT been removed yet — that happens in subsequent tasks).

Run: `uv run pytest -x -q`
Expected: all 179 tests pass

**Step 5: Commit**

```bash
git add claude-statusline/statusline-command.py
git commit -m "Add StatusLineContext class, _default_fetch, and creds_path param"
```

---

### Task 2: Move `load_config` to a method

**Files:**
- Modify: `claude-statusline/statusline-command.py`
- Modify: `tests/test_integration.py`

**Step 1: Add `load_config` as a method on `StatusLineContext`**

Add inside the class:

```python
    def load_config(self) -> dict:
        """Load user config from config_path, with defaults."""
        config: dict = {
            "figures": list(DEFAULT_FIGURES),
            "min_bar_width": DEFAULT_MIN_BAR_WIDTH,
            "max_width": None,
        }
        try:
            raw = self.config_path.read_text()
            user = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return config
        if "figures" in user and isinstance(user["figures"], list):
            config["figures"] = [f for f in user["figures"] if isinstance(f, str)]
        if "min_bar_width" in user and isinstance(user["min_bar_width"], int):
            config["min_bar_width"] = max(10, user["min_bar_width"])
        if "max_width" in user and (
            isinstance(user["max_width"], int) or user["max_width"] is None
        ):
            config["max_width"] = user["max_width"]
        return config
```

Delete the old free function `load_config()` (lines 51-71) and the module-level `CONFIG_PATH` constant (line 48). Keep `STATE_DIR` for now (other functions still use it).

**Step 2: Update `main()` to call `self.load_config()`**

This is a temporary bridge — `main()` still exists as a free function. Change:
```python
config = load_config()
```
to:
```python
config = StatusLineContext(
    input_text="", now=now, state_dir=STATE_DIR,
    config_path=STATE_DIR / "config.json",
    usage_cache=USAGE_CACHE, debug_log=DEBUG_LOG,
    logger=_log, console=Console(), fetch=_default_fetch,
).load_config()
```

Actually — this temporary bridge is ugly. Better approach: keep the free function as a thin wrapper during the migration:

```python
def load_config() -> dict:
    return StatusLineContext.create("").load_config()
```

No — that calls `Path.home()` and `time.time()`. Simplest bridge: just leave the free function calling `CONFIG_PATH` for now, and only delete it in the final task when `main()` becomes `ctx.run()`. Mark it with a `# TODO: remove after migration` comment.

**Revised approach:** Don't delete the free function yet. Just add the method. Tests for `load_config` continue to work. We'll wire everything together in the final task.

**Step 3: Run tests**

Run: `uv run pytest -x -q`
Expected: all 179 tests pass

**Step 4: Commit**

```bash
git add claude-statusline/statusline-command.py
git commit -m "Add load_config method to StatusLineContext"
```

---

### Task 3: Move cache and usage functions to methods

**Files:**
- Modify: `claude-statusline/statusline-command.py`

**Step 1: Add cache helper methods**

Add to `StatusLineContext`:

```python
    def _touch_cache(self) -> None:
        """Update cache mtime to prevent immediate retry after a failed fetch."""
        try:
            self.usage_cache.touch(exist_ok=True)
        except OSError:  # pragma: no cover
            pass

    def _read_cache(self) -> dict | None:
        """Read and parse the cache file."""
        try:
            data = json.loads(self.usage_cache.read_text())
            if "five_hour" in data and "seven_day" in data:
                return data
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            pass
        return None

    def _cache_is_fresh(self) -> bool:
        """Check if the cache file exists with an mtime within the TTL."""
        try:
            return (self.now - self.usage_cache.stat().st_mtime) <= USAGE_CACHE_AGE
        except OSError:  # pragma: no cover
            return False

    def _warn(self, msg: str) -> None:
        """Print a diagnostic message to stderr."""
        print(f"statusline: {msg}", file=sys.stderr)
        self.logger.warning(msg)
```

**Step 2: Add `fetch_usage` method**

```python
    def fetch_usage(self) -> tuple[dict | None, str | None]:
        """Fetch usage from Anthropic API and cache it."""
        token = get_oauth_token()
        if not token:
            self.logger.debug(
                "fetch_usage: no OAuth token in ~/.claude/.credentials.json"
            )
            self._touch_cache()
            return None, "no_token"

        t0 = time.monotonic()
        try:
            raw = self.fetch(
                "https://api.anthropic.com/api/oauth/usage",
                {
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
                3,
            )
            data = json.loads(raw)
        except (
            urllib.error.URLError, OSError, json.JSONDecodeError, ValueError,
        ) as exc:
            self._warn(f"usage API request failed: {exc}")
            self.logger.debug(
                "fetch_usage: %s: %s (%.3fs)",
                type(exc).__name__, exc, time.monotonic() - t0,
            )
            self._touch_cache()
            return None, "api_err"

        if "five_hour" not in data or "seven_day" not in data:
            self._warn("usage API response missing expected keys")
            self.logger.debug("fetch_usage: bad response, keys=%s", list(data.keys()))
            self._touch_cache()
            return None, "bad_response"

        self.logger.debug("fetch_usage: ok (%.3fs)", time.monotonic() - t0)
        try:
            tmp = self.usage_cache.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(self.usage_cache)
        except OSError:  # pragma: no cover
            pass

        return data, None
```

**Step 3: Add `get_usage` method**

```python
    def get_usage(self) -> tuple[dict | None, str | None]:
        """Return cached usage data, refreshing if stale."""
        first_run = not self.usage_cache.exists()
        if first_run:
            self.logger.debug("get_usage: first_run, creating placeholder")
            self._touch_cache()

        if not first_run and self._cache_is_fresh():
            cached = self._read_cache()
            return cached, (None if cached else "loading")

        data, reason = self.fetch_usage()
        if data:
            return data, None
        self.logger.debug(
            "get_usage: fetch failed (%s), falling back to cache", reason
        )
        cached = self._read_cache()
        if cached:
            return cached, reason
        return None, reason
```

**Step 4: Add `init_logging` method**

```python
    def init_logging(self) -> None:
        """Attach the rotating file handler to the logger."""
        if self.logger.handlers:
            return
        try:
            handler = logging.handlers.RotatingFileHandler(
                self.debug_log, maxBytes=100_000, backupCount=1
            )
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(process)d] %(message)s", datefmt="%H:%M:%S"
                )
            )
            self.logger.addHandler(handler)
        except OSError:  # pragma: no cover
            pass
```

**Step 5: Don't delete the old free functions yet** — `main()` still calls them. That wiring happens in Task 5.

**Step 6: Run tests**

Run: `uv run pytest -x -q`
Expected: all 179 tests pass (old free functions still work)

**Step 7: Commit**

```bash
git add claude-statusline/statusline-command.py
git commit -m "Add cache, usage, and logging methods to StatusLineContext"
```

---

### Task 4: Move `update_velocity` to a method

**Files:**
- Modify: `claude-statusline/statusline-command.py`

**Step 1: Add `update_velocity` method**

```python
    def update_velocity(
        self, session_id: str, total_tokens: int, total_cost: float
    ) -> tuple[int, float, float, float]:
        """Update EMA state and return (tok_delta, tok_ema, cost_delta, cost_ema)."""
        state_file = self.state_dir / f"state-{session_id}.json"

        prev_tokens = 0
        prev_tok_ema = 0.0
        prev_cost = 0.0
        prev_cost_ema = 0.0
        turn = 0

        try:
            state = json.loads(state_file.read_text())
            prev_tokens = state.get("total_tokens", 0)
            prev_tok_ema = state.get("ema", 0.0)
            prev_cost = state.get("total_cost", 0.0)
            prev_cost_ema = state.get("cost_ema", 0.0)
            turn = state.get("turn", 0)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        tok_delta = total_tokens - prev_tokens
        cost_delta = total_cost - prev_cost

        if tok_delta == 0 and cost_delta < 0.0001:
            return tok_delta, prev_tok_ema, cost_delta, prev_cost_ema

        turn += 1
        tok_ema = (
            float(tok_delta)
            if turn <= 1
            else EMA_ALPHA * tok_delta + (1 - EMA_ALPHA) * prev_tok_ema
        )
        cost_ema = (
            cost_delta
            if turn <= 1
            else EMA_ALPHA * cost_delta + (1 - EMA_ALPHA) * prev_cost_ema
        )

        try:
            state_file.write_text(
                json.dumps(
                    {
                        "turn": turn,
                        "total_tokens": total_tokens,
                        "ema": round(tok_ema, 1),
                        "total_cost": round(total_cost, 6),
                        "cost_ema": round(cost_ema, 6),
                    }
                )
                + "\n"
            )
        except OSError:  # pragma: no cover
            pass

        if turn == 1:
            try:
                cutoff = self.now - 86400
                for f in self.state_dir.glob("state-*.json"):
                    if f != state_file:
                        try:
                            if f.stat().st_mtime < cutoff:
                                f.unlink(missing_ok=True)
                        except OSError:  # pragma: no cover
                            pass
            except OSError:  # pragma: no cover
                pass

        return tok_delta, tok_ema, cost_delta, cost_ema
```

Note: uses `self.now` instead of `time.time()` for the cleanup cutoff.

**Step 2: Run tests**

Run: `uv run pytest -x -q`
Expected: all 179 tests pass

**Step 3: Commit**

```bash
git add claude-statusline/statusline-command.py
git commit -m "Add update_velocity method to StatusLineContext"
```

---

### Task 5: Add `run()` method and rewire `main()`

This is the big task — move the body of `main()` into `ctx.run()` and make `main()` a thin shell.

**Files:**
- Modify: `claude-statusline/statusline-command.py`

**Step 1: Add the `run` method**

Move the entire body of `main()` (lines 593-866) into a `run(self)` method. Replace all references:

- `load_config()` → `self.load_config()`
- `STATE_DIR.mkdir(...)` → `self.state_dir.mkdir(...)`
- `_init_logging()` → `self.init_logging()`
- `update_velocity(session_id, ...)` → `self.update_velocity(session_id, ...)`
- `get_usage(now)` → `self.get_usage()`
- `now` → `self.now`
- `config = load_config()` → `config = self.load_config()`
- The `Console(...)` construction at the end → use `self.console` but set its width:
  ```python
  self.console.width = render_width
  ```
- All `console.print(...)` → `self.console.print(...)`

The `data = json.loads(raw)` at the top of run should parse `self.input_text`:
```python
    def run(self) -> None:
        try:
            data = json.loads(self.input_text)
        except json.JSONDecodeError:
            return

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.init_logging()

        config = self.load_config()
        # ... rest of the body ...
```

**Step 2: Rewrite `main()`**

```python
def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        return
    ctx = StatusLineContext.create(raw)
    ctx.run()
```

**Step 3: Delete all old free functions and module-level state that are now methods**

Remove:
- Module-level `STATE_DIR`, `CONFIG_PATH`, `USAGE_CACHE`, `DEBUG_LOG` constants
- Module-level `_log` logger and `_init_logging()` free function
- Free functions: `load_config()`, `_warn()`, `_touch_cache()`, `fetch_usage()`, `_read_cache()`, `_cache_is_fresh()`, `get_usage()`, `update_velocity()`

Keep:
- `DEFAULT_FIGURES`, `DEFAULT_MIN_BAR_WIDTH`, `USAGE_CACHE_AGE`, `EMA_ALPHA`
- All style constants
- All pure free functions (formatting, bar, git, flow layout, pacing)
- `get_oauth_token(creds_path=None)`, `_default_fetch()`

**Step 4: Run lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Fix any issues.

**Step 5: Run tests — expect widespread failures**

Run: `uv run pytest -x -q`
Expected: many failures — tests still reference the old free functions via `mod.fetch_usage()`, `mod.get_usage()`, etc. That's expected. We fix the tests in the next tasks.

**Step 6: Commit (with failing tests — WIP)**

```bash
git add claude-statusline/statusline-command.py
git commit -m "WIP: Rewire main() to use StatusLineContext.run()"
```

---

### Task 6: Rewrite `conftest.py` fixtures

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Replace fixtures**

```python
"""Shared fixtures for statusline-command tests."""

import importlib.util
import json
import logging
import sys
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "claude-statusline"
    / "statusline-command.py"
)


@pytest.fixture()
def mod():
    """Import statusline-command.py as a module."""
    spec = importlib.util.spec_from_file_location("statusline_command", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    old = sys.modules.get("statusline_command")
    sys.modules["statusline_command"] = module
    spec.loader.exec_module(module)
    yield module
    if old is None:
        sys.modules.pop("statusline_command", None)
    else:
        sys.modules["statusline_command"] = old


def _noop_fetch(url: str, headers: dict[str, str], timeout: int) -> bytes:
    """Default test fetcher that returns empty JSON."""
    return b"{}"


@pytest.fixture()
def make_ctx(mod, tmp_path):
    """Factory fixture that builds a test StatusLineContext.

    All paths point into tmp_path.  Logger has no handlers (messages
    are silently dropped).  Console writes to an in-memory StringIO.
    Fetch is a no-op by default.
    """

    def _make(
        input_text: str = "{}",
        now: float = 1_000_000.0,
        fetch=_noop_fetch,
        console: Console | None = None,
        **overrides,
    ):
        state_dir = tmp_path / "statusline"
        state_dir.mkdir(exist_ok=True)
        defaults = dict(
            input_text=input_text,
            now=now,
            state_dir=state_dir,
            config_path=tmp_path / "config.json",
            usage_cache=tmp_path / "usage.json",
            debug_log=tmp_path / "debug.log",
            logger=logging.getLogger(f"test-{id(tmp_path)}"),
            console=console
            or Console(file=StringIO(), highlight=False, force_terminal=True),
            fetch=fetch,
        )
        defaults.update(overrides)
        return mod.StatusLineContext(**defaults)

    return _make
```

Delete `mock_home` and `mock_time` fixtures.

**Step 2: Run tests — most will still fail (tests not yet updated)**

Run: `uv run pytest -x -q`
Expected: failures — test files still use old API

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "WIP: Rewrite conftest fixtures for StatusLineContext"
```

---

### Task 7: Rewrite `test_usage.py`

**Files:**
- Rewrite: `tests/test_usage.py`

**Step 1: Rewrite the entire file**

Tests now create contexts via `make_ctx` and call methods on the context. No mocks.

Key patterns:
- **Successful fetch:** pass a `fetch` lambda that returns valid JSON bytes
- **No auth token:** don't create `.credentials.json` — `get_oauth_token()` returns None naturally
- **With auth token:** write `.credentials.json` into the home dir that `get_oauth_token` reads. Since `get_oauth_token` calls `Path.home()` at runtime, we either need `mock_home` back for these tests OR use the `creds_path` parameter. Use `creds_path` — but `fetch_usage` calls `get_oauth_token()` without passing `creds_path`. So `fetch_usage` needs to accept an optional `creds_path` override, or we need to handle this differently.

**Resolution:** The method `fetch_usage` should call `get_oauth_token(creds_path)` where `creds_path` is stored on the context. But the design said `get_oauth_token` stays a free function. Simplest fix: add `creds_path: Path | None = None` to the context, defaulting to None (which means real home). `fetch_usage` passes `self.creds_path` to `get_oauth_token()`.

Add to `StatusLineContext.__init__`:
```python
    self.creds_path = creds_path
```

Add to `StatusLineContext.create`:
```python
    creds_path=None,  # uses Path.home() default
```

Add `creds_path: Path | None = None` parameter to `__init__`.

Update `fetch_usage`:
```python
    token = get_oauth_token(self.creds_path)
```

Update `make_ctx` in conftest:
```python
    # In defaults dict, no creds_path needed (defaults to None in __init__)
```

Now test patterns:

```python
class TestFetchUsage:
    def test_successful_fetch(self, make_ctx, tmp_path):
        # Write a credentials file
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-abc"}}))

        usage_data = {
            "five_hour": {"utilization": 30, "resets_at": "2025-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 50, "resets_at": "2025-01-20T00:00:00+00:00"},
        }
        ctx = make_ctx(
            fetch=lambda u, h, t: json.dumps(usage_data).encode(),
            creds_path=creds,
        )
        data, reason = ctx.fetch_usage()
        assert data == usage_data
        assert reason is None
        assert ctx.usage_cache.exists()

    def test_no_auth_token(self, make_ctx, tmp_path):
        # No creds file → get_oauth_token returns None
        ctx = make_ctx(creds_path=tmp_path / "nonexistent.json")
        data, reason = ctx.fetch_usage()
        assert data is None
        assert reason == "no_token"

    def test_network_error(self, make_ctx, tmp_path):
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok"}}))

        def bad_fetch(url, headers, timeout):
            raise OSError("timeout")

        ctx = make_ctx(fetch=bad_fetch, creds_path=creds)
        data, reason = ctx.fetch_usage()
        assert data is None
        assert reason == "api_err"

    def test_missing_usage_keys(self, make_ctx, tmp_path):
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok"}}))

        ctx = make_ctx(
            fetch=lambda u, h, t: json.dumps({"other": "data"}).encode(),
            creds_path=creds,
        )
        data, reason = ctx.fetch_usage()
        assert data is None
        assert reason == "bad_response"
```

Similar patterns for `TestGetUsage`, `TestGetOauthToken` (uses free function directly with `creds_path` param). `TestResetEpoch`, `TestTimeUntilReset`, `TestPacingTarget` are unchanged — they test pure free functions.

**Step 2: Run tests**

Run: `uv run pytest tests/test_usage.py -x -q`
Expected: all pass

**Step 3: Commit**

```bash
git add tests/test_usage.py claude-statusline/statusline-command.py
git commit -m "Rewrite test_usage.py for StatusLineContext DI"
```

---

### Task 8: Rewrite `test_velocity.py`

**Files:**
- Rewrite: `tests/test_velocity.py`

**Step 1: Rewrite using `make_ctx`**

Tests call `ctx.update_velocity(...)` instead of `mod.update_velocity(...)`. State files land in `tmp_path/statusline/`. No monkeypatching needed.

```python
class TestUpdateVelocity:
    def test_first_turn_ema_equals_delta(self, make_ctx):
        ctx = make_ctx()
        tok_delta, tok_ema, cost_delta, cost_ema = ctx.update_velocity(
            "test-sess", 1000, 0.50
        )
        assert tok_delta == 1000
        assert tok_ema == 1000.0

    def test_state_file_created(self, make_ctx, tmp_path):
        ctx = make_ctx()
        ctx.update_velocity("test-sess", 1000, 0.50)
        state_file = tmp_path / "statusline" / "state-test-sess.json"
        assert state_file.exists()

    def test_old_state_cleanup(self, make_ctx, tmp_path):
        ctx = make_ctx(now=100_000.0)
        state_dir = tmp_path / "statusline"
        old_file = state_dir / "state-old-session.json"
        old_file.write_text(json.dumps({"turn": 1, "total_tokens": 0}))
        import os
        old_time = ctx.now - 90000
        os.utime(old_file, (old_time, old_time))
        ctx.update_velocity("new-sess", 1000, 0.50)
        assert not old_file.exists()
```

No `_patch_state_dir` autouse fixture. No `mock_home`. No `monkeypatch`.

**Step 2: Run tests**

Run: `uv run pytest tests/test_velocity.py -x -q`
Expected: all pass

**Step 3: Commit**

```bash
git add tests/test_velocity.py
git commit -m "Rewrite test_velocity.py for StatusLineContext DI"
```

---

### Task 9: Rewrite `test_integration.py`

**Files:**
- Rewrite: `tests/test_integration.py`

**Step 1: Rewrite using `make_ctx`**

The `_run_main` helper is replaced by:
```python
def _run(ctx):
    ctx.run()
    return ctx.console.file.getvalue()
```

Integration tests become:
```python
class TestMainEndToEnd:
    def test_model_name_in_output(self, make_ctx):
        ctx = make_ctx(input_text=json.dumps(SAMPLE_INPUT))
        ctx.run()
        assert "Opus 4.6" in ctx.console.file.getvalue()

    def test_empty_input(self, mod):
        # main() reads stdin — test it directly
        import sys
        from io import StringIO
        sys.stdin = StringIO("")
        mod.main()  # should return silently

    def test_with_usage_data(self, make_ctx, tmp_path):
        usage = {
            "five_hour": {"utilization": 30, "resets_at": "2099-01-15T05:00:00+00:00"},
            "seven_day": {"utilization": 55, "resets_at": "2099-01-20T00:00:00+00:00"},
        }
        cache = tmp_path / "usage.json"
        cache.write_text(json.dumps(usage))

        ctx = make_ctx(
            input_text=json.dumps(SAMPLE_INPUT),
            now=cache.stat().st_mtime + 5,
        )
        ctx.run()
        output = ctx.console.file.getvalue()
        assert "30%" in output
        assert "55%" in output
```

`TestLoadConfig` tests call `ctx.load_config()`:
```python
class TestLoadConfig:
    def test_defaults_when_no_file(self, make_ctx):
        ctx = make_ctx(config_path=Path("/nonexistent/config.json"))
        config = ctx.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES
```

Wait — `mod` is needed for `DEFAULT_FIGURES`. The `make_ctx` fixture depends on `mod`, so tests that use `make_ctx` can also request `mod`. Alternatively, the test can access `ctx` to get to the module constants... but that's indirect. Best to just also request the `mod` fixture when needed:

```python
    def test_defaults_when_no_file(self, mod, make_ctx, tmp_path):
        ctx = make_ctx(config_path=tmp_path / "nonexistent.json")
        config = ctx.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES
```

`TestConfigIntegration` and `TestShortenBranch` tests work similarly. The `test_no_token_*` tests use `creds_path` pointing to a nonexistent file.

**Step 2: Run tests**

Run: `uv run pytest tests/test_integration.py -x -q`
Expected: all pass

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "Rewrite test_integration.py for StatusLineContext DI"
```

---

### Task 10: Update remaining test files and remove `shorten_dir` mock_home dependency

**Files:**
- Modify: `tests/test_formatting.py` (if it uses `mock_home` for `shorten_dir`)
- Modify: `tests/test_git.py` (if it uses `mock_home`)

**Step 1: Check which tests still use `mock_home`**

`shorten_dir` calls `Path.home()` at runtime. Tests in `test_formatting.py` use `mock_home` to control the home path. Since we're removing `mock_home`, we need to handle this.

Options:
- Give `shorten_dir` an optional `home` parameter: `def shorten_dir(path: str, max_len: int = 30, home: str | None = None)`
- Or just test `shorten_dir` with paths that don't start with the real home

Simplest: add the `home` parameter with default `None` (resolves to `str(Path.home())`):
```python
def shorten_dir(path: str, max_len: int = 30, home: str | None = None) -> str:
    if home is None:
        home = str(Path.home())
    if path.startswith(home):
        path = "~" + path[len(home):]
    ...
```

Update tests to pass `home="/Users/testuser"` and use paths starting with that prefix.

`test_git.py` tests — `parse_git_status` is pure, `get_git_info` uses real subprocess in `tmp_path`. Neither uses `mock_home`. No changes needed.

**Step 2: Run full suite**

Run: `uv run pytest -x -q`
Expected: all pass

**Step 3: Commit**

```bash
git add claude-statusline/statusline-command.py tests/test_formatting.py
git commit -m "Add home param to shorten_dir, remove mock_home dependency"
```

---

### Task 11: Final cleanup — remove dead code, run full validation

**Files:**
- Modify: `claude-statusline/statusline-command.py` (remove any remaining dead free functions)
- Modify: `tests/conftest.py` (remove `mock_home`, `mock_time` if not already done)
- Modify: `CLAUDE.md` (update architecture docs)

**Step 1: Verify no dead free functions remain**

Search for any free functions that are now only methods. Remove them.

**Step 2: Run full validation**

```bash
uv run pytest -x -q                  # all tests pass, 100% coverage
uv run ruff check .                  # no lint errors
uv run ruff format --check .         # no format issues
uv run ty check                      # no new type errors
```

**Step 3: Smoke test**

```bash
echo '{"model":{"display_name":"Opus 4.6"},"session_id":"test","context_window":{"used_percentage":42,"context_window_size":200000,"total_input_tokens":50000,"total_output_tokens":10000},"cost":{"total_cost_usd":1.23,"total_duration_ms":312000},"workspace":{"current_dir":"/tmp"}}' | ./claude-statusline/statusline-command.py
```

**Step 4: Update CLAUDE.md**

Update the architecture section to describe the `StatusLineContext` class, methods vs free functions split, and the DI test pattern.

**Step 5: Commit**

```bash
git add -A
git commit -m "Complete DI refactoring: remove dead code, update docs"
```

---

### Task 12: Squash WIP commits and push

**Step 1: Interactive rebase to squash WIP commits into logical units**

Combine the WIP commits from Tasks 5-6 with their corresponding completion commits. Target: ~3-4 clean commits:
1. "Add StatusLineContext class with all methods"
2. "Rewrite test suite for dependency injection"
3. "Final cleanup: remove dead code, update docs"

**Step 2: Push**

```bash
git push
```

# Dependency Injection Refactoring

Date: 2026-03-08

## Problem

The script uses module-level constants (`STATE_DIR`, `USAGE_CACHE`, etc.) computed
at import time from `Path.home()`.  Tests compensate with extensive
`monkeypatch.setattr` and `unittest.mock.patch` calls — over 20 mock sites across
the suite.  The HTTP boundary (`urllib.request.urlopen`) is also patched globally,
and `Console.__init__` is monkeypatched to capture output.

This is fragile and led to concrete bugs: tests writing to the real
`~/.claude/statusline/debug.log` because the logger was initialised at import time.

## Design

### `StatusLineContext` class

A class that holds all injectable dependencies and exposes the I/O-bearing functions
as methods.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `input_text` | `str` | Raw JSON from stdin |
| `now` | `float` | `time.time()` snapshot |
| `state_dir` | `Path` | Base directory for state files |
| `config_path` | `Path` | Config file path |
| `usage_cache` | `Path` | Usage cache file path |
| `debug_log` | `Path` | Debug log file path |
| `logger` | `logging.Logger` | Logger instance |
| `console` | `Console` | Rich Console for output |
| `fetch` | `Callable[[str, dict[str, str], int], bytes]` | HTTP fetcher `(url, headers, timeout) -> bytes` |

**Methods** (moved from module-level functions):

- `run()` — main logic (body of old `main()`)
- `load_config()` — reads `self.config_path`
- `update_velocity(session_id, total_tokens, total_cost)` — reads/writes `self.state_dir`
- `fetch_usage()` — calls `self.fetch`, writes `self.usage_cache`
- `get_usage()` — orchestrates cache check + fetch
- `init_logging()` — attaches file handler to `self.logger`
- `_read_cache()`, `_cache_is_fresh()`, `_touch_cache()` — cache helpers
- `_warn(msg)` — stderr + logger warning

**Factory:**

```python
@classmethod
def create(cls, input_text: str) -> StatusLineContext:
    state_dir = Path.home() / ".claude" / "statusline"
    return cls(
        input_text=input_text,
        now=time.time(),
        state_dir=state_dir,
        config_path=state_dir / "config.json",
        usage_cache=state_dir / "usage.json",
        debug_log=state_dir / "debug.log",
        logger=logging.getLogger("statusline"),
        console=Console(highlight=False, force_terminal=True, ...),
        fetch=_default_fetch,
    )
```

### Free functions (unchanged)

Pure or near-pure functions that stay at module level:

- Formatting: `format_k`, `format_tok`, `format_ema`, `format_cost`, `format_duration`, `format_time_delta`
- Progress bar: `build_bar`, `pct_style`
- Paths: `shorten_dir`, `shorten_branch`
- Git: `parse_git_status`, `get_git_info`
- Usage helpers: `_reset_epoch`, `time_until_reset`, `pacing_target`
- Flow layout: `flow_figures`, `count_flow_lines`
- Auth: `get_oauth_token(creds_path=None)` — default reads `~/.claude/.credentials.json`
- HTTP: `_default_fetch(url, headers, timeout)` — wraps `urllib.request.urlopen`

### Entry point

```python
def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        return
    ctx = StatusLineContext.create(raw)
    ctx.run()
```

### Module-level constants

- `DEFAULT_FIGURES`, `DEFAULT_MIN_BAR_WIDTH` — stay (immutable config)
- `USAGE_CACHE_AGE` — stays (used by `_cache_is_fresh`)
- `EMA_ALPHA` — stays
- Style constants (`DIM`, `BAR_GREEN`, etc.) — stay
- `STATE_DIR`, `CONFIG_PATH`, `USAGE_CACHE`, `DEBUG_LOG` — **removed**, live in `create()`

### Test structure

**`conftest.py` fixtures:**

```python
@pytest.fixture()
def make_ctx(mod, tmp_path):
    """Factory that builds a test StatusLineContext."""
    def _make(input_text="{}", now=1_000_000.0, fetch=..., console=None, **overrides):
        state_dir = tmp_path / "statusline"
        state_dir.mkdir(exist_ok=True)
        return mod.StatusLineContext(
            input_text=input_text,
            now=now,
            state_dir=state_dir,
            config_path=tmp_path / "config.json",
            usage_cache=tmp_path / "usage.json",
            debug_log=tmp_path / "debug.log",
            logger=logging.getLogger(f"test-{id(tmp_path)}"),
            console=console or Console(file=StringIO(), force_terminal=True),
            fetch=fetch or (lambda url, headers, timeout: b"{}"),
            **overrides,
        )
    return _make
```

**What gets eliminated:**

- `mock_home` fixture
- `mock_time` fixture
- `_patch_state_dir` autouse fixture
- All `monkeypatch.setattr` on module paths/globals
- All `patch("urllib.request.urlopen", ...)`
- All `patch.object(mod, "get_oauth_token", ...)`
- The `Console.__init__` monkeypatch
- All `MagicMock` usage

**Test pattern:**

```python
def test_successful_fetch(self, make_ctx):
    data = {"five_hour": {...}, "seven_day": {...}}
    ctx = make_ctx(fetch=lambda u, h, t: json.dumps(data).encode())
    result, reason = ctx.fetch_usage()
    assert result == data

def test_model_in_output(self, make_ctx):
    ctx = make_ctx(input_text=json.dumps(SAMPLE_INPUT))
    ctx.run()
    assert "Opus 4.6" in ctx.console.file.getvalue()
```

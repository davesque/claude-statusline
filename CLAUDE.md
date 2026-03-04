# CLAUDE.md

## Project overview

A Python status line plugin for Claude Code, distributed as a plugin marketplace. It reads JSON from stdin (provided by Claude Code), fetches usage data from the Anthropic OAuth API, and renders a styled terminal dashboard using Rich.

## Architecture

### Plugin structure

The repo is a single-plugin marketplace:
- `.claude-plugin/marketplace.json` — marketplace manifest
- `claude-statusline/` — plugin subdirectory containing the script, plugin manifest, and slash commands (`setup`, `update`)
- `tests/`, `pyproject.toml`, `uv.lock` — dev tooling at repo root

### Script (`claude-statusline/statusline-command.py`)

Single-file script with these sections:
- **Styles**: Rich style constants
- **Formatting helpers**: `format_k`, `format_tok`, `format_ema`, `format_duration`, `format_cost`
- **Progress bar**: `build_bar()` returns Rich `Text` with color-coded fill and optional pacing marker
- **Working directory**: `shorten_dir()` truncates long paths
- **Per-turn velocity**: EMA tracking for both tokens and cost, persisted per session in `~/.claude/statusline-state-{session_id}.json`
- **Usage**: Fetches from Anthropic OAuth API (`/api/oauth/usage`), cached for 60s in `/tmp/claude-statusline-usage.json`. Provides 5-hour and 7-day rolling window utilization percentages with pacing targets and reset timers.
- **Main**: Parses stdin JSON, builds a Rich `Table` with two metric rows (fully justified, compact pipe separator) and three bar rows (context, 5h usage, 7d usage) with optional right cells for reset timers

## Key conventions

- Uses PEP 723 inline script metadata for dependency management (run via `uv run --script`)
- All terminal styling via Rich `Text` objects and style strings — no raw ANSI escapes
- Rolling usage windows: 5-hour and 7-day
- Auth token read from macOS keychain (`Claude Code-credentials`) or `~/.claude/.credentials.json`
- Usage API: `https://api.anthropic.com/api/oauth/usage`
- Usage cache write is atomic (write to `.tmp` then `replace()`)
- Status line config changes take effect immediately — no restart needed

## Dev workflow

```bash
uv sync                          # Set up dev environment
uv run pytest                    # Run all tests
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run ty check                  # Type check
```

The project uses dual metadata: PEP 723 inline metadata in the script for standalone `uv run --script` usage, and `pyproject.toml` with `[dependency-groups]` for dev tooling. Tests import the hyphenated script via `importlib.util.spec_from_file_location()` (see `tests/conftest.py`).

## Testing

Smoke test with sample JSON:
```bash
echo '{"model":{"display_name":"Opus 4.6"},"session_id":"test","context_window":{"used_percentage":42,"context_window_size":200000,"total_input_tokens":50000,"total_output_tokens":10000},"cost":{"total_cost_usd":1.23,"total_duration_ms":312000},"workspace":{"current_dir":"/tmp"}}' | ./claude-statusline/statusline-command.py
```

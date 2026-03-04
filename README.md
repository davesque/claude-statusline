# claude-statusline

A Claude Code status line plugin. Displays a terminal dashboard with model info, session cost, token velocity, context window usage, and 5-hour/7-day usage tracking with pacing markers.

## Install

1. **Requirements**: [uv](https://docs.astral.sh/uv/) must be installed. Dependencies (Rich) are managed automatically via PEP 723 inline metadata.

2. **Add the marketplace**:
   ```
   /plugin marketplace add https://github.com/davesque/claude-statusline.git
   ```

3. **Install the plugin**:
   ```
   /plugin install claude-statusline
   ```

4. **Run setup**:
   ```
   /claude-statusline:setup
   ```
   This configures `statusLine` in `~/.claude/settings.json`. The status line appears immediately.

5. **Auth**: The script reads your OAuth token from the macOS keychain (`Claude Code-credentials`) or `~/.claude/.credentials.json` to fetch usage data from the Anthropic API.

## Updating

1. **Update the marketplace** (from within a Claude session):
   ```
   /plugin marketplace update claude-statusline-marketplace
   ```

2. **Update the status line path**:
   ```
   /claude-statusline:update
   ```
   This detects the newest cached version and repoints the `statusLine` path in settings. The change takes effect immediately.

## Development

Requires [uv](https://docs.astral.sh/uv/). The project uses dual metadata: PEP 723 inline metadata in the script for standalone usage, and `pyproject.toml` for dev tooling.

```bash
uv sync                          # Install dev dependencies
uv run pytest                    # Run tests
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
```

Dev dependencies (pytest, pytest-mock, ruff, ty) are declared in the `[dependency-groups]` section of `pyproject.toml` and managed via `uv.lock`.

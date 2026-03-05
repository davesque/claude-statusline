# claude-statusline

A Claude Code status line plugin. Displays a terminal dashboard with metrics (model, git branch, session cost, burn rate, per-turn cost), context window and 5-hour/7-day usage progress bars with pacing markers, and reset timers via the Anthropic OAuth API.

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

## Features

### Metrics (top section)

Flowing figures with emoji labels, wrapping to fit the available width:

| Emoji | Figure | Description |
|-------|--------|-------------|
| 🔮 | Model | Claude model powering this session |
| 📂 | Working directory | Current directory (truncated if long) |
| 🌿 | Git branch | Branch name + status: `✓` clean, `+` staged, `*` modified, `?` untracked |
| ⏱️ | Duration | Wall-clock session time |
| 💰 | Total cost | Cumulative session cost |
| 🔥 | Burn rate | Cost per hour |
| 👈 | Last turn | Cost of the most recent turn |
| ⚖️ | Avg/turn | Exponential moving average cost per turn |

### Progress bars (bottom section)

| Bar | Description |
|-----|-------------|
| ctx | Context window usage with color thresholds (green/yellow/red) |
| 5h | 5-hour rolling usage with a pacing marker showing where usage *should* be |
| 7d | 7-day rolling usage with a pacing marker showing where usage *should* be |

Reset timers (⟳) show time until each usage window resets.

### Ask for explanations

Ask Claude about any figure and it will give a targeted explanation of what it means and how it's computed:

> "What does the fire emoji mean?"
> "How is the pacing marker calculated?"

### Customize the layout

Use `/claude-statusline:configure` to change settings interactively:

> "Hide the git and model figures"
> "Put duration first"
> "Make the progress bars wider"

Configuration is stored in `~/.claude/statusline.json` and takes effect immediately. Available options:

- **figures** — ordered list of which figures to show (`model`, `cwd`, `git`, `duration`, `total`, `burn`, `last`, `avg`)
- **min_bar_width** — minimum progress bar width in characters (default: 30)
- **max_width** — overall status line width override (default: auto)

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

Dev dependencies (pytest, pytest-cov, pytest-mock, ruff, ty) are declared in the `[dependency-groups]` section of `pyproject.toml` and managed via `uv.lock`. 100% test coverage is enforced.

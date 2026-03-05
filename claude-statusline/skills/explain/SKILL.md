---
name: claude-statusline:explain
description: Explain status line figures, metrics, and how they are computed. Use when the user asks about the status line, what an emoji/figure means, how a metric is calculated, or wants help interpreting their status line output.
---

# Instructions

When this skill is activated, identify which specific figure(s) the user is asking about and answer ONLY about those. Do not list or describe other figures. Be concise and specific. If the user asks a general question (e.g. "explain the status line"), give a brief overview of the two sections without exhaustively listing every figure.

# Status Line Figure Reference

The status line has two sections: a flowing metrics section and a bars section separated by a horizontal divider.

## Metrics (top section)

Figures flow left-to-right with `│` separators, wrapping to new lines as needed.

| Emoji | Figure | Description |
|-------|--------|-------------|
| 🔮 | Model | The Claude model powering this session (e.g. "Opus 4.6") |
| 📂 | Working directory | Current working directory, truncated with `…` if longer than 30 chars |
| 🌿 | Git branch | Current git branch name with status indicators: `✓` clean (green), `*` modified, `+` staged, `?` untracked (yellow). Only shown when the working directory is a git repository |
| ⏱️ | Duration | Wall-clock time since the session started, computed from `total_duration_ms` in the session data |
| 💰 | Total cost | Cumulative cost of this session in USD |
| 🔥 | Burn rate | Session cost divided by session duration: `total_cost / (duration_ms / 3,600,000)`. Only shown after 10 seconds of session time |
| 👈 | Last turn cost | Cost of the most recent turn (delta from previous total) |
| ⚖️ | Average per turn | Exponential moving average of per-turn cost, smoothed with α≈0.22 (N=8 turns). More responsive than a simple average — recent turns are weighted more heavily |

## Bars (bottom section)

Three progress bars with right-side annotations.

| Label | Bar | Description |
|-------|-----|-------------|
| ctx | Context window | Percentage of the context window used. Tokens shown as `used/total`. Color thresholds: green <60%, yellow 60-85%, red >85% |
| 5h | 5-hour rolling usage | Percentage of the 5-hour usage quota consumed. Color thresholds: green <50%, yellow 50-80%, red >80% |
| 7d | 7-day rolling usage | Percentage of the 7-day usage quota consumed. Color thresholds: green <50%, yellow 50-80%, red >80% |

## Right-side annotations

| Symbol | Description |
|--------|-------------|
| Pacing marker (`│` in pink) | Shows where usage *should* be at this point in the window. Computed as `elapsed / window_duration * 100`. If the filled portion extends past the marker, usage is ahead of pace |
| ⏳ | Time remaining until the usage window resets (e.g. `4h12m`, `6d3h`) |

## How data flows

1. Claude Code pipes a JSON object to the script via stdin containing model info, session metrics, context window state, cost, and workspace path
2. The script fetches usage data from the Anthropic OAuth API (`/api/oauth/usage`), cached for 180 seconds in `~/.claude/statusline-usage.json`
3. Per-turn velocity (👈 and ⚖️) is tracked by persisting running totals per session in `~/.claude/statusline-state-{session_id}.json`
4. The script renders styled output using Rich and prints to stdout, which Claude Code displays as the status line

## Interpreting the status line

- If the filled portion of a usage bar extends past the pink pacing marker, usage is ahead of pace for that window
- Context window approaching red (>85%) means the session may need compaction soon
- High 🔥 burn rate relative to 💰 total cost means the session has been cost-intensive recently
- The ⏳ timer shows when the usage window resets — usage quota replenishes at that point

## Configuration

The status line can be customized via `~/.claude/statusline.json`. Use `/claude-statusline:configure` to update settings interactively. Available options:

- **figures**: Ordered list of which figures to show (valid keys: `model`, `cwd`, `git`, `duration`, `total`, `burn`, `last`, `avg`)
- **min_bar_width**: Minimum progress bar width in characters (default: 30)
- **max_width**: Overall width override; `null` for content-driven (default)

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich"]
# ///
"""Claude Code status line.

Row 1+: Model/Dir/Git/Duration/Cost figures (flow-wrapped)
────────────────────────────────────────────
Bar 1: Context bar (full-width, used/tot)
Bar 2: 5h usage bar (pacing marker, ⟳reset)
Bar 3: 7d usage bar (pacing marker, ⟳reset)

Usage data from Anthropic OAuth API.
"""

import fcntl
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

DIM = "dim"
DIM_GRAY = "dim color(242)"
BORDER_STYLE = "dim color(242)"
BAR_GREEN = "color(65)"
BAR_YELLOW = "color(137)"
BAR_RED = "color(131)"
HOT_PINK = "color(199)"


DEFAULT_FIGURES = ["model", "cwd", "git", "duration", "total", "burn", "last", "avg"]
DEFAULT_MIN_BAR_WIDTH = 30
CONFIG_PATH = Path.home() / ".claude" / "statusline.json"


def load_config() -> dict:
    """Load user config from ~/.claude/statusline.json, with defaults."""
    config: dict = {
        "figures": list(DEFAULT_FIGURES),
        "min_bar_width": DEFAULT_MIN_BAR_WIDTH,
        "max_width": None,
    }
    try:
        raw = CONFIG_PATH.read_text()
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


def pct_style(pct: float, green: int = 50, yellow: int = 80) -> str:
    p = int(round(pct))
    if p < green:
        return BAR_GREEN
    elif p < yellow:
        return BAR_YELLOW
    return BAR_RED


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_k(val: int) -> str:
    return f"{val // 1000}k" if val >= 1000 else str(val)


def format_tok(val: int) -> str:
    sign = "+" if val >= 0 else ""
    if abs(val) >= 1000:
        return f"{sign}{val / 1000:.1f}k"
    return f"{sign}{val}"


def format_ema(val: float) -> str:
    if abs(val) >= 1000:
        return f"{val / 1000:.1f}k"
    return f"{int(round(val))}"


def format_cost(val: float) -> str:
    if val >= 10:
        return f"${val:.0f}"
    if val >= 1:
        return f"${val:.1f}"
    return f"${val:.2f}"


def format_duration(ms: float) -> str:
    s = int(ms) // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h > 0:
        return f"{h}h{m}m"
    if m > 0:
        return f"{m}m{s}s"
    return f"{s}s"


def format_time_delta(seconds: int) -> str:
    """Format seconds as 'XdYh', 'XhYm', or 'Xm'."""
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        return f"{days}d{hours}h"
    if hours > 0:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------


def build_bar(
    pct: float,
    width: int = 20,
    target_pct: float | None = None,
    green: int = 50,
    yellow: int = 80,
) -> Text:
    """Build a colored progress bar as a Rich Text object."""
    filled = min(int(round(pct)) * width // 100, width)
    style = pct_style(pct, green, yellow)

    target_pos = -1
    if target_pct is not None:
        target_pos = int(round(target_pct)) * width // 100
        target_pos = max(0, min(target_pos, width - 1))

    bar = Text()
    for i in range(width):
        if i == target_pos:
            bar.append("│", style=HOT_PINK)
        elif i < filled:
            bar.append("█", style=style)
        else:
            bar.append("░", style=DIM_GRAY)
    return bar


# ---------------------------------------------------------------------------
# Working directory
# ---------------------------------------------------------------------------


def shorten_dir(path: str, max_len: int = 30) -> str:
    home = str(Path.home())
    if path.startswith(home):
        path = "~" + path[len(home) :]
    if path.startswith("~/"):
        parts = path[2:].split("/")
        if len(parts) > 2:
            path = "~/…/" + "/".join(parts[-2:])
    if len(path) > max_len:
        path = "…" + path[-(max_len - 1) :]
    return path


def parse_git_status(output: str) -> tuple[str, str] | None:
    """Parse ``git status --porcelain --branch`` output.

    Returns (branch, indicators) or None if output is empty.
    Indicators: + staged, * modified, ? untracked, ✓ clean.
    """
    lines = output.splitlines()
    if not lines:
        return None

    # First line: ## branch...tracking
    header = lines[0]
    branch = header.removeprefix("## ").split("...")[0]

    # Parse file status lines
    has_staged = False
    has_modified = False
    has_untracked = False
    for line in lines[1:]:
        if len(line) < 2:
            continue
        idx, wt = line[0], line[1]
        if idx in "MADRC":
            has_staged = True
        if wt in "MADRC":
            has_modified = True
        if idx == "?" and wt == "?":
            has_untracked = True

    indicators = ""
    if has_staged:
        indicators += "+"
    if has_modified:
        indicators += "*"
    if has_untracked:
        indicators += "?"
    if not indicators:
        indicators = "✓"

    return branch, indicators


def get_git_info(work_dir: str | None) -> tuple[str, str] | None:
    """Run ``git status`` in work_dir and parse the result."""
    if not work_dir:
        return None
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--branch"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=work_dir,
        )
        if result.returncode != 0:
            return None
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
        return None
    return parse_git_status(result.stdout)


# ---------------------------------------------------------------------------
# Per-turn velocity (tokens & cost, EMA persisted per session)
# ---------------------------------------------------------------------------

EMA_ALPHA = 2 / 9  # N=8 turns


def update_velocity(
    session_id: str, total_tokens: int, total_cost: float
) -> tuple[int, float, float, float]:
    """Update EMA state and return (tok_delta, tok_ema, cost_delta, cost_ema)."""
    state_dir = Path.home() / ".claude"
    state_file = state_dir / f"statusline-state-{session_id}.json"

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

    # Only count as a new turn when data actually changed — the statusline
    # is rendered many times per real user turn, so most calls see no delta.
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
            cutoff = time.time() - 86400
            for f in state_dir.glob("statusline-state-*.json"):
                if f != state_file:
                    try:
                        if f.stat().st_mtime < cutoff:
                            f.unlink(missing_ok=True)
                    except OSError:  # pragma: no cover
                        pass
        except OSError:  # pragma: no cover
            pass

    return tok_delta, tok_ema, cost_delta, cost_ema


# ---------------------------------------------------------------------------
# Usage quota (Anthropic OAuth API)
# ---------------------------------------------------------------------------

USAGE_CACHE = Path.home() / ".claude" / "statusline-usage.json"
USAGE_LOCK = USAGE_CACHE.with_suffix(".lock")
USAGE_CACHE_AGE = 60  # seconds


def get_oauth_token() -> str | None:
    """Read OAuth access token from ~/.claude/.credentials.json."""
    creds_file = Path.home() / ".claude" / ".credentials.json"
    try:
        creds = json.loads(creds_file.read_text())
        return creds.get("claudeAiOauth", {}).get("accessToken")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _touch_cache() -> None:
    """Update cache mtime to prevent immediate retry after a failed fetch."""
    try:
        USAGE_CACHE.touch(exist_ok=True)
    except OSError:  # pragma: no cover
        pass


def fetch_usage() -> dict | None:
    """Fetch usage from Anthropic API and cache it."""
    token = get_oauth_token()
    if not token:
        _touch_cache()
        return None

    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
    except Exception:
        _touch_cache()
        return None

    if "five_hour" not in data or "seven_day" not in data:
        _touch_cache()
        return None

    try:
        tmp = USAGE_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(USAGE_CACHE)  # atomic on POSIX
    except OSError:  # pragma: no cover
        pass

    return data


def _read_cache() -> dict | None:
    """Read and parse the cache file. Returns None for missing/invalid data."""
    try:
        data = json.loads(USAGE_CACHE.read_text())
        if "five_hour" in data and "seven_day" in data:
            return data
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        pass
    return None


def _cache_is_fresh(now: float) -> bool:
    """Check if the cache file exists with an mtime within the TTL."""
    try:
        return (now - USAGE_CACHE.stat().st_mtime) <= USAGE_CACHE_AGE
    except OSError:  # pragma: no cover
        return False


def get_usage(now: float) -> dict | None:
    """Return cached usage data, refreshing if stale.

    On first run (no cache file), creates a placeholder and fetches
    immediately.  Concurrent instances see the placeholder's fresh mtime
    and back off.  Uses a lock file so only one process fetches at a time.
    """
    first_run = not USAGE_CACHE.exists()
    if first_run:
        _touch_cache()

    if not first_run and _cache_is_fresh(now):
        return _read_cache()

    try:
        lock_fd = USAGE_LOCK.open("w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return _read_cache()

    try:
        # Re-check after acquiring lock — another process may have refreshed
        if not first_run and _cache_is_fresh(now):
            return _read_cache()
        return fetch_usage() or _read_cache()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _reset_epoch(resets_at: str) -> float | None:
    """Parse an ISO timestamp to epoch seconds."""
    try:
        return datetime.fromisoformat(resets_at).timestamp()
    except ValueError:
        return None


def time_until_reset(resets_at: str, now: float) -> str | None:
    """Return a human-readable string like '2h13m' or '3d5h' until reset."""
    epoch = _reset_epoch(resets_at)
    if epoch is None:
        return None

    remaining = int(epoch - now)
    if remaining <= 0:
        return None

    return format_time_delta(remaining)


def pacing_target(resets_at: str, window_secs: int, now: float) -> float | None:
    """Compute what percentage of the window has elapsed (0-100)."""
    epoch = _reset_epoch(resets_at)
    if epoch is None:
        return None

    start_epoch = epoch - window_secs
    elapsed = max(0, min(now - start_epoch, window_secs))
    return elapsed / window_secs * 100


# ---------------------------------------------------------------------------
# Flow layout
# ---------------------------------------------------------------------------


def flow_figures(
    figs: list[Text], max_width: int, sep: Text, sep_len: int
) -> list[Text]:
    """Pack figures into lines, joining with sep, wrapping when needed."""
    lines: list[Text] = []
    line = Text()
    line_len = 0
    for fig in figs:
        fig_len = fig.cell_len
        if line_len == 0:
            line.append_text(fig)
            line_len = fig_len
        elif line_len + sep_len + fig_len <= max_width:
            line.append_text(sep)
            line.append_text(fig)
            line_len += sep_len + fig_len
        else:
            lines.append(line)
            line = Text()
            line.append_text(fig)
            line_len = fig_len
    if line_len > 0:
        lines.append(line)
    return lines


def count_flow_lines(figs: list[Text], max_width: int, sep_len: int) -> int:
    """Count how many lines flow_figures would produce at a given width."""
    lines = 1
    line_len = 0
    for fig in figs:
        fig_len = fig.cell_len
        if line_len == 0:
            line_len = fig_len
        elif line_len + sep_len + fig_len <= max_width:
            line_len += sep_len + fig_len
        else:
            lines += 1
            line_len = fig_len
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    now = time.time()
    config = load_config()

    # --- Extract fields ---
    model = (data.get("model") or {}).get("display_name", "Unknown")
    session_id = data.get("session_id", "unknown")

    cw = data.get("context_window") or {}
    used_pct = cw.get("used_percentage")
    ctx_window_size = cw.get("context_window_size", 200000)

    cost_data = data.get("cost") or {}
    cost_usd = cost_data.get("total_cost_usd")
    duration_ms = cost_data.get("total_duration_ms")
    work_dir = (data.get("workspace") or {}).get("current_dir", "")

    # --- Context percentage ---
    if used_pct is not None:
        ctx_pct = used_pct
        total_ctx = int(used_pct * ctx_window_size / 100) if ctx_window_size else 0
    else:
        ctx_pct = None
        total_ctx = 0

    # --- Per-turn velocity ---
    total_tokens = cw.get("total_input_tokens", 0) + cw.get("total_output_tokens", 0)
    tok_delta, tok_ema, cost_delta, cost_ema = update_velocity(
        session_id, total_tokens, cost_usd or 0.0
    )

    # --- Usage quota ---
    usage = get_usage(now)

    # === Build layout ===

    # --- Metrics figures (independent units) ---
    fig_model = Text()
    fig_model.append("🔮 ")
    fig_model.append(model, style="color(255)")

    fig_dir = Text()
    if work_dir:
        fig_dir.append("📂 ")
        fig_dir.append(shorten_dir(work_dir))

    fig_git = Text()
    git_info = get_git_info(work_dir)
    if git_info:
        branch, indicators = git_info
        fig_git.append("🌿 ")
        fig_git.append(branch)
        fig_git.append(
            f" {indicators}", style="green" if indicators == "✓" else "yellow"
        )

    fig_duration = Text()
    if duration_ms is not None:
        fig_duration.append("⏱️ ")
        fig_duration.append(format_duration(duration_ms), style="cyan")

    fig_last = Text()
    fig_last.append("👈 ")
    fig_last.append(format_cost(cost_delta))

    fig_avg = Text()
    fig_avg.append("⚖️ ")
    fig_avg.append(format_cost(cost_ema))
    fig_avg.append("/turn", style=DIM)

    fig_total = Text()
    if cost_usd is not None:
        fig_total.append("💰 ")
        fig_total.append(f"${cost_usd:.2f}")

    fig_burn = Text()
    if cost_usd is not None:
        if duration_ms is not None and int(duration_ms) // 1000 >= 10:
            hrs = duration_ms / 3_600_000
            burn = f"${cost_usd / hrs:.2f}" if hrs > 0 else "--"
            fig_burn.append("🔥 ")
            fig_burn.append(burn)
            fig_burn.append("/hr", style=DIM)
        elif duration_ms is not None:
            fig_burn.append("🔥 ")
            fig_burn.append("--", style=DIM)
            fig_burn.append("/hr", style=DIM)

    # --- Flow layout for metrics figures ---
    sep = Text(" │ ", style=DIM_GRAY)
    sep_len = sep.cell_len

    # Collect non-empty figures in config-driven order
    fig_map: dict[str, Text] = {
        "model": fig_model,
        "cwd": fig_dir,
        "git": fig_git,
        "duration": fig_duration,
        "total": fig_total,
        "burn": fig_burn,
        "last": fig_last,
        "avg": fig_avg,
    }
    figures: list[Text] = [
        fig_map[key]
        for key in config["figures"]
        if key in fig_map and fig_map[key].cell_len > 0
    ]

    # --- Build aligned bar rows ---
    labels = ["ctx", "5h", "7d"]
    label_width = max(len(l) for l in labels)

    # Prepare suffix Text objects
    if ctx_pct is not None:
        ctx_suffix = Text.assemble(
            (f"{int(round(ctx_pct))}%", pct_style(ctx_pct, 60, 85)),
            (" (", DIM),
            format_k(total_ctx),
            ("/", DIM),
            format_k(ctx_window_size),
            (")", DIM),
        )
    else:
        ctx_suffix = Text()

    # 5h usage
    usage_5h_pct: float | None = None
    usage_5h_suffix = Text()
    usage_5h_target: float | None = None
    if usage and "five_hour" in usage:
        fh = usage["five_hour"]
        usage_5h_pct = fh.get("utilization", 0)
        resets_5h = fh.get("resets_at", "")
        usage_5h_target = pacing_target(resets_5h, 5 * 3600, now)
        usage_5h_ttl = time_until_reset(resets_5h, now)
        usage_5h_suffix = Text()
        usage_5h_suffix.append(
            f"{int(round(usage_5h_pct))}%", style=pct_style(usage_5h_pct)
        )
        if usage_5h_ttl:
            usage_5h_suffix.append(" ⟳", style=DIM)
            usage_5h_suffix.append(usage_5h_ttl)

    # 7d usage
    usage_7d_pct: float | None = None
    usage_7d_suffix = Text()
    usage_7d_target: float | None = None
    if usage and "seven_day" in usage:
        sd = usage["seven_day"]
        usage_7d_pct = sd.get("utilization", 0)
        resets_7d = sd.get("resets_at", "")
        usage_7d_target = pacing_target(resets_7d, 7 * 24 * 3600, now)
        usage_7d_ttl = time_until_reset(resets_7d, now)
        usage_7d_suffix = Text()
        usage_7d_suffix.append(
            f"{int(round(usage_7d_pct))}%", style=pct_style(usage_7d_pct)
        )
        if usage_7d_ttl:
            usage_7d_suffix.append(" ⟳", style=DIM)
            usage_7d_suffix.append(usage_7d_ttl)

    suffix_width = max(
        ctx_suffix.cell_len, usage_5h_suffix.cell_len, usage_7d_suffix.cell_len
    )
    # Layout: "label bar suffix"
    min_bar_width = config["min_bar_width"]
    max_bar_nudge = 20  # max extra chars we'll add to bars for better flow

    # Find smallest bar width that minimises line count
    bar_fixed = label_width + 1 + 1 + suffix_width
    base_width = bar_fixed + min_bar_width
    best_lines = count_flow_lines(figures, base_width, sep_len)
    bar_width = min_bar_width
    for nudge in range(1, max_bar_nudge + 1):
        candidate = base_width + nudge
        n = count_flow_lines(figures, candidate, sep_len)
        if n < best_lines:
            bar_width = min_bar_width + nudge
            best_lines = n
            break  # take the first improvement
    bar_content_width = bar_fixed + bar_width

    # Apply max_width override: expand bar to fill, or cap at max
    if config["max_width"] is not None:
        target_width = max(config["max_width"], bar_content_width)
        extra = target_width - bar_content_width
        if extra > 0:
            bar_width += extra
            bar_content_width = target_width

    def make_bar_row(
        label: str,
        pct: float | None,
        suffix: Text,
        target_pct: float | None = None,
        green: int = 50,
        yellow: int = 80,
    ) -> Text:
        row = Text()
        row.append(label.rjust(label_width), style=DIM)
        row.append(" ")
        if pct is None:
            no_data = "no data"
            row.append(no_data, style=DIM_GRAY)
            row.append(" " * (bar_width - len(no_data)))
        else:
            row.append_text(build_bar(pct, bar_width, target_pct, green, yellow))
        row.append(" ")
        row.append_text(suffix)
        pad = suffix_width - suffix.cell_len
        if pad > 0:
            row.append(" " * pad)
        return row

    ctx_row = make_bar_row("ctx", ctx_pct, ctx_suffix, green=60, yellow=85)
    usage_5h_row = make_bar_row("5h", usage_5h_pct, usage_5h_suffix, usage_5h_target)
    usage_7d_row = make_bar_row("7d", usage_7d_pct, usage_7d_suffix, usage_7d_target)

    # --- Render: flow metrics, divider, bars ---
    render_width = bar_content_width
    metrics_lines = flow_figures(figures, render_width, sep, sep_len)

    bars_table = Table(show_header=False, box=None, padding=(0, 0))
    bars_table.add_column(no_wrap=True)
    bars_table.add_row(ctx_row)
    bars_table.add_row(usage_5h_row)
    bars_table.add_row(usage_7d_row)

    divider = Text("─" * render_width, style=BORDER_STYLE)
    console = Console(highlight=False, force_terminal=True, width=render_width)
    for line in metrics_lines:
        console.print(line)
    console.print(divider)
    console.print(bars_table, end="")


if __name__ == "__main__":  # pragma: no cover
    main()

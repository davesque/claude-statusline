#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich"]
# ///
"""Claude Code status line.

Row 1: Model/Dir/Duration       │  Cost last/avg per turn
Row 2: Session total (burn/hr)  │  Token velocity last/avg per turn
Row 3: Context bar (full-width, used/tot)
Row 4: 5h usage bar (pacing marker, ⟳reset)
Row 5: 7d usage bar (pacing marker, ⟳reset)

Usage data from Anthropic OAuth API.
"""

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from rich import box
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
    except OSError:
        pass

    if turn == 1:
        try:
            cutoff = time.time() - 86400
            for f in state_dir.glob("statusline-state-*.json"):
                if f != state_file:
                    try:
                        if f.stat().st_mtime < cutoff:
                            f.unlink(missing_ok=True)
                    except OSError:
                        pass
        except OSError:
            pass

    return tok_delta, tok_ema, cost_delta, cost_ema


# ---------------------------------------------------------------------------
# Usage quota (Anthropic OAuth API)
# ---------------------------------------------------------------------------

USAGE_CACHE = Path("/tmp/claude-statusline-usage.json")
USAGE_CACHE_AGE = 60  # seconds


def get_oauth_token() -> str | None:
    """Read OAuth access token from keychain (macOS) or credentials file."""
    # macOS keychain
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "Claude Code-credentials",
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            creds = json.loads(result.stdout.strip())
            token = creds.get("claudeAiOauth", {}).get("accessToken")
            if token:
                return token
    except (
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        FileNotFoundError,
        OSError,
    ):
        pass

    # Fallback: credentials file (~/.claude/.credentials.json)
    creds_file = Path.home() / ".claude" / ".credentials.json"
    try:
        creds = json.loads(creds_file.read_text())
        return creds.get("claudeAiOauth", {}).get("accessToken")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    return None


def fetch_usage() -> dict | None:
    """Fetch usage from Anthropic API and cache it."""
    token = get_oauth_token()
    if not token:
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
        return None

    if "five_hour" not in data or "seven_day" not in data:
        return None

    try:
        tmp = USAGE_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(USAGE_CACHE)  # atomic on POSIX
    except OSError:
        pass

    return data


def get_usage(now: float) -> dict | None:
    """Return cached usage data, refreshing if stale."""
    cached = None
    try:
        if USAGE_CACHE.exists():
            cached = json.loads(USAGE_CACHE.read_text())
            age = now - USAGE_CACHE.stat().st_mtime
            if age <= USAGE_CACHE_AGE:
                return cached
    except (json.JSONDecodeError, OSError):
        pass

    return fetch_usage() or cached


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

    # --- Row 1: model/dir/duration │ cost per turn ---
    r1_left = Text()
    r1_left.append(model, style="color(255)")
    if work_dir:
        r1_left.append(f" {shorten_dir(work_dir)}")
    if duration_ms is not None:
        r1_left.append(f" {format_duration(duration_ms)}", style="cyan")

    r1_right = Text()
    r1_right.append("last ", style=DIM)
    r1_right.append(format_cost(cost_delta))
    r1_right.append(" avg ", style=DIM)
    r1_right.append(format_cost(cost_ema))
    r1_right.append("/turn", style=DIM)

    # --- Row 2: session total + burn rate │ token velocity ---
    r2_left = Text()
    if cost_usd is not None:
        r2_left.append("total ", style=DIM)
        r2_left.append(f"${cost_usd:.2f}")
        if duration_ms is not None and int(duration_ms) // 1000 >= 10:
            hrs = duration_ms / 3_600_000
            burn = f"${cost_usd / hrs:.2f}" if hrs > 0 else "--"
            r2_left.append(" (", style=DIM)
            r2_left.append(burn)
            r2_left.append("/hr)", style=DIM)
        elif duration_ms is not None:
            r2_left.append(" (", style=DIM)
            r2_left.append("--", style=DIM)
            r2_left.append("/hr)", style=DIM)

    r2_right = Text()
    r2_right.append("last ", style=DIM)
    r2_right.append(format_tok(tok_delta))
    r2_right.append(" avg ", style=DIM)
    r2_right.append(format_ema(tok_ema))
    r2_right.append("/turn", style=DIM)

    # --- Compute widths across both rows ---
    sep = Text(" │ ", style=DIM_GRAY)
    left_half = max(r1_left.cell_len, r2_left.cell_len)
    right_half = max(r1_right.cell_len, r2_right.cell_len)
    content_width = left_half + sep.cell_len + right_half

    def center_text(text: Text, width: int) -> Text:
        pad = width - text.cell_len
        lp = pad // 2
        rp = pad - lp
        result = Text()
        if lp > 0:
            result.append(" " * lp)
        result.append_text(text)
        if rp > 0:
            result.append(" " * rp)
        return result

    def make_metrics_row(left: Text, right: Text, lw: int, rw: int) -> Text:
        row = Text()
        row.append_text(center_text(left, lw))
        row.append_text(sep)
        row.append_text(center_text(right, rw))
        return row

    # --- Build aligned bar rows ---
    labels = ["ctx", "5h", "7d"]
    label_width = max(len(l) for l in labels)

    # Context suffix
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
    usage_5h_ttl: str | None = None
    if usage and "five_hour" in usage:
        fh = usage["five_hour"]
        usage_5h_pct = fh.get("utilization", 0)
        resets_5h = fh.get("resets_at", "")
        usage_5h_target = pacing_target(resets_5h, 5 * 3600, now)
        usage_5h_ttl = time_until_reset(resets_5h, now)
        usage_5h_suffix = Text.assemble(
            (f"{int(round(usage_5h_pct))}%", pct_style(usage_5h_pct)),
        )

    # 7d usage
    usage_7d_pct: float | None = None
    usage_7d_suffix = Text()
    usage_7d_target: float | None = None
    usage_7d_ttl: str | None = None
    if usage and "seven_day" in usage:
        sd = usage["seven_day"]
        usage_7d_pct = sd.get("utilization", 0)
        resets_7d = sd.get("resets_at", "")
        usage_7d_target = pacing_target(resets_7d, 7 * 24 * 3600, now)
        usage_7d_ttl = time_until_reset(resets_7d, now)
        usage_7d_suffix = Text.assemble(
            (f"{int(round(usage_7d_pct))}%", pct_style(usage_7d_pct)),
        )

    # --- Right cell content (⟳ reset timers) ---
    ctx_right = Text()
    usage_5h_right = Text()
    usage_7d_right = Text()
    if usage_5h_ttl:
        usage_5h_right.append("⟳", style=DIM)
        usage_5h_right.append(usage_5h_ttl)
    if usage_7d_ttl:
        usage_7d_right.append("⟳", style=DIM)
        usage_7d_right.append(usage_7d_ttl)

    right_cell_width = max(
        ctx_right.cell_len, usage_5h_right.cell_len, usage_7d_right.cell_len
    )
    has_right_cell = right_cell_width > 0
    right_sep = Text(" │ ", style=DIM_GRAY)
    right_overhead = (right_sep.cell_len + right_cell_width) if has_right_cell else 0

    suffix_width = max(
        ctx_suffix.cell_len, usage_5h_suffix.cell_len, usage_7d_suffix.cell_len
    )
    min_bar_width = 30
    bar_width = max(
        min_bar_width,
        content_width - label_width - 1 - 1 - suffix_width - right_overhead,
    )
    min_bar_content = (
        label_width + 1 + min_bar_width + 1 + suffix_width + right_overhead
    )
    content_width = max(content_width, min_bar_content)

    # Justify metrics rows: distribute extra space evenly to both cells
    extra = content_width - left_half - sep.cell_len - right_half
    justified_left = left_half + extra // 2
    justified_right = content_width - justified_left - sep.cell_len
    metrics_r1 = make_metrics_row(r1_left, r1_right, justified_left, justified_right)
    metrics_r2 = make_metrics_row(r2_left, r2_right, justified_left, justified_right)

    def make_bar_row(
        label: str,
        pct: float | None,
        suffix: Text,
        right_content: Text,
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
        if has_right_cell:
            row.append_text(right_sep)
            row.append_text(center_text(right_content, right_cell_width))
        return row

    ctx_row = make_bar_row("ctx", ctx_pct, ctx_suffix, ctx_right, green=60, yellow=85)
    usage_5h_row = make_bar_row(
        "5h", usage_5h_pct, usage_5h_suffix, usage_5h_right, usage_5h_target
    )
    usage_7d_row = make_bar_row(
        "7d", usage_7d_pct, usage_7d_suffix, usage_7d_right, usage_7d_target
    )

    # --- Render table ---
    table = Table(
        show_header=False,
        box=box.SQUARE,
        border_style=BORDER_STYLE,
        padding=(0, 1),
    )
    table.add_column(no_wrap=True)
    table.add_row(metrics_r1)
    table.add_row(metrics_r2)
    table.add_section()
    table.add_row(ctx_row)
    table.add_row(usage_5h_row)
    table.add_row(usage_7d_row)

    # Width must accommodate the widest row plus table chrome (borders + padding)
    # Table adds: 1 (left border) + 1 (left pad) + content + 1 (right pad) + 1 (right border)
    table_width = content_width + 4
    console = Console(highlight=False, force_terminal=True, width=table_width)
    console.print(table, end="")


if __name__ == "__main__":
    main()

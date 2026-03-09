"""Shared fixtures for statusline-command tests."""

import importlib.util
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
        sys.modules["statusline_command"] = old  # pragma: no cover


def _noop_fetch(url: str, headers: dict[str, str], timeout: int) -> bytes:
    """Default test fetcher that returns empty JSON."""
    return b"{}"  # pragma: no cover


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
        defaults = {
            "input_text": input_text,
            "now": now,
            "state_dir": state_dir,
            "config_path": tmp_path / "config.json",
            "usage_cache": tmp_path / "usage.json",
            "debug_log": tmp_path / "debug.log",
            "logger": logging.getLogger(f"test-{id(tmp_path)}"),
            "console": console
            or Console(file=StringIO(), highlight=False, force_terminal=True),
            "fetch": fetch,
        }
        defaults.update(overrides)
        return mod.StatusLineContext(**defaults)

    return _make

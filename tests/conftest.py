"""Shared fixtures for statusline-command tests."""

import importlib.util
import sys
from pathlib import Path

import pytest

# The script has a hyphenated filename, so we import it via importlib.
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
    # Avoid polluting sys.modules across tests
    old = sys.modules.get("statusline_command")
    sys.modules["statusline_command"] = module
    spec.loader.exec_module(module)
    yield module
    if old is None:
        sys.modules.pop("statusline_command", None)
    else:
        sys.modules["statusline_command"] = old


@pytest.fixture()
def mock_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a temp directory with .claude/ created."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture()
def mock_time(monkeypatch):
    """Return a helper that patches time.time() to a fixed value."""
    import time

    def _set(value: float):
        monkeypatch.setattr(time, "time", lambda: value)

    return _set

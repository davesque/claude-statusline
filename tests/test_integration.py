"""End-to-end tests for main()."""

import json
import sys
from io import StringIO

SAMPLE_INPUT = {
    "model": {"display_name": "Opus 4.6"},
    "session_id": "test-integration",
    "context_window": {
        "used_percentage": 42,
        "context_window_size": 200000,
        "total_input_tokens": 50000,
        "total_output_tokens": 10000,
    },
    "cost": {
        "total_cost_usd": 1.23,
        "total_duration_ms": 312000,
    },
    "workspace": {"current_dir": "/tmp"},
}


def _run_main(mod, input_data, monkeypatch, mock_home, tmp_path):
    """Run main() with given input and return captured stdout."""
    monkeypatch.setattr(mod, "USAGE_CACHE", tmp_path / "usage-cache.json")

    stdin = StringIO(json.dumps(input_data))
    stdout = StringIO()

    monkeypatch.setattr(sys, "stdin", stdin)

    from rich.console import Console

    orig_init = Console.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["file"] = stdout
        kwargs["force_terminal"] = True
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(Console, "__init__", patched_init)

    mod.main()
    return stdout.getvalue()


class TestMainEndToEnd:
    """main() integration tests."""

    def test_valid_input_produces_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert len(output) > 0

    def test_model_name_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "Opus 4.6" in output

    def test_duration_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "5m12s" in output

    def test_cost_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "$1.23" in output

    def test_context_bar_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "ctx" in output
        assert "42%" in output

    def test_empty_stdin(self, mod, monkeypatch, mock_home, tmp_path):
        monkeypatch.setattr(sys, "stdin", StringIO(""))
        mod.main()
        # Should return silently without error

    def test_invalid_json(self, mod, monkeypatch, mock_home, tmp_path):
        monkeypatch.setattr(sys, "stdin", StringIO("not json{{{"))
        mod.main()
        # Should return silently without error

    def test_minimal_input(self, mod, monkeypatch, mock_home, tmp_path):
        minimal = {"model": {}, "session_id": "min", "context_window": {}, "cost": {}}
        output = _run_main(mod, minimal, monkeypatch, mock_home, tmp_path)
        assert len(output) > 0

    def test_with_usage_data(self, mod, monkeypatch, mock_home, tmp_path):
        cache = tmp_path / "usage-cache.json"
        usage = {
            "five_hour": {
                "utilization": 30,
                "resets_at": "2099-01-15T05:00:00+00:00",
            },
            "seven_day": {
                "utilization": 55,
                "resets_at": "2099-01-20T00:00:00+00:00",
            },
        }
        cache.write_text(json.dumps(usage))
        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        import time

        monkeypatch.setattr(time, "time", lambda: cache.stat().st_mtime + 5)

        stdin = StringIO(json.dumps(SAMPLE_INPUT))
        stdout = StringIO()
        monkeypatch.setattr(sys, "stdin", stdin)

        from rich.console import Console

        orig_init = Console.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["file"] = stdout
            kwargs["force_terminal"] = True
            orig_init(self, *args, **kwargs)

        monkeypatch.setattr(Console, "__init__", patched_init)

        mod.main()
        output = stdout.getvalue()
        assert "5h" in output
        assert "30%" in output
        assert "7d" in output
        assert "55%" in output

    def test_zero_duration(self, mod, monkeypatch, mock_home, tmp_path):
        data = {**SAMPLE_INPUT, "cost": {"total_cost_usd": 0.5, "total_duration_ms": 0}}
        output = _run_main(mod, data, monkeypatch, mock_home, tmp_path)
        assert "0s" in output

    def test_no_workspace(self, mod, monkeypatch, mock_home, tmp_path):
        data = {**SAMPLE_INPUT}
        data["workspace"] = {}
        output = _run_main(mod, data, monkeypatch, mock_home, tmp_path)
        assert "Opus 4.6" in output

    def test_emoji_labels_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "🔮" in output  # model
        assert "📂" in output  # cwd
        assert "⏱️" in output  # duration
        assert "💰" in output  # total cost
        assert "👈" in output  # last turn
        assert "⚖️" in output  # avg per turn

    def test_burn_rate_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "🔥" in output  # burn rate
        assert "/hr" in output

    def test_divider_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "──" in output  # horizontal divider

    def test_no_border_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "┌" not in output
        assert "┐" not in output
        assert "└" not in output
        assert "┘" not in output

    def test_git_branch_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        # /tmp won't be a git repo, so no git figure expected
        assert "🌿" not in output

    def test_git_branch_with_repo(self, mod, monkeypatch, mock_home, tmp_path):
        import subprocess

        # Create a git repo in tmp_path
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
            cwd=str(repo),
        )

        data = {**SAMPLE_INPUT, "workspace": {"current_dir": str(repo)}}
        output = _run_main(mod, data, monkeypatch, mock_home, tmp_path)
        assert "🌿" in output
        assert "✓" in output  # clean repo

    def test_usage_reset_timers(self, mod, monkeypatch, mock_home, tmp_path):
        cache = tmp_path / "usage-cache.json"
        usage = {
            "five_hour": {
                "utilization": 30,
                "resets_at": "2099-01-15T05:00:00+00:00",
            },
            "seven_day": {
                "utilization": 55,
                "resets_at": "2099-01-20T00:00:00+00:00",
            },
        }
        cache.write_text(json.dumps(usage))
        monkeypatch.setattr(mod, "USAGE_CACHE", cache)

        import time

        monkeypatch.setattr(time, "time", lambda: cache.stat().st_mtime + 5)

        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "⏳" in output  # reset timer indicator


class TestLoadConfig:
    """Tests for load_config()."""

    def test_defaults_when_no_file(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "CONFIG_PATH", tmp_path / "nonexistent.json")
        config = mod.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES
        assert config["min_bar_width"] == 30
        assert config["max_width"] is None

    def test_partial_config_merges_with_defaults(self, mod, tmp_path, monkeypatch):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text(json.dumps({"min_bar_width": 50}))
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        config = mod.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES
        assert config["min_bar_width"] == 50
        assert config["max_width"] is None

    def test_custom_figures_order(self, mod, tmp_path, monkeypatch):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text(json.dumps({"figures": ["duration", "model"]}))
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        config = mod.load_config()
        assert config["figures"] == ["duration", "model"]

    def test_min_bar_width_floor(self, mod, tmp_path, monkeypatch):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text(json.dumps({"min_bar_width": 3}))
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        config = mod.load_config()
        assert config["min_bar_width"] == 10  # clamped to minimum

    def test_max_width_override(self, mod, tmp_path, monkeypatch):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text(json.dumps({"max_width": 120}))
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        config = mod.load_config()
        assert config["max_width"] == 120

    def test_corrupt_json_returns_defaults(self, mod, tmp_path, monkeypatch):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text("not json{{{")
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        config = mod.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES

    def test_invalid_types_ignored(self, mod, tmp_path, monkeypatch):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "figures": "not-a-list",
                    "min_bar_width": "wide",
                    "max_width": "big",
                }
            )
        )
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        config = mod.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES
        assert config["min_bar_width"] == 30
        assert config["max_width"] is None


class TestConfigIntegration:
    """Integration tests for config-driven figure filtering."""

    def test_hidden_figures_not_in_output(self, mod, monkeypatch, mock_home, tmp_path):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text(json.dumps({"figures": ["model", "duration"]}))
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        assert "🔮" in output  # model included
        assert "⏱️" in output  # duration included
        assert "📂" not in output  # cwd hidden
        assert "💰" not in output  # total hidden
        assert "👈" not in output  # last hidden
        assert "⚖️" not in output  # avg hidden

    def test_max_width_override(self, mod, monkeypatch, mock_home, tmp_path):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text(json.dumps({"max_width": 120}))
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        # Divider should be at least 120 chars wide
        for line in output.splitlines():
            if "──" in line:
                # Strip ANSI codes to measure actual width
                plain = line
                import re

                plain = re.sub(r"\x1b\[[0-9;]*m", "", plain)
                assert len(plain) >= 120
                break

    def test_reordered_figures(self, mod, monkeypatch, mock_home, tmp_path):
        cfg_file = tmp_path / "statusline.json"
        cfg_file.write_text(json.dumps({"figures": ["duration", "model"]}))
        monkeypatch.setattr(mod, "CONFIG_PATH", cfg_file)
        output = _run_main(mod, SAMPLE_INPUT, monkeypatch, mock_home, tmp_path)
        # Both present
        assert "🔮" in output
        assert "⏱️" in output
        # Duration appears before model
        dur_pos = output.index("⏱️")
        model_pos = output.index("🔮")
        assert dur_pos < model_pos

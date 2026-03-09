"""End-to-end tests for main() / ctx.run()."""

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


def _output(ctx):
    """Run ctx and return console output."""
    ctx.run()
    return ctx.console.file.getvalue()


class TestMainEndToEnd:
    """main() / run() integration tests."""

    def test_valid_input_produces_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert len(output) > 0

    def test_model_name_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "Opus 4.6" in output

    def test_duration_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "5m12s" in output

    def test_cost_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "$1.23" in output

    def test_context_bar_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "ctx" in output
        assert "42%" in output

    def test_empty_stdin(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "stdin", StringIO(""))
        mod.main()  # should return silently

    def test_invalid_json(self, make_ctx):
        ctx = make_ctx(input_text="not json{{{")
        ctx.run()  # should return silently without error

    def test_minimal_input(self, make_ctx):
        minimal = {"model": {}, "session_id": "min", "context_window": {}, "cost": {}}
        output = _output(make_ctx(input_text=json.dumps(minimal)))
        assert len(output) > 0

    def test_with_usage_data(self, make_ctx, tmp_path):
        cache = tmp_path / "usage.json"
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

        ctx = make_ctx(
            input_text=json.dumps(SAMPLE_INPUT),
            now=cache.stat().st_mtime + 5,
        )
        output = _output(ctx)
        assert "5h" in output
        assert "30%" in output
        assert "7d" in output
        assert "55%" in output

    def test_zero_duration(self, make_ctx):
        data = {**SAMPLE_INPUT, "cost": {"total_cost_usd": 0.5, "total_duration_ms": 0}}
        output = _output(make_ctx(input_text=json.dumps(data)))
        assert "0s" in output

    def test_no_workspace(self, make_ctx):
        data = {**SAMPLE_INPUT, "workspace": {}}
        output = _output(make_ctx(input_text=json.dumps(data)))
        assert "Opus 4.6" in output

    def test_emoji_labels_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "🔮" in output
        assert "📂" in output
        assert "⏱️" in output
        assert "💰" in output
        assert "👈" in output
        assert "⚖️" in output

    def test_burn_rate_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "🔥" in output
        assert "/hr" in output

    def test_divider_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "──" in output

    def test_no_border_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "┌" not in output
        assert "┐" not in output
        assert "└" not in output
        assert "┘" not in output

    def test_git_branch_in_output(self, make_ctx):
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "🌿" not in output  # /tmp is not a git repo

    def test_git_branch_with_repo(self, make_ctx, tmp_path):
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
            cwd=str(repo),
        )

        data = {**SAMPLE_INPUT, "workspace": {"current_dir": str(repo)}}
        output = _output(make_ctx(input_text=json.dumps(data)))
        assert "🌿" in output
        assert "✓" in output

    def test_usage_reset_timers(self, make_ctx, tmp_path):
        cache = tmp_path / "usage.json"
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

        output = _output(
            make_ctx(
                input_text=json.dumps(SAMPLE_INPUT),
                now=cache.stat().st_mtime + 5,
            )
        )
        assert "⏳" in output

    def test_no_token_shows_warning(self, make_ctx, tmp_path):
        """When there's no OAuth token, warning figure appears."""
        cfg = tmp_path / "config.json"
        figures = [
            "model",
            "cwd",
            "git",
            "duration",
            "total",
            "burn",
            "last",
            "avg",
            "warning",
        ]
        cfg.write_text(json.dumps({"figures": figures}))

        output = _output(
            make_ctx(
                input_text=json.dumps(SAMPLE_INPUT),
                creds_path=tmp_path / "nonexistent.json",
            )
        )
        assert "⚠️" in output
        assert "no token" in output

    def test_no_token_usage_bar_label(self, make_ctx, tmp_path):
        """When there's no OAuth token, usage bars show 'no token' label."""
        output = _output(
            make_ctx(
                input_text=json.dumps(SAMPLE_INPUT),
                creds_path=tmp_path / "nonexistent.json",
            )
        )
        assert "no token" in output


class TestInitLogging:
    """Tests for ctx.init_logging()."""

    def test_init_logging_idempotent(self, make_ctx):
        """Calling init_logging twice doesn't add duplicate handlers."""
        ctx = make_ctx()
        ctx.init_logging()
        ctx.init_logging()  # should return early
        assert len(ctx.logger.handlers) == 1


class TestLoadConfig:
    """Tests for ctx.load_config()."""

    def test_defaults_when_no_file(self, mod, make_ctx, tmp_path):
        ctx = make_ctx(config_path=tmp_path / "nonexistent.json")
        config = ctx.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES
        assert config["min_bar_width"] == 30
        assert config["max_width"] is None

    def test_partial_config_merges_with_defaults(self, mod, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"min_bar_width": 50}))
        ctx = make_ctx()
        config = ctx.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES
        assert config["min_bar_width"] == 50
        assert config["max_width"] is None

    def test_custom_figures_order(self, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"figures": ["duration", "model"]}))
        ctx = make_ctx()
        config = ctx.load_config()
        assert config["figures"] == ["duration", "model"]

    def test_min_bar_width_floor(self, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"min_bar_width": 3}))
        ctx = make_ctx()
        config = ctx.load_config()
        assert config["min_bar_width"] == 10

    def test_max_width_override(self, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"max_width": 120}))
        ctx = make_ctx()
        config = ctx.load_config()
        assert config["max_width"] == 120

    def test_corrupt_json_returns_defaults(self, mod, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("not json{{{")
        ctx = make_ctx()
        config = ctx.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES

    def test_invalid_types_ignored(self, mod, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "figures": "not-a-list",
                    "min_bar_width": "wide",
                    "max_width": "big",
                }
            )
        )
        ctx = make_ctx()
        config = ctx.load_config()
        assert config["figures"] == mod.DEFAULT_FIGURES
        assert config["min_bar_width"] == 30
        assert config["max_width"] is None


class TestConfigIntegration:
    """Integration tests for config-driven figure filtering."""

    def test_hidden_figures_not_in_output(self, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"figures": ["model", "duration"]}))
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "🔮" in output
        assert "⏱️" in output
        assert "📂" not in output
        assert "💰" not in output
        assert "👈" not in output
        assert "⚖️" not in output

    def test_max_width_override(self, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"max_width": 120}))
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        import re

        for line in output.splitlines():
            if "──" in line:
                plain = re.sub(r"\x1b\[[0-9;]*m", "", line)
                assert len(plain) >= 120
                break

    def test_reordered_figures(self, make_ctx, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"figures": ["duration", "model"]}))
        output = _output(make_ctx(input_text=json.dumps(SAMPLE_INPUT)))
        assert "🔮" in output
        assert "⏱️" in output
        dur_pos = output.index("⏱️")
        model_pos = output.index("🔮")
        assert dur_pos < model_pos


class TestShortenBranch:
    """shorten_branch: prefix-aware branch name truncation."""

    def test_short_name_unchanged(self, mod):
        assert mod.shorten_branch("main") == "main"

    def test_long_name_no_slash(self, mod):
        name = "a" * 30
        result = mod.shorten_branch(name, max_len=24)
        assert len(result) == 24
        assert result.startswith("…")

    def test_long_name_with_slash(self, mod):
        name = "feat/implement-very-long-feature-name"
        result = mod.shorten_branch(name, max_len=24)
        assert result.startswith("feat/…")
        assert len(result) == 24

    def test_exact_max_len(self, mod):
        name = "a" * 24
        assert mod.shorten_branch(name, max_len=24) == name

    def test_prefix_too_long(self, mod):
        name = "very-long-prefix-without-slash" + "x" * 10
        result = mod.shorten_branch(name, max_len=24)
        assert result.startswith("…")
        assert len(result) == 24

    def test_slash_prefix_preserved(self, mod):
        name = "fix/JIRA-12345-some-very-long-description"
        result = mod.shorten_branch(name, max_len=24)
        assert result.startswith("fix/")
        assert "…" in result

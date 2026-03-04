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

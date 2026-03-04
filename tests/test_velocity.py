"""Tests for update_velocity (EMA tracking, state persistence)."""

import json
import time

import pytest


class TestUpdateVelocity:
    """update_velocity: EMA calculations and state file management."""

    def test_first_turn_ema_equals_delta(self, mod, mock_home):
        tok_delta, tok_ema, cost_delta, cost_ema = mod.update_velocity(
            "test-sess", 1000, 0.50
        )
        assert tok_delta == 1000
        assert tok_ema == 1000.0
        assert cost_delta == 0.50
        assert cost_ema == 0.50

    def test_second_turn_ema_formula(self, mod, mock_home):
        # Turn 1
        mod.update_velocity("test-sess", 1000, 0.50)
        # Turn 2
        tok_delta, tok_ema, cost_delta, cost_ema = mod.update_velocity(
            "test-sess", 2500, 1.00
        )
        assert tok_delta == 1500
        # EMA = alpha * delta + (1 - alpha) * prev_ema
        alpha = mod.EMA_ALPHA
        expected_tok = alpha * 1500 + (1 - alpha) * 1000.0
        assert abs(tok_ema - expected_tok) < 1.0  # rounded in file

    def test_no_change_skip(self, mod, mock_home):
        mod.update_velocity("test-sess", 1000, 0.50)
        # Same values → no new turn
        tok_delta, tok_ema, cost_delta, cost_ema = mod.update_velocity(
            "test-sess", 1000, 0.50
        )
        assert tok_delta == 0
        assert cost_delta < 0.0001
        # EMA should be preserved from first turn
        assert tok_ema == 1000.0

    def test_state_file_created(self, mod, mock_home):
        mod.update_velocity("test-sess", 1000, 0.50)
        state_file = mock_home / ".claude" / "statusline-state-test-sess.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["turn"] == 1
        assert state["total_tokens"] == 1000

    def test_state_file_updated(self, mod, mock_home):
        mod.update_velocity("test-sess", 1000, 0.50)
        mod.update_velocity("test-sess", 2000, 1.00)
        state_file = mock_home / ".claude" / "statusline-state-test-sess.json"
        state = json.loads(state_file.read_text())
        assert state["turn"] == 2
        assert state["total_tokens"] == 2000

    def test_corrupted_state_recovery(self, mod, mock_home):
        state_file = mock_home / ".claude" / "statusline-state-test-sess.json"
        state_file.write_text("not json{{{")
        # Should recover gracefully
        tok_delta, tok_ema, cost_delta, cost_ema = mod.update_velocity(
            "test-sess", 1000, 0.50
        )
        assert tok_delta == 1000
        assert tok_ema == 1000.0

    def test_missing_state_file(self, mod, mock_home):
        # No state file exists — should work like first turn
        tok_delta, tok_ema, cost_delta, cost_ema = mod.update_velocity(
            "test-sess", 500, 0.25
        )
        assert tok_delta == 500
        assert tok_ema == 500.0

    def test_old_state_cleanup(self, mod, mock_home, monkeypatch):
        claude_dir = mock_home / ".claude"
        # Create an old state file
        old_file = claude_dir / "statusline-state-old-session.json"
        old_file.write_text(json.dumps({"turn": 1, "total_tokens": 0}))

        # Make the old file look older than 24h by backdating mtime
        import os

        old_time = time.time() - 90000  # > 86400
        os.utime(old_file, (old_time, old_time))

        # First turn of a new session triggers cleanup
        mod.update_velocity("new-sess", 1000, 0.50)
        assert not old_file.exists()

    def test_recent_state_not_cleaned(self, mod, mock_home):
        claude_dir = mock_home / ".claude"
        recent_file = claude_dir / "statusline-state-recent.json"
        recent_file.write_text(json.dumps({"turn": 1, "total_tokens": 0}))

        mod.update_velocity("new-sess", 1000, 0.50)
        assert recent_file.exists()

    def test_multiple_turns_ema_converges(self, mod, mock_home):
        """EMA should converge toward the constant delta."""
        for i in range(1, 20):
            tok_delta, tok_ema, cost_delta, cost_ema = mod.update_velocity(
                "test-sess", i * 1000, i * 0.50
            )
        # After many turns of constant delta=1000, EMA → 1000
        assert abs(tok_ema - 1000.0) < 50

    def test_cost_tiny_change_not_skipped(self, mod, mock_home):
        """A cost change >= 0.0001 with tok_delta=0 should still count."""
        # Turn 1: establish state
        mod.update_velocity("test-sess", 1000, 0.50)
        # Turn 2: tokens same, but cost changed significantly
        tok_delta, tok_ema, cost_delta, cost_ema = mod.update_velocity(
            "test-sess", 1000, 0.60
        )
        # tok_delta is 0 but cost_delta=0.10 ≥ 0.0001 → new turn
        assert cost_delta == pytest.approx(0.10, abs=0.001)
        alpha = mod.EMA_ALPHA
        expected = alpha * 0.10 + (1 - alpha) * 0.50
        assert cost_ema == pytest.approx(expected, abs=0.01)

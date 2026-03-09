"""Tests for update_velocity (EMA tracking, state persistence)."""

import json
import os

import pytest


class TestUpdateVelocity:
    """update_velocity: EMA calculations and state file management."""

    def test_first_turn_ema_equals_delta(self, make_ctx):
        ctx = make_ctx()
        tok_delta, tok_ema, cost_delta, cost_ema = ctx.update_velocity(
            "test-sess", 1000, 0.50
        )
        assert tok_delta == 1000
        assert tok_ema == 1000.0
        assert cost_delta == 0.50
        assert cost_ema == 0.50

    def test_second_turn_ema_formula(self, mod, make_ctx):
        ctx = make_ctx()
        # Turn 1
        ctx.update_velocity("test-sess", 1000, 0.50)
        # Turn 2
        tok_delta, tok_ema, cost_delta, cost_ema = ctx.update_velocity(
            "test-sess", 2500, 1.00
        )
        assert tok_delta == 1500
        alpha = mod.EMA_ALPHA
        expected_tok = alpha * 1500 + (1 - alpha) * 1000.0
        assert abs(tok_ema - expected_tok) < 1.0

    def test_no_change_skip(self, make_ctx):
        ctx = make_ctx()
        ctx.update_velocity("test-sess", 1000, 0.50)
        tok_delta, tok_ema, cost_delta, cost_ema = ctx.update_velocity(
            "test-sess", 1000, 0.50
        )
        assert tok_delta == 0
        assert cost_delta < 0.0001
        assert tok_ema == 1000.0

    def test_state_file_created(self, make_ctx, tmp_path):
        ctx = make_ctx()
        ctx.update_velocity("test-sess", 1000, 0.50)
        state_file = tmp_path / "statusline" / "state-test-sess.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["turn"] == 1
        assert state["total_tokens"] == 1000

    def test_state_file_updated(self, make_ctx, tmp_path):
        ctx = make_ctx()
        ctx.update_velocity("test-sess", 1000, 0.50)
        ctx.update_velocity("test-sess", 2000, 1.00)
        state_file = tmp_path / "statusline" / "state-test-sess.json"
        state = json.loads(state_file.read_text())
        assert state["turn"] == 2
        assert state["total_tokens"] == 2000

    def test_corrupted_state_recovery(self, make_ctx, tmp_path):
        ctx = make_ctx()
        state_file = tmp_path / "statusline" / "state-test-sess.json"
        state_file.write_text("not json{{{")
        tok_delta, tok_ema, cost_delta, cost_ema = ctx.update_velocity(
            "test-sess", 1000, 0.50
        )
        assert tok_delta == 1000
        assert tok_ema == 1000.0

    def test_missing_state_file(self, make_ctx):
        ctx = make_ctx()
        tok_delta, tok_ema, cost_delta, cost_ema = ctx.update_velocity(
            "test-sess", 500, 0.25
        )
        assert tok_delta == 500
        assert tok_ema == 500.0

    def test_old_state_cleanup(self, make_ctx, tmp_path):
        ctx = make_ctx(now=100_000.0)
        state_dir = tmp_path / "statusline"
        old_file = state_dir / "state-old-session.json"
        old_file.write_text(json.dumps({"turn": 1, "total_tokens": 0}))

        old_time = ctx.now - 90000  # > 86400
        os.utime(old_file, (old_time, old_time))

        ctx.update_velocity("new-sess", 1000, 0.50)
        assert not old_file.exists()

    def test_recent_state_not_cleaned(self, make_ctx, tmp_path):
        ctx = make_ctx()
        state_dir = tmp_path / "statusline"
        recent_file = state_dir / "state-recent.json"
        recent_file.write_text(json.dumps({"turn": 1, "total_tokens": 0}))

        ctx.update_velocity("new-sess", 1000, 0.50)
        assert recent_file.exists()

    def test_multiple_turns_ema_converges(self, make_ctx):
        """EMA should converge toward the constant delta."""
        ctx = make_ctx()
        for i in range(1, 20):
            tok_delta, tok_ema, cost_delta, cost_ema = ctx.update_velocity(
                "test-sess", i * 1000, i * 0.50
            )
        assert abs(tok_ema - 1000.0) < 50

    def test_cost_tiny_change_not_skipped(self, mod, make_ctx):
        """A cost change >= 0.0001 with tok_delta=0 should still count."""
        ctx = make_ctx()
        ctx.update_velocity("test-sess", 1000, 0.50)
        tok_delta, tok_ema, cost_delta, cost_ema = ctx.update_velocity(
            "test-sess", 1000, 0.60
        )
        assert cost_delta == pytest.approx(0.10, abs=0.001)
        alpha = mod.EMA_ALPHA
        expected = alpha * 0.10 + (1 - alpha) * 0.50
        assert cost_ema == pytest.approx(expected, abs=0.01)

"""Tests for build_bar and shorten_dir."""


class TestBuildBar:
    """build_bar: Rich Text progress bar."""

    def test_empty_bar(self, mod):
        bar = mod.build_bar(0, width=10)
        assert bar.plain == "░" * 10

    def test_full_bar(self, mod):
        bar = mod.build_bar(100, width=10)
        assert bar.plain == "█" * 10

    def test_half_bar(self, mod):
        bar = mod.build_bar(50, width=10)
        plain = bar.plain
        assert plain.count("█") == 5
        assert plain.count("░") == 5

    def test_partial_bar_fractional(self, mod):
        # 33% of 10 = 3.3 chars → 3 full + fractional boundary
        bar = mod.build_bar(33, width=10)
        assert bar.plain.count("█") == 3
        # Boundary char is ▎ (round(0.3*8)=2 → index 2 in FRACTIONAL_BLOCKS)
        assert bar.plain[3] == "▎"
        assert bar.plain.count("░") == 6

    def test_bar_length_always_correct(self, mod):
        for pct in [0, 25, 50, 75, 100]:
            bar = mod.build_bar(pct, width=20)
            assert len(bar.plain) == 20

    def test_target_marker(self, mod):
        bar = mod.build_bar(30, width=10, target_pct=50)
        assert "│" in bar.plain

    def test_target_marker_position(self, mod):
        bar = mod.build_bar(30, width=20, target_pct=50)
        # 50% of 20 = position 10
        assert bar.plain[10] == "│"

    def test_target_marker_at_zero(self, mod):
        bar = mod.build_bar(50, width=10, target_pct=0)
        assert bar.plain[0] == "│"

    def test_target_marker_at_end(self, mod):
        bar = mod.build_bar(50, width=10, target_pct=100)
        # Clamped to width - 1
        assert bar.plain[9] == "│"

    def test_no_target_marker(self, mod):
        bar = mod.build_bar(50, width=10)
        assert "│" not in bar.plain

    def test_exact_boundary_no_fractional(self, mod):
        # 50% of 20 = 10.0 chars → no fractional block
        bar = mod.build_bar(50, width=20)
        assert bar.plain[9] == "█"
        assert bar.plain[10] == "░"

    def test_fractional_just_above_boundary(self, mod):
        # 1% of 20 = 0.2 chars → fractional at position 0
        bar = mod.build_bar(1, width=20)
        # round(0.2*8)=round(1.6)=2 → ▎
        assert bar.plain[0] == "▎"
        assert bar.plain[1] == "░"

    def test_fractional_just_below_full(self, mod):
        # 99% of 20 = 19.8 chars → 19 full + fractional at position 19
        bar = mod.build_bar(99, width=20)
        assert bar.plain[18] == "█"
        # round(0.8*8)=round(6.4)=6 → ▊
        assert bar.plain[19] == "▊"

    def test_fractional_rounds_to_full_block(self, mod):
        # Need frac where round(frac*8)=8 → frac >= 0.4375 (7/16)
        # 47% of 10 = 4.7 chars → round(0.7*8)=round(5.6)=6 → ▊ (not full)
        # 49% of 10 = 4.9 chars → round(0.9*8)=round(7.2)=7 → ▉ (not full)
        # 94% of 20 = 18.8 → round(0.8*8)=6 → ▊
        # We need frac*8 >= 7.5 → frac >= 0.9375
        # 96% of 20 = 19.2 → round(0.2*8)=2 → ▎ (nope, full=19, boundary at 19)
        # 99.7% of 20 = 19.94 → full=19, frac=0.94, round(0.94*8)=round(7.52)=8 → █
        bar = mod.build_bar(99.7, width=20)
        assert bar.plain[19] == "█"
        assert bar.plain == "█" * 20

    def test_fractional_rounds_to_zero(self, mod):
        # frac*8 < 0.5 → rounds to 0 → empty char
        # 50.1% of 20 = 10.02 → round(0.02*8)=round(0.16)=0 → ░
        bar = mod.build_bar(50.1, width=20)
        assert bar.plain[10] == "░"

    def test_target_marker_overrides_fractional(self, mod):
        # 33% of 10 = 3.3 → fractional would be at position 3
        # Put target at position 3 (30%) — target should win
        bar = mod.build_bar(33, width=10, target_pct=30)
        assert bar.plain[3] == "│"

    def test_length_correct_with_all_fractional_percentages(self, mod):
        # Sweep 0-100 in 0.5% steps — length must always be exact
        for pct_x10 in range(0, 1001, 5):
            pct = pct_x10 / 10.0
            bar = mod.build_bar(pct, width=20)
            assert len(bar.plain) == 20, f"length wrong at {pct}%"

    def test_over_100_clamped(self, mod):
        bar = mod.build_bar(150, width=10)
        assert bar.plain == "█" * 10


class TestShortenDir:
    """shorten_dir: path abbreviation."""

    def test_home_replacement(self, mod, mock_home):
        home = str(mock_home)
        assert mod.shorten_dir(f"{home}/projects") == "~/projects"

    def test_deep_path_ellipsis(self, mod, mock_home):
        home = str(mock_home)
        result = mod.shorten_dir(f"{home}/a/b/c/d")
        assert result == "~/…/c/d"

    def test_exactly_two_parts(self, mod, mock_home):
        home = str(mock_home)
        # Two parts after ~/ → no ellipsis
        result = mod.shorten_dir(f"{home}/a/b")
        assert result == "~/a/b"

    def test_one_part(self, mod, mock_home):
        home = str(mock_home)
        result = mod.shorten_dir(f"{home}/projects")
        assert result == "~/projects"

    def test_max_len_truncation(self, mod, mock_home):
        long_path = "/very/long/absolute/path/that/exceeds/limit"
        result = mod.shorten_dir(long_path, max_len=20)
        assert len(result) <= 20
        assert result.startswith("…")

    def test_short_path_no_truncation(self, mod):
        result = mod.shorten_dir("/tmp", max_len=30)
        assert result == "/tmp"

    def test_non_home_path(self, mod):
        result = mod.shorten_dir("/opt/data/files")
        assert result == "/opt/data/files"

    def test_custom_max_len(self, mod, mock_home):
        home = str(mock_home)
        result = mod.shorten_dir(f"{home}/a/b/c/d", max_len=10)
        assert len(result) <= 10

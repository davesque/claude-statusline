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

    def test_partial_bar_rounding(self, mod):
        # 33% of 10 = 3.3 → rounds to 3
        bar = mod.build_bar(33, width=10)
        assert bar.plain.count("█") == 3
        assert bar.plain.count("░") == 7

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

    def test_over_100_clamped(self, mod):
        bar = mod.build_bar(150, width=10)
        assert bar.plain == "█" * 10


class TestShortenDir:
    """shorten_dir: path abbreviation."""

    def test_home_replacement(self, mod):
        result = mod.shorten_dir("/Users/testuser/projects", home="/Users/testuser")
        assert result == "~/projects"

    def test_deep_path_ellipsis(self, mod):
        result = mod.shorten_dir("/Users/testuser/a/b/c/d", home="/Users/testuser")
        assert result == "~/…/c/d"

    def test_exactly_two_parts(self, mod):
        result = mod.shorten_dir("/Users/testuser/a/b", home="/Users/testuser")
        assert result == "~/a/b"

    def test_one_part(self, mod):
        result = mod.shorten_dir("/Users/testuser/projects", home="/Users/testuser")
        assert result == "~/projects"

    def test_max_len_truncation(self, mod):
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

    def test_custom_max_len(self, mod):
        result = mod.shorten_dir(
            "/Users/testuser/a/b/c/d", max_len=10, home="/Users/testuser"
        )
        assert len(result) <= 10

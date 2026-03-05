"""Tests for flow_figures and count_flow_lines."""

from rich.text import Text


def _make_figs(widths: list[int]) -> list[Text]:
    """Create Text objects with given cell widths."""
    return [Text("x" * w) for w in widths]


def _sep():
    return Text(" | "), 3  # sep and sep_len


class TestFlowFigures:
    """flow_figures: packing figures into wrapped lines."""

    def test_single_figure(self, mod):
        figs = _make_figs([10])
        sep, sep_len = _sep()
        lines = mod.flow_figures(figs, 80, sep, sep_len)
        assert len(lines) == 1
        assert lines[0].plain == "x" * 10

    def test_all_fit_one_line(self, mod):
        figs = _make_figs([5, 5, 5])
        sep, sep_len = _sep()
        # 5 + 3 + 5 + 3 + 5 = 21, fits in 25
        lines = mod.flow_figures(figs, 25, sep, sep_len)
        assert len(lines) == 1

    def test_wraps_to_two_lines(self, mod):
        figs = _make_figs([10, 10, 10])
        sep, sep_len = _sep()
        # 10 + 3 + 10 = 23, fits in 25; 10 wraps to line 2
        lines = mod.flow_figures(figs, 25, sep, sep_len)
        assert len(lines) == 2

    def test_each_on_own_line(self, mod):
        figs = _make_figs([10, 10, 10])
        sep, sep_len = _sep()
        # Width 10: each figure takes a full line
        lines = mod.flow_figures(figs, 10, sep, sep_len)
        assert len(lines) == 3

    def test_empty_list(self, mod):
        sep, sep_len = _sep()
        lines = mod.flow_figures([], 80, sep, sep_len)
        assert lines == []

    def test_separator_appears_between_figures(self, mod):
        figs = _make_figs([3, 3])
        sep, sep_len = _sep()
        lines = mod.flow_figures(figs, 20, sep, sep_len)
        assert len(lines) == 1
        assert " | " in lines[0].plain


class TestCountFlowLines:
    """count_flow_lines: line counting without building Text objects."""

    def test_single_figure(self, mod):
        figs = _make_figs([10])
        assert mod.count_flow_lines(figs, 80, 3) == 1

    def test_all_fit(self, mod):
        figs = _make_figs([5, 5, 5])
        # 5 + 3 + 5 + 3 + 5 = 21
        assert mod.count_flow_lines(figs, 25, 3) == 1

    def test_wraps(self, mod):
        figs = _make_figs([10, 10, 10])
        # 10 + 3 + 10 = 23 fits in 25, third wraps
        assert mod.count_flow_lines(figs, 25, 3) == 2

    def test_each_own_line(self, mod):
        figs = _make_figs([10, 10, 10])
        assert mod.count_flow_lines(figs, 10, 3) == 3

    def test_empty(self, mod):
        assert mod.count_flow_lines([], 80, 3) == 1

    def test_agrees_with_flow_figures(self, mod):
        """count_flow_lines should return same count as len(flow_figures(...))."""
        figs = _make_figs([8, 12, 6, 15, 10])
        sep, sep_len = _sep()
        for width in [20, 30, 40, 50, 80]:
            lines = mod.flow_figures(figs, width, sep, sep_len)
            count = mod.count_flow_lines(figs, width, sep_len)
            assert count == len(lines), f"Mismatch at width={width}"

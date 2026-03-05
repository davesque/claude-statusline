"""Tests for git status parsing (parse_git_status) and get_git_info."""


class TestParseGitStatus:
    """parse_git_status: pure parsing of git status --porcelain --branch output."""

    def test_clean_repo(self, mod):
        output = "## main...origin/main\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "✓")

    def test_branch_without_tracking(self, mod):
        output = "## feature-branch\n"
        result = mod.parse_git_status(output)
        assert result == ("feature-branch", "✓")

    def test_modified_files(self, mod):
        output = "## main...origin/main\n M file.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "*")

    def test_staged_files(self, mod):
        output = "## main...origin/main\nM  file.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "+")

    def test_untracked_files(self, mod):
        output = "## main...origin/main\n?? newfile.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "?")

    def test_staged_and_modified(self, mod):
        output = "## main\nM  staged.py\n M modified.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "+*")

    def test_all_indicators(self, mod):
        output = "## dev\nA  added.py\n M changed.py\n?? unknown.py\n"
        result = mod.parse_git_status(output)
        assert result == ("dev", "+*?")

    def test_staged_and_untracked(self, mod):
        output = "## main\nM  staged.py\n?? new.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "+?")

    def test_renamed_file(self, mod):
        output = "## main\nR  old.py -> new.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "+")

    def test_deleted_file_staged(self, mod):
        output = "## main\nD  removed.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "+")

    def test_deleted_file_unstaged(self, mod):
        output = "## main\n D removed.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "*")

    def test_copied_file(self, mod):
        output = "## main\nC  copy.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "+")

    def test_empty_output(self, mod):
        assert mod.parse_git_status("") is None

    def test_short_line_ignored(self, mod):
        # A line with fewer than 2 chars after header should be skipped
        output = "## main\nX\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "✓")

    def test_indicator_order_is_plus_star_question(self, mod):
        """Indicators should always be in order: + * ? regardless of file order."""
        output = "## main\n?? new.py\n M mod.py\nA  add.py\n"
        result = mod.parse_git_status(output)
        assert result == ("main", "+*?")


class TestGetGitInfo:
    """get_git_info: subprocess wrapper."""

    def test_none_for_no_workdir(self, mod):
        assert mod.get_git_info(None) is None
        assert mod.get_git_info("") is None

    def test_none_for_non_git_dir(self, mod, tmp_path):
        assert mod.get_git_info(str(tmp_path)) is None

    def test_real_git_repo(self, mod, tmp_path):
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
            cwd=str(repo),
        )
        result = mod.get_git_info(str(repo))
        assert result is not None
        branch, indicators = result
        assert isinstance(branch, str)
        assert indicators == "✓"

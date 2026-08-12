"""Tests for the Forge commit-message checker script."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_commit_messages import check_subject


def test_valid_subjects_pass():
    for subject in [
        "[cli/feat]: add resize command",
        "[repo/docs]: update GOAL frontier",
        "[cli/feat!]: remove watch command",
        "[deps/build]: bump pillow from 12.3.0 to 12.4.0",
    ]:
        assert check_subject(subject) == [], subject


def test_merge_commits_are_exempt():
    assert check_subject("Merge pull request #11 from ChangWinde/feat/ai-native") == []


def test_invalid_subjects_fail():
    for subject in [
        "feat: conventional style",
        "[cli/unknown]: bad op",
        "[cli/feat] missing colon",
        "[cli/feat]!: bang outside brackets",
        "random text",
    ]:
        assert check_subject(subject), subject


def test_overlong_subject_fails():
    subject = "[cli/feat]: " + "x" * 70
    problems = check_subject(subject)
    assert any("72" in problem for problem in problems)

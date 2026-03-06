"""Regression tests for workflow command helper behaviors."""

from pathlib import Path

from pixshift.commands.workflow_commands import _resolve_strip_mode
from pixshift.dedup_engine import DuplicateGroup, delete_duplicates


def test_resolve_strip_mode_privacy():
    flags = _resolve_strip_mode("privacy")
    assert flags == (False, True, True, True, False)


def test_resolve_strip_mode_all():
    flags = _resolve_strip_mode("all")
    assert flags == (True, False, False, False, False)


def test_delete_duplicates_dry_run_and_real_delete(tmp_path):
    keep = tmp_path / "keep.jpg"
    dup = tmp_path / "dup.jpg"
    keep.write_bytes(b"keep")
    dup.write_bytes(b"dup")

    group = DuplicateGroup(
        files=[str(keep), str(dup)],
        sizes=[keep.stat().st_size, dup.stat().st_size],
        keep=str(keep),
        duplicates=[str(dup)],
    )

    dry_result = delete_duplicates([group], dry_run=True)
    assert len(dry_result["deleted"]) == 1
    assert Path(dup).exists()

    real_result = delete_duplicates([group], dry_run=False)
    assert len(real_result["deleted"]) == 1
    assert not Path(dup).exists()


def test_dedup_wrapper_delete_supports_dry_run(monkeypatch):
    from pixshift.ops import dedup as dedup_ops

    called = {"dry_run": None}

    def fake_delete_duplicates(groups, dry_run):
        called["dry_run"] = dry_run
        return {"deleted": groups, "kept": [], "errors": []}

    monkeypatch.setattr("pixshift.ops.dedup.delete_duplicates", fake_delete_duplicates)
    dedup_ops.delete(["g"], dry_run=True)
    assert called["dry_run"] is True


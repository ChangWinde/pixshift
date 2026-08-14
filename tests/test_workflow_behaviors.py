"""Regression tests for workflow command helper behaviors."""

from pathlib import Path

from pixshift.commands.workflow_commands import _resolve_strip_mode
from pixshift.dedup_engine import DeleteCandidate, delete_duplicates


def test_resolve_strip_mode_privacy():
    flags = _resolve_strip_mode("privacy")
    assert flags == (False, True, True, True, False)


def test_resolve_strip_mode_all():
    flags = _resolve_strip_mode("all")
    assert flags == (True, False, False, False, False)


def test_delete_duplicates_dry_run_and_real_delete(tmp_path):
    keep = tmp_path / "keep.jpg"
    dup = tmp_path / "dup.jpg"
    keep.write_bytes(b"same")
    dup.write_bytes(b"same")

    candidate = DeleteCandidate(
        keep=str(keep),
        duplicate=str(dup),
        sha256="0967115f2813a3541eaef77de9d9d5773f1c0c04314b0bbfe4ff3b3b1c55b5d5",
        size=4,
    )

    dry_result = delete_duplicates([candidate], dry_run=True)
    assert len(dry_result["deleted"]) == 1
    assert Path(dup).exists()

    real_result = delete_duplicates([candidate], dry_run=False)
    assert len(real_result["deleted"]) == 1
    assert not Path(dup).exists()


def test_dedup_wrapper_delete_supports_dry_run(monkeypatch):
    from pixshift.ops import dedup as dedup_ops

    called = {"dry_run": None, "backup_dir": "unset"}

    def fake_delete_duplicates(groups, dry_run, backup_dir=None):
        called["dry_run"] = dry_run
        called["backup_dir"] = backup_dir
        return {"deleted": groups, "kept": [], "errors": []}

    monkeypatch.setattr("pixshift.ops.dedup.delete_duplicates", fake_delete_duplicates)
    dedup_ops.delete(["g"], dry_run=True)
    assert called["backup_dir"] is None
    assert called["dry_run"] is True

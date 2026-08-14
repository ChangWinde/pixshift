"""Regression coverage for the shared filesystem publication boundary."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pixshift import dedup_engine
from pixshift.core.errors import OutputBoundaryError
from pixshift.core.files import (
    _WINDOWS_FILE_ATTRIBUTE_DIRECTORY,
    _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT,
    _validate_windows_parent_chain,
    atomic_output_path,
    atomic_write_bytes,
    collect_supported_files,
    safe_output_path,
)
from pixshift.ops import prep as prep_ops
from pixshift.ops.hashing import _collect_all_files
from pixshift.pdf_engine import _collect_images, _collect_pdfs
from pixshift.video_engine import collect_video_files


def test_atomic_no_clobber_is_enforced_at_commit(tmp_path: Path) -> None:
    target = tmp_path / "result.bin"

    with (
        pytest.raises(FileExistsError, match="output_exists"),
        atomic_output_path(str(target), overwrite=False) as candidate,
    ):
        Path(candidate).write_bytes(b"candidate")
        # Simulate another process winning after the caller's preflight.
        target.write_bytes(b"concurrent owner")

    assert target.read_bytes() == b"concurrent owner"
    assert not list(tmp_path.glob(".pixshift-output-*"))


def test_windows_parent_chain_policy_rejects_reparse_components() -> None:
    _validate_windows_parent_chain(
        [("drive", _WINDOWS_FILE_ATTRIBUTE_DIRECTORY), ("safe", _WINDOWS_FILE_ATTRIBUTE_DIRECTORY)]
    )

    with pytest.raises(OutputBoundaryError, match="reparse"):
        _validate_windows_parent_chain(
            [
                ("drive", _WINDOWS_FILE_ATTRIBUTE_DIRECTORY),
                (
                    "junction",
                    _WINDOWS_FILE_ATTRIBUTE_DIRECTORY | _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT,
                ),
            ]
        )

    with pytest.raises(OutputBoundaryError, match="non-directory"):
        _validate_windows_parent_chain([("file", 0)])


def _create_windows_junction(link: Path, target: Path) -> None:
    completed = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert link.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction semantics")
def test_windows_publication_rejects_junction_inserted_after_planning(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    planned = safe_output_path(approved, "nested/result.bin")
    _create_windows_junction(approved / "nested", outside)

    with pytest.raises(OutputBoundaryError, match="reparse"):
        atomic_write_bytes(planned, b"escaped", overwrite=False)

    assert not (outside / "result.bin").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory handle semantics")
def test_windows_publication_binds_parent_against_junction_swap(tmp_path: Path) -> None:
    parent = tmp_path / "approved" / "nested"
    parent.mkdir(parents=True)
    target = parent / "result.bin"

    with atomic_output_path(str(target), overwrite=False) as candidate:
        Path(candidate).write_bytes(b"candidate")
        with pytest.raises(OSError):
            parent.rename(tmp_path / "parked")

    assert target.read_bytes() == b"candidate"


@pytest.mark.skipif(os.name != "nt", reason="Windows directory handle semantics")
def test_windows_publication_binds_staging_directory_against_junction_swap(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "approved"
    outside = tmp_path / "outside"
    parent.mkdir()
    outside.mkdir()
    target = parent / "result.bin"

    with atomic_output_path(str(target), overwrite=False) as candidate:
        candidate_path = Path(candidate)
        staging_directory = candidate_path.parent
        with pytest.raises(OSError):
            staging_directory.rename(tmp_path / "parked-stage")
        candidate_path.write_bytes(b"candidate")

    assert target.read_bytes() == b"candidate"
    assert not (outside / "result.bin").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@pytest.mark.parametrize("mode", [0o600, 0o640])
def test_atomic_overwrite_preserves_target_mode(tmp_path: Path, mode: int) -> None:
    target = tmp_path / "private.bin"
    target.write_bytes(b"old")
    target.chmod(mode)

    atomic_write_bytes(str(target), b"new", overwrite=True)

    assert target.read_bytes() == b"new"
    assert target.stat().st_mode & 0o777 == mode


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_atomic_overwrite_preserves_mode_replaced_during_encode(tmp_path: Path) -> None:
    target = tmp_path / "private.bin"
    target.write_bytes(b"old")
    target.chmod(0o644)

    with atomic_output_path(str(target), overwrite=True) as temporary:
        Path(temporary).write_bytes(b"new")
        target.write_bytes(b"concurrent")
        target.chmod(0o600)

    assert target.read_bytes() == b"new"
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_directory_collection_does_not_follow_file_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    scanned = tmp_path / "scanned"
    scanned.mkdir()
    (scanned / "escape.png").symlink_to(outside)

    assert collect_supported_files([str(scanned)], {".png"}) == []
    # Explicit files remain authoritative for backwards compatibility.
    assert collect_supported_files([str(scanned / "escape.png")], {".png"}) == [str(outside)]


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow directory descriptors")
def test_publication_rejects_parent_symlink_swap_after_planning(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    planned = safe_output_path(approved, "nested/result.bin")
    (approved / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OutputBoundaryError):
        atomic_write_bytes(planned, b"escaped", overwrite=False)

    assert not (outside / "result.bin").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX system temporary alias semantics")
def test_prep_canonicalises_its_trusted_internal_temporary_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Internal `/var`-style aliases must not trip the user-path no-follow gate."""
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    real_temporary = tmp_path / "real-temporary"
    real_temporary.mkdir()
    temporary_alias = tmp_path / "temporary-alias"
    temporary_alias.symlink_to(real_temporary, target_is_directory=True)

    class TrustedTemporaryDirectory:
        def __init__(self, *, prefix: str) -> None:
            assert prefix == "pixshift-prep-"

        def __enter__(self) -> str:
            return str(temporary_alias)

        def __exit__(self, *args: object) -> None:
            return None

    def fake_convert(_source: str, output: str, _arguments: dict[str, object]):
        assert Path(output).parent == real_temporary.resolve()
        Path(output).write_bytes(b"converted")
        return SimpleNamespace(success=True, error="")

    monkeypatch.setattr(prep_ops.tempfile, "TemporaryDirectory", TrustedTemporaryDirectory)
    monkeypatch.setattr(prep_ops.convert_ops, "convert_one", fake_convert)

    result = prep_ops._prep_one(
        str(source),
        str(tmp_path / "output.png"),
        output_format="png",
        max_size=None,
        quality="balanced",
        overwrite=False,
        dry_run=False,
        strip_privacy=False,
        color_space="srgb",
    )

    assert result.success is True
    assert (tmp_path / "output.png").read_bytes() == b"converted"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_all_directory_collectors_skip_file_symlinks(tmp_path: Path) -> None:
    outside_image = tmp_path / "outside.png"
    outside_pdf = tmp_path / "outside.pdf"
    outside_video = tmp_path / "outside.mp4"
    for path in (outside_image, outside_pdf, outside_video):
        path.write_bytes(b"outside")
    scanned = tmp_path / "scanned"
    scanned.mkdir()
    (scanned / "escape.png").symlink_to(outside_image)
    (scanned / "escape.pdf").symlink_to(outside_pdf)
    (scanned / "escape.mp4").symlink_to(outside_video)

    assert _collect_images([str(scanned)]) == []
    assert _collect_pdfs([str(scanned)]) == []
    assert collect_video_files([str(scanned)]) == []
    assert _collect_all_files([str(scanned)], recursive=False) == []


def test_dedup_race_preserves_replacement_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanned = tmp_path / "scanned"
    scanned.mkdir()
    keep = scanned / "a.bin"
    duplicate = scanned / "b.bin"
    keep.write_bytes(b"duplicate")
    duplicate.write_bytes(b"duplicate")
    digest = dedup_engine._sha256_file(str(keep))
    candidate = dedup_engine.DeleteCandidate(
        keep=str(keep), duplicate=str(duplicate), sha256=digest, size=keep.stat().st_size
    )
    original_check = dedup_engine._candidate_is_still_safe

    def replace_after_check(item: dedup_engine.DeleteCandidate) -> tuple[int, int] | None:
        identity = original_check(item)
        parked = scanned / "verified.bin"
        duplicate.replace(parked)
        duplicate.write_bytes(b"unrelated replacement")
        return identity

    monkeypatch.setattr(dedup_engine, "_candidate_is_still_safe", replace_after_check)

    result = dedup_engine.delete_duplicates([candidate], dry_run=False)

    assert duplicate.read_bytes() == b"unrelated replacement"
    assert not result["deleted"]
    assert result["skipped"]


def test_backup_directory_creation_failure_is_a_result_not_an_exception(
    tmp_path: Path,
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_bytes(b"file")
    candidate = dedup_engine.DeleteCandidate(
        keep=str(tmp_path / "a"), duplicate=str(tmp_path / "b"), sha256="0" * 64, size=1
    )

    result = dedup_engine.delete_duplicates(
        [candidate], dry_run=False, backup_dir=str(blocked_parent / "backup")
    )

    assert result["errors"]
    assert not result["deleted"]


def test_dedup_backup_failure_restores_isolated_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep = tmp_path / "a.bin"
    duplicate = tmp_path / "b.bin"
    keep.write_bytes(b"duplicate")
    duplicate.write_bytes(b"duplicate")
    candidate = dedup_engine.DeleteCandidate(
        keep=str(keep),
        duplicate=str(duplicate),
        sha256=dedup_engine._sha256_file(str(keep)),
        size=keep.stat().st_size,
    )
    monkeypatch.setattr(
        dedup_engine,
        "_publish_backup_no_clobber",
        lambda source, backup: (_ for _ in ()).throw(OSError("backup failed")),
    )

    result = dedup_engine.delete_duplicates(
        [candidate], dry_run=False, backup_dir=str(tmp_path / "backup")
    )

    assert duplicate.read_bytes() == b"duplicate"
    assert "restored to original path" in result["errors"][0]
    assert not list(tmp_path.glob(".pixshift-delete-*"))


def test_dedup_restore_conflict_discloses_preserved_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep = tmp_path / "a.bin"
    duplicate = tmp_path / "b.bin"
    keep.write_bytes(b"duplicate")
    duplicate.write_bytes(b"duplicate")
    candidate = dedup_engine.DeleteCandidate(
        keep=str(keep),
        duplicate=str(duplicate),
        sha256=dedup_engine._sha256_file(str(keep)),
        size=keep.stat().st_size,
    )

    def fail_after_replacement(source: Path, backup: str) -> Path:
        duplicate.write_bytes(b"concurrent replacement")
        raise OSError("backup failed")

    monkeypatch.setattr(dedup_engine, "_publish_backup_no_clobber", fail_after_replacement)

    result = dedup_engine.delete_duplicates(
        [candidate], dry_run=False, backup_dir=str(tmp_path / "backup")
    )

    assert duplicate.read_bytes() == b"concurrent replacement"
    assert "preserved at " in result["errors"][0]
    preserved = Path(result["errors"][0].split("preserved at ", 1)[1])
    assert preserved.read_bytes() == b"duplicate"

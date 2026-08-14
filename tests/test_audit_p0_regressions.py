"""Regressions for the P0 defects found by the audit sweep.

Every test here reproduces a specific reported failure. Each one failed
before the corresponding fix, so a future refactor that reopens the hole
turns red instead of silently shipping.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from pixshift import dedup_engine
from pixshift.compress_engine import parse_target_size
from pixshift.core.errors import OutputCollisionError
from pixshift.core.files import validate_unique_output_paths


def _write_image(path: Path, colour: tuple[int, int, int] = (10, 120, 200)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), colour).save(path, "PNG")
    return path


class TestTargetSizeParsing:
    """``--target-size`` must reject junk instead of crashing the process."""

    @pytest.mark.parametrize(
        "text", ["inf", "-inf", "nan", "1e999", "0", "-5", "9e99GB", "", "huge"]
    )
    def test_non_finite_and_non_positive_inputs_raise_value_error(self, text: str) -> None:
        # OverflowError used to escape here and surface as a traceback.
        with pytest.raises(ValueError):
            parse_target_size(text)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [("500KB", 512_000), ("2.5MB", 2_621_440), ("1024", 1024), ("1B", 1)],
    )
    def test_valid_sizes_still_parse(self, text: str, expected: int) -> None:
        assert parse_target_size(text) == expected


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
class TestDedupSymlinkEscape:
    """A symlink must never let deletion reach outside the scanned tree."""

    def test_symlinked_duplicate_does_not_delete_the_outside_target(self, tmp_path: Path) -> None:
        outside = _write_image(tmp_path / "outside" / "precious.png")
        scanned = tmp_path / "scanned"
        _write_image(scanned / "a.png")
        # Same bytes as the outside file, reachable only through a link.
        (scanned / "link.png").symlink_to(outside)

        result = dedup_engine.find_duplicates([str(scanned)], recursive=True, hash_method="exact")
        listed = {c.duplicate for c in result.delete_candidates} | {
            c.keep for c in result.delete_candidates
        }
        assert str(outside) not in listed

        dedup_engine.delete_duplicates(result.delete_candidates, dry_run=False)
        assert outside.exists(), "deletion escaped the scanned directory"

    def test_symlink_is_not_reported_as_recoverable_space(self, tmp_path: Path) -> None:
        scanned = tmp_path / "scanned"
        original = _write_image(scanned / "a.png")
        (scanned / "link.png").symlink_to(original)

        result = dedup_engine.find_duplicates([str(scanned)], recursive=True, hash_method="exact")

        assert result.recoverable_size == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX hardlink semantics")
class TestDedupHardlinkAccounting:
    """Hardlinks share one inode, so unlinking a name frees nothing."""

    def test_hardlink_is_not_counted_as_recoverable(self, tmp_path: Path) -> None:
        scanned = tmp_path / "scanned"
        original = _write_image(scanned / "a.png")
        os.link(original, scanned / "b.png")

        result = dedup_engine.find_duplicates([str(scanned)], recursive=True, hash_method="exact")

        assert result.recoverable_size == 0, "hardlink promised space it cannot free"

    def test_a_real_copy_is_still_counted(self, tmp_path: Path) -> None:
        scanned = tmp_path / "scanned"
        original = _write_image(scanned / "a.png")
        (scanned / "b.png").write_bytes(original.read_bytes())

        result = dedup_engine.find_duplicates([str(scanned)], recursive=True, hash_method="exact")

        assert result.recoverable_size == original.stat().st_size


class TestStripRemovesEveryDeclaredTimeTag:
    """``--mode time`` must remove sub-second timestamps too.

    Asserted by numeric EXIF tag id rather than by name: the defect was that
    Pillow's spelling (``SubsecTimeOriginal``) differs from the specification's
    (``SubSecTimeOriginal``), so a name-based test could pass while the tag
    survived in the file.
    """

    SUBSEC_ORIGINAL = 37521
    DATETIME_ORIGINAL = 36867

    def _image_with_timestamps(self, path: Path) -> Path:
        from PIL import Image as PILImage

        path.parent.mkdir(parents=True, exist_ok=True)
        image = PILImage.new("RGB", (32, 32), (70, 110, 160))
        exif = image.getexif()
        ifd = exif.get_ifd(0x8769)
        ifd[self.DATETIME_ORIGINAL] = "2020:01:01 00:00:00"
        ifd[self.SUBSEC_ORIGINAL] = "123456"
        image.save(path, "JPEG", quality=90, exif=exif)
        return path

    def _exif_ids(self, path: Path) -> set[int]:
        from PIL import Image as PILImage

        with PILImage.open(path) as image:
            exif = image.getexif()
            ids = set(exif.keys())
            ids |= set(exif.get_ifd(0x8769).keys())
        return ids

    def test_sub_second_timestamp_does_not_survive_time_mode(self, tmp_path: Path) -> None:
        from pixshift import strip_engine

        source = self._image_with_timestamps(tmp_path / "shot.jpg")
        assert self.SUBSEC_ORIGINAL in self._exif_ids(source), "fixture lacks the tag"

        destination = tmp_path / "out" / "shot.jpg"
        destination.parent.mkdir(parents=True, exist_ok=True)
        strip_engine.strip_metadata(
            str(source),
            str(destination),
            strip_exif=False,
            strip_gps=False,
            strip_device=False,
            strip_personal=False,
            strip_time=True,
        )

        remaining = self._exif_ids(destination)
        assert self.SUBSEC_ORIGINAL not in remaining
        assert self.DATETIME_ORIGINAL not in remaining


class TestBatchOutputOverwritesInput:
    """One task's output must not silently destroy another task's source."""

    def test_output_landing_on_another_input_is_rejected(self, tmp_path: Path) -> None:
        first = _write_image(tmp_path / "a.png")
        second = _write_image(tmp_path / "b.png")

        with pytest.raises(OutputCollisionError):
            validate_unique_output_paths(
                [(str(first), str(second)), (str(second), str(tmp_path / "c.png"))]
            )

    def test_rewriting_a_file_in_place_is_still_allowed(self, tmp_path: Path) -> None:
        first = _write_image(tmp_path / "a.png")
        second = _write_image(tmp_path / "b.png")

        validate_unique_output_paths([(str(first), str(first)), (str(second), str(second))])

    def test_distinct_outputs_are_still_allowed(self, tmp_path: Path) -> None:
        first = _write_image(tmp_path / "a.png")
        second = _write_image(tmp_path / "b.png")

        validate_unique_output_paths(
            [(str(first), str(tmp_path / "out_a.png")), (str(second), str(tmp_path / "out_b.png"))]
        )


class TestDedupDeleteRevalidation:
    """Content that changes after planning must not be deleted."""

    def test_modified_duplicate_is_skipped_not_deleted(self, tmp_path: Path) -> None:
        scanned = tmp_path / "scanned"
        original = _write_image(scanned / "a.png")
        duplicate = scanned / "b.png"
        duplicate.write_bytes(original.read_bytes())

        result = dedup_engine.find_duplicates([str(scanned)], recursive=True, hash_method="exact")
        assert result.delete_candidates, "setup produced no duplicate to delete"
        # Simulate a concurrent edit between planning and applying.
        _write_image(duplicate, colour=(240, 30, 30))

        outcome = dedup_engine.delete_duplicates(result.delete_candidates, dry_run=False)

        assert duplicate.exists()
        assert outcome["skipped"], "changed file was deleted without warning"
        assert not outcome["deleted"]

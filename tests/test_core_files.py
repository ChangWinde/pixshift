"""Tests for shared file planning utilities."""

from pathlib import Path

from pixshift.core.files import (
    collect_supported_files,
    conversion_output_name,
    derivative_output_name,
    plan_output_path,
)


def test_collect_supported_files_respects_recursive_and_filter(tmp_path):
    src = tmp_path / "src"
    nested = src / "nested"
    src.mkdir()
    nested.mkdir()

    (src / "a.jpg").write_bytes(b"a")
    (src / "b.png").write_bytes(b"b")
    (nested / "c.jpg").write_bytes(b"c")

    non_recursive = collect_supported_files(
        input_paths=[str(src)],
        supported_exts={".jpg", ".png"},
        recursive=False,
    )
    assert len(non_recursive) == 2

    recursive = collect_supported_files(
        input_paths=[str(src)],
        supported_exts={".jpg", ".png"},
        recursive=True,
    )
    assert len(recursive) == 3

    only_jpg = collect_supported_files(
        input_paths=[str(src)],
        supported_exts={".jpg", ".png"},
        input_format="jpg",
        recursive=True,
    )
    assert len(only_jpg) == 2
    assert all(Path(p).suffix.lower() == ".jpg" for p in only_jpg)


def test_plan_output_path_preserves_relative_structure_when_not_flatten(tmp_path):
    src = tmp_path / "source"
    nested = src / "a" / "b"
    nested.mkdir(parents=True)
    file_path = nested / "photo.jpg"
    file_path.write_bytes(b"image")

    out_dir = tmp_path / "out"
    output_name = conversion_output_name(str(file_path), "webp")

    target = plan_output_path(
        input_path=str(file_path),
        output_name=output_name,
        output_dir=str(out_dir),
        flatten=False,
        source_paths=[str(src)],
    )

    assert Path(target) == out_dir / "a" / "b" / "photo.webp"


def test_plan_output_path_flatten_writes_into_output_root(tmp_path):
    src = tmp_path / "source"
    nested = src / "nested"
    nested.mkdir(parents=True)
    file_path = nested / "photo.jpg"
    file_path.write_bytes(b"image")

    out_dir = tmp_path / "out"
    output_name = derivative_output_name(str(file_path), "_clean")
    target = plan_output_path(
        input_path=str(file_path),
        output_name=output_name,
        output_dir=str(out_dir),
        flatten=True,
        source_paths=[str(src)],
    )

    assert Path(target) == out_dir / "photo_clean.jpg"


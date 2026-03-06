"""Tests for operation-layer wrapper modules."""

from pixshift.ops import compress as compress_ops
from pixshift.ops import convert as convert_ops
from pixshift.ops import dedup as dedup_ops
from pixshift.ops import pdf as pdf_ops
from pixshift.ops import strip as strip_ops


def test_convert_build_tasks_uses_expected_output_format(tmp_path):
    src = tmp_path / "a.png"
    src.write_bytes(b"x")
    tasks = convert_ops.build_convert_tasks(
        files=[str(src)],
        output_format="jpg",
        output_dir=str(tmp_path / "out"),
        prefix="p_",
        suffix="_s",
        flatten=True,
        source_paths=[str(tmp_path)],
    )
    assert len(tasks) == 1
    assert tasks[0][0] == str(src)
    assert tasks[0][1].endswith("p_a_s.jpg")


def test_compress_collect_files_delegates(monkeypatch):
    monkeypatch.setattr(
        "pixshift.ops.compress.collect_compressible_files",
        lambda paths, fmt, recursive: ["ok.jpg"],
    )
    assert compress_ops.collect_files(["/tmp"], "jpg", True) == ["ok.jpg"]


def test_strip_analyze_and_strip_delegate(monkeypatch):
    monkeypatch.setattr("pixshift.ops.strip.analyze_metadata", lambda _: {"has_exif": True})
    assert strip_ops.analyze_one("x")["has_exif"] is True

    class Result:
        success = True
        input_size = 1
        output_size = 1
        fields_removed = 1
        error = ""

    monkeypatch.setattr("pixshift.ops.strip.strip_metadata", lambda **_: Result())
    result = strip_ops.strip_one("in", "out", True, True, False, True, True, False, True, True)
    assert result.success is True


def test_dedup_wrappers_delegate(monkeypatch):
    monkeypatch.setattr("pixshift.ops.dedup.find_duplicates", lambda **_: "analysis")
    monkeypatch.setattr("pixshift.ops.dedup.delete_duplicates", lambda groups, dry_run: {"deleted": groups})
    assert dedup_ops.analyze(["a"], False, "phash", 5) == "analysis"
    assert dedup_ops.delete(["g"]) == {"deleted": ["g"]}


def test_pdf_wrappers_delegate(monkeypatch):
    monkeypatch.setattr("pixshift.ops.pdf._collect_images", lambda inputs, recursive: ["i1"])
    monkeypatch.setattr("pixshift.ops.pdf._collect_pdfs", lambda inputs, recursive: ["p1"])
    monkeypatch.setattr("pixshift.ops.pdf.pdf_get_info", lambda p: {"path": p})

    assert isinstance(pdf_ops.is_available(), bool)
    assert pdf_ops.collect_images(["/tmp"], False) == ["i1"]
    assert pdf_ops.collect_pdfs(["/tmp"], True) == ["p1"]
    assert pdf_ops.info("doc.pdf") == {"path": "doc.pdf"}


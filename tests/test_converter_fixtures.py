"""Targeted fixture tests for convert engine behavior."""

from pathlib import Path

from PIL import Image

from pixshift.converter import PixShiftConverter


def test_process_image_strips_alpha_with_background_color():
    converter = PixShiftConverter(strip_alpha=True, background_color=(7, 8, 9))
    source = Image.new("RGBA", (2, 2), (255, 0, 0, 0))

    result = converter._process_image(source, "jpg")
    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (7, 8, 9)


def test_process_image_auto_orient_hook_is_used(monkeypatch):
    converter = PixShiftConverter(auto_orient=True)
    source = Image.new("RGB", (10, 20), (120, 120, 120))
    called = {"ok": False}

    def fake_orient(img):
        called["ok"] = True
        return img.transpose(Image.ROTATE_90)

    monkeypatch.setattr(converter, "_auto_orient", fake_orient)
    result = converter._process_image(source, "png")
    assert called["ok"] is True
    assert result.size == (20, 10)


def test_convert_single_includes_exif_and_icc_when_enabled(tmp_path, monkeypatch):
    source_path = tmp_path / "input.png"
    output_path = tmp_path / "out.jpg"
    source_path.write_bytes(b"input")

    src_image = Image.new("RGB", (4, 4), (1, 2, 3))
    src_image.info["exif"] = b"fake-exif"
    src_image.info["icc_profile"] = b"fake-icc"
    captured = {}

    monkeypatch.setattr("pixshift.converter.Image.open", lambda _path: src_image)

    def fake_save(self, fp, **kwargs):
        captured.update(kwargs)
        Path(fp).write_bytes(b"ok")

    monkeypatch.setattr("pixshift.converter.Image.Image.save", fake_save, raising=False)

    converter = PixShiftConverter(overwrite=True, keep_exif=True, keep_icc=True)
    result = converter.convert_single(str(source_path), str(output_path))

    assert result.success is True
    assert captured["exif"] == b"fake-exif"
    assert captured["icc_profile"] == b"fake-icc"


def test_convert_single_excludes_exif_and_icc_when_disabled(tmp_path, monkeypatch):
    source_path = tmp_path / "input.png"
    output_path = tmp_path / "out.jpg"
    source_path.write_bytes(b"input")

    src_image = Image.new("RGB", (4, 4), (1, 2, 3))
    src_image.info["exif"] = b"fake-exif"
    src_image.info["icc_profile"] = b"fake-icc"
    captured = {}

    monkeypatch.setattr("pixshift.converter.Image.open", lambda _path: src_image)

    def fake_save(self, fp, **kwargs):
        captured.update(kwargs)
        Path(fp).write_bytes(b"ok")

    monkeypatch.setattr("pixshift.converter.Image.Image.save", fake_save, raising=False)

    converter = PixShiftConverter(overwrite=True, keep_exif=False, keep_icc=False)
    result = converter.convert_single(str(source_path), str(output_path))

    assert result.success is True
    assert "exif" not in captured
    assert "icc_profile" not in captured


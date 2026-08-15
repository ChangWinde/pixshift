"""End-to-end contract tests for the cross-media quality gate."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from PIL import Image, ImageCms

from pixshift.cli import cli
from pixshift.compare_engine import compare_images
from pixshift.converter import PixShiftConverter
from pixshift.video_engine import VideoInfo


def _payload(result):
    return json.loads(result.output)


def test_verify_identical_image_passes(tmp_path):
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGBA", (32, 24), (10, 80, 200, 120)).save(source)
    candidate.write_bytes(source.read_bytes())

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload["passed"] is True
    assert payload["media_type"] == "image"
    assert payload["metrics"]["ssim"] == 1.0
    assert payload["checks"]["frame_count"] is True


def test_verify_visibly_different_image_fails_gate(tmp_path):
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (32, 24), "black").save(source)
    Image.new("RGB", (32, 24), "white").save(candidate)

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["error"] == "quality_gate_failed"
    assert payload["passed"] is False


@pytest.mark.parametrize(
    ("source_pixel", "candidate_pixel"),
    [
        ((200, 10, 10, 0), (200, 10, 10, 255)),
        ((255, 0, 0, 255), (0, 130, 0, 255)),
    ],
)
def test_verify_default_gate_includes_alpha_and_colour(tmp_path, source_pixel, candidate_pixel):
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGBA", (32, 24), source_pixel).save(source)
    Image.new("RGBA", (32, 24), candidate_pixel).save(candidate)

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["error"] == "quality_gate_failed"
    assert payload["metrics"]["ssim"] < 0.99


def test_verify_block_ssim_rejects_material_alpha_loss(tmp_path):
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGBA", (128, 128), (0, 0, 0, 255)).save(source)
    Image.new("RGBA", (128, 128), (0, 0, 0, 200)).save(candidate)

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 1
    assert _payload(result)["metrics"]["ssim"] < 0.99


def test_verify_accepts_near_identical_colour_without_zero_channel_artifact(tmp_path):
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGBA", (128, 128), (255, 0, 0, 255)).save(source)
    Image.new("RGBA", (128, 128), (255, 1, 0, 255)).save(candidate)

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 0, result.output


def test_verify_compares_valid_profiles_in_a_common_srgb_space(tmp_path):
    source = tmp_path / "source.tiff"
    candidate = tmp_path / "candidate.png"
    lab_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB"))
    srgb_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    lab = Image.new("LAB", (32, 24), (128, 140, 120))
    lab.save(source, "TIFF", icc_profile=lab_profile.tobytes())
    converted = ImageCms.profileToProfile(lab, lab_profile, srgb_profile, outputMode="RGB")
    assert converted is not None
    converted.save(candidate, "PNG", icc_profile=srgb_profile.tobytes())

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 0, result.output

    compared = compare_images(str(source), str(candidate))
    assert compared.success, compared.error
    assert compared.ssim >= 0.99


def test_verify_reports_invalid_embedded_profile(tmp_path):
    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (16, 16), "red").save(source, icc_profile=b"invalid")
    Image.new("RGB", (16, 16), "red").save(candidate)

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 1
    assert _payload(result)["error"] == "invalid_icc_profile"


def test_compare_downsamples_each_input_before_retaining_the_second(tmp_path, monkeypatch):
    import pixshift.compare_engine as compare_engine

    source = tmp_path / "source.png"
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (40, 40), "red").save(source)
    candidate.write_bytes(source.read_bytes())
    monkeypatch.setattr(compare_engine, "MAX_COMPARISON_PIXELS", 100)

    result = compare_engine.compare_images(str(source), str(candidate))

    assert result.success, result.error
    assert result.size_a == (40, 40)
    assert result.size_b == (40, 40)
    assert result.comparison_size[0] * result.comparison_size[1] <= 100
    assert result.sampled_for_comparison is True


def test_verify_rejects_aggregate_animation_budget_before_copying(tmp_path, monkeypatch):
    import pixshift.verify_engine as verify_engine

    source = tmp_path / "source.gif"
    candidate = tmp_path / "candidate.gif"
    frames = [Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")]
    frames[0].save(source, save_all=True, append_images=frames[1:], duration=50)
    candidate.write_bytes(source.read_bytes())
    monkeypatch.setenv("PIXSHIFT_MAX_PIXELS", "100")
    monkeypatch.setattr(
        verify_engine,
        "extract_animation",
        lambda _image: (_ for _ in ()).throw(AssertionError("decoded before budget check")),
    )

    result = verify_engine.verify_media(str(source), str(candidate))

    assert result.success is False
    assert result.error == "verification_failed"
    assert "image_too_large" in result.detail


def test_verify_rejects_mixed_media_before_work(tmp_path):
    image = tmp_path / "image.png"
    pdf = tmp_path / "document.pdf"
    Image.new("RGB", (4, 4), "red").save(image)
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    result = CliRunner().invoke(cli, ["verify", str(image), str(pdf), "--json"])

    assert result.exit_code == 2
    assert _payload(result)["error"] == "unsupported_media_pair"


def test_verify_identical_pdf_passes(tmp_path):
    fitz = pytest.importorskip("fitz")
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((20, 40), "PixShift verification")
    document.save(source)
    document.close()
    candidate.write_bytes(source.read_bytes())

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload["media_type"] == "pdf"
    assert payload["checks"]["page_count"] is True
    assert payload["metrics"]["ssim"] == 1.0


def test_verify_pdf_rejects_loss_of_links_and_text_semantics(tmp_path):
    fitz = pytest.importorskip("fitz")
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    with fitz.open() as document:
        page = document.new_page(width=200, height=120)
        page.insert_text((20, 40), "semantic text")
        page.insert_link(
            {
                "kind": fitz.LINK_URI,
                "from": fitz.Rect(20, 50, 120, 70),
                "uri": "https://example.com/",
            }
        )
        document.save(source)
    with fitz.open() as document:
        page = document.new_page(width=200, height=120)
        # Preserve the visual pixels while deliberately dropping the text
        # layer and URI annotation.
        with fitz.open(source) as original:
            pixmap = original[0].get_pixmap(alpha=False)
        page.insert_image(page.rect, pixmap=pixmap)
        document.save(candidate)

    result = CliRunner().invoke(cli, ["verify", str(source), str(candidate), "--json"])

    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["checks"]["links"] is False
    assert payload["checks"]["text_layer"] is False


def test_verify_pdf_allow_resize_requires_matching_aspect_ratio(tmp_path):
    fitz = pytest.importorskip("fitz")
    source = tmp_path / "source.pdf"
    candidate = tmp_path / "candidate.pdf"
    for path, size in ((source, (200, 100)), (candidate, (100, 100))):
        document = fitz.open()
        page = document.new_page(width=size[0], height=size[1])
        page.insert_text((20, 40), "aspect ratio")
        document.save(path)
        document.close()

    result = CliRunner().invoke(
        cli,
        ["verify", str(source), str(candidate), "--allow-resize", "--json"],
    )

    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["error"] == "quality_gate_failed"
    assert payload["checks"]["page_geometry"] is False


def test_verify_video_computes_requested_psnr(tmp_path, monkeypatch):
    import pixshift.verify_engine as verify_engine

    source = tmp_path / "source.mp4"
    candidate = tmp_path / "candidate.mp4"
    source.write_bytes(b"source")
    candidate.write_bytes(b"candidate")
    monkeypatch.setattr(verify_engine, "FFMPEG_AVAILABLE", True)
    monkeypatch.setattr(
        verify_engine,
        "probe",
        lambda path: VideoInfo(
            path=path,
            duration_sec=1.0,
            width=320,
            height=180,
            video_codec="h264",
        ),
    )
    calls = []

    def fake_run_ffmpeg(args):
        calls.append(args)
        if "ssim" in args[args.index("-lavfi") + 1]:
            return 0, "SSIM Y:1.0 All:0.999900"
        return 0, "PSNR y:50.0 average:49.750000 min:48.0 max:51.0"

    monkeypatch.setattr(verify_engine, "run_ffmpeg", fake_run_ffmpeg)

    result = verify_engine.verify_media(str(source), str(candidate), min_ssim=0.99, min_psnr=49.0)

    assert result.passed is True
    assert result.psnr == 49.75
    assert len(calls) == 2


def test_verify_video_rejects_silent_or_replaced_audio(tmp_path, monkeypatch):
    import pixshift.verify_engine as verify_engine

    source = tmp_path / "source.mp4"
    candidate = tmp_path / "candidate.mp4"
    source.write_bytes(b"source")
    candidate.write_bytes(b"candidate")
    monkeypatch.setattr(verify_engine, "FFMPEG_AVAILABLE", True)
    monkeypatch.setattr(
        verify_engine,
        "probe",
        lambda path: VideoInfo(
            path=path,
            duration_sec=1.0,
            width=320,
            height=180,
            video_codec="h264",
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
        ),
    )

    difference_graphs = []

    def fake_run_ffmpeg(args):
        graph = args[args.index("-filter_complex") + 1] if "-filter_complex" in args else ""
        if "astats" in graph:
            if "amix=" in graph:
                difference_graphs.append(graph)
            # Replaced/silent candidate: the difference is as loud as source,
            # yielding 0 dB SNR rather than the required 20 dB.
            return 0, "RMS level dB: -20.0"
        return 0, "SSIM Y:1.0 All:1.000000"

    monkeypatch.setattr(verify_engine, "run_ffmpeg", fake_run_ffmpeg)

    result = verify_engine.verify_media(str(source), str(candidate))

    assert result.success is True
    assert result.passed is False
    assert result.checks["audio_content"] is False
    assert result.observations["audio_snr_db"] == 0.0
    assert len(difference_graphs) == 1
    assert "normalize=0" in difference_graphs[0]


def test_verify_normalizes_single_play_gif_and_webp_loop_semantics(tmp_path):
    source = tmp_path / "once.gif"
    candidate = tmp_path / "once.webp"
    frames = [Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")]
    frames[0].save(
        source,
        "GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[60, 80],
    )
    converted = PixShiftConverter(overwrite=True).convert_single(str(source), str(candidate))
    assert converted.success, converted.error

    result = CliRunner().invoke(
        cli, ["verify", str(source), str(candidate), "--min-ssim", "0.95", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload["checks"]["loop"] is True
    assert payload["checks"]["frame_count"] is True


def test_verify_excludes_apng_default_poster_from_playback_frames(tmp_path):
    source = tmp_path / "poster.apng"
    candidate = tmp_path / "animation.webp"
    poster = Image.new("RGBA", (8, 8), "red")
    green = Image.new("RGBA", (8, 8), "green")
    blue = Image.new("RGBA", (8, 8), "blue")
    poster.save(
        source,
        "PNG",
        save_all=True,
        append_images=[green, blue],
        default_image=True,
        duration=[110, 220],
        loop=0,
    )
    converted = PixShiftConverter(overwrite=True).convert_single(str(source), str(candidate))
    assert converted.success, converted.error

    result = CliRunner().invoke(
        cli, ["verify", str(source), str(candidate), "--min-ssim", "0.95", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload["observations"]["source_frames"] == 2
    assert payload["observations"]["candidate_frames"] == 2

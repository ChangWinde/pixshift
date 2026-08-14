"""Cross-media postcondition verification for agent and CI workflows."""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .compare_engine import compare_image_objects
from .converter import SUPPORTED_INPUT_FORMATS
from .core.metadata import (
    convert_color_to_srgb,
    ensure_pixel_count_within_limit,
    extract_animation,
    image_frame_count,
    normalize_orientation,
    normalized_animation_loop,
    open_image,
)
from .video_engine import (
    FFMPEG_AVAILABLE,
    VIDEO_INPUT_FORMATS,
    FFmpegNotAvailableError,
    probe,
    run_ffmpeg,
)

MIN_AUDIO_SNR_DB = 20.0


@dataclass
class VerifyResult:
    """One media-pair verification result."""

    source: str
    candidate: str
    media_type: str = ""
    success: bool = False
    passed: bool = False
    rejected: bool = False
    error: str = ""
    detail: str = ""
    source_bytes: int = 0
    candidate_bytes: int = 0
    min_ssim: float = 0.99
    min_psnr: float | None = None
    ssim: float | None = None
    psnr: float | None = None
    sampled: bool = False
    checks: dict[str, bool] = field(default_factory=dict)
    observations: dict[str, Any] = field(default_factory=dict)


def verify_media(
    source: str,
    candidate: str,
    *,
    min_ssim: float = 0.99,
    min_psnr: float | None = None,
    max_bytes: int | None = None,
    allow_resize: bool = False,
) -> VerifyResult:
    """Verify structural and perceptual postconditions for one media pair."""
    result = VerifyResult(
        source=source,
        candidate=candidate,
        min_ssim=min_ssim,
        min_psnr=min_psnr,
    )
    if not 0 <= min_ssim <= 1 or (
        min_psnr is not None and (not math.isfinite(min_psnr) or min_psnr < 0)
    ):
        result.rejected = True
        result.error = "invalid_quality_threshold"
        return result
    if max_bytes is not None and max_bytes <= 0:
        result.rejected = True
        result.error = "invalid_max_size"
        return result
    if not Path(source).is_file() or not Path(candidate).is_file():
        result.rejected = True
        result.error = "input_not_found"
        return result

    result.source_bytes = os.path.getsize(source)
    result.candidate_bytes = os.path.getsize(candidate)
    source_type = _media_type(source)
    candidate_type = _media_type(candidate)
    if not source_type or source_type != candidate_type:
        result.rejected = True
        result.error = "unsupported_media_pair"
        result.detail = f"{source_type or '?'}:{candidate_type or '?'}"
        return result
    result.media_type = source_type
    if max_bytes is not None:
        result.checks["max_size"] = result.candidate_bytes <= max_bytes

    try:
        if source_type == "image":
            _verify_images(result, allow_resize=allow_resize)
        elif source_type == "pdf":
            _verify_pdfs(result, allow_resize=allow_resize)
        else:
            _verify_videos(result, allow_resize=allow_resize)
    except FFmpegNotAvailableError:
        result.error = "ffmpeg_missing"
        return result
    except ValueError as error:
        result.error = (
            "invalid_icc_profile" if str(error) == "invalid_icc_profile" else "verification_failed"
        )
        result.detail = str(error)
        return result
    except Exception as error:
        result.error = "verification_failed"
        result.detail = str(error)
        return result

    structural = all(result.checks.values())
    quality = result.ssim is not None and result.ssim >= result.min_ssim
    if result.min_psnr is not None:
        quality = quality and result.psnr is not None and result.psnr >= result.min_psnr
    result.success = True
    result.passed = bool(structural and quality)
    if not result.passed:
        result.error = "quality_gate_failed"
    return result


def _media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in VIDEO_INPUT_FORMATS:
        return "video"
    if suffix in SUPPORTED_INPUT_FORMATS:
        return "image"
    return ""


def _verify_images(result: VerifyResult, *, allow_resize: bool) -> None:
    with open_image(result.source) as source, open_image(result.candidate) as candidate:
        source_raw_frames = image_frame_count(source)
        candidate_raw_frames = image_frame_count(candidate)
        # Reject the declared aggregate before iterating frames. Seeking an
        # animation can decode it, so a post-copy check is too late to serve as
        # a memory-safety boundary. Counting a possible APNG poster is a safe,
        # deliberately conservative overestimate.
        ensure_pixel_count_within_limit(
            source.width * source.height * source_raw_frames
            + candidate.width * candidate.height * candidate_raw_frames
        )
        if source_raw_frames > 1:
            source_images, durations_a, source_loop, _ = extract_animation(source)
        else:
            source_images = [normalize_orientation(source.copy())]
            durations_a = []
            source_loop = None
        if candidate_raw_frames > 1:
            candidate_images, durations_b, candidate_loop, _ = extract_animation(candidate)
        else:
            candidate_images = [normalize_orientation(candidate.copy())]
            durations_b = []
            candidate_loop = None

        source_frames = len(source_images)
        candidate_frames = len(candidate_images)
        result.checks["frame_count"] = source_frames == candidate_frames
        result.observations["source_frames"] = source_frames
        result.observations["candidate_frames"] = candidate_frames
        if source_raw_frames > 1 or candidate_raw_frames > 1:
            result.checks["loop"] = normalized_animation_loop(
                source_loop
            ) == normalized_animation_loop(candidate_loop)
        if source_frames != candidate_frames:
            return

        ensure_pixel_count_within_limit(
            sum(image.width * image.height for image in source_images + candidate_images)
        )
        result.checks["timing"] = durations_a == durations_b

        scores: list[tuple[float, float]] = []
        sampled = False
        dimensions_match = True
        resize_compatible = True
        for first, second in zip(source_images, candidate_images, strict=True):
            first = convert_color_to_srgb(first)
            second = convert_color_to_srgb(second)
            if first.size != second.size:
                dimensions_match = False
                if not allow_resize:
                    continue
                ratio_a = first.width / first.height
                ratio_b = second.width / second.height
                if abs(ratio_a - ratio_b) / max(ratio_a, ratio_b) > 0.01:
                    resize_compatible = False
                    continue
                target = (min(first.width, second.width), min(first.height, second.height))
                first = first.resize(target, Image.Resampling.LANCZOS)
                second = second.resize(target, Image.Resampling.LANCZOS)
            _, psnr, ssim, was_sampled, _ = compare_image_objects(first, second)
            scores.append((ssim, psnr))
            sampled = sampled or was_sampled
        result.checks["dimensions"] = dimensions_match or (allow_resize and resize_compatible)
        if scores:
            result.ssim = min(score[0] for score in scores)
            result.psnr = min(score[1] for score in scores)
            result.sampled = sampled


def _verify_pdfs(result: VerifyResult, *, allow_resize: bool) -> None:
    import fitz

    with fitz.open(result.source) as source, fitz.open(result.candidate) as candidate:
        if source.needs_pass or candidate.needs_pass:
            raise ValueError("pdf_password_required")
        result.checks["page_count"] = source.page_count == candidate.page_count
        result.observations["source_pages"] = source.page_count
        result.observations["candidate_pages"] = candidate.page_count
        if source.page_count != candidate.page_count:
            return
        source_semantics = _pdf_semantic_snapshot(source)
        candidate_semantics = _pdf_semantic_snapshot(candidate)
        for key in (
            "text_layer",
            "links",
            "annotations",
            "forms",
            "outline",
            "attachments",
            "metadata",
            "page_labels",
        ):
            result.checks[key] = source_semantics[key] == candidate_semantics[key]
        for key in ("links", "annotations", "forms", "attachments"):
            result.observations[f"source_{key}"] = len(source_semantics[key])
            result.observations[f"candidate_{key}"] = len(candidate_semantics[key])
        scores: list[tuple[float, float]] = []
        sampled = False
        page_geometry = True
        resize_compatible = True
        matrix = fitz.Matrix(96 / 72, 96 / 72)
        for index in range(source.page_count):
            first_page = source[index]
            second_page = candidate[index]
            first_pix = first_page.get_pixmap(matrix=matrix, alpha=True)
            second_pix = second_page.get_pixmap(matrix=matrix, alpha=True)
            first = Image.frombytes("RGBA", (first_pix.width, first_pix.height), first_pix.samples)
            second = Image.frombytes(
                "RGBA", (second_pix.width, second_pix.height), second_pix.samples
            )
            ensure_pixel_count_within_limit(
                first.width * first.height + second.width * second.height
            )
            if first.size != second.size:
                page_geometry = False
                if not allow_resize:
                    continue
                ratio_a = first.width / first.height
                ratio_b = second.width / second.height
                if abs(ratio_a - ratio_b) / max(ratio_a, ratio_b) > 0.01:
                    resize_compatible = False
                    continue
                second = second.resize(first.size, Image.Resampling.LANCZOS)
            _, psnr, ssim, was_sampled, _ = compare_image_objects(first, second)
            scores.append((ssim, psnr))
            sampled = sampled or was_sampled
        result.checks["page_geometry"] = page_geometry or (allow_resize and resize_compatible)
        if scores:
            result.ssim = min(score[0] for score in scores)
            result.psnr = min(score[1] for score in scores)
            result.sampled = sampled


def _pdf_semantic_snapshot(document: Any) -> dict[str, Any]:
    """Capture stable user-visible PDF semantics that raster comparison misses."""

    def coordinates(value: Any) -> tuple[float, ...]:
        try:
            return tuple(round(float(component), 4) for component in value)
        except TypeError:
            return ()

    text_layers: list[str] = []
    links: list[tuple[Any, ...]] = []
    annotations: list[tuple[Any, ...]] = []
    forms: list[tuple[Any, ...]] = []
    for page_index in range(document.page_count):
        page = document[page_index]
        text_layers.append(page.get_text("text"))
        for link in page.get_links():
            links.append(
                (
                    page_index,
                    int(link.get("kind", 0) or 0),
                    coordinates(link.get("from")),
                    str(link.get("uri", "")),
                    str(link.get("file", "")),
                    int(link.get("page", -1) or -1),
                    coordinates(link.get("to")),
                )
            )
        for annotation in page.annots() or ():
            annotations.append(
                (
                    page_index,
                    tuple(annotation.type),
                    coordinates(annotation.rect),
                    tuple(sorted((annotation.info or {}).items())),
                    int(annotation.flags),
                )
            )
        for widget in page.widgets() or ():
            forms.append(
                (
                    page_index,
                    str(widget.field_name or ""),
                    int(widget.field_type or 0),
                    str(widget.field_value or ""),
                    coordinates(widget.rect),
                )
            )

    attachments: list[tuple[str, str]] = []
    for index in range(document.embfile_count()):
        name = document.embfile_info(index).get("name", "")
        payload = document.embfile_get(index)
        attachments.append((str(name), hashlib.sha256(payload).hexdigest()))
    metadata = document.metadata or {}
    semantic_metadata = tuple(
        (key, str(metadata.get(key, "")))
        for key in (
            "title",
            "author",
            "subject",
            "keywords",
            "creator",
            "creationDate",
        )
    )
    return {
        "text_layer": tuple(text_layers),
        "links": tuple(links),
        "annotations": tuple(annotations),
        "forms": tuple(forms),
        "outline": tuple(tuple(row) for row in document.get_toc(simple=True)),
        "attachments": tuple(attachments),
        "metadata": semantic_metadata,
        "page_labels": tuple(tuple(sorted(label.items())) for label in document.get_page_labels()),
    }


def _verify_videos(result: VerifyResult, *, allow_resize: bool) -> None:
    if not FFMPEG_AVAILABLE:
        raise FFmpegNotAvailableError()
    source = probe(result.source)
    candidate = probe(result.candidate)
    if source.error or candidate.error:
        raise ValueError(source.error or candidate.error)
    duration_delta = abs(source.duration_sec - candidate.duration_sec)
    duration_tolerance = max(0.25, source.duration_sec * 0.005)
    result.checks["duration"] = duration_delta <= duration_tolerance
    result.observations["duration_delta_sec"] = round(duration_delta, 6)
    dimensions_match = (source.width, source.height) == (candidate.width, candidate.height)
    resize_compatible = False
    if min(source.width, source.height, candidate.width, candidate.height) > 0:
        source_ratio = source.width / source.height
        candidate_ratio = candidate.width / candidate.height
        resize_compatible = (
            abs(source_ratio - candidate_ratio) / max(source_ratio, candidate_ratio) <= 0.01
        )
    result.checks["dimensions"] = dimensions_match or (allow_resize and resize_compatible)
    result.checks["audio_presence"] = bool(source.audio_codec) == bool(candidate.audio_codec)
    if source.audio_codec and candidate.audio_codec:
        result.checks["audio_channels"] = source.audio_channels == candidate.audio_channels
        result.checks["audio_sample_rate"] = source.audio_sample_rate == candidate.audio_sample_rate
    if not result.checks["dimensions"]:
        return

    scale = (
        f"scale={source.width}:{source.height}" if allow_resize and resize_compatible else "null"
    )
    tail = _run_video_metric(result, scale=scale, metric="ssim")
    match = re.search(r"All:([0-9]+(?:\.[0-9]+)?)", tail)
    if match is None:
        raise ValueError("video_metric_unavailable")
    result.ssim = float(match.group(1))
    if result.min_psnr is not None:
        tail = _run_video_metric(result, scale=scale, metric="psnr")
        match = re.search(r"average:([0-9]+(?:\.[0-9]+)?|inf)", tail)
        if match is None:
            raise ValueError("video_metric_unavailable")
        result.psnr = float(match.group(1))
    if source.audio_codec and candidate.audio_codec:
        source_rms = _run_audio_rms(result, difference=False)
        difference_rms = _run_audio_rms(result, difference=True)
        if source_rms == float("-inf"):
            audio_snr = float("inf") if difference_rms == float("-inf") else float("-inf")
        elif difference_rms == float("-inf"):
            audio_snr = float("inf")
        else:
            audio_snr = source_rms - difference_rms
        result.observations["audio_snr_db"] = None if math.isinf(audio_snr) else round(audio_snr, 4)
        result.checks["audio_content"] = audio_snr >= MIN_AUDIO_SNR_DB


def _run_video_metric(result: VerifyResult, *, scale: str, metric: str) -> str:
    """Run one ffmpeg video metric and return its bounded diagnostic tail."""
    filter_graph = f"[1:v]{scale}[candidate];[0:v][candidate]{metric}"
    returncode, tail = run_ffmpeg(
        [
            "-loglevel",
            "info",
            "-i",
            str(Path(result.source).resolve()),
            "-i",
            str(Path(result.candidate).resolve()),
            "-lavfi",
            filter_graph,
            "-f",
            "null",
            "-",
        ]
    )
    if returncode != 0:
        raise ValueError(tail or "video_metric_failed")
    return tail


def _run_audio_rms(result: VerifyResult, *, difference: bool) -> float:
    """Measure source or source-minus-candidate RMS through a streaming filter."""
    source_filter = (
        "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:"
        "channel_layouts=stereo,asetpts=PTS-STARTPTS[source]"
    )
    if difference:
        candidate_filter = (
            "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:"
            "channel_layouts=stereo,asetpts=PTS-STARTPTS,volume=-1[candidate]"
        )
        # ``amix`` normalizes by the number of inputs unless explicitly told
        # not to.  That default would halve the residual and overstate SNR by
        # roughly 6 dB, allowing materially attenuated audio through the gate.
        measured = (
            "[source][candidate]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0"
        )
        filter_graph = f"{source_filter};{candidate_filter};{measured},"
    else:
        filter_graph = f"{source_filter};[source]"
    filter_graph += "astats=metadata=0:reset=0:measure_perchannel=none:measure_overall=RMS_level"
    args = [
        "-loglevel",
        "info",
        "-i",
        str(Path(result.source).resolve()),
    ]
    if difference:
        args += ["-i", str(Path(result.candidate).resolve())]
    args += ["-filter_complex", filter_graph, "-f", "null", "-"]
    returncode, tail = run_ffmpeg(args)
    if returncode != 0:
        raise ValueError(tail or "audio_metric_failed")
    matches = re.findall(r"RMS level dB:\s*(-?inf|-?[0-9]+(?:\.[0-9]+)?)", tail)
    if not matches:
        raise ValueError("audio_metric_unavailable")
    return float(matches[-1])

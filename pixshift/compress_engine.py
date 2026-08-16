"""
PixShift Compress Engine — 智能图片压缩（不改格式，只优化体积）

功能:
  - 同格式压缩优化（优化 PNG 和 JPEG 编码，不改变输出格式）
  - 目标文件大小限制（二分法自动调质量）
  - 批量 + 并行处理
"""

import io
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .core.defaults import DEFAULT_COMPRESS_PRESET
from .core.files import (
    SelectionFilters,
    atomic_copy_file,
    atomic_write_bytes,
    collect_supported_files,
)
from .core.metadata import (
    convert_color_to_rgb,
    ensure_static_image,
    flatten_transparency,
    image_has_transparency,
    normalize_orientation,
    normalized_exif_bytes,
    open_image,
)

# ============================================================
#  数据结构
# ============================================================


@dataclass
class CompressResult:
    """单个文件的压缩结果"""

    input_path: str = ""
    output_path: str = ""
    success: bool = False
    input_size: int = 0
    output_size: int = 0
    duration: float = 0.0
    error: str = ""
    quality_used: int = 0
    iterations: int = 0  # 二分法迭代次数


@dataclass
class CompressBatchResult:
    """批量压缩汇总"""

    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    total_input_size: int = 0
    total_output_size: int = 0
    total_duration: float = 0.0
    results: list[CompressResult] = field(default_factory=list)


# ============================================================
#  压缩格式配置
# ============================================================

# 支持压缩的格式及其质量参数范围
COMPRESSIBLE_FORMATS: dict[str, dict[str, Any]] = {
    ".jpg": {"min_q": 1, "max_q": 100, "format": "JPEG", "param": "quality"},
    ".jpeg": {"min_q": 1, "max_q": 100, "format": "JPEG", "param": "quality"},
    ".png": {"min_q": 0, "max_q": 9, "format": "PNG", "param": "compress_level"},
    ".webp": {"min_q": 1, "max_q": 100, "format": "WEBP", "param": "quality"},
    ".avif": {"min_q": 1, "max_q": 100, "format": "AVIF", "param": "quality"},
    ".heic": {"min_q": 1, "max_q": 100, "format": "HEIF", "param": "quality"},
    ".heif": {"min_q": 1, "max_q": 100, "format": "HEIF", "param": "quality"},
    ".tiff": {"min_q": 0, "max_q": 9, "format": "TIFF", "param": "compression"},
    ".tif": {"min_q": 0, "max_q": 9, "format": "TIFF", "param": "compression"},
}

LOSSLESS_COMPRESSION_FORMATS = {".png", ".tif", ".tiff"}

# 压缩预设
COMPRESS_PRESETS: dict[str, dict[str, Any]] = {
    "lossless": {
        # 无缩放时有损源按字节复制（见 exact_copy_formats）；一旦被迫重编码
        # （--max-size 缩放），JPEG 用 q95 subsampling0 作归档级近无损，避免 q100
        # 体积暴涨，WebP 则走真·无损（见 _encode_compressed 的 lossless 分支）。
        "description": "严格无损 — 有损源格式按字节复制，避免再次编码",
        "jpg_quality": 95,
        "png_level": 9,
        "webp_quality": 100,
    },
    "high": {
        "description": "高质量 — 几乎无视觉损失",
        "jpg_quality": 92,
        "png_level": 9,
        "webp_quality": 90,
    },
    "medium": {
        "description": "中等 — 体积明显减小，质量良好",
        "jpg_quality": 82,
        "png_level": 9,
        "webp_quality": 80,
    },
    "low": {
        "description": "低质量 — 大幅缩小体积",
        "jpg_quality": 60,
        "png_level": 9,
        "webp_quality": 55,
    },
    "tiny": {
        "description": "极限 — 最小体积，适合缩略图",
        "jpg_quality": 40,
        "png_level": 9,
        "webp_quality": 35,
    },
}


# ============================================================
#  核心压缩函数
# ============================================================


# 1 EiB：远超任何真实文件，但能挡住 "9e99GB" 这类会溢出后续算术的输入。
_MAX_TARGET_BYTES = 1 << 60


def parse_target_size(target_str: str) -> int:
    """
    解析目标文件大小字符串

    支持: "500KB", "1MB", "2.5MB", "1024B", "500kb"
    返回: 字节数

    只接受有限的正数。``float()`` 会接受 "inf"/"nan"，若不拦截，
    ``int(float("inf"))`` 抛出的是 OverflowError 而非 ValueError，
    调用方的参数校验就会漏过去变成崩溃。
    """
    target_str = target_str.strip().upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 * 1024,
        "GB": 1024 * 1024 * 1024,
    }

    number_text = target_str
    multiplier = 1
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if target_str.endswith(suffix):
            number_text = target_str[: -len(suffix)].strip()
            multiplier = mult
            break

    value = float(number_text)  # 非数字文本在此抛出 ValueError
    if not math.isfinite(value) or value <= 0:
        raise ValueError("invalid_target_size")
    scaled = value * multiplier
    if not math.isfinite(scaled) or scaled > _MAX_TARGET_BYTES:
        raise ValueError("invalid_target_size")
    return int(scaled)


def compress_single(
    input_path: str,
    output_path: str,
    quality: int | None = None,
    preset: str = DEFAULT_COMPRESS_PRESET,
    target_size: str | None = None,
    max_size: int | None = None,
    overwrite: bool = False,
) -> CompressResult:
    """
    压缩单个图片文件（不改变格式）

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        quality: 直接指定质量 (1-100)，覆盖预设
        preset: 压缩预设 (lossless/high/medium/low/tiny)
        target_size: 目标文件大小，如 "500KB"、"1MB"
        max_size: 最大边长限制（像素）
        overwrite: 是否覆盖
    """
    result = CompressResult(input_path=input_path, output_path=output_path)
    start_time = time.time()

    try:
        if not os.path.exists(input_path):
            result.error = f"文件不存在: {input_path}"
            return result
        result.input_size = os.path.getsize(input_path)
        ext, fmt_config = _validate_compress_request(
            Path(input_path).suffix.lower(),
            output_path,
            quality=quality,
            preset=preset,
            target_size=target_size,
            max_size=max_size,
            overwrite=overwrite,
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        if _can_copy_losslessly(
            ext, preset=preset, quality=quality, target_size=target_size, max_size=max_size
        ):
            atomic_copy_file(input_path, output_path, overwrite=overwrite)
            result.quality_used = 100
            result.iterations = 1
        else:
            _compress_decoded(
                input_path,
                output_path,
                ext,
                fmt_config,
                quality=quality,
                preset=preset,
                target_size=target_size,
                max_size=max_size,
                overwrite=overwrite,
                result=result,
            )

        if os.path.exists(output_path):
            result.output_size = os.path.getsize(output_path)
            result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _validate_compress_request(
    ext: str,
    output_path: str,
    *,
    quality: int | None,
    preset: str,
    target_size: str | None,
    max_size: int | None,
    overwrite: bool,
) -> tuple[str, dict[str, Any]]:
    if os.path.exists(output_path) and not overwrite:
        raise ValueError("输出文件已存在（使用 --overwrite 覆盖）")
    fmt_config = COMPRESSIBLE_FORMATS.get(ext)
    if fmt_config is None:
        raise ValueError(f"不支持压缩此格式: {ext}")
    if preset not in COMPRESS_PRESETS:
        raise ValueError(f"unsupported_compress_preset:{preset}")
    if max_size is not None and max_size <= 0:
        raise ValueError("max_size_must_be_positive")
    if quality is not None and not 1 <= quality <= 100:
        raise ValueError("quality_must_be_between_1_and_100")
    if quality is not None and target_size is not None:
        raise ValueError("quality_and_target_size_are_mutually_exclusive")
    return ext, fmt_config


def _can_copy_losslessly(
    ext: str,
    *,
    preset: str,
    quality: int | None,
    target_size: str | None,
    max_size: int | None,
) -> bool:
    exact_copy_formats = {".jpg", ".jpeg", ".webp", ".avif", ".heic", ".heif"}
    return (
        preset == "lossless"
        and quality is None
        and target_size is None
        and max_size is None
        and ext in exact_copy_formats
    )


def _compress_decoded(
    input_path: str,
    output_path: str,
    ext: str,
    fmt_config: dict[str, Any],
    *,
    quality: int | None,
    preset: str,
    target_size: str | None,
    max_size: int | None,
    overwrite: bool,
    result: CompressResult,
) -> None:
    with open_image(input_path) as source:
        ensure_static_image(source)
        target_bytes = parse_target_size(target_size) if target_size else None
        if _source_already_fits(result.input_size, source.size, target_bytes, max_size):
            atomic_copy_file(input_path, output_path, overwrite=overwrite)
            result.quality_used = 100
            result.iterations = 1
            return

        image = normalize_orientation(source)
        if max_size:
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if target_bytes is not None:
            _compress_to_target(
                image,
                output_path,
                ext,
                fmt_config,
                target_bytes,
                result,
                overwrite=overwrite,
            )
            return
        _compress_at_quality(
            image,
            input_path,
            output_path,
            ext,
            fmt_config,
            quality=quality,
            preset=preset,
            resized=max_size is not None,
            overwrite=overwrite,
            result=result,
        )


def _source_already_fits(
    input_size: int,
    dimensions: tuple[int, int],
    target_bytes: int | None,
    max_size: int | None,
) -> bool:
    return (
        target_bytes is not None
        and input_size <= target_bytes
        and (max_size is None or max(dimensions) <= max_size)
    )


def _compress_at_quality(
    image: Image.Image,
    input_path: str,
    output_path: str,
    ext: str,
    fmt_config: dict[str, Any],
    *,
    quality: int | None,
    preset: str,
    resized: bool,
    overwrite: bool,
    result: CompressResult,
) -> None:
    actual_quality = _get_quality(ext, quality, preset)
    lossless = preset == "lossless" and quality is None
    payload = _encode_compressed(image, ext, fmt_config, actual_quality, lossless=lossless)
    # Select the winner before publishing. Publishing a larger encode and then
    # replacing it with the source creates a second commit-time race.
    if not resized and len(payload) >= result.input_size:
        atomic_copy_file(input_path, output_path, overwrite=overwrite)
    else:
        atomic_write_bytes(output_path, payload, overwrite=overwrite)
    result.quality_used = actual_quality
    result.iterations = 1


def _get_quality(ext: str, quality: int | None, preset: str) -> int:
    """根据格式、自定义质量、预设获取实际质量值"""
    preset_config = COMPRESS_PRESETS[preset]

    # PNG and TIFF are lossless here. A 1-100 visual-quality value has no
    # meaningful mapping to their compression effort and must not override it.
    if ext == ".png":
        return int(preset_config.get("png_level", 9))
    if ext in (".tif", ".tiff"):
        return 0
    if quality is not None:
        return quality

    if ext in (".jpg", ".jpeg"):
        return int(preset_config.get("jpg_quality", 82))
    elif ext == ".webp" or ext in (".avif",):
        return int(preset_config.get("webp_quality", 80))
    elif ext in (".heic", ".heif"):
        return int(preset_config.get("jpg_quality", 82))
    else:
        return 80


def _save_compressed(
    img: Image.Image,
    output_path: str,
    ext: str,
    fmt_config: dict[str, Any],
    quality_val: int,
    lossless: bool = False,
    overwrite: bool = True,
) -> None:
    """按指定质量保存压缩后的图片"""
    atomic_write_bytes(
        output_path,
        _encode_compressed(img, ext, fmt_config, quality_val, lossless=lossless),
        overwrite=overwrite,
    )


def _encode_compressed(
    img: Image.Image,
    ext: str,
    fmt_config: dict[str, Any],
    quality_val: int,
    lossless: bool = False,
) -> bytes:
    """Encode one image using the exact payload used for final output."""
    save_img = _prepare_compressed_image(img, ext)
    save_kwargs = _compression_save_kwargs(ext, fmt_config, quality_val, lossless=lossless)
    save_kwargs.update(_compression_metadata(img, save_img))
    buf = io.BytesIO()
    save_img.save(buf, **save_kwargs)
    return buf.getvalue()


def _prepare_compressed_image(image: Image.Image, ext: str) -> Image.Image:
    prepared = image
    if prepared.mode in {"CMYK", "YCCK", "LAB"} and ext not in {".tif", ".tiff"}:
        prepared = convert_color_to_rgb(prepared)
    if ext in (".jpg", ".jpeg"):
        return _prepare_jpeg_image(prepared)
    if ext in {".avif", ".heic", ".heif"} and prepared.mode not in ("RGB", "RGBA"):
        prepared = convert_color_to_rgb(prepared)
        if prepared.mode not in ("RGB", "RGBA"):
            prepared = prepared.convert("RGB")
    return prepared


def _prepare_jpeg_image(image: Image.Image) -> Image.Image:
    if image_has_transparency(image):
        return flatten_transparency(image)
    if image.mode in ("RGB", "L"):
        return image
    converted = convert_color_to_rgb(image)
    return converted if converted.mode in ("RGB", "L") else converted.convert("RGB")


def _compression_save_kwargs(
    ext: str,
    fmt_config: dict[str, Any],
    quality_val: int,
    *,
    lossless: bool,
) -> dict[str, Any]:
    if ext in (".jpg", ".jpeg"):
        return {
            "format": "JPEG",
            "quality": quality_val,
            "optimize": True,
            "subsampling": 0 if quality_val >= 95 else 2,
        }
    if ext == ".png":
        return {
            "format": "PNG",
            "compress_level": min(9, max(0, quality_val)),
            "optimize": True,
        }
    if ext == ".webp":
        return (
            {"format": "WEBP", "lossless": True, "method": 6}
            if lossless
            else {"format": "WEBP", "quality": quality_val, "method": 6}
        )
    if ext == ".avif":
        return {"format": "AVIF", "quality": quality_val}
    if ext in (".heic", ".heif"):
        return {"format": "HEIF", "quality": quality_val}
    if ext in (".tiff", ".tif"):
        return {"format": "TIFF", "compression": "tiff_lzw"}
    return {"format": fmt_config["format"]}


def _compression_metadata(original: Image.Image, encoded: Image.Image) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    try:
        exif_data = normalized_exif_bytes(original)
        if exif_data:
            metadata["exif"] = exif_data
    except Exception:
        pass
    try:
        icc_profile = encoded.info.get("icc_profile")
        if icc_profile:
            metadata["icc_profile"] = icc_profile
    except Exception:
        pass
    return metadata


def _compress_to_target(
    img: Image.Image,
    output_path: str,
    ext: str,
    fmt_config: dict[str, Any],
    target_bytes: int,
    result: CompressResult,
    *,
    overwrite: bool = True,
) -> CompressResult:
    """
    二分法压缩到目标文件大小

    对 PNG 等无损格式，通过缩小尺寸来达到目标大小。
    对 JPG/WebP 等有损格式，通过调整质量参数来达到目标。
    """
    if target_bytes <= 0:
        raise ValueError("target_size_must_be_positive")

    if ext in {".png", ".tif", ".tiff"}:
        return _compress_lossless_to_target(
            img,
            output_path,
            ext,
            fmt_config,
            target_bytes,
            result,
            overwrite=overwrite,
        )

    minimum_quality = int(fmt_config["min_q"])
    maximum_quality = int(fmt_config["max_q"])
    best_quality: int | None = None
    best_payload: bytes | None = None
    smallest_size: int | None = None
    iterations = 0
    # JPEG-family encoders are close to monotonic but not guaranteed to be:
    # quantisation-table and entropy changes can make a higher quality smaller.
    # The supported integer domain is bounded, so descending enumeration is the
    # only way to prove that the first fit is the highest feasible quality.
    for quality in range(maximum_quality, minimum_quality - 1, -1):
        payload = _encode_compressed(img, ext, fmt_config, quality)
        iterations += 1
        smallest_size = len(payload) if smallest_size is None else min(smallest_size, len(payload))
        if len(payload) <= target_bytes:
            best_quality = quality
            best_payload = payload
            break

    if best_quality is None or best_payload is None:
        raise ValueError(
            f"target_size_unreachable: minimum={smallest_size or 0} target={target_bytes}"
        )

    atomic_write_bytes(output_path, best_payload, overwrite=overwrite)
    result.quality_used = best_quality
    result.iterations = iterations
    return result


def _compress_lossless_to_target(
    img: Image.Image,
    output_path: str,
    ext: str,
    fmt_config: dict[str, Any],
    target_bytes: int,
    result: CompressResult,
    *,
    overwrite: bool = True,
) -> CompressResult:
    """Encode at full dimensions or fail rather than silently discarding pixels."""
    quality = 9 if ext == ".png" else 0
    full_payload = _encode_compressed(img, ext, fmt_config, quality)
    if len(full_payload) <= target_bytes:
        atomic_write_bytes(output_path, full_payload, overwrite=overwrite)
        result.quality_used = quality
        result.iterations = 1
        return result

    raise ValueError(f"target_size_unreachable: minimum={len(full_payload)} target={target_bytes}")


def _save_to_buffer(img: Image.Image, buf: io.BytesIO, ext: str, quality: int) -> None:
    """将图片保存到内存缓冲区（用于二分法测试大小）"""
    config = COMPRESSIBLE_FORMATS.get(ext)
    if config is None:
        raise ValueError(f"unsupported compression format: {ext}")
    buf.write(_encode_compressed(img, ext, config, quality))


def collect_compressible_files(
    input_paths: list[str],
    input_format: str | None = None,
    recursive: bool = False,
    selection: SelectionFilters | None = None,
) -> list[str]:
    """收集所有可压缩的图片文件"""
    return collect_supported_files(
        input_paths,
        set(COMPRESSIBLE_FORMATS),
        input_format=input_format,
        recursive=recursive,
        selection=selection,
    )

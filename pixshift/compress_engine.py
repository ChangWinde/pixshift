"""
PixShift Compress Engine — 智能图片压缩（不改格式，只优化体积）

功能:
  - 同格式压缩优化（优化 PNG 和 JPEG 编码，不改变输出格式）
  - 目标文件大小限制（二分法自动调质量）
  - 批量 + 并行处理
"""

import io
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
    ensure_static_image,
    flatten_transparency,
    image_has_transparency,
    normalize_orientation,
    normalized_exif_bytes,
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


def parse_target_size(target_str: str) -> int:
    """
    解析目标文件大小字符串

    支持: "500KB", "1MB", "2.5MB", "1024B", "500kb"
    返回: 字节数
    """
    target_str = target_str.strip().upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 * 1024,
        "GB": 1024 * 1024 * 1024,
    }

    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if target_str.endswith(suffix):
            num_str = target_str[: -len(suffix)].strip()
            return int(float(num_str) * mult)

    # 纯数字，默认字节
    return int(float(target_str))


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

        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        ext = Path(input_path).suffix.lower()
        fmt_config = COMPRESSIBLE_FORMATS.get(ext)

        if not fmt_config:
            result.error = f"不支持压缩此格式: {ext}"
            return result

        if preset not in COMPRESS_PRESETS:
            raise ValueError(f"unsupported_compress_preset:{preset}")
        if max_size is not None and max_size <= 0:
            raise ValueError("max_size_must_be_positive")
        if quality is not None and not 1 <= quality <= 100:
            raise ValueError("quality_must_be_between_1_and_100")
        if quality is not None and target_size is not None:
            raise ValueError("quality_and_target_size_are_mutually_exclusive")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        exact_copy_formats = {".jpg", ".jpeg", ".webp", ".avif", ".heic", ".heif"}
        if (
            preset == "lossless"
            and quality is None
            and target_size is None
            and max_size is None
            and ext in exact_copy_formats
        ):
            atomic_copy_file(input_path, output_path)
            result.quality_used = 100
            result.iterations = 1
        else:
            with Image.open(input_path) as source:
                ensure_static_image(source)
                img = normalize_orientation(source)

                if max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

                if target_size:
                    target_bytes = parse_target_size(target_size)
                    result = _compress_to_target(
                        img, output_path, ext, fmt_config, target_bytes, result
                    )
                else:
                    actual_quality = _get_quality(ext, quality, preset)
                    lossless = preset == "lossless" and quality is None
                    _save_compressed(
                        img, output_path, ext, fmt_config, actual_quality, lossless=lossless
                    )
                    result.quality_used = actual_quality
                    result.iterations = 1

        # compress 的语义是"减小体积"，绝不应把文件改大。未缩放时若重编码结果
        # 不比原文件小（常见于已高度优化的 JPEG），保留原始字节——同格式下严格
        # 更优且零质量损失。
        if (
            not result.error
            and max_size is None
            and os.path.exists(output_path)
            and os.path.getsize(output_path) >= result.input_size
            and os.path.getsize(input_path) == result.input_size
        ):
            atomic_copy_file(input_path, output_path)

        if os.path.exists(output_path):
            result.output_size = os.path.getsize(output_path)
            result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


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
) -> None:
    """按指定质量保存压缩后的图片"""
    atomic_write_bytes(
        output_path, _encode_compressed(img, ext, fmt_config, quality_val, lossless=lossless)
    )


def _encode_compressed(
    img: Image.Image,
    ext: str,
    fmt_config: dict[str, Any],
    quality_val: int,
    lossless: bool = False,
) -> bytes:
    """Encode one image using the exact payload used for final output."""
    save_kwargs: dict[str, Any] = {}
    save_img = img

    if ext in (".jpg", ".jpeg"):
        if image_has_transparency(save_img):
            save_img = flatten_transparency(save_img)
        elif save_img.mode not in ("RGB", "L"):
            save_img = save_img.convert("RGB")
        save_kwargs = {
            "format": "JPEG",
            "quality": quality_val,
            "optimize": True,
            "subsampling": 0 if quality_val >= 95 else 2,
        }
    elif ext == ".png":
        save_kwargs = {
            "format": "PNG",
            "compress_level": min(9, max(0, quality_val)),
            "optimize": True,
        }
    elif ext == ".webp":
        # lossless 预设走 WebP 真·无损，而非 quality=100 的有损近似。
        save_kwargs = (
            {"format": "WEBP", "lossless": True, "method": 6}
            if lossless
            else {"format": "WEBP", "quality": quality_val, "method": 6}
        )
    elif ext == ".avif":
        if save_img.mode not in ("RGB", "RGBA"):
            save_img = save_img.convert("RGB")
        save_kwargs = {
            "format": "AVIF",
            "quality": quality_val,
        }
    elif ext in (".heic", ".heif"):
        if save_img.mode not in ("RGB", "RGBA"):
            save_img = save_img.convert("RGB")
        save_kwargs = {
            "format": "HEIF",
            "quality": quality_val,
        }
    elif ext in (".tiff", ".tif"):
        save_kwargs = {
            "format": "TIFF",
            "compression": "tiff_lzw",
        }
    else:
        save_kwargs = {"format": fmt_config["format"]}

    # 保留 EXIF 和 ICC
    try:
        exif_data = normalized_exif_bytes(img)
        if exif_data:
            save_kwargs["exif"] = exif_data
    except Exception:
        pass

    try:
        icc_profile = img.info.get("icc_profile")
        if icc_profile:
            save_kwargs["icc_profile"] = icc_profile
    except Exception:
        pass

    buf = io.BytesIO()
    save_img.save(buf, **save_kwargs)
    return buf.getvalue()


def _compress_to_target(
    img: Image.Image,
    output_path: str,
    ext: str,
    fmt_config: dict[str, Any],
    target_bytes: int,
    result: CompressResult,
) -> CompressResult:
    """
    二分法压缩到目标文件大小

    对 PNG 等无损格式，通过缩小尺寸来达到目标大小。
    对 JPG/WebP 等有损格式，通过调整质量参数来达到目标。
    """
    if target_bytes <= 0:
        raise ValueError("target_size_must_be_positive")

    if ext in {".png", ".tif", ".tiff"}:
        return _compress_lossless_to_target(img, output_path, ext, fmt_config, target_bytes, result)

    q_low = int(fmt_config["min_q"])
    q_high = int(fmt_config["max_q"])
    minimum = _encode_compressed(img, ext, fmt_config, q_low)
    if len(minimum) > target_bytes:
        raise ValueError(f"target_size_unreachable: minimum={len(minimum)} target={target_bytes}")

    best_quality = q_low
    best_payload = minimum
    iterations = 1
    while q_low <= q_high and iterations < 20:
        q_mid = (q_low + q_high) // 2
        payload = _encode_compressed(img, ext, fmt_config, q_mid)
        iterations += 1
        if len(payload) <= target_bytes:
            best_quality = q_mid
            best_payload = payload
            q_low = q_mid + 1
        else:
            q_high = q_mid - 1

    atomic_write_bytes(output_path, best_payload)
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
) -> CompressResult:
    """Find the largest lossless image dimensions that fit the target."""
    quality = 9 if ext == ".png" else 0
    full_payload = _encode_compressed(img, ext, fmt_config, quality)
    if len(full_payload) <= target_bytes:
        atomic_write_bytes(output_path, full_payload)
        result.quality_used = quality
        result.iterations = 1
        return result

    smallest = img.resize((1, 1), Image.Resampling.LANCZOS)
    best_payload = _encode_compressed(smallest, ext, fmt_config, quality)
    if len(best_payload) > target_bytes:
        raise ValueError(
            f"target_size_unreachable: minimum={len(best_payload)} target={target_bytes}"
        )

    low = 1.0 / max(img.width, img.height)
    high = 1.0
    iterations = 1
    while iterations < 20 and high - low > 0.0001:
        scale = (low + high) / 2
        resized = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
        payload = _encode_compressed(resized, ext, fmt_config, quality)
        iterations += 1
        if len(payload) <= target_bytes:
            best_payload = payload
            low = scale
        else:
            high = scale

    atomic_write_bytes(output_path, best_payload)
    result.quality_used = quality
    result.iterations = iterations
    return result


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

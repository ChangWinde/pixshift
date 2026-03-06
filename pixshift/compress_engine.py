"""
PixShift Compress Engine — 智能图片压缩（不改格式，只优化体积）

功能:
  - 同格式压缩优化（PNG→优化PNG, JPG→更小JPG）
  - 目标文件大小限制（二分法自动调质量）
  - 批量 + 并行处理
"""

import os
import io
import time
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass, field

from PIL import Image

from .converter import SUPPORTED_INPUT_FORMATS, _human_size


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
    results: List[CompressResult] = field(default_factory=list)


# ============================================================
#  压缩格式配置
# ============================================================

# 支持压缩的格式及其质量参数范围
COMPRESSIBLE_FORMATS = {
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

# 压缩预设
COMPRESS_PRESETS = {
    "lossless": {
        "description": "无损优化 — 仅优化编码，不降低质量",
        "jpg_quality": 100,
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

def _parse_target_size(target_str: str) -> int:
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
            num_str = target_str[:-len(suffix)].strip()
            return int(float(num_str) * mult)

    # 纯数字，默认字节
    return int(float(target_str))


def compress_single(
    input_path: str,
    output_path: str,
    quality: Optional[int] = None,
    preset: str = "medium",
    target_size: Optional[str] = None,
    max_size: Optional[int] = None,
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

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        img = Image.open(input_path)

        # 缩小尺寸
        if max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)

        # 目标大小模式：二分法
        if target_size:
            target_bytes = _parse_target_size(target_size)
            result = _compress_to_target(
                img, input_path, output_path, ext, fmt_config,
                target_bytes, result
            )
        else:
            # 固定质量模式
            actual_quality = _get_quality(ext, quality, preset)
            _save_compressed(img, output_path, ext, fmt_config, actual_quality)
            result.quality_used = actual_quality
            result.iterations = 1

        if os.path.exists(output_path):
            result.output_size = os.path.getsize(output_path)
            result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _get_quality(ext: str, quality: Optional[int], preset: str) -> int:
    """根据格式、自定义质量、预设获取实际质量值"""
    if quality is not None:
        return quality

    preset_config = COMPRESS_PRESETS.get(preset, COMPRESS_PRESETS["medium"])

    if ext in (".jpg", ".jpeg"):
        return preset_config.get("jpg_quality", 82)
    elif ext == ".png":
        return preset_config.get("png_level", 9)
    elif ext == ".webp":
        return preset_config.get("webp_quality", 80)
    elif ext in (".avif",):
        return preset_config.get("webp_quality", 80)
    elif ext in (".heic", ".heif"):
        return preset_config.get("jpg_quality", 82)
    else:
        return 80


def _save_compressed(
    img: Image.Image,
    output_path: str,
    ext: str,
    fmt_config: dict,
    quality_val: int,
):
    """按指定质量保存压缩后的图片"""
    save_kwargs = {}

    if ext in (".jpg", ".jpeg"):
        if img.mode in ("RGBA", "LA", "PA"):
            img = img.convert("RGB")
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
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
        save_kwargs = {
            "format": "WEBP",
            "quality": quality_val,
            "method": 6,
        }
    elif ext == ".avif":
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        save_kwargs = {
            "format": "AVIF",
            "quality": quality_val,
        }
    elif ext in (".heic", ".heif"):
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
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
        exif_data = img.info.get("exif")
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

    img.save(output_path, **save_kwargs)


def _compress_to_target(
    img: Image.Image,
    input_path: str,
    output_path: str,
    ext: str,
    fmt_config: dict,
    target_bytes: int,
    result: CompressResult,
) -> CompressResult:
    """
    二分法压缩到目标文件大小

    对 PNG 等无损格式，通过缩小尺寸来达到目标大小。
    对 JPG/WebP 等有损格式，通过调整质量参数来达到目标。
    """
    if ext == ".png":
        # PNG 是无损的，质量参数只影响压缩速度不影响大小
        # 先尝试最大压缩，如果还是太大就缩小尺寸
        _save_compressed(img, output_path, ext, fmt_config, 9)
        current_size = os.path.getsize(output_path)

        if current_size <= target_bytes:
            result.quality_used = 9
            result.iterations = 1
            return result

        # 需要缩小尺寸
        iterations = 0
        scale_low, scale_high = 0.1, 1.0

        while iterations < 20:
            iterations += 1
            scale = (scale_low + scale_high) / 2
            new_w = max(1, int(img.width * scale))
            new_h = max(1, int(img.height * scale))
            resized = img.resize((new_w, new_h), Image.LANCZOS)

            _save_compressed(resized, output_path, ext, fmt_config, 9)
            current_size = os.path.getsize(output_path)

            if abs(current_size - target_bytes) < target_bytes * 0.05:
                break
            elif current_size > target_bytes:
                scale_high = scale
            else:
                scale_low = scale

        result.quality_used = 9
        result.iterations = iterations
        return result

    else:
        # 有损格式：二分法调质量
        q_low = fmt_config["min_q"]
        q_high = fmt_config["max_q"]
        best_quality = q_high
        iterations = 0

        while q_low <= q_high and iterations < 20:
            iterations += 1
            q_mid = (q_low + q_high) // 2

            buf = io.BytesIO()
            _save_to_buffer(img, buf, ext, q_mid)
            current_size = buf.tell()

            if current_size <= target_bytes:
                best_quality = q_mid
                q_low = q_mid + 1
                # 如果已经很接近目标，停止
                if current_size >= target_bytes * 0.9:
                    break
            else:
                q_high = q_mid - 1

        _save_compressed(img, output_path, ext, fmt_config, best_quality)
        result.quality_used = best_quality
        result.iterations = iterations
        return result


def _save_to_buffer(img: Image.Image, buf: io.BytesIO, ext: str, quality: int):
    """将图片保存到内存缓冲区（用于二分法测试大小）"""
    if ext in (".jpg", ".jpeg"):
        save_img = img
        if save_img.mode in ("RGBA", "LA", "PA"):
            save_img = save_img.convert("RGB")
        elif save_img.mode not in ("RGB", "L"):
            save_img = save_img.convert("RGB")
        save_img.save(buf, format="JPEG", quality=quality, optimize=True)
    elif ext == ".webp":
        img.save(buf, format="WEBP", quality=quality, method=6)
    elif ext == ".avif":
        save_img = img
        if save_img.mode not in ("RGB", "RGBA"):
            save_img = save_img.convert("RGB")
        save_img.save(buf, format="AVIF", quality=quality)
    elif ext in (".heic", ".heif"):
        save_img = img
        if save_img.mode not in ("RGB", "RGBA"):
            save_img = save_img.convert("RGB")
        save_img.save(buf, format="HEIF", quality=quality)


def collect_compressible_files(
    input_paths: List[str],
    input_format: Optional[str] = None,
    recursive: bool = False,
) -> List[str]:
    """收集所有可压缩的图片文件"""
    files = []
    compressible_exts = set(COMPRESSIBLE_FORMATS.keys())

    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file():
            ext = path.suffix.lower()
            if input_format:
                if ext == f".{input_format.lower().lstrip('.')}":
                    files.append(str(path.resolve()))
            elif ext in compressible_exts:
                files.append(str(path.resolve()))
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for item in sorted(path.glob(pattern)):
                if item.is_file():
                    ext = item.suffix.lower()
                    if input_format:
                        if ext == f".{input_format.lower().lstrip('.')}":
                            files.append(str(item.resolve()))
                    elif ext in compressible_exts:
                        files.append(str(item.resolve()))

    return sorted(set(files))

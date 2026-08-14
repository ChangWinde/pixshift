"""
PixShift Optimize Engine — 格式智能推荐 + 体积对比

功能:
  - 分析图片内容特征（照片/截图/简单图形）
  - 推荐最佳输出格式
  - 生成各格式预估体积对比表
  - 显示压缩率和质量评估
"""

import io
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from .converter import _human_size
from .core.errors import AnimatedInputNotSupportedError
from .core.metadata import (
    convert_color_to_rgb,
    ensure_pixel_count_within_limit,
    ensure_within_pixel_limit,
    flatten_transparency,
    image_frame_count,
    image_has_transparency,
    normalize_orientation,
    open_image,
)

ANALYSIS_MAX_SIDE = 1600

# ============================================================
#  数据结构
# ============================================================


@dataclass
class FormatEstimate:
    """单个格式的预估结果"""

    format_name: str = ""
    format_key: str = ""  # stable machine token matching convert's -t vocabulary
    estimated_size: int = 0
    estimated_size_human: str = ""
    compression_ratio: float = 0.0  # 相对原始大小的比例
    quality_note: str = ""
    is_recommended: bool = False
    supports_alpha: bool = False
    is_lossless: bool = False


@dataclass
class OptimizeResult:
    """图片优化分析结果"""

    input_path: str = ""
    input_size: int = 0
    input_size_human: str = ""
    input_format: str = ""
    width: int = 0
    height: int = 0
    has_alpha: bool = False
    image_type: str = ""  # photo / screenshot / graphic / text
    image_type_reason: str = ""
    recommended_format: str = ""
    recommended_reason: str = ""
    analysis_size: tuple[int, int] = (0, 0)
    sampled: bool = False
    estimate_scale: float = 1.0
    plan: dict[str, Any] = field(default_factory=dict)
    estimates: list[FormatEstimate] = field(default_factory=list)
    duration: float = 0.0
    error: str = ""


# ============================================================
#  图片类型检测
# ============================================================


def _detect_image_type(img: Image.Image) -> tuple[str, str]:
    """
    检测图片类型

    返回: (类型, 原因)
    类型: photo / screenshot / graphic / text
    """
    # 统一为可见 RGB 像素，避免透明调色板索引影响内容分类。
    if image_has_transparency(img):
        analyze_img = flatten_transparency(img)
    elif img.mode in {"CMYK", "YCCK", "LAB"}:
        analyze_img = convert_color_to_rgb(img)
    elif img.mode != "RGB":
        analyze_img = img.convert("RGB")
    else:
        analyze_img = img

    stat = ImageStat.Stat(analyze_img)

    # 颜色统计
    stddevs = stat.stddev  # 各通道标准差

    avg_stddev = sum(stddevs) / len(stddevs)

    # 采样分析颜色数量
    small = analyze_img.copy()
    small.thumbnail((200, 200), Image.Resampling.NEAREST)
    colors = small.getcolors(maxcolors=10000)

    unique_colors = 10000 if colors is None else len(colors)
    entropy = analyze_img.entropy()

    # 判断逻辑
    if unique_colors < 50:
        return "graphic", f"仅 {unique_colors} 种颜色，适合无损压缩"
    elif unique_colors >= 128 and entropy >= 7:
        return "photo", f"高图像熵 ({entropy:.1f})，像照片"
    elif unique_colors < 256 and avg_stddev < 40:
        return "screenshot", f"{unique_colors} 种颜色，低复杂度，像截图/UI"
    elif avg_stddev > 50:
        return "photo", f"高色彩复杂度 (σ={avg_stddev:.0f})，像照片"
    elif unique_colors < 500:
        return "graphic", f"{unique_colors} 种颜色，像图形/图标"
    else:
        return "photo", f"丰富色彩 ({unique_colors} 色)，像照片"


# ============================================================
#  格式推荐
# ============================================================

FORMAT_CONFIGS: dict[str, dict[str, Any]] = {
    "webp": {
        "quality": 90,
        "method": 4,
        "supports_alpha": True,
        "is_lossless": False,
        "note": "现代格式，体积小，浏览器广泛支持",
    },
    "webp_lossless": {
        "quality": 100,
        "lossless": True,
        "supports_alpha": True,
        "is_lossless": True,
        "note": "WebP 无损模式",
    },
    "avif": {
        "quality": 90,
        "supports_alpha": True,
        "is_lossless": False,
        "note": "最新格式，极高压缩率，支持逐渐增加",
    },
    "jpg_high": {
        "quality": 95,
        "supports_alpha": False,
        "is_lossless": False,
        "note": "JPEG 高质量，兼容性最好",
    },
    "jpg_medium": {
        "quality": 85,
        "supports_alpha": False,
        "is_lossless": False,
        "note": "JPEG 中等质量，体积更小",
    },
    "png": {
        "compress_level": 9,
        "supports_alpha": True,
        "is_lossless": True,
        "note": "PNG 无损，适合截图/图形",
    },
}


def analyze_image(input_path: str) -> OptimizeResult:
    """
    分析图片并推荐最佳格式

    返回各格式的预估体积对比
    """
    result = OptimizeResult(input_path=input_path)
    start_time = time.time()

    try:
        if not os.path.exists(input_path):
            result.error = f"文件不存在: {input_path}"
            return result

        result.input_size = os.path.getsize(input_path)
        result.input_size_human = _human_size(result.input_size)
        result.input_format = Path(input_path).suffix.lower().lstrip(".")

        with open_image(input_path) as source:
            # Analysis copies and thumbnails the image, so the pixel budget
            # must be enforced here too — the still-image guard that carries
            # it elsewhere is deliberately skipped for animations.
            ensure_within_pixel_limit(source)
            frame_total = image_frame_count(source)
            if frame_total > 1:
                if source.format == "TIFF":
                    raise AnimatedInputNotSupportedError()
                _analyze_animation(result, source, frame_total)
                result.duration = time.time() - start_time
                return result
            img = normalize_orientation(source).copy()
        result.width, result.height = img.size
        result.has_alpha = image_has_transparency(img)

        analysis_img = img.copy()
        analysis_img.thumbnail(
            (ANALYSIS_MAX_SIDE, ANALYSIS_MAX_SIDE),
            Image.Resampling.LANCZOS,
        )
        result.analysis_size = analysis_img.size
        result.sampled = analysis_img.size != img.size
        source_pixels = max(1, img.width * img.height)
        analysis_pixels = max(1, analysis_img.width * analysis_img.height)
        result.estimate_scale = source_pixels / analysis_pixels

        # 检测图片类型
        img_type, reason = _detect_image_type(analysis_img)
        result.image_type = img_type
        result.image_type_reason = reason

        # 预估各格式大小
        estimates = []

        # JPEG (仅无 Alpha)
        if not result.has_alpha:
            for label, q in [("jpg_high", 95), ("jpg_medium", 85)]:
                est = _estimate_format(
                    analysis_img,
                    "JPEG",
                    {"quality": q, "optimize": True},
                    result.estimate_scale,
                )
                est.format_name = f"JPEG (q={q})"
                est.format_key = "jpg"
                est.compression_ratio = (
                    est.estimated_size / result.input_size if result.input_size > 0 else 0
                )
                est.supports_alpha = False
                est.is_lossless = False
                est.quality_note = str(FORMAT_CONFIGS[label]["note"])
                estimates.append(est)

        # PNG
        est = _estimate_format(
            analysis_img,
            "PNG",
            {"compress_level": 9, "optimize": True},
            result.estimate_scale,
        )
        est.format_name = "PNG"
        est.format_key = "png"
        est.compression_ratio = (
            est.estimated_size / result.input_size if result.input_size > 0 else 0
        )
        est.supports_alpha = True
        est.is_lossless = True
        est.quality_note = str(FORMAT_CONFIGS["png"]["note"])
        estimates.append(est)

        # WebP
        est = _estimate_format(
            analysis_img,
            "WEBP",
            {"quality": 90, "method": 4},
            result.estimate_scale,
        )
        est.format_name = "WebP (q=90)"
        est.format_key = "webp"
        est.compression_ratio = (
            est.estimated_size / result.input_size if result.input_size > 0 else 0
        )
        est.supports_alpha = True
        est.is_lossless = False
        est.quality_note = str(FORMAT_CONFIGS["webp"]["note"])
        estimates.append(est)

        # WebP Lossless
        est = _estimate_format(
            analysis_img,
            "WEBP",
            {"lossless": True},
            result.estimate_scale,
        )
        est.format_name = "WebP (无损)"
        est.format_key = "webp"
        est.compression_ratio = (
            est.estimated_size / result.input_size if result.input_size > 0 else 0
        )
        est.supports_alpha = True
        est.is_lossless = True
        est.quality_note = str(FORMAT_CONFIGS["webp_lossless"]["note"])
        estimates.append(est)

        # AVIF (如果支持)
        try:
            est = _estimate_format(
                analysis_img,
                "AVIF",
                {"quality": 90},
                result.estimate_scale,
            )
            est.format_name = "AVIF (q=90)"
            est.format_key = "avif"
            est.compression_ratio = (
                est.estimated_size / result.input_size if result.input_size > 0 else 0
            )
            est.supports_alpha = True
            est.is_lossless = False
            est.quality_note = str(FORMAT_CONFIGS["avif"]["note"])
            estimates.append(est)
        except Exception:
            pass  # AVIF 可能不可用

        # 排序：按大小
        estimates.sort(key=lambda e: e.estimated_size)

        # 推荐逻辑
        recommended = _recommend_format(img_type, estimates)
        for est in estimates:
            if est.format_name == recommended:
                est.is_recommended = True

        result.estimates = estimates
        result.recommended_format = recommended
        result.recommended_reason = _get_recommendation_reason(img_type, recommended)
        result.plan = _build_plan(result.input_format, recommended)

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _analyze_animation(result: OptimizeResult, source: Image.Image, frame_total: int) -> None:
    """Fill an OptimizeResult for a multi-frame image without re-encoding it.

    Deterministic, probe-style analysis (mirroring the video pillar): animated
    GIF/APNG get an executable convert-to-WebP plan — animation preserved by
    the converter — while an already-animated WebP is kept as-is because
    re-encoding it would only lose quality.
    """
    result.width, result.height = source.size
    ensure_pixel_count_within_limit(int(source.width) * int(source.height) * frame_total)
    result.has_alpha = image_has_transparency(source)
    result.image_type = "animation"
    result.image_type_reason = f"{frame_total} 帧动画"
    result.analysis_size = source.size
    if result.input_format == "webp":
        result.recommended_format = "keep"
        result.recommended_reason = "已是动画 WebP，重编码只会损失质量"
        result.plan = {"command": "keep", "arguments": {}}
        return
    result.recommended_format = "WebP (动画)"
    result.recommended_reason = (
        f"动画 {result.input_format.upper() or '?'} 转 WebP 通常可减 30-60% 体积且保留动画"
    )
    result.plan = {"command": "convert", "arguments": {"to": "webp", "quality": "high"}}


def _estimate_format(
    img: Image.Image,
    format_name: str,
    save_kwargs: dict,
    size_scale: float = 1.0,
) -> FormatEstimate:
    """预估指定格式的文件大小"""
    est = FormatEstimate()

    save_img = img
    if save_img.mode in {"CMYK", "YCCK", "LAB"}:
        save_img = convert_color_to_rgb(save_img)
    if format_name == "JPEG" and image_has_transparency(save_img):
        save_img = flatten_transparency(save_img)
    elif format_name == "JPEG" and save_img.mode not in ("RGB", "L"):
        save_img = save_img.convert("RGB")

    buf = io.BytesIO()
    save_img.save(buf, format=format_name, **save_kwargs)
    est.estimated_size = max(1, round(buf.tell() * size_scale))
    est.estimated_size_human = _human_size(est.estimated_size)

    return est


def _recommend_format(
    img_type: str,
    estimates: list[FormatEstimate],
) -> str:
    """根据图片类型推荐最佳格式"""
    if img_type == "photo":
        # 照片：优先 WebP > AVIF > JPEG
        for est in estimates:
            if "WebP (q=" in est.format_name and not est.is_lossless:
                return est.format_name
        for est in estimates:
            if "AVIF" in est.format_name:
                return est.format_name
        for est in estimates:
            if "JPEG" in est.format_name:
                return est.format_name

    elif img_type == "screenshot":
        # 截图：优先可直接执行的 PNG 无损工作流。
        for est in estimates:
            if est.format_name == "PNG":
                return est.format_name
        for est in estimates:
            if "WebP (无损)" in est.format_name:
                return est.format_name

    elif img_type == "graphic":
        # 图形：PNG 无损、兼容，并能由现有 CLI 精确执行。
        for est in estimates:
            if est.format_name == "PNG":
                return est.format_name
        for est in estimates:
            if "WebP (无损)" in est.format_name:
                return est.format_name

    # 默认：最小的
    if estimates:
        return estimates[0].format_name
    return "PNG"


def _build_plan(input_format: str, recommended: str) -> dict[str, Any]:
    """Translate a display recommendation into stable CLI arguments."""
    normalized_input = input_format.lower().lstrip(".")
    if recommended == "PNG":
        if normalized_input == "png":
            return {"command": "compress", "arguments": {"preset": "lossless"}}
        return {
            "command": "convert",
            "arguments": {"to": "png", "quality": "web"},
        }
    if recommended.startswith("WebP"):
        if normalized_input == "webp":
            return {"command": "compress", "arguments": {"quality": 90}}
        return {
            "command": "convert",
            "arguments": {"to": "webp", "quality": "high"},
        }
    if recommended.startswith("AVIF"):
        if normalized_input == "avif":
            return {"command": "compress", "arguments": {"quality": 90}}
        return {
            "command": "convert",
            "arguments": {"to": "avif", "quality": "high"},
        }
    if recommended.startswith("JPEG"):
        if normalized_input in {"jpg", "jpeg"}:
            return {"command": "compress", "arguments": {"quality": 95}}
        return {
            "command": "convert",
            "arguments": {"to": "jpg", "quality": "high"},
        }
    return {"command": "convert", "arguments": {"to": "png", "quality": "web"}}


def _get_recommendation_reason(img_type: str, recommended: str) -> str:
    """获取推荐原因"""
    reasons = {
        "photo": "照片类图片，有损压缩效果最佳",
        "screenshot": "截图/UI 类图片，无损压缩保持清晰",
        "graphic": "图形/图标类图片，颜色少适合无损",
        "text": "文字类图片，需要无损保持清晰",
    }
    base = reasons.get(img_type, "")

    if "WebP" in recommended:
        base += "，WebP 兼容性好且压缩率高"
    elif "AVIF" in recommended:
        base += "，AVIF 压缩率最高但兼容性稍差"
    elif "PNG" in recommended:
        base += "，PNG 无损且兼容性最好"
    elif "JPEG" in recommended:
        base += "，JPEG 兼容性最广"

    return base

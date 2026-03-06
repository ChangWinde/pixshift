"""
PixShift Optimize Engine — 格式智能推荐 + 体积对比

功能:
  - 分析图片内容特征（照片/截图/简单图形）
  - 推荐最佳输出格式
  - 生成各格式预估体积对比表
  - 显示压缩率和质量评估
"""

import os
import io
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field

from PIL import Image, ImageStat

from .converter import SUPPORTED_INPUT_FORMATS, _human_size


# ============================================================
#  数据结构
# ============================================================

@dataclass
class FormatEstimate:
    """单个格式的预估结果"""
    format_name: str = ""
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
    recommended_format: str = ""
    recommended_reason: str = ""
    estimates: List[FormatEstimate] = field(default_factory=list)
    duration: float = 0.0
    error: str = ""


# ============================================================
#  图片类型检测
# ============================================================

def _detect_image_type(img: Image.Image) -> Tuple[str, str]:
    """
    检测图片类型

    返回: (类型, 原因)
    类型: photo / screenshot / graphic / text
    """
    # 转为 RGB 分析
    if img.mode in ("RGBA", "LA", "PA"):
        analyze_img = img.convert("RGB")
    elif img.mode == "L":
        analyze_img = img.convert("RGB")
    else:
        analyze_img = img

    stat = ImageStat.Stat(analyze_img)

    # 颜色统计
    means = stat.mean  # 各通道均值
    stddevs = stat.stddev  # 各通道标准差

    avg_stddev = sum(stddevs) / len(stddevs)

    # 采样分析颜色数量
    small = analyze_img.copy()
    small.thumbnail((200, 200), Image.NEAREST)
    colors = small.getcolors(maxcolors=10000)

    if colors is None:
        unique_colors = 10000
    else:
        unique_colors = len(colors)

    # 判断逻辑
    if unique_colors < 50:
        return "graphic", f"仅 {unique_colors} 种颜色，适合无损压缩"
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

FORMAT_CONFIGS = {
    "webp": {
        "quality": 85,
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
        "quality": 80,
        "supports_alpha": True,
        "is_lossless": False,
        "note": "最新格式，极高压缩率，支持逐渐增加",
    },
    "jpg_high": {
        "quality": 92,
        "supports_alpha": False,
        "is_lossless": False,
        "note": "JPEG 高质量，兼容性最好",
    },
    "jpg_medium": {
        "quality": 80,
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

        img = Image.open(input_path)
        result.width, result.height = img.size
        result.has_alpha = img.mode in ("RGBA", "LA", "PA")

        # 检测图片类型
        img_type, reason = _detect_image_type(img)
        result.image_type = img_type

        # 预估各格式大小
        estimates = []

        # JPEG (仅无 Alpha)
        if not result.has_alpha:
            for label, q in [("jpg_high", 92), ("jpg_medium", 80)]:
                est = _estimate_format(img, "JPEG", {"quality": q, "optimize": True})
                est.format_name = f"JPEG (q={q})"
                est.compression_ratio = est.estimated_size / result.input_size if result.input_size > 0 else 0
                est.supports_alpha = False
                est.is_lossless = False
                est.quality_note = FORMAT_CONFIGS[label]["note"]
                estimates.append(est)

        # PNG
        est = _estimate_format(img, "PNG", {"compress_level": 9, "optimize": True})
        est.format_name = "PNG"
        est.compression_ratio = est.estimated_size / result.input_size if result.input_size > 0 else 0
        est.supports_alpha = True
        est.is_lossless = True
        est.quality_note = FORMAT_CONFIGS["png"]["note"]
        estimates.append(est)

        # WebP
        est = _estimate_format(img, "WEBP", {"quality": 85, "method": 4})
        est.format_name = "WebP (q=85)"
        est.compression_ratio = est.estimated_size / result.input_size if result.input_size > 0 else 0
        est.supports_alpha = True
        est.is_lossless = False
        est.quality_note = FORMAT_CONFIGS["webp"]["note"]
        estimates.append(est)

        # WebP Lossless
        est = _estimate_format(img, "WEBP", {"lossless": True})
        est.format_name = "WebP (无损)"
        est.compression_ratio = est.estimated_size / result.input_size if result.input_size > 0 else 0
        est.supports_alpha = True
        est.is_lossless = True
        est.quality_note = FORMAT_CONFIGS["webp_lossless"]["note"]
        estimates.append(est)

        # AVIF (如果支持)
        try:
            est = _estimate_format(img, "AVIF", {"quality": 80})
            est.format_name = "AVIF (q=80)"
            est.compression_ratio = est.estimated_size / result.input_size if result.input_size > 0 else 0
            est.supports_alpha = True
            est.is_lossless = False
            est.quality_note = FORMAT_CONFIGS["avif"]["note"]
            estimates.append(est)
        except Exception:
            pass  # AVIF 可能不可用

        # 排序：按大小
        estimates.sort(key=lambda e: e.estimated_size)

        # 推荐逻辑
        recommended = _recommend_format(img_type, result.has_alpha, estimates)
        for est in estimates:
            if est.format_name == recommended:
                est.is_recommended = True

        result.estimates = estimates
        result.recommended_format = recommended
        result.recommended_reason = _get_recommendation_reason(img_type, recommended)

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _estimate_format(
    img: Image.Image,
    format_name: str,
    save_kwargs: dict,
) -> FormatEstimate:
    """预估指定格式的文件大小"""
    est = FormatEstimate()

    save_img = img
    if format_name == "JPEG" and save_img.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGB", save_img.size, (255, 255, 255))
        bg.paste(save_img, mask=save_img.split()[-1])
        save_img = bg
    elif format_name == "JPEG" and save_img.mode not in ("RGB", "L"):
        save_img = save_img.convert("RGB")

    buf = io.BytesIO()
    save_img.save(buf, format=format_name, **save_kwargs)
    est.estimated_size = buf.tell()
    est.estimated_size_human = _human_size(est.estimated_size)

    return est


def _recommend_format(
    img_type: str,
    has_alpha: bool,
    estimates: List[FormatEstimate],
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
        # 截图：优先 WebP 无损 > PNG
        for est in estimates:
            if "WebP (无损)" in est.format_name:
                return est.format_name
        for est in estimates:
            if est.format_name == "PNG":
                return est.format_name

    elif img_type == "graphic":
        # 图形：优先 PNG > WebP 无损
        if has_alpha:
            for est in estimates:
                if est.format_name == "PNG":
                    return est.format_name
        for est in estimates:
            if "WebP (无损)" in est.format_name:
                return est.format_name
        for est in estimates:
            if est.format_name == "PNG":
                return est.format_name

    # 默认：最小的
    if estimates:
        return estimates[0].format_name
    return "PNG"


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

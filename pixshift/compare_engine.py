"""
PixShift Compare Engine — 图片对比（SSIM / PSNR）

功能:
  - 计算 SSIM（结构相似性指数）
  - 计算 PSNR（峰值信噪比）
  - 计算 MSE（均方误差）
  - 生成对比报告
  - 无需 numpy/scipy，纯 Pillow 实现
"""

import math
import os
import time
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter, ImageStat

from .core.metadata import (
    convert_color_to_srgb,
    ensure_static_image,
    normalize_orientation,
    open_image,
)

MAX_COMPARISON_PIXELS = 4_000_000

# ============================================================
#  数据结构
# ============================================================


@dataclass
class CompareResult:
    """图片对比结果"""

    image_a: str = ""
    image_b: str = ""
    success: bool = False
    error: str = ""
    duration: float = 0.0

    # 尺寸信息
    size_a: tuple[int, int] = (0, 0)
    size_b: tuple[int, int] = (0, 0)
    comparison_size: tuple[int, int] = (0, 0)
    resized_for_comparison: bool = False
    sampled_for_comparison: bool = False
    sample_scale: float = 1.0
    filesize_a: int = 0
    filesize_b: int = 0

    # 质量指标
    mse: float = 0.0  # 均方误差 (越小越好，0=完全相同)
    psnr: float = 0.0  # 峰值信噪比 (越大越好，>40dB 几乎无损)
    ssim: float = 0.0  # 结构相似性 (0-1，1=完全相同)

    # 质量评估
    quality_rating: str = ""  # 优秀/良好/一般/较差
    quality_detail: str = ""


# ============================================================
#  SSIM 计算（纯 Pillow 实现）
# ============================================================


def _ssim_channels(image: Image.Image) -> tuple[Image.Image, ...]:
    """Return perceptual colour channels plus an independent alpha plane."""
    rgba = image.convert("RGBA")
    return (*rgba.convert("RGB").convert("YCbCr").split(), rgba.getchannel("A"))


def _compute_ssim(img_a: Image.Image, img_b: Image.Image) -> float:
    """
    计算 SSIM（结构相似性指数）

    简化版 SSIM，使用 Pillow 的统计功能。
    SSIM = (2*μa*μb + C1)(2*σab + C2) / ((μa² + μb² + C1)(σa² + σb² + C2))

    C1 = (K1*L)², C2 = (K2*L)²
    L = 255, K1 = 0.01, K2 = 0.03
    """
    L = 255.0
    C1 = (0.01 * L) ** 2
    C2 = (0.03 * L) ** 2

    def channel_ssim(a_channel: Image.Image, b_channel: Image.Image) -> float:
        # A blurred channel approximates the local mean used by windowed SSIM.
        radius = 11 // 2
        a_data = a_channel.tobytes()
        b_data = b_channel.tobytes()
        a_blur_data = a_channel.filter(ImageFilter.GaussianBlur(radius=radius)).tobytes()
        b_blur_data = b_channel.filter(ImageFilter.GaussianBlur(radius=radius)).tobytes()
        n = len(a_data)
        if n == 0:
            return 1.0
        mu_a = sum(a_blur_data) / n
        mu_b = sum(b_blur_data) / n
        sigma_a_sq = sum((value - mu_a) ** 2 for value in a_data) / n
        sigma_b_sq = sum((value - mu_b) ** 2 for value in b_data) / n
        sigma_ab = sum((a - mu_a) * (b - mu_b) for a, b in zip(a_data, b_data, strict=True)) / n
        numerator = (2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)
        denominator = (mu_a**2 + mu_b**2 + C1) * (sigma_a_sq + sigma_b_sq + C2)
        if denominator == 0:
            return 1.0
        return max(0.0, min(1.0, numerator / denominator))

    # Luminance-only SSIM misses equal-brightness colour swaps and alpha loss.
    # Raw RGB channel minima are also unstable near zero (red 255,0,0 versus
    # 255,1,0 looks far worse than it is). YCbCr gives chroma a meaningful
    # centred range; alpha remains independent. The worst semantic channel
    # prevents averaging away a material visibility or colour regression.
    channels_a = _ssim_channels(img_a)
    channels_b = _ssim_channels(img_b)
    scores = [
        channel_ssim(a_channel, b_channel)
        for a_channel, b_channel in zip(channels_a, channels_b, strict=True)
    ]
    return min(scores)


def _compute_ssim_blocks(img_a: Image.Image, img_b: Image.Image, block_size: int = 64) -> float:
    """
    分块计算 SSIM，更准确的局部结构相似性

    将图片分成 block_size x block_size 的块，分别计算 SSIM 后取平均
    """
    channels_a = _ssim_channels(img_a)
    channels_b = _ssim_channels(img_b)
    w, h = img_a.size
    channel_scores: list[float] = []

    L = 255.0
    C1 = (0.01 * L) ** 2
    C2 = (0.03 * L) ** 2

    for a_channel, b_channel in zip(channels_a, channels_b, strict=True):
        block_scores: list[float] = []
        for y in range(0, h - block_size + 1, block_size // 2):
            for x in range(0, w - block_size + 1, block_size // 2):
                box = (x, y, x + block_size, y + block_size)
                a_data = a_channel.crop(box).tobytes()
                b_data = b_channel.crop(box).tobytes()
                n = len(a_data)
                if n == 0:
                    continue
                mu_a = sum(a_data) / n
                mu_b = sum(b_data) / n
                sigma_a_sq = sum((a - mu_a) ** 2 for a in a_data) / n
                sigma_b_sq = sum((b - mu_b) ** 2 for b in b_data) / n
                sigma_ab = (
                    sum((a - mu_a) * (b - mu_b) for a, b in zip(a_data, b_data, strict=True)) / n
                )
                numerator = (2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)
                denominator = (mu_a**2 + mu_b**2 + C1) * (sigma_a_sq + sigma_b_sq + C2)
                if denominator > 0:
                    block_scores.append(numerator / denominator)
        if block_scores:
            channel_scores.append(sum(block_scores) / len(block_scores))

    if not channel_scores:
        return _compute_ssim(img_a, img_b)
    return max(0.0, min(1.0, min(channel_scores)))


# ============================================================
#  MSE / PSNR 计算
# ============================================================


def _compute_mse(img_a: Image.Image, img_b: Image.Image) -> float:
    """计算均方误差 (MSE)"""
    a_rgba = img_a.convert("RGBA")
    b_rgba = img_b.convert("RGBA")

    diff = ImageChops.difference(a_rgba, b_rgba)
    stat = ImageStat.Stat(diff)

    # 各通道的均方值
    mse_per_channel = [s**2 for s in stat.rms]
    return sum(mse_per_channel) / len(mse_per_channel)


def _compute_psnr(mse: float) -> float:
    """根据 MSE 计算 PSNR"""
    if mse == 0:
        return float("inf")
    max_pixel = 255.0
    return 10 * math.log10((max_pixel**2) / mse)


def compare_image_objects(
    image_a: Image.Image,
    image_b: Image.Image,
    *,
    use_blocks: bool = True,
    block_size: int = 64,
) -> tuple[float, float, float, bool, float]:
    """Compare two equally-sized decoded images with a bounded working set.

    Large images are deterministically downsampled to at most four megapixels.
    The caller receives the sampling flag and scale so an automation client can
    distinguish a bounded perceptual measurement from an exact pixel audit.
    """
    if image_a.size != image_b.size:
        raise ValueError("comparison_size_mismatch")
    pixels = image_a.width * image_a.height
    sampled = pixels > MAX_COMPARISON_PIXELS
    scale = 1.0
    if sampled:
        scale = math.sqrt(MAX_COMPARISON_PIXELS / pixels)
        size = (max(1, int(image_a.width * scale)), max(1, int(image_a.height * scale)))
        image_a = image_a.resize(size, Image.Resampling.LANCZOS)
        image_b = image_b.resize(size, Image.Resampling.LANCZOS)
    mse = _compute_mse(image_a, image_b)
    psnr = _compute_psnr(mse)
    if use_blocks and min(image_a.size) >= block_size * 2:
        ssim = _compute_ssim_blocks(image_a, image_b, block_size)
    else:
        ssim = _compute_ssim(image_a, image_b)
    return mse, psnr, ssim, sampled, scale


# ============================================================
#  核心对比函数
# ============================================================


def compare_images(
    image_a: str,
    image_b: str,
    use_blocks: bool = True,
    block_size: int = 64,
) -> CompareResult:
    """
    对比两张图片的质量差异

    Args:
        image_a: 原始图片路径
        image_b: 处理后的图片路径
        use_blocks: 是否使用分块 SSIM（更准确但更慢）
        block_size: 分块大小
    """
    result = CompareResult(image_a=image_a, image_b=image_b)
    start_time = time.time()

    try:
        if not os.path.exists(image_a):
            result.error = f"文件不存在: {image_a}"
            return result
        if not os.path.exists(image_b):
            result.error = f"文件不存在: {image_b}"
            return result

        result.filesize_a = os.path.getsize(image_a)
        result.filesize_b = os.path.getsize(image_b)

        img_a, result.size_a, sampled_a, scale_a = _load_comparison_image(image_a)
        img_b, result.size_b, sampled_b, scale_b = _load_comparison_image(image_b)

        # 如果尺寸不同，调整到相同大小
        if img_a.size != img_b.size:
            ratio_a = img_a.width / img_a.height
            ratio_b = img_b.width / img_b.height
            relative_ratio_difference = abs(ratio_a - ratio_b) / max(ratio_a, ratio_b)
            if relative_ratio_difference > 0.01:
                raise ValueError("aspect_ratio_mismatch")
            # 缩放到较小的尺寸
            target_w = min(img_a.width, img_b.width)
            target_h = min(img_a.height, img_b.height)
            img_a = img_a.resize((target_w, target_h), Image.Resampling.LANCZOS)
            img_b = img_b.resize((target_w, target_h), Image.Resampling.LANCZOS)
            result.resized_for_comparison = True
        result.comparison_size = img_a.size

        (
            result.mse,
            result.psnr,
            result.ssim,
            result.sampled_for_comparison,
            result.sample_scale,
        ) = compare_image_objects(
            img_a,
            img_b,
            use_blocks=use_blocks,
            block_size=block_size,
        )
        if sampled_a or sampled_b:
            result.sampled_for_comparison = True
            result.sample_scale = min(result.sample_scale, scale_a, scale_b)

        # 质量评估
        result.quality_rating, result.quality_detail = _rate_quality(
            result.ssim, result.psnr, result.mse
        )

        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _load_comparison_image(
    path: str,
) -> tuple[Image.Image, tuple[int, int], bool, float]:
    """Decode, orient, colour-normalise, and promptly bound one comparison input."""
    with open_image(path) as source:
        ensure_static_image(source)
        normalized = normalize_orientation(source)
        original_size = normalized.size
        pixels = normalized.width * normalized.height
        sampled = pixels > MAX_COMPARISON_PIXELS
        scale = 1.0
        if sampled:
            scale = math.sqrt(MAX_COMPARISON_PIXELS / pixels)
            normalized.thumbnail(
                (
                    max(1, int(normalized.width * scale)),
                    max(1, int(normalized.height * scale)),
                ),
                Image.Resampling.LANCZOS,
            )
        converted = convert_color_to_srgb(normalized)
        # Detach from lazy decoder state before closing the source. Only the
        # bounded image survives while the second input is decoded.
        return converted.copy(), original_size, sampled, scale


def _rate_quality(ssim: float, psnr: float, mse: float) -> tuple[str, str]:
    """评估质量等级"""
    if mse == 0:
        return "完美", "像素与透明度完全相同"
    elif ssim >= 0.95 and psnr >= 40:
        return "优秀", "极微小差异，肉眼几乎不可见"
    elif ssim >= 0.90 and psnr >= 35:
        return "良好", "轻微差异，日常使用完全可接受"
    elif ssim >= 0.80 and psnr >= 30:
        return "一般", "有一定差异，仔细看可以察觉"
    elif ssim >= 0.60:
        return "较差", "明显差异，质量有所下降"
    else:
        return "差", "严重质量损失，不建议使用"

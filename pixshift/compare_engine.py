"""
PixShift Compare Engine — 图片对比（SSIM / PSNR）

功能:
  - 计算 SSIM（结构相似性指数）
  - 计算 PSNR（峰值信噪比）
  - 计算 MSE（均方误差）
  - 生成对比报告
  - 无需 numpy/scipy，纯 Pillow 实现
"""

import os
import math
import time
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter, ImageStat

from .converter import _human_size


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
    size_a: Tuple[int, int] = (0, 0)
    size_b: Tuple[int, int] = (0, 0)
    filesize_a: int = 0
    filesize_b: int = 0

    # 质量指标
    mse: float = 0.0       # 均方误差 (越小越好，0=完全相同)
    psnr: float = 0.0      # 峰值信噪比 (越大越好，>40dB 几乎无损)
    ssim: float = 0.0      # 结构相似性 (0-1，1=完全相同)

    # 质量评估
    quality_rating: str = ""  # 优秀/良好/一般/较差
    quality_detail: str = ""


# ============================================================
#  SSIM 计算（纯 Pillow 实现）
# ============================================================

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

    # 转灰度
    a_gray = img_a.convert("L")
    b_gray = img_b.convert("L")

    # 使用高斯模糊模拟窗口
    window_size = 11
    a_blur = a_gray.filter(ImageFilter.GaussianBlur(radius=window_size // 2))
    b_blur = b_gray.filter(ImageFilter.GaussianBlur(radius=window_size // 2))

    # 获取像素数据
    a_data = list(a_gray.tobytes())
    b_data = list(b_gray.tobytes())
    a_blur_data = list(a_blur.tobytes())
    b_blur_data = list(b_blur.tobytes())

    n = len(a_data)
    if n == 0:
        return 1.0

    # 计算均值 (使用模糊后的值作为局部均值的近似)
    mu_a = sum(a_blur_data) / n
    mu_b = sum(b_blur_data) / n

    # 计算方差和协方差
    sigma_a_sq = sum((a - mu_a) ** 2 for a in a_data) / n
    sigma_b_sq = sum((b - mu_b) ** 2 for b in b_data) / n
    sigma_ab = sum((a - mu_a) * (b - mu_b) for a, b in zip(a_data, b_data)) / n

    # SSIM 公式
    numerator = (2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)
    denominator = (mu_a ** 2 + mu_b ** 2 + C1) * (sigma_a_sq + sigma_b_sq + C2)

    if denominator == 0:
        return 1.0

    ssim_val = numerator / denominator
    return max(0.0, min(1.0, ssim_val))


def _compute_ssim_blocks(img_a: Image.Image, img_b: Image.Image, block_size: int = 64) -> float:
    """
    分块计算 SSIM，更准确的局部结构相似性

    将图片分成 block_size x block_size 的块，分别计算 SSIM 后取平均
    """
    a_gray = img_a.convert("L")
    b_gray = img_b.convert("L")

    w, h = a_gray.size
    ssim_values = []

    L = 255.0
    C1 = (0.01 * L) ** 2
    C2 = (0.03 * L) ** 2

    for y in range(0, h - block_size + 1, block_size // 2):
        for x in range(0, w - block_size + 1, block_size // 2):
            box = (x, y, x + block_size, y + block_size)
            block_a = a_gray.crop(box)
            block_b = b_gray.crop(box)

            a_data = list(block_a.tobytes())
            b_data = list(block_b.tobytes())
            n = len(a_data)

            if n == 0:
                continue

            mu_a = sum(a_data) / n
            mu_b = sum(b_data) / n

            sigma_a_sq = sum((a - mu_a) ** 2 for a in a_data) / n
            sigma_b_sq = sum((b - mu_b) ** 2 for b in b_data) / n
            sigma_ab = sum((a - mu_a) * (b - mu_b) for a, b in zip(a_data, b_data)) / n

            num = (2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)
            den = (mu_a ** 2 + mu_b ** 2 + C1) * (sigma_a_sq + sigma_b_sq + C2)

            if den > 0:
                ssim_values.append(num / den)

    if not ssim_values:
        return _compute_ssim(img_a, img_b)

    return sum(ssim_values) / len(ssim_values)


# ============================================================
#  MSE / PSNR 计算
# ============================================================

def _compute_mse(img_a: Image.Image, img_b: Image.Image) -> float:
    """计算均方误差 (MSE)"""
    a_rgb = img_a.convert("RGB")
    b_rgb = img_b.convert("RGB")

    diff = ImageChops.difference(a_rgb, b_rgb)
    stat = ImageStat.Stat(diff)

    # 各通道的均方值
    mse_per_channel = [s ** 2 for s in stat.rms]
    return sum(mse_per_channel) / len(mse_per_channel)


def _compute_psnr(mse: float) -> float:
    """根据 MSE 计算 PSNR"""
    if mse == 0:
        return float("inf")
    max_pixel = 255.0
    return 10 * math.log10((max_pixel ** 2) / mse)


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

        img_a = Image.open(image_a)
        img_b = Image.open(image_b)

        result.size_a = img_a.size
        result.size_b = img_b.size

        # 如果尺寸不同，调整到相同大小
        if img_a.size != img_b.size:
            # 缩放到较小的尺寸
            target_w = min(img_a.width, img_b.width)
            target_h = min(img_a.height, img_b.height)
            img_a = img_a.resize((target_w, target_h), Image.LANCZOS)
            img_b = img_b.resize((target_w, target_h), Image.LANCZOS)

        # 计算 MSE
        result.mse = _compute_mse(img_a, img_b)

        # 计算 PSNR
        result.psnr = _compute_psnr(result.mse)

        # 计算 SSIM
        if use_blocks and min(img_a.size) >= block_size * 2:
            result.ssim = _compute_ssim_blocks(img_a, img_b, block_size)
        else:
            result.ssim = _compute_ssim(img_a, img_b)

        # 质量评估
        result.quality_rating, result.quality_detail = _rate_quality(
            result.ssim, result.psnr, result.mse
        )

        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _rate_quality(ssim: float, psnr: float, mse: float) -> Tuple[str, str]:
    """评估质量等级"""
    if ssim >= 0.99 or psnr == float("inf"):
        return "完美", "几乎无差异，视觉上完全相同"
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

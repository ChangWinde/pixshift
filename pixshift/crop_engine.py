"""
PixShift Crop Engine — 批量裁剪引擎

功能:
  - 按区域裁剪 --crop 100,100,800,600 (left,top,right,bottom)
  - 按比例裁剪 --aspect 16:9 / 1:1（居中裁剪）
  - 自动裁剪白边 --trim
  - 批量 + 并行处理
"""

import os
import time
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass, field

from PIL import Image, ImageChops

from .converter import SUPPORTED_INPUT_FORMATS, _human_size


# ============================================================
#  数据结构
# ============================================================

@dataclass
class CropResult:
    """单个文件的裁剪结果"""
    input_path: str = ""
    output_path: str = ""
    success: bool = False
    input_size: int = 0
    output_size: int = 0
    duration: float = 0.0
    error: str = ""
    original_size: Tuple[int, int] = (0, 0)
    cropped_size: Tuple[int, int] = (0, 0)
    crop_box: Tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class CropBatchResult:
    """批量裁剪汇总"""
    total: int = 0
    success: int = 0
    failed: int = 0
    total_input_size: int = 0
    total_output_size: int = 0
    total_duration: float = 0.0
    results: List[CropResult] = field(default_factory=list)


# ============================================================
#  裁剪模式解析
# ============================================================

def parse_crop_box(crop_str: str) -> Tuple[int, int, int, int]:
    """
    解析裁剪区域字符串

    格式: "left,top,right,bottom" 或 "left,top,width,height" (带 w 前缀)
    示例: "100,100,800,600" → (100, 100, 800, 600)
    """
    parts = [int(x.strip()) for x in crop_str.split(",")]
    if len(parts) != 4:
        raise ValueError(f"裁剪区域需要 4 个值 (left,top,right,bottom)，得到 {len(parts)} 个")
    return tuple(parts)


def parse_aspect_ratio(aspect_str: str) -> Tuple[int, int]:
    """
    解析宽高比字符串

    格式: "16:9", "1:1", "4:3", "3:2"
    """
    parts = aspect_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"宽高比格式错误: {aspect_str}，应为 W:H（如 16:9）")
    return (int(parts[0]), int(parts[1]))


# ============================================================
#  核心裁剪函数
# ============================================================

def crop_single(
    input_path: str,
    output_path: str,
    crop_box: Optional[str] = None,
    aspect: Optional[str] = None,
    trim: bool = False,
    trim_fuzz: int = 10,
    gravity: str = "center",
    overwrite: bool = False,
) -> CropResult:
    """
    裁剪单个图片

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        crop_box: 裁剪区域 "left,top,right,bottom"
        aspect: 宽高比 "16:9"
        trim: 自动裁剪白边
        trim_fuzz: 白边检测容差 (0-255)
        gravity: 裁剪重心 (center/top-left/top-right/bottom-left/bottom-right)
        overwrite: 是否覆盖
    """
    result = CropResult(input_path=input_path, output_path=output_path)
    start_time = time.time()

    try:
        if not os.path.exists(input_path):
            result.error = f"文件不存在: {input_path}"
            return result

        result.input_size = os.path.getsize(input_path)

        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        img = Image.open(input_path)
        result.original_size = img.size

        if crop_box:
            # 区域裁剪
            box = parse_crop_box(crop_box)
            # 确保不超出图片范围
            box = (
                max(0, box[0]),
                max(0, box[1]),
                min(img.width, box[2]),
                min(img.height, box[3]),
            )
            cropped = img.crop(box)
            result.crop_box = box

        elif aspect:
            # 比例裁剪（居中）
            ratio_w, ratio_h = parse_aspect_ratio(aspect)
            cropped, box = _crop_to_aspect(img, ratio_w, ratio_h, gravity)
            result.crop_box = box

        elif trim:
            # 自动裁剪白边
            cropped, box = _auto_trim(img, trim_fuzz)
            result.crop_box = box

        else:
            result.error = "请指定裁剪模式: --crop / --aspect / --trim"
            return result

        result.cropped_size = cropped.size

        # 保存
        _save_cropped(cropped, output_path, img)

        result.output_size = os.path.getsize(output_path)
        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _crop_to_aspect(
    img: Image.Image,
    ratio_w: int,
    ratio_h: int,
    gravity: str = "center",
) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """
    按宽高比居中裁剪

    保留尽可能大的区域
    """
    img_w, img_h = img.size
    target_ratio = ratio_w / ratio_h
    current_ratio = img_w / img_h

    if current_ratio > target_ratio:
        # 图片太宽，裁剪左右
        new_w = int(img_h * target_ratio)
        new_h = img_h
    else:
        # 图片太高，裁剪上下
        new_w = img_w
        new_h = int(img_w / target_ratio)

    # 根据重心计算偏移
    if "left" in gravity:
        x_offset = 0
    elif "right" in gravity:
        x_offset = img_w - new_w
    else:
        x_offset = (img_w - new_w) // 2

    if "top" in gravity:
        y_offset = 0
    elif "bottom" in gravity:
        y_offset = img_h - new_h
    else:
        y_offset = (img_h - new_h) // 2

    box = (x_offset, y_offset, x_offset + new_w, y_offset + new_h)
    return img.crop(box), box


def _auto_trim(
    img: Image.Image,
    fuzz: int = 10,
) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """
    自动裁剪白边/纯色边框

    使用图片四角的颜色作为背景色参考
    """
    if img.mode in ("RGBA", "LA"):
        # 有 Alpha 通道，检测透明区域
        bg = Image.new(img.mode, img.size, (0, 0, 0, 0))
    else:
        # 使用左上角像素作为背景色
        bg_color = img.getpixel((0, 0))
        bg = Image.new(img.mode, img.size, bg_color)

    diff = ImageChops.difference(img, bg)

    if diff.mode in ("RGBA",):
        # 转为灰度来找边界
        diff = diff.convert("L")
    elif diff.mode in ("RGB",):
        diff = diff.convert("L")

    # 应用容差
    if fuzz > 0:
        diff = diff.point(lambda x: 255 if x > fuzz else 0)

    bbox = diff.getbbox()

    if bbox is None:
        # 整张图都是背景色
        return img, (0, 0, img.width, img.height)

    # 添加少量边距
    padding = 2
    box = (
        max(0, bbox[0] - padding),
        max(0, bbox[1] - padding),
        min(img.width, bbox[2] + padding),
        min(img.height, bbox[3] + padding),
    )

    return img.crop(box), box


def _save_cropped(cropped: Image.Image, output_path: str, original: Image.Image):
    """保存裁剪后的图片，保持原格式和质量"""
    ext = Path(output_path).suffix.lower()

    save_kwargs = {}

    if ext in (".jpg", ".jpeg"):
        if cropped.mode in ("RGBA", "LA", "PA"):
            bg = Image.new("RGB", cropped.size, (255, 255, 255))
            bg.paste(cropped, mask=cropped.split()[-1])
            cropped = bg
        elif cropped.mode not in ("RGB", "L"):
            cropped = cropped.convert("RGB")
        save_kwargs = {"format": "JPEG", "quality": 95, "optimize": True}
    elif ext == ".png":
        save_kwargs = {"format": "PNG", "optimize": True}
    elif ext == ".webp":
        save_kwargs = {"format": "WEBP", "quality": 95}
    elif ext in (".tiff", ".tif"):
        save_kwargs = {"format": "TIFF", "compression": "tiff_lzw"}
    else:
        if original.format:
            save_kwargs = {"format": original.format}

    # 保留 EXIF 和 ICC
    try:
        exif_data = original.info.get("exif")
        if exif_data:
            save_kwargs["exif"] = exif_data
    except Exception:
        pass

    try:
        icc = original.info.get("icc_profile")
        if icc:
            save_kwargs["icc_profile"] = icc
    except Exception:
        pass

    cropped.save(output_path, **save_kwargs)


def collect_croppable_files(
    input_paths: List[str],
    recursive: bool = False,
) -> List[str]:
    """收集所有可裁剪的图片文件"""
    files = []
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file():
            if path.suffix.lower() in SUPPORTED_INPUT_FORMATS:
                files.append(str(path.resolve()))
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for item in sorted(path.glob(pattern)):
                if item.is_file() and item.suffix.lower() in SUPPORTED_INPUT_FORMATS:
                    files.append(str(item.resolve()))
    return sorted(set(files))

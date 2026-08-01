"""
PixShift Watermark Engine — 批量水印引擎

功能:
  - 文字水印（自定义字体/大小/颜色/透明度/位置/旋转）
  - 图片水印（Logo 叠加，自定义大小/位置/透明度）
  - 平铺水印（全图重复水印）
  - 批量 + 并行处理
"""

import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .converter import SUPPORTED_INPUT_FORMATS
from .core.files import atomic_output_path
from .core.metadata import normalize_orientation, normalized_exif_bytes

# ============================================================
#  数据结构
# ============================================================


@dataclass
class WatermarkResult:
    """单个文件的水印结果"""

    input_path: str = ""
    output_path: str = ""
    success: bool = False
    input_size: int = 0
    output_size: int = 0
    duration: float = 0.0
    error: str = ""


@dataclass
class WatermarkBatchResult:
    """批量水印汇总"""

    total: int = 0
    success: int = 0
    failed: int = 0
    total_input_size: int = 0
    total_output_size: int = 0
    total_duration: float = 0.0
    results: list[WatermarkResult] = field(default_factory=list)


# ============================================================
#  水印位置
# ============================================================

POSITION_MAP = {
    "top-left": (0.02, 0.02),
    "top-center": (0.5, 0.02),
    "top-right": (0.98, 0.02),
    "center-left": (0.02, 0.5),
    "center": (0.5, 0.5),
    "center-right": (0.98, 0.5),
    "bottom-left": (0.02, 0.98),
    "bottom-center": (0.5, 0.98),
    "bottom-right": (0.98, 0.98),
}


# ============================================================
#  文字水印
# ============================================================


def _get_font(
    font_path: str | None, font_size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """获取字体对象"""
    if font_path and os.path.exists(font_path):
        return ImageFont.truetype(font_path, font_size)

    # 尝试系统字体
    system_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\msyh.ttc",
    ]

    for sf in system_fonts:
        if os.path.exists(sf):
            try:
                return ImageFont.truetype(sf, font_size)
            except Exception:
                continue

    # 回退到默认字体
    try:
        return ImageFont.truetype("DejaVuSans.ttf", font_size)
    except Exception:
        return ImageFont.load_default()


def _parse_color(color_str: str) -> tuple[int, int, int, int]:
    """
    解析颜色字符串

    支持: "255,255,255", "#FFFFFF", "#FFFFFFAA", "white", "red"
    返回: (R, G, B, A)
    """
    color_str = color_str.strip()

    # 命名颜色
    named_colors = {
        "white": (255, 255, 255, 255),
        "black": (0, 0, 0, 255),
        "red": (255, 0, 0, 255),
        "green": (0, 255, 0, 255),
        "blue": (0, 0, 255, 255),
        "yellow": (255, 255, 0, 255),
        "gray": (128, 128, 128, 255),
        "grey": (128, 128, 128, 255),
    }
    if color_str.lower() in named_colors:
        return named_colors[color_str.lower()]

    # Hex 格式
    if color_str.startswith("#"):
        hex_str = color_str[1:]
        if len(hex_str) == 6:
            r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
            return (r, g, b, 255)
        elif len(hex_str) == 8:
            r, g, b, a = (
                int(hex_str[0:2], 16),
                int(hex_str[2:4], 16),
                int(hex_str[4:6], 16),
                int(hex_str[6:8], 16),
            )
            return (r, g, b, a)

    # R,G,B 或 R,G,B,A 格式
    parts = [int(x.strip()) for x in color_str.split(",")]
    if len(parts) == 3:
        result = (parts[0], parts[1], parts[2], 255)
    elif len(parts) == 4:
        result = (parts[0], parts[1], parts[2], parts[3])
    else:
        raise ValueError("颜色必须是名称、#RRGGBB、#RRGGBBAA 或 R,G,B[,A]")

    if any(not 0 <= channel <= 255 for channel in result):
        raise ValueError("颜色通道必须在 0 到 255 之间")
    return result


def add_text_watermark(
    input_path: str,
    output_path: str,
    text: str,
    font_path: str | None = None,
    font_size: int = 36,
    color: str = "255,255,255",
    opacity: int = 128,
    position: str = "bottom-right",
    rotation: int = 0,
    tile: bool = False,
    tile_spacing: int = 100,
    margin: int = 20,
    overwrite: bool = False,
) -> WatermarkResult:
    """
    添加文字水印

    Args:
        input_path: 输入图片路径
        output_path: 输出图片路径
        text: 水印文字
        font_path: 字体文件路径（可选）
        font_size: 字体大小
        color: 颜色 (R,G,B 或 #HEX 或 颜色名)
        opacity: 透明度 (0-255, 0=完全透明, 255=不透明)
        position: 位置 (top-left/center/bottom-right 等)
        rotation: 旋转角度
        tile: 是否平铺水印
        tile_spacing: 平铺间距
        margin: 边距（像素）
        overwrite: 是否覆盖
    """
    result = WatermarkResult(input_path=input_path, output_path=output_path)
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

        if not 0 <= opacity <= 255:
            raise ValueError("透明度必须在 0 到 255 之间")
        if font_size <= 0 or tile_spacing < 0 or margin < 0:
            raise ValueError("字体大小必须为正数，间距和边距不能为负数")

        with Image.open(input_path) as source:
            original_format = source.format
            original = normalize_orientation(source)
            img = original.convert("RGBA")
            font = _get_font(font_path, font_size)
            r, g, b, _ = _parse_color(color)
            fill_color = (r, g, b, opacity)

            if tile:
                watermark_layer = _create_tiled_text_layer(
                    img.size, text, font, fill_color, rotation, tile_spacing
                )
            else:
                watermark_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(watermark_layer)

                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = max(1, int(bbox[2] - bbox[0]))
                text_h = max(1, int(bbox[3] - bbox[1]))

                x, y = _calc_position(img.size, (text_w, text_h), position, margin)

                if rotation != 0:
                    txt_img = Image.new("RGBA", (text_w + 20, text_h + 20), (0, 0, 0, 0))
                    txt_draw = ImageDraw.Draw(txt_img)
                    txt_draw.text((10, 10), text, font=font, fill=fill_color)
                    txt_img = txt_img.rotate(
                        rotation, expand=True, resample=Image.Resampling.BICUBIC
                    )
                    watermark_layer.paste(txt_img, (int(x), int(y)), txt_img)
                else:
                    draw.text((x, y), text, font=font, fill=fill_color)

            result_img = Image.alpha_composite(img, watermark_layer)
            _save_watermarked(result_img, output_path, original, original_format)

        result.output_size = os.path.getsize(output_path)
        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _create_tiled_text_layer(
    img_size: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill_color: tuple[int, int, int, int],
    rotation: int,
    spacing: int,
) -> Image.Image:
    """创建平铺文字水印层"""
    w, h = img_size

    # 创建单个水印文字
    tmp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = tmp_draw.textbbox((0, 0), text, font=font)
    text_w = max(1, int(bbox[2] - bbox[0]) + 20)
    text_h = max(1, int(bbox[3] - bbox[1]) + 20)

    txt_img = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    txt_draw = ImageDraw.Draw(txt_img)
    txt_draw.text((10, 10), text, font=font, fill=fill_color)

    if rotation != 0:
        txt_img = txt_img.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)

    tile_w, tile_h = txt_img.size

    # 创建平铺层（扩大范围以覆盖旋转后的区域）
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    step_x = tile_w + spacing
    step_y = tile_h + spacing

    for y_pos in range(-tile_h, h + tile_h, step_y):
        for x_pos in range(-tile_w, w + tile_w, step_x):
            with suppress(Exception):
                layer.paste(txt_img, (x_pos, y_pos), txt_img)

    return layer


# ============================================================
#  图片水印
# ============================================================


def add_image_watermark(
    input_path: str,
    output_path: str,
    watermark_path: str,
    scale: float = 0.2,
    opacity: int = 128,
    position: str = "bottom-right",
    margin: int = 20,
    tile: bool = False,
    tile_spacing: int = 100,
    overwrite: bool = False,
) -> WatermarkResult:
    """
    添加图片水印（Logo 叠加）

    Args:
        input_path: 输入图片路径
        output_path: 输出图片路径
        watermark_path: 水印图片路径
        scale: 水印相对于原图的缩放比例 (0.0-1.0)
        opacity: 透明度 (0-255)
        position: 位置
        margin: 边距
        tile: 是否平铺
        tile_spacing: 平铺间距
        overwrite: 是否覆盖
    """
    result = WatermarkResult(input_path=input_path, output_path=output_path)
    start_time = time.time()

    try:
        if not os.path.exists(input_path):
            result.error = f"文件不存在: {input_path}"
            return result
        if not os.path.exists(watermark_path):
            result.error = f"水印图片不存在: {watermark_path}"
            return result

        result.input_size = os.path.getsize(input_path)

        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if not 0 < scale <= 1:
            raise ValueError("水印缩放比例必须大于 0 且不超过 1")
        if not 0 <= opacity <= 255:
            raise ValueError("透明度必须在 0 到 255 之间")
        if tile_spacing < 0 or margin < 0:
            raise ValueError("间距和边距不能为负数")

        with Image.open(input_path) as source, Image.open(watermark_path) as wm_source:
            original_format = source.format
            original = normalize_orientation(source)
            img = original.convert("RGBA")
            wm = normalize_orientation(wm_source).convert("RGBA")

            target_w = max(1, int(img.width * scale))
            ratio = target_w / wm.width
            target_h = max(1, int(wm.height * ratio))
            wm = wm.resize((target_w, target_h), Image.Resampling.LANCZOS)

            if opacity < 255:
                alpha = wm.split()[3]
                alpha = alpha.point(lambda p: int(p * opacity / 255))
                wm.putalpha(alpha)

            if tile:
                layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                step_x = target_w + tile_spacing
                step_y = target_h + tile_spacing
                for y_pos in range(0, img.height, step_y):
                    for x_pos in range(0, img.width, step_x):
                        layer.paste(wm, (x_pos, y_pos), wm)
                result_img = Image.alpha_composite(img, layer)
            else:
                x, y = _calc_position(img.size, wm.size, position, margin)
                layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
                layer.paste(wm, (int(x), int(y)), wm)
                result_img = Image.alpha_composite(img, layer)

            _save_watermarked(result_img, output_path, original, original_format)

        result.output_size = os.path.getsize(output_path)
        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


# ============================================================
#  工具函数
# ============================================================


def _calc_position(
    img_size: tuple[int, int],
    wm_size: tuple[int, int],
    position: str,
    margin: int,
) -> tuple[int, int]:
    """计算水印位置"""
    img_w, img_h = img_size
    wm_w, wm_h = wm_size

    pos = POSITION_MAP.get(position, POSITION_MAP["bottom-right"])
    px, py = pos

    x = px * img_w - wm_w * px
    y = py * img_h - wm_h * py

    # 应用边距
    if px < 0.5:
        x = max(margin, x)
    elif px > 0.5:
        x = min(img_w - wm_w - margin, x)

    if py < 0.5:
        y = max(margin, y)
    elif py > 0.5:
        y = min(img_h - wm_h - margin, y)

    return int(x), int(y)


def _save_watermarked(
    result_img: Image.Image,
    output_path: str,
    original: Image.Image,
    original_format: str | None,
) -> None:
    """保存水印后的图片，保持原格式"""
    ext = Path(output_path).suffix.lower()
    no_alpha = {".jpg", ".jpeg", ".bmp", ".pdf"}

    if ext in no_alpha:
        bg = Image.new("RGB", result_img.size, (255, 255, 255))
        bg.paste(result_img, mask=result_img.split()[3])
        result_img = bg

    save_kwargs: dict[str, Any] = {}
    if ext in (".jpg", ".jpeg"):
        save_kwargs = {"format": "JPEG", "quality": 95, "optimize": True}
    elif ext == ".png":
        save_kwargs = {"format": "PNG", "optimize": True}
    elif ext == ".webp":
        save_kwargs = {"format": "WEBP", "quality": 95}
    elif original_format:
        save_kwargs = {"format": original_format}
    else:
        save_kwargs = {"format": "PNG"}

    exif_data = normalized_exif_bytes(original)
    if exif_data and ext in {".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        save_kwargs["exif"] = exif_data
    icc_profile = original.info.get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile

    with atomic_output_path(output_path) as temporary:
        result_img.save(temporary, **save_kwargs)


def collect_watermark_files(
    input_paths: list[str],
    recursive: bool = False,
) -> list[str]:
    """收集所有可添加水印的图片文件"""
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

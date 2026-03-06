"""
PixShift Watermark Engine — 批量水印引擎

功能:
  - 文字水印（自定义字体/大小/颜色/透明度/位置/旋转）
  - 图片水印（Logo 叠加，自定义大小/位置/透明度）
  - 平铺水印（全图重复水印）
  - 批量 + 并行处理
"""

import os
import math
import time
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from .converter import SUPPORTED_INPUT_FORMATS, _human_size


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
    results: List[WatermarkResult] = field(default_factory=list)


# ============================================================
#  水印位置
# ============================================================

POSITION_MAP = {
    "top-left":      (0.02, 0.02),
    "top-center":    (0.5, 0.02),
    "top-right":     (0.98, 0.02),
    "center-left":   (0.02, 0.5),
    "center":        (0.5, 0.5),
    "center-right":  (0.98, 0.5),
    "bottom-left":   (0.02, 0.98),
    "bottom-center": (0.5, 0.98),
    "bottom-right":  (0.98, 0.98),
}


# ============================================================
#  文字水印
# ============================================================

def _get_font(font_path: Optional[str], font_size: int) -> ImageFont.FreeTypeFont:
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


def _parse_color(color_str: str) -> Tuple[int, int, int, int]:
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
            r, g, b, a = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16), int(hex_str[6:8], 16)
            return (r, g, b, a)

    # R,G,B 或 R,G,B,A 格式
    parts = [int(x.strip()) for x in color_str.split(",")]
    if len(parts) == 3:
        return (parts[0], parts[1], parts[2], 255)
    elif len(parts) == 4:
        return (parts[0], parts[1], parts[2], parts[3])

    return (255, 255, 255, 255)


def add_text_watermark(
    input_path: str,
    output_path: str,
    text: str,
    font_path: Optional[str] = None,
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

        img = Image.open(input_path).convert("RGBA")
        font = _get_font(font_path, font_size)
        r, g, b, _ = _parse_color(color)
        fill_color = (r, g, b, opacity)

        if tile:
            # 平铺水印
            watermark_layer = _create_tiled_text_layer(
                img.size, text, font, fill_color, rotation, tile_spacing
            )
        else:
            # 单个水印
            watermark_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(watermark_layer)

            # 获取文字尺寸
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            # 计算位置
            x, y = _calc_position(
                img.size, (text_w, text_h), position, margin
            )

            if rotation != 0:
                # 创建旋转文字
                txt_img = Image.new("RGBA", (text_w + 20, text_h + 20), (0, 0, 0, 0))
                txt_draw = ImageDraw.Draw(txt_img)
                txt_draw.text((10, 10), text, font=font, fill=fill_color)
                txt_img = txt_img.rotate(rotation, expand=True, resample=Image.BICUBIC)
                watermark_layer.paste(txt_img, (int(x), int(y)), txt_img)
            else:
                draw.text((x, y), text, font=font, fill=fill_color)

        # 合成
        result_img = Image.alpha_composite(img, watermark_layer)

        # 保存（保持原格式）
        _save_watermarked(result_img, output_path, input_path)

        result.output_size = os.path.getsize(output_path)
        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _create_tiled_text_layer(
    img_size: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill_color: Tuple[int, int, int, int],
    rotation: int,
    spacing: int,
) -> Image.Image:
    """创建平铺文字水印层"""
    w, h = img_size

    # 创建单个水印文字
    tmp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = tmp_draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0] + 20
    text_h = bbox[3] - bbox[1] + 20

    txt_img = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    txt_draw = ImageDraw.Draw(txt_img)
    txt_draw.text((10, 10), text, font=font, fill=fill_color)

    if rotation != 0:
        txt_img = txt_img.rotate(rotation, expand=True, resample=Image.BICUBIC)

    tile_w, tile_h = txt_img.size

    # 创建平铺层（扩大范围以覆盖旋转后的区域）
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    step_x = tile_w + spacing
    step_y = tile_h + spacing

    for y_pos in range(-tile_h, h + tile_h, step_y):
        for x_pos in range(-tile_w, w + tile_w, step_x):
            try:
                layer.paste(txt_img, (x_pos, y_pos), txt_img)
            except Exception:
                pass

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

        img = Image.open(input_path).convert("RGBA")
        wm = Image.open(watermark_path).convert("RGBA")

        # 缩放水印
        target_w = max(1, int(img.width * scale))
        ratio = target_w / wm.width
        target_h = max(1, int(wm.height * ratio))
        wm = wm.resize((target_w, target_h), Image.LANCZOS)

        # 调整透明度
        if opacity < 255:
            alpha = wm.split()[3]
            alpha = alpha.point(lambda p: int(p * opacity / 255))
            wm.putalpha(alpha)

        if tile:
            # 平铺
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            step_x = target_w + tile_spacing
            step_y = target_h + tile_spacing
            for y_pos in range(0, img.height, step_y):
                for x_pos in range(0, img.width, step_x):
                    layer.paste(wm, (x_pos, y_pos), wm)
            result_img = Image.alpha_composite(img, layer)
        else:
            # 单个水印
            x, y = _calc_position(
                img.size, wm.size, position, margin
            )
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            layer.paste(wm, (int(x), int(y)), wm)
            result_img = Image.alpha_composite(img, layer)

        _save_watermarked(result_img, output_path, input_path)

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
    img_size: Tuple[int, int],
    wm_size: Tuple[int, int],
    position: str,
    margin: int,
) -> Tuple[int, int]:
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


def _save_watermarked(result_img: Image.Image, output_path: str, input_path: str):
    """保存水印后的图片，保持原格式"""
    ext = Path(output_path).suffix.lower()
    no_alpha = {".jpg", ".jpeg", ".bmp", ".pdf", ".ico"}

    if ext in no_alpha:
        # 不支持 Alpha 的格式，合成到白色背景
        bg = Image.new("RGB", result_img.size, (255, 255, 255))
        bg.paste(result_img, mask=result_img.split()[3])
        result_img = bg

        if ext in (".jpg", ".jpeg"):
            result_img.save(output_path, format="JPEG", quality=95, optimize=True)
        else:
            result_img.save(output_path)
    elif ext == ".png":
        result_img.save(output_path, format="PNG", optimize=True)
    elif ext == ".webp":
        result_img.save(output_path, format="WEBP", quality=95)
    else:
        # 尝试保持原格式
        try:
            orig_format = Image.open(input_path).format
            if orig_format:
                result_img.save(output_path, format=orig_format)
            else:
                result_img.save(output_path)
        except Exception:
            result_img.save(output_path, format="PNG")


def collect_watermark_files(
    input_paths: List[str],
    recursive: bool = False,
) -> List[str]:
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

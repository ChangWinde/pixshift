"""
PixShift Montage Engine — 拼图/网格拼接

功能:
  - 多图拼接成一张大图（网格布局）
  - 自定义列数、间距、背景色
  - 自动调整图片大小以适应网格
  - 支持标签/标题
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .converter import SUPPORTED_INPUT_FORMATS
from .core.errors import AnimatedInputNotSupportedError
from .core.files import SelectionFilters, atomic_output_path, collect_supported_files
from .core.metadata import (
    convert_color_to_rgb,
    ensure_pixel_count_within_limit,
    ensure_static_image,
    image_has_transparency,
    normalize_orientation,
    open_image,
)

# ============================================================
#  数据结构
# ============================================================


@dataclass
class MontageResult:
    """拼图结果"""

    output_path: str = ""
    success: bool = False
    output_size: int = 0
    duration: float = 0.0
    error: str = ""
    total_images: int = 0
    grid_size: tuple[int, int] = (0, 0)  # (cols, rows)
    canvas_size: tuple[int, int] = (0, 0)  # (width, height)
    skipped_invalid: int = 0


# ============================================================
#  核心拼图函数
# ============================================================


def create_montage(
    input_paths: list[str],
    output_path: str,
    cols: int = 3,
    gap: int = 10,
    cell_width: int | None = None,
    cell_height: int | None = None,
    background: str = "255,255,255",
    border: int = 0,
    border_color: str = "200,200,200",
    label: bool = False,
    label_size: int = 14,
    auto_size: bool = True,
    overwrite: bool = False,
) -> MontageResult:
    """
    创建网格拼图

    Args:
        input_paths: 输入图片路径列表
        output_path: 输出文件路径
        cols: 列数
        gap: 图片间距（像素）
        cell_width: 单元格宽度（不指定则自动计算）
        cell_height: 单元格高度（不指定则自动计算）
        background: 背景色 (R,G,B)
        border: 边框宽度
        border_color: 边框颜色
        label: 是否显示文件名标签
        label_size: 标签字体大小
        auto_size: 自动调整图片大小
        overwrite: 是否覆盖
    """
    result = MontageResult(output_path=output_path)
    start_time = time.time()

    try:
        if not input_paths:
            result.error = "没有输入图片"
            return result

        output_extension = Path(output_path).suffix.lower()
        if output_extension not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError(f"unsupported_output_format: {output_extension or '<none>'}")

        if cols <= 0 or gap < 0 or border < 0:
            raise ValueError("列数必须为正数，间距和边框不能为负数")
        if cell_width is not None and cell_width <= 0:
            raise ValueError("单元格宽度必须为正数")
        if cell_height is not None and cell_height <= 0:
            raise ValueError("单元格高度必须为正数")

        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # First pass keeps only dimensions and paths. Full decoded images are
        # intentionally not retained together, which bounds peak memory for batches.
        image_specs: list[tuple[str, int, int]] = []
        for p in input_paths:
            try:
                with open_image(p) as source:
                    ensure_static_image(source)
                    normalized = normalize_orientation(source)
                    image_specs.append((p, normalized.width, normalized.height))
            except AnimatedInputNotSupportedError:
                raise
            except Exception:
                result.skipped_invalid += 1
                continue

        if not image_specs:
            result.error = "没有可用的图片"
            return result

        result.total_images = len(image_specs)

        # 计算网格
        rows = (len(image_specs) + cols - 1) // cols
        result.grid_size = (cols, rows)

        # 计算单元格大小
        if cell_width is None or cell_height is None:
            if auto_size:
                # 自动计算：取所有图片的中位数大小
                widths = sorted(spec[1] for spec in image_specs)
                heights = sorted(spec[2] for spec in image_specs)
                median_w = widths[len(widths) // 2]
                median_h = heights[len(heights) // 2]

                if cell_width is None:
                    cell_width = min(median_w, 800)
                if cell_height is None:
                    cell_height = min(median_h, 600)
            else:
                # 使用最大尺寸
                cell_width = cell_width or max(spec[1] for spec in image_specs)
                cell_height = cell_height or max(spec[2] for spec in image_specs)

        # 标签高度
        label_height = (label_size + 10) if label else 0

        # 计算画布大小
        canvas_w = cols * cell_width + (cols + 1) * gap
        canvas_h = rows * (cell_height + label_height) + (rows + 1) * gap
        result.canvas_size = (canvas_w, canvas_h)
        ensure_pixel_count_within_limit(canvas_w * canvas_h)

        # 解析颜色
        bg_color = _parse_rgb(background)
        bd_color = _parse_rgb(border_color)

        # 创建画布
        canvas = Image.new("RGB", (canvas_w, canvas_h), bg_color)
        draw = ImageDraw.Draw(canvas)

        # 获取字体
        font = None
        if label:
            font = _get_simple_font(label_size)

        # 放置图片
        for idx, (image_path, _, _) in enumerate(image_specs):
            row = idx // cols
            col = idx % cols

            x = gap + col * (cell_width + gap)
            y = gap + row * (cell_height + label_height + gap)

            # 缩放图片以适应单元格
            with open_image(image_path) as source:
                ensure_static_image(source)
                img = convert_color_to_rgb(normalize_orientation(source))
                resized = _fit_image(img, cell_width, cell_height)

            # 居中放置
            offset_x = x + (cell_width - resized.width) // 2
            offset_y = y + (cell_height - resized.height) // 2

            # 边框
            if border > 0:
                draw.rectangle(
                    [
                        offset_x - border,
                        offset_y - border,
                        offset_x + resized.width + border - 1,
                        offset_y + resized.height + border - 1,
                    ],
                    outline=bd_color,
                    width=border,
                )

            # 粘贴图片
            if image_has_transparency(resized):
                rgba = resized.convert("RGBA")
                canvas.paste(rgba, (offset_x, offset_y), rgba)
            else:
                canvas.paste(resized, (offset_x, offset_y))

            # 标签
            if label and font:
                label_x = x + cell_width // 2
                label_y = y + cell_height + 2
                text = Path(image_path).name
                # 截断过长的文件名
                if len(text) > 30:
                    text = text[:27] + "..."
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                draw.text(
                    (label_x - text_w // 2, label_y),
                    text,
                    fill=(80, 80, 80),
                    font=font,
                )

        # 保存
        ext = output_extension
        with atomic_output_path(output_path, overwrite=overwrite) as temporary:
            if ext in (".jpg", ".jpeg"):
                canvas.save(temporary, format="JPEG", quality=95, optimize=True)
            elif ext == ".webp":
                canvas.save(temporary, format="WEBP", quality=95)
            else:
                canvas.save(temporary, format="PNG", optimize=True)

        result.output_size = os.path.getsize(output_path)
        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


# ============================================================
#  工具函数
# ============================================================


def _fit_image(
    img: Image.Image,
    max_width: int,
    max_height: int,
) -> Image.Image:
    """缩放图片以适应指定大小（保持比例）"""
    img_copy = img.copy()
    img_copy.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return img_copy


def _parse_rgb(color_str: str) -> tuple[int, int, int]:
    """解析 RGB 颜色字符串"""
    if color_str.startswith("#"):
        hex_str = color_str[1:]
        if len(hex_str) != 6:
            raise ValueError("十六进制颜色必须使用 #RRGGBB")
        result = (
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16),
        )
    else:
        parts = [int(x.strip()) for x in color_str.split(",")]
        if len(parts) != 3:
            raise ValueError("颜色必须使用 R,G,B 或 #RRGGBB")
        result = (parts[0], parts[1], parts[2])

    if any(not 0 <= channel <= 255 for channel in result):
        raise ValueError("颜色通道必须在 0 到 255 之间")
    return result


def _get_simple_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """获取简单字体"""
    system_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for sf in system_fonts:
        if os.path.exists(sf):
            try:
                return ImageFont.truetype(sf, size)
            except Exception:
                continue
    return ImageFont.load_default()


def collect_montage_files(
    input_paths: list[str],
    recursive: bool = False,
    selection: SelectionFilters | None = None,
) -> list[str]:
    """收集所有可拼接的图片文件"""
    return collect_supported_files(
        input_paths, SUPPORTED_INPUT_FORMATS, recursive=recursive, selection=selection
    )

"""
PixShift PDF Engine — 基于 PyMuPDF 的 PDF 处理引擎

功能:
  1. merge    — 多图合并成 PDF
  2. extract  — PDF 拆分为图片
  3. compress — PDF 压缩优化
  4. concat   — 多个 PDF 合并
  5. info     — PDF 信息查看
"""

import os
import io
import time
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass, field

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

from PIL import Image


# ============================================================
#  常量定义
# ============================================================

# 支持的图片输入格式（用于 merge）
PDF_IMAGE_FORMATS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".avif", ".ppm", ".tga", ".ico",
}

# 标准纸张尺寸 (宽, 高) 单位: 点 (1点 = 1/72英寸)
PAGE_SIZES = {
    "a4":       (595.28, 841.89),
    "a3":       (841.89, 1190.55),
    "a5":       (419.53, 595.28),
    "letter":   (612, 792),
    "legal":    (612, 1008),
    "b5":       (498.90, 708.66),
    "fit":      None,  # 自适应图片大小
}

# PDF 压缩预设
# 核心思路:
#   - lossless: 不重压缩图片，只做 PDF 结构优化（去重、清理）
#   - light:    轻度压缩，图片质量 95，几乎无损
#   - medium:   中度压缩，图片质量 80，肉眼难辨
#   - heavy:    重度压缩，图片质量 60，明显缩小
#   - extreme:  极限压缩，图片质量 40 + 缩小分辨率，最小体积
PDF_COMPRESS_PRESETS = {
    "lossless": {
        "description": "无损 — 仅优化 PDF 结构，不重压缩图片",
        "image_quality": None,   # None = 不重压缩图片
        "max_image_dpi": None,   # None = 不缩小分辨率
        "deflate": True,         # 对流数据使用 deflate 压缩
        "clean": True,           # 清理无用对象
        "garbage": 4,            # 垃圾回收等级 (0-4, 4最彻底)
    },
    "light": {
        "description": "轻度 — 图片质量95，几乎无视觉损失",
        "image_quality": 95,
        "max_image_dpi": None,
        "deflate": True,
        "clean": True,
        "garbage": 4,
    },
    "medium": {
        "description": "中度 — 图片质量80，体积明显减小",
        "image_quality": 80,
        "max_image_dpi": 200,
        "deflate": True,
        "clean": True,
        "garbage": 4,
    },
    "heavy": {
        "description": "重度 — 图片质量60，大幅缩小体积",
        "image_quality": 60,
        "max_image_dpi": 150,
        "deflate": True,
        "clean": True,
        "garbage": 4,
    },
    "extreme": {
        "description": "极限 — 图片质量40+降分辨率，最小体积",
        "image_quality": 40,
        "max_image_dpi": 96,
        "deflate": True,
        "clean": True,
        "garbage": 4,
    },
}


# ============================================================
#  数据结构
# ============================================================

@dataclass
class PDFResult:
    """PDF 操作结果"""
    success: bool = False
    output_path: str = ""
    input_size: int = 0
    output_size: int = 0
    duration: float = 0.0
    page_count: int = 0
    error: str = ""
    details: Dict = field(default_factory=dict)


@dataclass
class PDFInfo:
    """PDF 文件信息"""
    path: str = ""
    size_bytes: int = 0
    page_count: int = 0
    title: str = ""
    author: str = ""
    subject: str = ""
    creator: str = ""
    producer: str = ""
    creation_date: str = ""
    mod_date: str = ""
    encrypted: bool = False
    pdf_version: str = ""
    pages: List[Dict] = field(default_factory=list)
    image_count: int = 0
    total_image_size: int = 0


# ============================================================
#  工具函数
# ============================================================

def _human_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的大小"""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _check_pymupdf():
    """检查 PyMuPDF 是否可用"""
    if not PYMUPDF_AVAILABLE:
        raise ImportError(
            "PDF 功能需要 PyMuPDF。请安装: pip install PyMuPDF"
        )


def _collect_images(input_paths: List[str], recursive: bool = False) -> List[str]:
    """收集所有图片文件（用于 merge）"""
    files = []
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file():
            if path.suffix.lower() in PDF_IMAGE_FORMATS:
                files.append(str(path.resolve()))
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for item in sorted(path.glob(pattern)):
                if item.is_file() and item.suffix.lower() in PDF_IMAGE_FORMATS:
                    files.append(str(item.resolve()))
    return files


def _collect_pdfs(input_paths: List[str], recursive: bool = False) -> List[str]:
    """收集所有 PDF 文件（用于 concat）"""
    files = []
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file():
            if path.suffix.lower() == ".pdf":
                files.append(str(path.resolve()))
        elif path.is_dir():
            pattern = "**/*.pdf" if recursive else "*.pdf"
            for item in sorted(path.glob(pattern)):
                if item.is_file():
                    files.append(str(item.resolve()))
    return files


def _image_to_bytes(image_path: str, quality: int = 95) -> bytes:
    """将图片转为 JPEG/PNG bytes，供 PyMuPDF 插入"""
    img = Image.open(image_path)

    # 自动旋转
    try:
        from PIL import ExifTags
        exif = img.getexif()
        for key, val in ExifTags.TAGS.items():
            if val == "Orientation":
                orientation = exif.get(key)
                if orientation:
                    rotations = {
                        3: Image.ROTATE_180,
                        6: Image.ROTATE_270,
                        8: Image.ROTATE_90,
                    }
                    if orientation in rotations:
                        img = img.transpose(rotations[orientation])
                break
    except Exception:
        pass

    # 有透明通道用 PNG，否则用 JPEG
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "PA"):
        img.save(buf, format="PNG")
    else:
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=quality)

    return buf.getvalue(), img.size


# ============================================================
#  1. merge — 多图合并成 PDF
# ============================================================

def pdf_merge_images(
    image_paths: List[str],
    output_path: str,
    page_size: str = "a4",
    quality: int = 95,
    margin: int = 0,
    landscape: bool = False,
    overwrite: bool = False,
) -> PDFResult:
    """
    将多张图片合并成一个 PDF 文件

    Args:
        image_paths: 图片文件路径列表
        output_path: 输出 PDF 路径
        page_size: 页面大小 (a4/a3/a5/letter/legal/b5/fit)
        quality: 图片嵌入质量 (1-100)
        margin: 页边距 (点, 1点=1/72英寸)
        landscape: 是否横向
        overwrite: 是否覆盖已存在文件
    """
    _check_pymupdf()
    result = PDFResult(output_path=output_path)
    start_time = time.time()

    try:
        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        # 计算总输入大小
        result.input_size = sum(os.path.getsize(p) for p in image_paths)

        doc = fitz.open()

        for img_path in image_paths:
            img_data, (img_w, img_h) = _image_to_bytes(img_path, quality)

            # 确定页面大小
            if page_size.lower() == "fit":
                # 自适应：页面大小 = 图片大小 (像素→点, 假设 72 DPI)
                pw, ph = float(img_w), float(img_h)
            else:
                size = PAGE_SIZES.get(page_size.lower(), PAGE_SIZES["a4"])
                pw, ph = size

            # 横向
            if landscape:
                pw, ph = ph, pw

            # 创建页面
            page = doc.new_page(width=pw, height=ph)

            # 计算图片在页面中的位置（居中，保持比例）
            avail_w = pw - 2 * margin
            avail_h = ph - 2 * margin

            scale_w = avail_w / img_w
            scale_h = avail_h / img_h
            scale = min(scale_w, scale_h)

            draw_w = img_w * scale
            draw_h = img_h * scale

            x0 = margin + (avail_w - draw_w) / 2
            y0 = margin + (avail_h - draw_h) / 2

            rect = fitz.Rect(x0, y0, x0 + draw_w, y0 + draw_h)
            page.insert_image(rect, stream=img_data)

        # 保存
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        doc.save(output_path, deflate=True, garbage=4)
        doc.close()

        result.output_size = os.path.getsize(output_path)
        result.page_count = len(image_paths)
        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


# ============================================================
#  2. extract — PDF 拆分为图片
# ============================================================

def pdf_extract_pages(
    pdf_path: str,
    output_dir: str,
    output_format: str = "png",
    dpi: int = 300,
    pages: Optional[str] = None,
    prefix: str = "",
    overwrite: bool = False,
) -> PDFResult:
    """
    将 PDF 每页导出为图片

    Args:
        pdf_path: 输入 PDF 路径
        output_dir: 输出目录
        output_format: 输出图片格式 (png/jpg/webp/tiff)
        dpi: 渲染 DPI (越高越清晰，默认 300)
        pages: 指定页码，如 "1-5,8,10-12"，None 表示全部
        prefix: 输出文件名前缀
        overwrite: 是否覆盖
    """
    _check_pymupdf()
    result = PDFResult(output_path=output_dir)
    start_time = time.time()

    try:
        result.input_size = os.path.getsize(pdf_path)
        doc = fitz.open(pdf_path)
        total_pages = doc.page_count

        # 解析页码范围
        page_indices = _parse_page_range(pages, total_pages)

        os.makedirs(output_dir, exist_ok=True)

        fmt = output_format.lower().lstrip(".")
        if fmt in ("jpg", "jpeg"):
            pix_format = "jpeg"
            ext = ".jpg"
        elif fmt == "webp":
            # PyMuPDF 不直接支持 webp，先导出 PNG 再用 Pillow 转
            pix_format = "png"
            ext = ".webp"
        elif fmt == "tiff":
            pix_format = "png"
            ext = ".tiff"
        else:
            pix_format = "png"
            ext = ".png"

        output_total_size = 0
        extracted_count = 0

        for page_idx in page_indices:
            page = doc[page_idx]
            page_num = page_idx + 1

            out_name = f"{prefix}page_{page_num:04d}{ext}"
            out_path = os.path.join(output_dir, out_name)

            if os.path.exists(out_path) and not overwrite:
                continue

            # 渲染页面
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            if fmt in ("webp", "tiff"):
                # 通过 Pillow 转换
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                if fmt == "webp":
                    img.save(out_path, format="WEBP", quality=95)
                else:
                    img.save(out_path, format="TIFF")
            elif pix_format == "jpeg":
                pix.save(out_path, output=pix_format)
            else:
                pix.save(out_path)

            output_total_size += os.path.getsize(out_path)
            extracted_count += 1

        doc.close()

        result.output_size = output_total_size
        result.page_count = extracted_count
        result.success = True
        result.details["total_pages"] = total_pages
        result.details["extracted_pages"] = extracted_count

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _parse_page_range(pages_str: Optional[str], total: int) -> List[int]:
    """
    解析页码范围字符串

    支持格式: "1-5,8,10-12" → [0,1,2,3,4,7,9,10,11]
    None → 全部页码
    """
    if pages_str is None:
        return list(range(total))

    indices = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start = max(1, int(start.strip()))
            end = min(total, int(end.strip()))
            for i in range(start, end + 1):
                indices.add(i - 1)
        else:
            idx = int(part.strip()) - 1
            if 0 <= idx < total:
                indices.add(idx)

    return sorted(indices)


# ============================================================
#  3. compress — PDF 压缩优化
# ============================================================

def pdf_compress(
    input_path: str,
    output_path: str,
    preset: str = "medium",
    image_quality: Optional[int] = None,
    max_image_dpi: Optional[int] = None,
    overwrite: bool = False,
) -> PDFResult:
    """
    压缩优化 PDF 文件

    压缩策略:
      - lossless:  仅结构优化，不碰图片
      - light:     图片质量95，几乎无损
      - medium:    图片质量80，体积明显减小
      - heavy:     图片质量60，大幅缩小
      - extreme:   图片质量40+降分辨率，最小体积

    也可以通过 image_quality / max_image_dpi 自定义覆盖预设值。

    Args:
        input_path: 输入 PDF 路径
        output_path: 输出 PDF 路径
        preset: 压缩预设 (lossless/light/medium/heavy/extreme)
        image_quality: 自定义图片质量 (1-100)，覆盖预设
        max_image_dpi: 自定义最大 DPI，覆盖预设
        overwrite: 是否覆盖
    """
    _check_pymupdf()
    result = PDFResult(output_path=output_path)
    start_time = time.time()

    try:
        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        result.input_size = os.path.getsize(input_path)

        # 获取压缩参数
        config = PDF_COMPRESS_PRESETS.get(preset, PDF_COMPRESS_PRESETS["medium"]).copy()

        # 自定义参数覆盖预设
        if image_quality is not None:
            config["image_quality"] = image_quality
        if max_image_dpi is not None:
            config["max_image_dpi"] = max_image_dpi

        img_quality = config.get("image_quality")
        max_dpi = config.get("max_image_dpi")
        garbage_level = config.get("garbage", 4)
        do_deflate = config.get("deflate", True)
        do_clean = config.get("clean", True)

        doc = fitz.open(input_path)
        result.page_count = doc.page_count

        # 保存优化后的 PDF
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        save_opts = {
            "garbage": garbage_level,
            "deflate": do_deflate,
            "clean": do_clean,
        }

        if img_quality is not None:
            # 有损压缩：重压缩图片 + 结构优化
            stats = _compress_rebuild(doc, output_path, img_quality, max_dpi, save_opts)
        else:
            # 无损压缩：仅结构优化（去重、清理、deflate）
            doc.save(output_path, **save_opts)
            stats = {"images_processed": 0, "images_skipped": 0, "images_replaced": 0}

        doc.close()

        result.output_size = os.path.getsize(output_path)
        result.success = True
        result.details["images_processed"] = stats["images_processed"]
        result.details["images_skipped"] = stats["images_skipped"]
        result.details["images_replaced"] = stats["images_replaced"]
        result.details["preset"] = preset

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _compress_rebuild(
    doc: "fitz.Document",
    output_path: str,
    image_quality: int,
    max_dpi: Optional[int],
    save_opts: dict,
) -> Dict:
    """
    通过重建方式压缩 PDF：
    遍历每页，提取所有图片并用指定质量重新编码，然后替换。
    最后用优化参数保存。

    使用 xref 去重，避免同一张图片被多次处理。

    Returns:
        统计信息字典: images_processed, images_skipped, images_replaced
    """
    import logging

    # 抑制 MuPDF 的非关键警告
    logging.getLogger("fitz").setLevel(logging.ERROR)

    # 统计计数
    images_processed = 0
    images_skipped = 0
    images_replaced = 0

    # 收集所有唯一的图片 xref，避免重复处理
    processed_xrefs = set()

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        image_list = page.get_images(full=True)

        for img_info in image_list:
            xref = img_info[0]

            # 跳过已处理的图片（同一图片可能在多页引用）
            if xref in processed_xrefs:
                continue
            processed_xrefs.add(xref)
            images_processed += 1

            try:
                base_image = doc.extract_image(xref)
                if not base_image or not base_image.get("image"):
                    images_skipped += 1
                    continue

                img_bytes = base_image["image"]
                img_width = base_image.get("width", 0)
                img_height = base_image.get("height", 0)

                pil_img = Image.open(io.BytesIO(img_bytes))

                # 降低分辨率
                if max_dpi and img_width > 0 and img_height > 0:
                    try:
                        img_rects = page.get_image_rects(xref)
                        if img_rects:
                            display_rect = img_rects[0]
                            display_w_inch = display_rect.width / 72.0
                            display_h_inch = display_rect.height / 72.0
                            if display_w_inch > 0 and display_h_inch > 0:
                                current_dpi = max(
                                    img_width / display_w_inch,
                                    img_height / display_h_inch,
                                )
                                if current_dpi > max_dpi:
                                    scale = max_dpi / current_dpi
                                    new_w = max(1, int(img_width * scale))
                                    new_h = max(1, int(img_height * scale))
                                    pil_img = pil_img.resize(
                                        (new_w, new_h), Image.LANCZOS
                                    )
                    except Exception:
                        pass

                # 重新编码
                buf = io.BytesIO()
                if pil_img.mode in ("RGBA", "LA", "PA"):
                    pil_img.save(buf, format="PNG", optimize=True)
                else:
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    pil_img.save(
                        buf, format="JPEG",
                        quality=image_quality,
                        optimize=True,
                    )

                new_bytes = buf.getvalue()

                # 替换图片（只有新图更小时才替换）
                if len(new_bytes) < len(img_bytes):
                    page.replace_image(xref, stream=new_bytes)
                    images_replaced += 1
                else:
                    images_skipped += 1

            except Exception:
                images_skipped += 1
                continue

        # 清理页面内容流
        page.clean_contents()

    doc.save(output_path, **save_opts)

    return {
        "images_processed": images_processed,
        "images_skipped": images_skipped,
        "images_replaced": images_replaced,
    }


# ============================================================
#  4. concat — 多个 PDF 合并
# ============================================================

def pdf_concat(
    pdf_paths: List[str],
    output_path: str,
    overwrite: bool = False,
) -> PDFResult:
    """
    将多个 PDF 文件合并成一个

    Args:
        pdf_paths: PDF 文件路径列表
        output_path: 输出 PDF 路径
        overwrite: 是否覆盖
    """
    _check_pymupdf()
    result = PDFResult(output_path=output_path)
    start_time = time.time()

    try:
        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        result.input_size = sum(os.path.getsize(p) for p in pdf_paths)

        merged = fitz.open()
        total_pages = 0

        for pdf_path in pdf_paths:
            src = fitz.open(pdf_path)
            merged.insert_pdf(src)
            total_pages += src.page_count
            src.close()

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        merged.save(output_path, deflate=True, garbage=4)
        merged.close()

        result.output_size = os.path.getsize(output_path)
        result.page_count = total_pages
        result.success = True
        result.details["file_count"] = len(pdf_paths)

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


# ============================================================
#  5. info — PDF 信息查看
# ============================================================

def pdf_get_info(pdf_path: str) -> PDFInfo:
    """
    获取 PDF 文件的详细信息

    Args:
        pdf_path: PDF 文件路径
    """
    _check_pymupdf()
    info = PDFInfo(path=pdf_path)

    try:
        info.size_bytes = os.path.getsize(pdf_path)
        doc = fitz.open(pdf_path)

        info.page_count = doc.page_count
        info.encrypted = doc.is_encrypted

        # 元数据
        meta = doc.metadata or {}
        info.title = meta.get("title", "") or ""
        info.author = meta.get("author", "") or ""
        info.subject = meta.get("subject", "") or ""
        info.creator = meta.get("creator", "") or ""
        info.producer = meta.get("producer", "") or ""
        info.creation_date = meta.get("creationDate", "") or ""
        info.mod_date = meta.get("modDate", "") or ""

        # PDF 版本
        # PyMuPDF 中没有直接的 version_string，用文件头读取
        try:
            with open(pdf_path, "rb") as f:
                header = f.read(20).decode("latin-1", errors="ignore")
                if header.startswith("%PDF-"):
                    info.pdf_version = header[5:8]
        except Exception:
            pass

        # 逐页信息
        total_images = 0
        for page_idx in range(doc.page_count):
            page = doc[page_idx]
            page_info = {
                "number": page_idx + 1,
                "width": round(page.rect.width, 1),
                "height": round(page.rect.height, 1),
                "width_mm": round(page.rect.width / 72 * 25.4, 1),
                "height_mm": round(page.rect.height / 72 * 25.4, 1),
                "rotation": page.rotation,
                "image_count": len(page.get_images(full=True)),
            }
            total_images += page_info["image_count"]
            info.pages.append(page_info)

        info.image_count = total_images

        doc.close()

    except Exception as e:
        info.title = f"错误: {e}"

    return info

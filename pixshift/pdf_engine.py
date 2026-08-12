"""
PixShift PDF Engine — 基于 PyMuPDF 的 PDF 处理引擎

功能:
  1. merge    — 多图合并成 PDF
  2. extract  — PDF 拆分为图片
  3. compress — PDF 压缩优化
  4. concat   — 多个 PDF 合并
  5. info     — PDF 信息查看
"""

import importlib.util
import io
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .core.defaults import DEFAULT_PDF_EXTRACT_DPI, DEFAULT_PDF_MERGE_MARGIN
from .core.files import atomic_output_path, safe_output_path
from .core.metadata import ensure_static_image, image_has_transparency, normalize_orientation

# PyMuPDF is heavy (~34ms import, ~36MB RSS) and only the pdf.* commands need
# it. Detect availability cheaply with find_spec and defer the real import to
# _check_pymupdf(), so convert/compress/agent commands don't pay for it.
PYMUPDF_AVAILABLE = importlib.util.find_spec("pymupdf") is not None
fitz: Any = None

# ============================================================
#  常量定义
# ============================================================

# 支持的图片输入格式（用于 merge）
PDF_IMAGE_FORMATS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".tiff",
    ".tif",
    ".webp",
    ".heic",
    ".heif",
    ".avif",
    ".ppm",
    ".tga",
    ".ico",
}

# 标准纸张尺寸 (宽, 高) 单位: 点 (1点 = 1/72英寸)
PAGE_SIZES: dict[str, tuple[float, float] | None] = {
    "a4": (595.28, 841.89),
    "a3": (841.89, 1190.55),
    "a5": (419.53, 595.28),
    "letter": (612, 792),
    "legal": (612, 1008),
    "b5": (498.90, 708.66),
    "fit": None,  # 自适应图片大小
}

# PDF 压缩预设
# 核心思路:
#   - lossless: 不重压缩图片，只做 PDF 结构优化（去重、清理）
#   - light:    轻度压缩，图片质量 95，几乎无损
#   - medium:   中度压缩，图片质量 80，肉眼难辨
#   - heavy:    重度压缩，图片质量 60，明显缩小
#   - extreme:  极限压缩，图片质量 40 + 缩小分辨率，最小体积
PDF_COMPRESS_PRESETS: dict[str, dict[str, Any]] = {
    "lossless": {
        "description": "无损 — 仅优化 PDF 结构，不重压缩图片",
        "image_quality": None,  # None = 不重压缩图片
        "max_image_dpi": None,  # None = 不缩小分辨率
        "deflate": True,  # 对流数据使用 deflate 压缩
        "clean": True,  # 清理无用对象
        "garbage": 4,  # 垃圾回收等级 (0-4, 4最彻底)
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
    details: dict = field(default_factory=dict)


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
    pages: list[dict] = field(default_factory=list)
    image_count: int = 0
    total_image_size: int = 0
    error: str = ""


# ============================================================
#  工具函数
# ============================================================


def _human_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的大小"""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _check_pymupdf() -> None:
    """确保 PyMuPDF 可用并已完成惰性导入。"""
    global fitz
    if fitz is not None:
        return
    try:
        import pymupdf as _pymupdf
    except ImportError as error:
        raise ImportError("PDF 功能需要 PyMuPDF。请安装: pip install PyMuPDF") from error
    fitz = _pymupdf


def _open_pdf(path: str) -> Any:
    """打开待处理的 PDF，对需要口令的加密文件给出清晰错误而非生涩崩溃。

    ``needs_pass`` 为 True 时页面内容被锁，后续 merge/split/extract/compress
    会以底层异常中止；此处提前失败并返回稳定错误码。
    """
    _check_pymupdf()
    doc = fitz.open(path)
    if doc.needs_pass:
        doc.close()
        raise ValueError("pdf_password_required")
    return doc


def _collect_images(input_paths: list[str], recursive: bool = False) -> list[str]:
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
    return list(dict.fromkeys(files))


def _collect_pdfs(input_paths: list[str], recursive: bool = False) -> list[str]:
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
    return list(dict.fromkeys(files))


# JPEG 段过滤：保留 SOI/JFIF(APP0)/Adobe(APP14) 与编码数据，丢弃携带
# EXIF/GPS/XMP/ICC/注释的段。熵编码数据零改动 => 像素无损。
_JPEG_DROPPED_MARKERS = set(range(0xE1, 0xEE)) | {0xEF, 0xFE}  # APP1-13, APP15, COM


def _strip_jpeg_metadata(data: bytes) -> bytes | None:
    """Drop metadata segments from a JPEG byte stream without re-encoding.

    Returns ``None`` when the stream does not parse as a well-formed JPEG,
    in which case the caller must fall back to the decode/re-encode path.
    """
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return None
    kept = [b"\xff\xd8"]
    offset = 2
    total = len(data)
    while offset < total:
        if data[offset] != 0xFF:
            return None
        marker = data[offset + 1] if offset + 1 < total else None
        if marker is None:
            return None
        if marker == 0xDA:
            # Start-of-scan: entropy-coded data follows; copy the rest as-is.
            kept.append(data[offset:])
            return b"".join(kept)
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            kept.append(data[offset : offset + 2])
            offset += 2
            continue
        if offset + 4 > total:
            return None
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if length < 2 or offset + 2 + length > total:
            return None
        segment_end = offset + 2 + length
        if marker not in _JPEG_DROPPED_MARKERS:
            kept.append(data[offset:segment_end])
        offset = segment_end
    return None


def _spliceable_jpeg(image_path: str, quality: int) -> tuple[bytes, tuple[int, int]] | None:
    """Return metadata-stripped original JPEG bytes when no transform is needed.

    Re-encoding an already-encoded JPEG at q95 costs a full decode/encode per
    page (the dominant cost of ``pdf merge``) and loses a generation for no
    size benefit. Splicing is only valid when nothing about the pixels must
    change: baseline RGB/grayscale, no EXIF orientation to apply, and the
    caller did not ask for recompression (quality below the default 95).
    """
    if quality < 95:
        return None
    try:
        with Image.open(image_path) as probe:
            if probe.format != "JPEG" or probe.mode not in ("RGB", "L"):
                return None
            if probe.getexif().get(0x0112, 1) != 1:  # orientation must be neutral
                return None
            size = probe.size
    except Exception:
        return None
    data = Path(image_path).read_bytes()
    stripped = _strip_jpeg_metadata(data)
    if stripped is None:
        return None
    return stripped, size


def _image_to_bytes(image_path: str, quality: int = 95) -> tuple[bytes, tuple[int, int]]:
    """将图片转为 JPEG/PNG bytes，供 PyMuPDF 插入"""
    spliced = _spliceable_jpeg(image_path, quality)
    if spliced is not None:
        return spliced

    with Image.open(image_path) as source:
        ensure_static_image(source)
        img = normalize_orientation(source).copy()

    # 有透明通道用 PNG，否则用 JPEG
    buf = io.BytesIO()
    if image_has_transparency(img):
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
    image_paths: list[str],
    output_path: str,
    page_size: str = "a4",
    quality: int = 95,
    margin: int = DEFAULT_PDF_MERGE_MARGIN,
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
        normalized_page_size = page_size.lower()
        if not image_paths:
            raise ValueError("no_input_images")
        if normalized_page_size not in PAGE_SIZES:
            raise ValueError(f"unsupported_page_size:{page_size}")
        if not 1 <= quality <= 100:
            raise ValueError("quality_must_be_between_1_and_100")
        if margin < 0:
            raise ValueError("margin_must_not_be_negative")
        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        # 计算总输入大小
        result.input_size = sum(os.path.getsize(p) for p in image_paths)
        with fitz.open() as doc:
            for img_path in image_paths:
                img_data, (img_w, img_h) = _image_to_bytes(img_path, quality)

                # 确定页面大小
                if normalized_page_size == "fit":
                    # 自适应页面使用图片尺寸，按 72 DPI 将像素换算为点。
                    pw, ph = float(img_w), float(img_h)
                else:
                    size = PAGE_SIZES[normalized_page_size]
                    if size is None:
                        raise ValueError(f"无效页面尺寸: {page_size}")
                    pw, ph = size

                # 横向
                if landscape:
                    pw, ph = ph, pw

                # 创建页面
                page = doc.new_page(width=pw, height=ph)

                # 计算图片在页面中的位置（居中，保持比例）
                avail_w = pw - 2 * margin
                avail_h = ph - 2 * margin
                if avail_w <= 0 or avail_h <= 0:
                    raise ValueError("margin_too_large_for_page")

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
            with atomic_output_path(output_path) as temporary:
                doc.save(temporary, deflate=True, garbage=4)

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
    dpi: int = DEFAULT_PDF_EXTRACT_DPI,
    pages: str | None = None,
    prefix: str = "",
    overwrite: bool = False,
) -> PDFResult:
    """
    将 PDF 每页导出为图片

    Args:
        pdf_path: 输入 PDF 路径
        output_dir: 输出目录
        output_format: 输出图片格式 (png/jpg/webp/tiff)
        dpi: 渲染 DPI (越高越清晰，默认 150)
        pages: 指定页码，如 "1-5,8,10-12"，None 表示全部
        prefix: 输出文件名前缀
        overwrite: 是否覆盖
    """
    _check_pymupdf()
    result = PDFResult(output_path=output_dir)
    start_time = time.time()

    try:
        fmt = output_format.lower().lstrip(".")
        if fmt not in {"png", "jpg", "jpeg", "webp", "tiff"}:
            raise ValueError(f"unsupported_output_format:{output_format}")
        if not 72 <= dpi <= 1200:
            raise ValueError("dpi_must_be_between_72_and_1200")
        result.input_size = os.path.getsize(pdf_path)
        doc = _open_pdf(pdf_path)
        total_pages = doc.page_count

        # 解析页码范围
        page_indices = _parse_page_range(pages, total_pages)

        os.makedirs(output_dir, exist_ok=True)

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
        skipped_existing = 0

        for page_idx in page_indices:
            page = doc[page_idx]
            page_num = page_idx + 1

            out_name = f"{prefix}page_{page_num:04d}{ext}"
            out_path = safe_output_path(output_dir, out_name)

            if os.path.exists(out_path) and not overwrite:
                skipped_existing += 1
                continue

            # 渲染页面
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            with atomic_output_path(out_path) as temporary:
                if fmt in ("webp", "tiff"):
                    # 通过 Pillow 转换
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    if fmt == "webp":
                        img.save(temporary, format="WEBP", quality=95)
                    else:
                        img.save(temporary, format="TIFF")
                elif pix_format == "jpeg":
                    pix.save(temporary, output=pix_format)
                else:
                    pix.save(temporary)

            output_total_size += os.path.getsize(out_path)
            extracted_count += 1

        doc.close()

        result.output_size = output_total_size
        result.page_count = extracted_count
        result.success = True
        result.details["total_pages"] = total_pages
        result.details["requested_pages"] = len(page_indices)
        result.details["extracted_pages"] = extracted_count
        result.details["skipped_existing"] = skipped_existing

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def pdf_split(
    pdf_path: str,
    output_dir: str,
    pages: str | None = None,
    single: bool = False,
    overwrite: bool = False,
) -> PDFResult:
    """Split a PDF into per-page documents or one sub-range document.

    Args:
        pdf_path: Input PDF path.
        output_dir: Destination directory for the split documents.
        pages: Page selection such as "1-5,8"; None selects every page.
        single: Write one document containing the selected pages instead of
            one document per page.
        overwrite: Replace existing outputs instead of skipping them.
    """
    _check_pymupdf()
    result = PDFResult(output_path=output_dir)
    start_time = time.time()

    try:
        result.input_size = os.path.getsize(pdf_path)
        stem = Path(pdf_path).stem
        doc = _open_pdf(pdf_path)
        total_pages = doc.page_count
        page_indices = _parse_page_range(pages, total_pages)

        os.makedirs(output_dir, exist_ok=True)

        written = 0
        skipped_existing = 0
        output_total_size = 0

        if single:
            spec = (pages or f"1-{total_pages}").replace(",", "_").replace(" ", "")
            out_path = safe_output_path(output_dir, f"{stem}_pages_{spec}.pdf")
            if os.path.exists(out_path) and not overwrite:
                skipped_existing += 1
            else:
                new_doc = fitz.open()
                for page_idx in page_indices:
                    new_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
                with atomic_output_path(out_path) as temporary:
                    new_doc.save(temporary)
                new_doc.close()
                output_total_size += os.path.getsize(out_path)
                written += 1
        else:
            for page_idx in page_indices:
                out_path = safe_output_path(output_dir, f"{stem}_page_{page_idx + 1:04d}.pdf")
                if os.path.exists(out_path) and not overwrite:
                    skipped_existing += 1
                    continue
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
                with atomic_output_path(out_path) as temporary:
                    new_doc.save(temporary)
                new_doc.close()
                output_total_size += os.path.getsize(out_path)
                written += 1

        doc.close()
        result.output_size = output_total_size
        result.page_count = len(page_indices)
        result.success = True
        result.details["total_pages"] = total_pages
        result.details["requested_pages"] = len(page_indices)
        result.details["written_files"] = written
        result.details["skipped_existing"] = skipped_existing

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _parse_page_range(pages_str: str | None, total: int) -> list[int]:
    """
    解析页码范围字符串

    格式 "1-5,8,10-12" 解析为 [0,1,2,3,4,7,9,10,11]。
    None 表示全部页码。
    """
    if pages_str is None:
        return list(range(total))

    if total <= 0 or not pages_str.strip():
        raise ValueError("invalid_page_range")

    indices = set()
    try:
        for part in pages_str.split(","):
            part = part.strip()
            if not part:
                raise ValueError
            if "-" in part:
                if part.count("-") != 1:
                    raise ValueError
                start_text, end_text = part.split("-", 1)
                start = int(start_text.strip())
                end = int(end_text.strip())
                if start < 1 or end > total or start > end:
                    raise ValueError
                for page_number in range(start, end + 1):
                    indices.add(page_number - 1)
            else:
                page_number = int(part)
                if not 1 <= page_number <= total:
                    raise ValueError
                indices.add(page_number - 1)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid_page_range") from error

    return sorted(indices)


# ============================================================
#  3. compress — PDF 压缩优化
# ============================================================


def pdf_compress(
    input_path: str,
    output_path: str,
    preset: str = "medium",
    image_quality: int | None = None,
    max_image_dpi: int | None = None,
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
        normalized_preset = preset.lower()
        if normalized_preset not in PDF_COMPRESS_PRESETS:
            raise ValueError(f"unsupported_pdf_compress_preset:{preset}")
        if image_quality is not None and not 1 <= image_quality <= 100:
            raise ValueError("image_quality_must_be_between_1_and_100")
        if max_image_dpi is not None and not 72 <= max_image_dpi <= 1200:
            raise ValueError("max_image_dpi_must_be_between_72_and_1200")
        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        result.input_size = os.path.getsize(input_path)

        # 获取压缩参数
        config = PDF_COMPRESS_PRESETS[normalized_preset].copy()

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

        doc = _open_pdf(input_path)
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
            with atomic_output_path(output_path) as temporary:
                stats = _compress_rebuild(doc, temporary, img_quality, max_dpi, save_opts)
        else:
            # 无损压缩：仅结构优化（去重、清理、deflate）
            with atomic_output_path(output_path) as temporary:
                doc.save(temporary, **save_opts)
            stats = {"images_processed": 0, "images_skipped": 0, "images_replaced": 0}

        doc.close()

        result.output_size = os.path.getsize(output_path)
        result.success = True
        result.details["images_processed"] = stats["images_processed"]
        result.details["images_skipped"] = stats["images_skipped"]
        result.details["images_replaced"] = stats["images_replaced"]
        result.details["preset"] = normalized_preset

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _compress_rebuild(
    doc: "fitz.Document",
    output_path: str,
    image_quality: int,
    max_dpi: int | None,
    save_opts: dict,
) -> dict:
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

                # 透明度存于独立的 SMask xref，extract_image 不含它；若在此重编码
                # 并 replace_image，透明通道会被静默丢弃导致视觉损坏。带 SMask 的
                # 图像一律跳过（保留原样），不做压缩。
                if base_image.get("smask", 0):
                    images_skipped += 1
                    continue

                img_bytes = base_image["image"]
                img_width = base_image.get("width", 0)
                img_height = base_image.get("height", 0)

                pil_img: Image.Image = Image.open(io.BytesIO(img_bytes))

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
                                        (new_w, new_h), Image.Resampling.LANCZOS
                                    )
                    except Exception:
                        pass

                # 重新编码
                buf = io.BytesIO()
                if image_has_transparency(pil_img):
                    pil_img.save(buf, format="PNG", optimize=True)
                else:
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    pil_img.save(
                        buf,
                        format="JPEG",
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
    pdf_paths: list[str],
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
        if len(pdf_paths) < 2:
            raise ValueError("need_at_least_two")
        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        result.input_size = sum(os.path.getsize(p) for p in pdf_paths)

        merged = fitz.open()
        total_pages = 0

        for pdf_path in pdf_paths:
            src = _open_pdf(pdf_path)
            merged.insert_pdf(src)
            total_pages += src.page_count
            src.close()

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with atomic_output_path(output_path) as temporary:
            merged.save(temporary, deflate=True, garbage=4)
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
        info.error = str(e)

    return info

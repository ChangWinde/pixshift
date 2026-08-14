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
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .core.defaults import DEFAULT_PDF_EXTRACT_DPI, DEFAULT_PDF_MERGE_MARGIN
from .core.errors import OperationPolicyError
from .core.files import atomic_output_path, safe_output_path, validate_aggregate_output_path
from .core.metadata import (
    convert_color_to_srgb,
    ensure_pixel_count_within_limit,
    ensure_static_image,
    image_has_transparency,
    normalize_orientation,
    open_image,
)

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


class PDFPageRangeError(ValueError):
    """A malformed or out-of-bounds PDF page selection."""

    code = "invalid_page_range"


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
                if (
                    not item.is_symlink()
                    and item.is_file()
                    and item.suffix.lower() in PDF_IMAGE_FORMATS
                ):
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
                if not item.is_symlink() and item.is_file():
                    files.append(str(item.resolve()))
    return list(dict.fromkeys(files))


# JPEG 段过滤：保留 SOI/JFIF(APP0)、功能性 ICC(APP2)、Adobe(APP14)
# 与编码数据，丢弃 EXIF/GPS/XMP/注释。熵编码数据零改动 => 像素无损。
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
            # Baseline JPEGs have one entropy-coded scan. Walk it to the exact
            # EOI instead of copying the tail blindly: comments, APP metadata,
            # or arbitrary bytes are legal after SOS/EOI and would otherwise
            # defeat the privacy guarantee of this fast path. Streams with
            # multiple scans or uncommon in-scan markers take the safe
            # decode/re-encode fallback.
            if offset + 4 > total:
                return None
            length = int.from_bytes(data[offset + 2 : offset + 4], "big")
            scan_start = offset + 2 + length
            if length < 2 or scan_start > total:
                return None
            cursor = scan_start
            while cursor < total:
                if data[cursor] != 0xFF:
                    cursor += 1
                    continue
                if cursor + 1 >= total:
                    return None
                scan_marker = data[cursor + 1]
                if scan_marker == 0x00:  # stuffed entropy byte
                    cursor += 2
                    continue
                if scan_marker == 0xFF:  # marker fill byte
                    cursor += 1
                    continue
                if 0xD0 <= scan_marker <= 0xD7:  # restart marker
                    cursor += 2
                    continue
                if scan_marker == 0xD9:  # end of image
                    end = cursor + 2
                    if end != total:
                        return None
                    kept.append(data[offset:end])
                    return b"".join(kept)
                return None
            return None
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
        segment = data[offset:segment_end]
        is_icc = marker == 0xE2 and segment[4:].startswith(b"ICC_PROFILE\x00")
        if marker not in _JPEG_DROPPED_MARKERS or is_icc:
            kept.append(segment)
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
        with open_image(image_path) as probe:
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

    with open_image(image_path) as source:
        ensure_static_image(source)
        img = normalize_orientation(source).copy()
        img.info.update(source.info)

    img = convert_color_to_srgb(img)
    icc_profile = img.info.get("icc_profile")

    # 有透明通道用 PNG，否则用 JPEG
    buf = io.BytesIO()
    if image_has_transparency(img):
        img.save(buf, format="PNG", icc_profile=icc_profile)
    else:
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=quality, icc_profile=icc_profile)

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
        validate_aggregate_output_path(image_paths, output_path)
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
            with atomic_output_path(output_path, overwrite=overwrite) as temporary:
                doc.save(temporary, deflate=True, garbage=4)

        result.output_size = os.path.getsize(output_path)
        result.page_count = len(image_paths)
        result.success = True

    except OperationPolicyError as error:
        result.error = error.code
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
    doc: Any | None = None

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

        # Validate every selected page before creating the output directory or
        # rasterizing the first page. A compact PDF can otherwise expand into a
        # multi-hundred-megapixel pixmap at a high requested DPI.
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for page_idx in page_indices:
            rendered_rect = (doc[page_idx].rect * mat).irect
            ensure_pixel_count_within_limit(rendered_rect.width * rendered_rect.height)

        os.makedirs(output_dir, exist_ok=True)

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
            pix = page.get_pixmap(matrix=mat, alpha=False)

            with atomic_output_path(out_path, overwrite=overwrite) as temporary:
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

        result.output_size = output_total_size
        result.page_count = extracted_count
        result.success = True
        result.details["total_pages"] = total_pages
        result.details["requested_pages"] = len(page_indices)
        result.details["extracted_pages"] = extracted_count
        result.details["skipped_existing"] = skipped_existing

    except PDFPageRangeError as error:
        result.error = error.code
        result.details["error_kind"] = "usage"
    except OperationPolicyError as error:
        result.error = error.code
    except Exception as error:
        result.error = str(error)
    finally:
        if doc is not None:
            doc.close()

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
    doc: Any | None = None

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
                with atomic_output_path(out_path, overwrite=overwrite) as temporary:
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
                with atomic_output_path(out_path, overwrite=overwrite) as temporary:
                    new_doc.save(temporary)
                new_doc.close()
                output_total_size += os.path.getsize(out_path)
                written += 1

        result.output_size = output_total_size
        result.page_count = len(page_indices)
        result.success = True
        result.details["total_pages"] = total_pages
        result.details["requested_pages"] = len(page_indices)
        result.details["written_files"] = written
        result.details["skipped_existing"] = skipped_existing

    except PDFPageRangeError as error:
        result.error = error.code
        result.details["error_kind"] = "usage"
    except Exception as error:
        result.error = str(error)
    finally:
        if doc is not None:
            doc.close()

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
        raise PDFPageRangeError(PDFPageRangeError.code)

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
        raise PDFPageRangeError(PDFPageRangeError.code) from error

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
            with atomic_output_path(output_path, overwrite=overwrite) as temporary:
                stats = _compress_rebuild(doc, temporary, img_quality, max_dpi, save_opts)
        else:
            # 无损压缩：仅结构优化（去重、清理、deflate）
            with atomic_output_path(output_path, overwrite=overwrite) as temporary:
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


PDF_TARGET_MIN_QUALITY = 20
PDF_TARGET_MAX_QUALITY = 95


def pdf_compress_to_target(
    input_path: str,
    output_path: str,
    target_size: int,
    max_image_dpi: int | None = None,
    overwrite: bool = False,
) -> PDFResult:
    """Compress a PDF to fit under ``target_size`` bytes at the best quality.

    Strategy (bounded, deterministic): if the input already fits, copy it
    untouched; otherwise try lossless structure optimisation, then test the
    finite quality domain from highest to lowest. Encoded sizes are not
    strictly monotonic, so a binary search cannot prove the highest feasible
    quality. If no supported quality fits, fail without publishing output.
    """
    _check_pymupdf()
    result = PDFResult(output_path=output_path)
    start_time = time.time()

    try:
        if target_size <= 0:
            raise ValueError("target_size_must_be_positive")
        if max_image_dpi is not None and not 72 <= max_image_dpi <= 1200:
            raise ValueError("max_image_dpi_must_be_between_72_and_1200")
        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        result.input_size = os.path.getsize(input_path)
        with fitz.open(input_path) as probe_doc:
            result.page_count = probe_doc.page_count

        if result.input_size <= target_size:
            with atomic_output_path(output_path, overwrite=overwrite) as temporary:
                shutil.copyfile(input_path, temporary)
            result.output_size = os.path.getsize(output_path)
            result.success = True
            result.details["strategy"] = "already_within_target"
            result.details["target_size"] = target_size
            return result

        save_opts = {"garbage": 4, "deflate": True, "clean": True}
        attempts: list[tuple[int | None, int]] = []

        def _encode_candidate(image_quality: int | None, destination: str) -> int:
            doc = _open_pdf(input_path)
            try:
                if image_quality is None:
                    doc.save(destination, **save_opts)
                else:
                    _compress_rebuild(doc, destination, image_quality, max_image_dpi, save_opts)
            finally:
                doc.close()
            return os.path.getsize(destination)

        output_parent = os.path.dirname(output_path) or "."
        os.makedirs(output_parent, exist_ok=True)
        candidates_dir = tempfile.mkdtemp(prefix=".pixshift-target-", dir=output_parent)
        try:
            winner: str | None = None
            winner_quality: int | None = None
            lossless_candidate = os.path.join(candidates_dir, "cand_lossless.pdf")
            lossless_size = _encode_candidate(None, lossless_candidate)
            attempts.append((None, lossless_size))
            if lossless_size <= target_size:
                winner = lossless_candidate
            else:
                for image_quality in range(PDF_TARGET_MAX_QUALITY, PDF_TARGET_MIN_QUALITY - 1, -1):
                    candidate = os.path.join(candidates_dir, f"cand_q{image_quality}.pdf")
                    size = _encode_candidate(image_quality, candidate)
                    attempts.append((image_quality, size))
                    if size <= target_size:
                        winner = candidate
                        winner_quality = image_quality
                        break
            if winner is None:
                result.error = "target_size_unreachable"
                result.details["target_size"] = target_size
                result.details["closest_size"] = min(size for _, size in attempts)
                result.details["attempts"] = len(attempts)
                return result
            with atomic_output_path(output_path, overwrite=overwrite) as temporary:
                shutil.copyfile(winner, temporary)
        finally:
            shutil.rmtree(candidates_dir, ignore_errors=True)

        result.output_size = os.path.getsize(output_path)
        result.success = True
        result.details["strategy"] = (
            "lossless" if winner_quality is None else f"image_quality_{winner_quality}"
        )
        result.details["target_size"] = target_size
        result.details["attempts"] = len(attempts)

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _has_nondefault_decode(doc: "fitz.Document", xref: int, components: int) -> bool:
    """Return whether an image XObject has pixel semantics unsafe to replace."""
    decode_type, decode_value = doc.xref_get_key(xref, "Decode")
    if decode_type == "null":
        return False
    if decode_type != "array" or components <= 0:
        return True
    try:
        values = [float(token) for token in decode_value.strip("[]").split()]
    except (TypeError, ValueError):
        return True
    default = [component for _ in range(components) for component in (0.0, 1.0)]
    return values != default


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

    # An image XObject may be reused at different sizes across pages. Gather
    # every placement before replacing any xref so downsampling is based on the
    # placement that needs the most pixels, not whichever page happens to come
    # first in the document.
    placement_rects_by_xref: dict[int, list[Any]] = {}
    if max_dpi:
        for page_idx in range(doc.page_count):
            try:
                for placement in doc[page_idx].get_image_info(xrefs=True):
                    info_xref = int(placement.get("xref", 0) or 0)
                    if not info_xref:
                        continue
                    rect = fitz.Rect(placement["bbox"])
                    if rect.width > 0 and rect.height > 0:
                        placement_rects_by_xref.setdefault(info_xref, []).append(rect)
            except Exception:
                # Missing placement metadata must disable downsampling for the
                # affected image rather than risk under-resolving it.
                continue

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

                # ``replace_image`` rebuilds the image dictionary. Preserve
                # XObjects whose rendering depends on dictionary semantics not
                # represented by the extracted pixel payload: soft/colour-key
                # masks, stencil masks, and non-default Decode arrays.
                mask_type, _ = doc.xref_get_key(xref, "Mask")
                image_mask_type, image_mask_value = doc.xref_get_key(xref, "ImageMask")
                is_stencil = image_mask_type == "bool" and image_mask_value.lower() == "true"
                components = int(base_image.get("colorspace", 0) or 0)
                if (
                    base_image.get("smask", 0)
                    or mask_type != "null"
                    or is_stencil
                    or _has_nondefault_decode(doc, xref, components)
                ):
                    images_skipped += 1
                    continue

                img_bytes = base_image["image"]
                img_width = base_image.get("width", 0)
                img_height = base_image.get("height", 0)

                with open_image(io.BytesIO(img_bytes)) as opened_image:
                    pil_img = opened_image.copy()
                    pil_img.info.update(opened_image.info)

                # 降低分辨率
                if max_dpi and img_width > 0 and img_height > 0:
                    try:
                        required_scales = []
                        for display_rect in placement_rects_by_xref.get(xref, []):
                            display_w_inch = display_rect.width / 72
                            display_h_inch = display_rect.height / 72
                            if display_w_inch > 0 and display_h_inch > 0:
                                current_dpi = max(
                                    img_width / display_w_inch,
                                    img_height / display_h_inch,
                                )
                                required_scales.append(min(1.0, max_dpi / current_dpi))
                        if required_scales:
                            scale = max(required_scales)
                            if scale < 1:
                                new_w = max(1, int(img_width * scale))
                                new_h = max(1, int(img_height * scale))
                                pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    except Exception:
                        pass

                # 重新编码
                pil_img = convert_color_to_srgb(pil_img)
                buf = io.BytesIO()
                icc_profile = pil_img.info.get("icc_profile")
                if image_has_transparency(pil_img):
                    pil_img.save(
                        buf,
                        format="PNG",
                        optimize=True,
                        icc_profile=icc_profile,
                    )
                else:
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    pil_img.save(
                        buf,
                        format="JPEG",
                        quality=image_quality,
                        optimize=True,
                        icc_profile=icc_profile,
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


def _unpreserved_concat_semantics(doc: "fitz.Document") -> set[str]:
    """Detect document-level semantics that ``insert_pdf`` does not copy."""
    warnings: set[str] = set()
    metadata_fields = {
        "title",
        "author",
        "subject",
        "keywords",
        "creator",
        "producer",
        "creationDate",
        "modDate",
        "trapped",
    }
    try:
        metadata = doc.metadata or {}
        if any(metadata.get(field) for field in metadata_fields):
            warnings.add("document_metadata_not_preserved")
    except Exception:
        pass
    try:
        if doc.embfile_count():
            warnings.add("document_embedded_files_not_preserved")
    except Exception:
        pass
    try:
        open_action_type, _ = doc.xref_get_key(doc.pdf_catalog(), "OpenAction")
        if open_action_type != "null":
            warnings.add("document_open_action_not_preserved")
    except Exception:
        pass
    try:
        if doc.get_toc(simple=True):
            warnings.add("document_outline_not_preserved")
    except Exception:
        pass
    try:
        page_labels_type, _ = doc.xref_get_key(doc.pdf_catalog(), "PageLabels")
        if page_labels_type != "null":
            warnings.add("document_page_labels_not_preserved")
    except Exception:
        pass
    catalog_semantics = {
        "Lang": "document_language_not_preserved",
        "ViewerPreferences": "document_viewer_preferences_not_preserved",
        "Names": "document_names_not_preserved",
        "MarkInfo": "document_mark_info_not_preserved",
        "OutputIntents": "document_output_intents_not_preserved",
    }
    for key, warning in catalog_semantics.items():
        try:
            value_type, _ = doc.xref_get_key(doc.pdf_catalog(), key)
            if value_type != "null":
                warnings.add(warning)
        except Exception:
            pass
    return warnings


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
        validate_aggregate_output_path(pdf_paths, output_path)
        if len(pdf_paths) < 2:
            raise ValueError("need_at_least_two")
        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        result.input_size = sum(os.path.getsize(p) for p in pdf_paths)

        merged = fitz.open()
        total_pages = 0
        semantic_warnings: set[str] = set()

        for pdf_path in pdf_paths:
            src = _open_pdf(pdf_path)
            try:
                semantic_warnings.update(_unpreserved_concat_semantics(src))
                merged.insert_pdf(src)
                total_pages += src.page_count
            finally:
                src.close()

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with atomic_output_path(output_path, overwrite=overwrite) as temporary:
            merged.save(temporary, deflate=True, garbage=4)
        merged.close()

        result.output_size = os.path.getsize(output_path)
        result.page_count = total_pages
        result.success = True
        result.details["file_count"] = len(pdf_paths)
        result.details["warnings"] = sorted(semantic_warnings)

    except OperationPolicyError as error:
        result.error = error.code
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
    doc: Any | None = None

    try:
        info.size_bytes = os.path.getsize(pdf_path)

        # PyMuPDF 中没有直接的 version_string，用文件头读取。
        try:
            with open(pdf_path, "rb") as stream:
                header = stream.read(20).decode("latin-1", errors="ignore")
                if header.startswith("%PDF-"):
                    info.pdf_version = header[5:8]
        except Exception:
            pass

        doc = fitz.open(pdf_path)
        info.page_count = doc.page_count
        info.encrypted = bool(doc.is_encrypted or doc.needs_pass)
        if doc.needs_pass:
            raise ValueError("pdf_password_required")

        # 元数据
        meta = doc.metadata or {}
        info.title = meta.get("title", "") or ""
        info.author = meta.get("author", "") or ""
        info.subject = meta.get("subject", "") or ""
        info.creator = meta.get("creator", "") or ""
        info.producer = meta.get("producer", "") or ""
        info.creation_date = meta.get("creationDate", "") or ""
        info.mod_date = meta.get("modDate", "") or ""

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

    except Exception as error:
        info.error = str(error)
    finally:
        if doc is not None:
            doc.close()

    return info

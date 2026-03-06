"""Operation wrappers for PDF workflows."""

from typing import List, Optional

from ..pdf_engine import (
    PYMUPDF_AVAILABLE,
    _collect_images,
    _collect_pdfs,
    pdf_compress,
    pdf_concat,
    pdf_extract_pages,
    pdf_get_info,
    pdf_merge_images,
)


def is_available() -> bool:
    """Return whether PyMuPDF-backed PDF operations are available."""
    return PYMUPDF_AVAILABLE


def collect_images(input_paths: List[str], recursive: bool) -> List[str]:
    """Collect image files for PDF merge."""
    return _collect_images(input_paths, recursive)


def collect_pdfs(input_paths: List[str], recursive: bool) -> List[str]:
    """Collect PDF files for concat."""
    return _collect_pdfs(input_paths, recursive)


def merge_images(
    image_paths: List[str],
    output_path: str,
    page_size: str,
    quality: int,
    margin: int,
    landscape: bool,
    overwrite: bool,
):
    """Merge images into one PDF."""
    return pdf_merge_images(
        image_paths=image_paths,
        output_path=output_path,
        page_size=page_size,
        quality=quality,
        margin=margin,
        landscape=landscape,
        overwrite=overwrite,
    )


def extract_pages(
    pdf_path: str,
    output_dir: str,
    output_format: str,
    dpi: int,
    pages: Optional[str],
    prefix: str,
    overwrite: bool,
):
    """Extract PDF pages to image files."""
    return pdf_extract_pages(
        pdf_path=pdf_path,
        output_dir=output_dir,
        output_format=output_format,
        dpi=dpi,
        pages=pages,
        prefix=prefix,
        overwrite=overwrite,
    )


def compress(
    input_path: str,
    output_path: str,
    preset: str,
    image_quality: Optional[int],
    max_image_dpi: Optional[int],
    overwrite: bool,
):
    """Compress one PDF."""
    return pdf_compress(
        input_path=input_path,
        output_path=output_path,
        preset=preset,
        image_quality=image_quality,
        max_image_dpi=max_image_dpi,
        overwrite=overwrite,
    )


def concat(pdf_paths: List[str], output_path: str, overwrite: bool):
    """Concatenate multiple PDFs."""
    return pdf_concat(pdf_paths=pdf_paths, output_path=output_path, overwrite=overwrite)


def info(pdf_path: str):
    """Read PDF information."""
    return pdf_get_info(pdf_path)


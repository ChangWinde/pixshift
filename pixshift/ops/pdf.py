"""Operation wrappers for PDF workflows."""

from ..pdf_engine import (
    PYMUPDF_AVAILABLE,
    PDFInfo,
    PDFResult,
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


def collect_images(input_paths: list[str], recursive: bool) -> list[str]:
    """Collect image files for PDF merge."""
    return _collect_images(input_paths, recursive)


def collect_pdfs(input_paths: list[str], recursive: bool) -> list[str]:
    """Collect PDF files for concat."""
    return _collect_pdfs(input_paths, recursive)


def merge_images(
    image_paths: list[str],
    output_path: str,
    page_size: str,
    quality: int,
    margin: int,
    landscape: bool,
    overwrite: bool,
) -> PDFResult:
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
    pages: str | None,
    prefix: str,
    overwrite: bool,
) -> PDFResult:
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
    image_quality: int | None,
    max_image_dpi: int | None,
    overwrite: bool,
) -> PDFResult:
    """Compress one PDF."""
    return pdf_compress(
        input_path=input_path,
        output_path=output_path,
        preset=preset,
        image_quality=image_quality,
        max_image_dpi=max_image_dpi,
        overwrite=overwrite,
    )


def concat(pdf_paths: list[str], output_path: str, overwrite: bool) -> PDFResult:
    """Concatenate multiple PDFs."""
    return pdf_concat(pdf_paths=pdf_paths, output_path=output_path, overwrite=overwrite)


def info(pdf_path: str) -> PDFInfo:
    """Read PDF information."""
    return pdf_get_info(pdf_path)

"""Canonical product defaults shared by CLI, engines, and capability output."""

from typing import Any

DEFAULT_COMPRESS_PRESET = "medium"
DEFAULT_CONVERT_QUALITY = "high"
DEFAULT_PDF_EXTRACT_DPI = 150
DEFAULT_PDF_MERGE_MARGIN = 20
DEFAULT_STRIP_MODE = "privacy"
DEFAULT_WATERMARK_FONT_SIZE = "auto"


def automation_defaults() -> dict[str, Any]:
    """Return stable, machine-readable defaults for common workflows."""
    return {
        "compress_preset": DEFAULT_COMPRESS_PRESET,
        "convert_quality": DEFAULT_CONVERT_QUALITY,
        "pdf_extract_dpi": DEFAULT_PDF_EXTRACT_DPI,
        "pdf_merge_margin": DEFAULT_PDF_MERGE_MARGIN,
        "strip_mode": DEFAULT_STRIP_MODE,
        "watermark_font_size": DEFAULT_WATERMARK_FONT_SIZE,
    }

"""Operation boundary for cross-media verification."""

from ..verify_engine import VerifyResult, verify_media


def verify(
    source: str,
    candidate: str,
    *,
    min_ssim: float,
    min_psnr: float | None,
    max_bytes: int | None,
    allow_resize: bool,
) -> VerifyResult:
    """Verify a candidate against its source using explicit thresholds."""
    return verify_media(
        source,
        candidate,
        min_ssim=min_ssim,
        min_psnr=min_psnr,
        max_bytes=max_bytes,
        allow_resize=allow_resize,
    )

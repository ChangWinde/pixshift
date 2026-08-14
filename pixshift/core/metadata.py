"""Canonical image metadata and visual-orientation helpers."""

import io
import os
import re
from contextlib import suppress
from typing import Any

from PIL import Image, ImageCms, ImageOps, ImageSequence

from .errors import AnimatedInputNotSupportedError, ImageTooLargeError

ORIENTATION_TAG = 274

# A decompression bomb is a small file that declares an enormous canvas: a few
# hundred kilobytes can expand to tens of gigabytes of pixels and take the
# machine down. Pillow warns at its own threshold, but a warning is easy to
# miss and its text is not a stable contract, so the limit is enforced here and
# reported as `image_too_large`. 120 megapixels still admits current 100MP
# medium-format photos while bounding one decoded RGB frame to roughly 360 MB.
DEFAULT_MAX_IMAGE_PIXELS = 120_000_000
DEFAULT_FRAME_DURATION_MS = 100


def max_image_pixels() -> int:
    """The PixShift pixel budget; ``0`` disables only this additional guard."""
    raw = os.environ.get("PIXSHIFT_MAX_PIXELS")
    if raw is None:
        return DEFAULT_MAX_IMAGE_PIXELS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_IMAGE_PIXELS
    return max(0, value)


def open_image(
    fp: Any,
    formats: list[str] | tuple[str, ...] | None = None,
) -> Image.Image:
    """Open one image and enforce PixShift's budget without mutating Pillow.

    Pillow's independent decompression-bomb policy remains intact. In
    particular, this helper does not install warning filters or mutate Pillow
    globals, because either change would affect unrelated threads in a host
    process importing PixShift.
    """
    try:
        image = Image.open(fp) if formats is None else Image.open(fp, formats=formats)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        match = re.search(r"Image size \((\d+) pixels\)", str(error))
        pixels = int(match.group(1)) if match else max_image_pixels() + 1
        multiplier = 1 if isinstance(error, Image.DecompressionBombWarning) else 2
        pillow_limit = int((Image.MAX_IMAGE_PIXELS or 0) * multiplier)
        raise ImageTooLargeError(pixels, pillow_limit or max_image_pixels()) from error
    try:
        ensure_within_pixel_limit(image)
    except ImageTooLargeError:
        # Pillow owns a path it opened, but callers retain ownership of file
        # objects. Cleanup is best-effort and must not replace the stable
        # policy error if a third-party image plugin has a broken close().
        if isinstance(fp, (str, bytes, os.PathLike)):
            with suppress(Exception):
                image.close()
        raise
    return image


def ensure_within_pixel_limit(image: Image.Image) -> None:
    """Reject an image whose declared canvas exceeds the pixel budget.

    Checked against the header dimensions before the pixels are decoded, so a
    hostile file is refused without allocating for it.
    """
    width, height = image.size
    ensure_pixel_count_within_limit(int(width) * int(height))


def ensure_pixel_count_within_limit(pixels: int) -> None:
    """Reject one declared or aggregate decoded-pixel count over budget."""
    limit = max_image_pixels()
    if limit and pixels > limit:
        raise ImageTooLargeError(pixels, limit)


def image_frame_count(image: Image.Image) -> int:
    """Return the number of frames exposed by a Pillow image.

    Args:
        image: Open Pillow image.

    Returns:
        At least one frame, including for formats without animation metadata.
    """
    return max(1, int(getattr(image, "n_frames", 1)))


def ensure_static_image(image: Image.Image) -> None:
    """Reject an animation where an operation only supports still images.

    Also enforces the pixel budget, since every still-image operation opens
    its input through this guard.

    Args:
        image: Open Pillow image.

    Raises:
        AnimatedInputNotSupportedError: The image contains more than one frame.
        ImageTooLargeError: The canvas exceeds the pixel budget.
    """
    ensure_within_pixel_limit(image)
    if image_frame_count(image) > 1:
        raise AnimatedInputNotSupportedError()


def image_has_transparency(image: Image.Image) -> bool:
    """Return whether an image contains an alpha channel or transparency table.

    Args:
        image: Pillow image in any color mode.

    Returns:
        ``True`` for explicit alpha channels and indexed transparency metadata.
    """
    # LAB names its chroma channels ``A`` and ``B``; checking band names alone
    # therefore misclassifies every LAB image as transparent. Pillow's alpha-
    # bearing modes are explicit, while palette transparency lives in info.
    return image.mode in {"RGBA", "RGBa", "LA", "La", "PA"} or (
        image.mode == "P" and "transparency" in image.info
    )


def extract_animation(
    image: Image.Image,
) -> tuple[list[Image.Image], list[int], int | None, Image.Image | None]:
    """Copy the semantic playback frames, timings, loop value, and optional poster.

    APNG counts a non-playing default image in ``n_frames`` while GIF and WebP
    do not. Centralising that distinction keeps conversion and verification
    from disagreeing about the same animation. A missing loop value is retained
    as ``None`` here; callers can use :func:`normalized_animation_loop` when
    comparing playback semantics across formats.
    """
    default_duration = int(image.info.get("duration") or DEFAULT_FRAME_DURATION_MS)
    if default_duration <= 0:
        default_duration = DEFAULT_FRAME_DURATION_MS
    has_default_image = bool(image.info.get("default_image"))
    loop_value = image.info.get("loop")
    frames: list[Image.Image] = []
    durations: list[int] = []
    default_frame: Image.Image | None = None
    total_pixels = 0
    for index, frame in enumerate(ImageSequence.Iterator(image)):
        ensure_within_pixel_limit(frame)
        total_pixels += int(frame.width) * int(frame.height)
        ensure_pixel_count_within_limit(total_pixels)
        # copy() forces load(); some decoders only expose timing after load.
        copied = frame.copy()
        if has_default_image and index == 0:
            default_frame = copied
            continue
        duration = int(copied.info.get("duration") or default_duration)
        durations.append(duration if duration > 0 else default_duration)
        frames.append(copied)
    loop = int(loop_value) if loop_value is not None else None
    return frames, durations, loop, default_frame


def normalized_animation_loop(loop: int | None) -> int:
    """Return a cross-format playback-loop value (missing means play once)."""
    return 1 if loop is None else loop


def flatten_transparency(
    image: Image.Image,
    background_color: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Composite image transparency onto an opaque RGB background.

    Args:
        image: Pillow image in any color mode.
        background_color: Opaque RGB background used for compositing.

    Returns:
        Opaque RGB image.
    """
    foreground = image.convert("RGBA")
    background = Image.new("RGBA", foreground.size, (*background_color, 255))
    flattened = Image.alpha_composite(background, foreground).convert("RGB")
    flattened.info.update(image.info)
    flattened.info.pop("transparency", None)
    return flattened


def convert_color_to_rgb(image: Image.Image) -> Image.Image:
    """Convert CMYK/LAB pixels to RGB without relabelling their ICC profile.

    A valid embedded source profile is transformed through LittleCMS and replaced
    with an sRGB profile. Missing or invalid profiles fall back to Pillow's numeric
    conversion and deliberately drop the stale source profile.
    """
    if image.mode not in {"CMYK", "YCCK", "LAB"}:
        return image

    source_info = {key: value for key, value in image.info.items() if key != "icc_profile"}
    profile_bytes = image.info.get("icc_profile")
    converted: Image.Image
    output_profile: bytes | None = None
    if profile_bytes:
        try:
            source_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
            destination_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            transformed = ImageCms.profileToProfile(
                image,
                source_profile,
                destination_profile,
                outputMode="RGB",
            )
            if transformed is None:  # Pillow typing permits an in-place result.
                raise OSError("icc_transform_failed")
            converted = transformed
            output_profile = destination_profile.tobytes()
        except (OSError, TypeError, ValueError):
            converted = image.convert("RGB")
    else:
        converted = image.convert("RGB")

    converted.info.update(source_info)
    converted.info.pop("icc_profile", None)
    if output_profile:
        converted.info["icc_profile"] = output_profile
    return converted


def convert_color_to_srgb(image: Image.Image) -> Image.Image:
    """Convert pixels to the sRGB colour space and attach an sRGB profile.

    Untagged inputs are interpreted as already using sRGB, which matches the
    de-facto browser and Pillow convention. A tagged input is transformed via
    LittleCMS. Unlike the compatibility conversion above, an invalid embedded
    profile is a stable error: silently treating those pixels as sRGB would
    relabel colours rather than convert them.
    """
    source_info = {
        key: value
        for key, value in image.info.items()
        if key not in {"icc_profile", "transparency"}
    }
    profile_bytes = image.info.get("icc_profile")
    destination_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    alpha = image.convert("RGBA").getchannel("A") if image_has_transparency(image) else None

    if profile_bytes:
        try:
            source_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
            source_pixels = (
                image
                if image.mode in {"RGB", "CMYK", "LAB"} and alpha is None
                else image.convert("RGB")
            )
            transformed = ImageCms.profileToProfile(
                source_pixels,
                source_profile,
                destination_profile,
                outputMode="RGB",
            )
            if transformed is None:
                raise OSError("icc_transform_failed")
            converted = transformed
        except (OSError, TypeError, ValueError) as error:
            raise ValueError("invalid_icc_profile") from error
    else:
        converted = image.convert("RGB")

    if alpha is not None:
        converted.putalpha(alpha)
    converted.info.update(source_info)
    converted.info.pop("transparency", None)
    converted.info["icc_profile"] = destination_profile.tobytes()
    return converted


def normalize_orientation(image: Image.Image) -> Image.Image:
    """Apply EXIF orientation once and remove the stale orientation tag.

    Args:
        image: Source Pillow image.

    Returns:
        An image whose stored pixels match its visual orientation.
    """
    normalized = ImageOps.exif_transpose(image)
    exif = normalized.getexif()
    if ORIENTATION_TAG in exif:
        del exif[ORIENTATION_TAG]
    if exif:
        normalized.info["exif"] = exif.tobytes()
    else:
        normalized.info.pop("exif", None)
    return normalized


def normalized_exif_bytes(
    image: Image.Image,
    *,
    remove_orientation: bool = True,
) -> bytes | None:
    """Serialize EXIF metadata without a visual-orientation instruction.

    Args:
        image: An image that may contain EXIF metadata.
        remove_orientation: Whether transformed pixels make the orientation tag stale.

    Returns:
        Serialized EXIF bytes, or ``None`` when no EXIF fields remain.
    """
    exif = image.getexif()
    if remove_orientation and ORIENTATION_TAG in exif:
        del exif[ORIENTATION_TAG]
    return exif.tobytes() if exif else None

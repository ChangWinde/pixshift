"""Canonical image metadata and visual-orientation helpers."""

from PIL import Image, ImageOps

from .errors import AnimatedInputNotSupportedError

ORIENTATION_TAG = 274


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

    Args:
        image: Open Pillow image.

    Raises:
        AnimatedInputNotSupportedError: The image contains more than one frame.
    """
    if image_frame_count(image) > 1:
        raise AnimatedInputNotSupportedError()


def image_has_transparency(image: Image.Image) -> bool:
    """Return whether an image contains an alpha channel or transparency table.

    Args:
        image: Pillow image in any color mode.

    Returns:
        ``True`` for explicit alpha channels and indexed transparency metadata.
    """
    return "A" in image.getbands() or "transparency" in image.info


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

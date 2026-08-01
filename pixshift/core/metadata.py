"""Canonical image metadata and visual-orientation helpers."""

from PIL import Image, ImageOps

ORIENTATION_TAG = 274


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

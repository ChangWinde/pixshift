"""Directory inventory / manifest helpers for agents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..converter import SUPPORTED_INPUT_FORMATS, PixShiftConverter
from ..core.files import SelectionFilters, collect_supported_files


@dataclass
class InventoryItem:
    """One inventoried media file."""

    path: str
    sha256: str = ""
    bytes: int = 0
    format: str = ""
    width: int | None = None
    height: int | None = None
    mode: str = ""
    has_alpha: bool | None = None
    frame_count: int | None = None
    sensitive_exif_keys: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class InventoryResult:
    """Batch inventory summary."""

    items: list[InventoryItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(not item.error for item in self.items)


_SENSITIVE_HINTS = (
    "gps",
    "make",
    "model",
    "serial",
    "artist",
    "copyright",
    "datetime",
    "hostcomputer",
    "software",
    "lens",
    "owner",
)


def build_inventory(
    input_paths: list[str],
    *,
    recursive: bool = False,
    selection: SelectionFilters | None = None,
) -> InventoryResult:
    """Collect image properties and content hashes."""
    files = collect_supported_files(
        input_paths, SUPPORTED_INPUT_FORMATS, recursive=recursive, selection=selection
    )
    result = InventoryResult()
    for path in files:
        item = InventoryItem(path=path)
        try:
            item.bytes = Path(path).stat().st_size
            item.sha256 = _sha256(path)
            info = PixShiftConverter.get_image_info(path)
            if info.get("error"):
                item.error = str(info["error"])
            item.format = str(info.get("format") or "")
            item.width = info.get("width")
            item.height = info.get("height")
            item.mode = str(info.get("mode") or "")
            item.has_alpha = info.get("has_alpha")
            item.frame_count = info.get("frame_count")
            exif = info.get("exif") or {}
            if isinstance(exif, dict):
                item.sensitive_exif_keys = sorted(
                    key
                    for key in exif
                    if any(hint in str(key).lower() for hint in _SENSITIVE_HINTS)
                )
        except Exception as error:
            item.error = str(error)
        result.items.append(item)
    return result


def inventory_payload(result: InventoryResult) -> list[dict[str, Any]]:
    """Serialize inventory items."""
    return [
        {
            "path": item.path,
            "sha256": item.sha256,
            "size_bytes": item.bytes,
            "format": item.format,
            "width": item.width,
            "height": item.height,
            "mode": item.mode,
            "has_alpha": item.has_alpha,
            "frame_count": item.frame_count,
            "sensitive_exif_keys": item.sensitive_exif_keys,
            "error": item.error,
        }
        for item in result.items
    ]


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

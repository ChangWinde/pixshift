"""Compose convert + privacy strip into a delivery prep workflow."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..converter import SUPPORTED_INPUT_FORMATS
from ..core.defaults import DEFAULT_CONVERT_QUALITY
from ..core.files import (
    atomic_copy_file,
    collect_supported_files,
    conversion_output_name,
    filter_generated_inputs,
    partition_existing_outputs,
    plan_output_path,
    validate_unique_output_paths,
)
from . import convert as convert_ops
from . import strip as strip_ops


@dataclass
class PrepItem:
    """One prepared asset."""

    input_path: str
    output_path: str = ""
    success: bool = False
    skipped: bool = False
    input_bytes: int = 0
    output_bytes: int = 0
    sha256: str = ""
    width: int | None = None
    height: int | None = None
    error: str = ""


@dataclass
class PrepResult:
    """Batch prep summary."""

    items: list[PrepItem] = field(default_factory=list)
    ignored_generated: int = 0

    @property
    def ok(self) -> bool:
        """Whether every item succeeded or was an idempotent skip."""
        return all(item.success or item.skipped for item in self.items)


def prep_files(
    input_paths: list[str],
    *,
    output_dir: str,
    output_format: str = "webp",
    max_size: int | None = 2048,
    quality: str = DEFAULT_CONVERT_QUALITY,
    recursive: bool = False,
    overwrite: bool = False,
    dry_run: bool = False,
    strip_privacy: bool = True,
) -> PrepResult:
    """Prepare delivery-ready assets under ``output_dir``.

    Each source image is converted (bounded by ``max_size``), optionally
    privacy-stripped, and atomically published. Existing outputs are
    idempotent skips unless ``overwrite`` is set.
    """
    collected = collect_supported_files(input_paths, SUPPORTED_INPUT_FORMATS, recursive=recursive)
    files, ignored = filter_generated_inputs(
        collected,
        input_paths,
        output_root=output_dir,
    )
    result = PrepResult(ignored_generated=ignored)

    tasks: list[tuple[str, str]] = []
    for path in files:
        name = conversion_output_name(path, output_format)
        destination = plan_output_path(
            path,
            name,
            output_dir=output_dir,
            flatten=False,
            source_paths=input_paths,
        )
        tasks.append((path, destination))

    # Two sources (e.g. a.png and a.jpg) can map to the same prepared name and
    # would silently overwrite each other; fail the batch as convert does.
    validate_unique_output_paths(tasks)

    pending, skipped = partition_existing_outputs(tasks, overwrite=overwrite)
    for source, dest in skipped:
        item = PrepItem(input_path=source, output_path=dest, skipped=True, success=True)
        source_file = Path(source)
        if source_file.is_file():
            item.input_bytes = source_file.stat().st_size
        dest_file = Path(dest)
        if dest_file.is_file():
            item.output_bytes = dest_file.stat().st_size
            item.sha256 = _sha256(dest)
        result.items.append(item)

    for source, dest in pending:
        result.items.append(
            _prep_one(
                source,
                dest,
                output_format=output_format,
                max_size=max_size,
                quality=quality,
                overwrite=overwrite,
                dry_run=dry_run,
                strip_privacy=strip_privacy,
            )
        )
    return result


def _prep_one(
    source: str,
    dest: str,
    *,
    output_format: str,
    max_size: int | None,
    quality: str,
    overwrite: bool,
    dry_run: bool,
    strip_privacy: bool,
) -> PrepItem:
    item = PrepItem(input_path=source, output_path=dest)
    item.input_bytes = Path(source).stat().st_size
    if dry_run:
        item.success = True
        return item
    try:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="pixshift-prep-") as tmp:
            tmp_convert = str(Path(tmp) / Path(dest).name)
            convert_result = convert_ops.convert_one(
                source,
                tmp_convert,
                {"quality": quality, "max_size": max_size, "overwrite": True},
            )
            if not convert_result.success:
                item.error = convert_result.error or "convert_failed"
                return item
            final_source = tmp_convert
            if strip_privacy:
                tmp_strip = str(Path(tmp) / f"stripped-{Path(dest).name}")
                strip_result = strip_ops.strip_one(
                    tmp_convert,
                    tmp_strip,
                    strip_exif=True,
                    strip_gps=True,
                    strip_icc=False,
                    strip_device=True,
                    strip_personal=True,
                    strip_time=False,
                    keep_orientation=True,
                    overwrite=True,
                )
                if not strip_result.success:
                    item.error = strip_result.error or "strip_failed"
                    return item
                final_source = tmp_strip
            atomic_copy_file(final_source, dest)
        item.success = True
        item.output_bytes = Path(dest).stat().st_size
        item.sha256 = _sha256(dest)
        item.width, item.height = _dims(dest)
    except Exception as error:
        item.error = str(error)
    return item


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dims(path: str) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return None, None


def prep_payload(result: PrepResult) -> list[dict[str, Any]]:
    """Serialize prep items for JSON output."""
    return [
        {
            "input": item.input_path,
            "output": item.output_path,
            "ok": item.success or item.skipped,
            "skipped": item.skipped,
            "input_bytes": item.input_bytes,
            "output_bytes": item.output_bytes,
            "sha256": item.sha256,
            "width": item.width,
            "height": item.height,
            "error": item.error,
        }
        for item in result.items
    ]

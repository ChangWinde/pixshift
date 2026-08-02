"""Shared file collection and safe output planning helpers."""

import os
import shutil
import uuid
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path

from .errors import (
    InvalidFilenameComponentError,
    OutputBoundaryError,
    OutputCollisionError,
)


def collect_supported_files(
    input_paths: Sequence[str],
    supported_exts: set[str],
    input_format: str | None = None,
    recursive: bool = False,
) -> list[str]:
    """Collect unique files that match a supported extension."""
    files: list[str] = []
    normalized_filter = _normalize_ext(input_format) if input_format else None

    for path_str in input_paths:
        source = Path(path_str)
        if source.is_file():
            ext = source.suffix.lower()
            if normalized_filter:
                if ext == normalized_filter:
                    files.append(str(source.resolve()))
            elif ext in supported_exts:
                files.append(str(source.resolve()))
            continue

        if not source.is_dir():
            continue

        pattern = "**/*" if recursive else "*"
        for item in source.glob(pattern):
            if not item.is_file():
                continue
            ext = item.suffix.lower()
            if normalized_filter:
                if ext == normalized_filter:
                    files.append(str(item.resolve()))
            elif ext in supported_exts:
                files.append(str(item.resolve()))

    return sorted(set(files))


def filter_generated_inputs(
    files: Sequence[str],
    source_paths: Sequence[str],
    *,
    output_root: str | None = None,
    generated_suffix: str | None = None,
    excluded_extension: str | None = None,
    excluded_files: Sequence[str] = (),
) -> tuple[list[str], int]:
    """Remove generated artifacts discovered through directory scans.

    Explicit file arguments remain authoritative. Exact operation assets and outputs in
    ``excluded_files`` are always excluded so a watermark or prior aggregate output cannot
    accidentally consume itself.

    Args:
        files: Collected candidate files.
        source_paths: Original user-supplied file and directory arguments.
        output_root: Generated output directory, when one exists.
        generated_suffix: Derivative stem suffix such as ``_compressed``.
        excluded_extension: Target extension to skip for discovered conversion inputs.
        excluded_files: Exact assets or aggregate outputs that must never be inputs.

    Returns:
        A tuple of retained files and the number of ignored generated candidates.
    """
    explicit_files = {Path(source).resolve() for source in source_paths if Path(source).is_file()}
    source_dirs = [Path(source).resolve() for source in source_paths if Path(source).is_dir()]
    exact_exclusions = {Path(path).resolve(strict=False) for path in excluded_files}
    normalized_extension = _normalize_ext(excluded_extension) if excluded_extension else None

    generated_root: Path | None = None
    if output_root:
        candidate_root = Path(output_root).resolve(strict=False)
        if any(
            candidate_root != source_root and _is_relative_to(candidate_root, source_root)
            for source_root in source_dirs
        ):
            generated_root = candidate_root

    candidates = {Path(file_path).resolve() for file_path in files}
    retained: list[str] = []
    ignored = 0
    for file_path in files:
        resolved = Path(file_path).resolve()
        if resolved in exact_exclusions:
            ignored += 1
            continue
        if resolved in explicit_files:
            retained.append(file_path)
            continue
        if generated_root is not None and _is_relative_to(resolved, generated_root):
            ignored += 1
            continue
        if generated_suffix and resolved.stem.endswith(generated_suffix):
            original_stem = resolved.stem[: -len(generated_suffix)]
            original = resolved.with_name(f"{original_stem}{resolved.suffix}")
            if original in candidates:
                ignored += 1
                continue
        if normalized_extension and resolved.suffix.lower() == normalized_extension:
            ignored += 1
            continue
        retained.append(file_path)

    return retained, ignored


def partition_existing_outputs(
    tasks: Sequence[tuple[str, str]],
    *,
    overwrite: bool,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Split batch tasks into pending work and idempotent existing-output skips.

    Args:
        tasks: Input/output task pairs.
        overwrite: Whether existing outputs should remain pending.

    Returns:
        A tuple of pending tasks and tasks skipped because their output exists.
    """
    if overwrite:
        return list(tasks), []
    pending: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    for task in tasks:
        if Path(task[1]).is_file():
            skipped.append(task)
        else:
            pending.append(task)
    return pending, skipped


def plan_output_path(
    input_path: str,
    output_name: str,
    output_dir: str | None = None,
    flatten: bool = False,
    source_paths: Iterable[str] | None = None,
) -> str:
    """Plan destination path with optional structure preservation."""
    inp = Path(input_path).resolve()
    if not output_dir:
        return str(inp.parent / output_name)

    target_base = Path(output_dir).resolve()
    if flatten:
        return safe_output_path(target_base, output_name)

    rel_parent = _resolve_relative_parent(inp, source_paths or [])
    return safe_output_path(target_base, rel_parent / output_name)


def conversion_output_name(
    input_path: str,
    output_format: str,
    prefix: str = "",
    suffix: str = "",
) -> str:
    """Build output filename for format conversion."""
    validate_filename_affix(prefix, "prefix")
    validate_filename_affix(suffix, "suffix")
    normalized_format = output_format.lower().lstrip(".")
    validate_filename_component(normalized_format, "output format")
    inp = Path(input_path)
    out_ext = f".{normalized_format}"
    return f"{prefix}{inp.stem}{suffix}{out_ext}"


def derivative_output_name(
    input_path: str,
    suffix: str,
) -> str:
    """Build output filename for same-format derivative operations."""
    inp = Path(input_path)
    return f"{inp.stem}{suffix}{inp.suffix.lower()}"


def validate_filename_affix(value: str, label: str) -> None:
    """Validate a user-controlled filename prefix or suffix.

    Args:
        value: Prefix or suffix supplied by a caller.
        label: Human-readable field name for errors.

    Raises:
        InvalidFilenameComponentError: If path syntax is present.
    """
    if not value:
        return
    validate_filename_component(value, label)


def validate_filename_component(value: str, label: str = "filename") -> None:
    """Reject path syntax in a value that must be one filename component."""
    if (
        not value
        or "\x00" in value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
        or Path(value).is_absolute()
        or Path(value).name != value
    ):
        raise InvalidFilenameComponentError(f"{label} must be a plain filename component")


def safe_output_path(output_root: Path | str, relative_path: Path | str) -> str:
    """Resolve an output below an approved root and reject traversal.

    Args:
        output_root: Directory the caller explicitly selected.
        relative_path: Relative destination within that directory.

    Returns:
        Absolute validated output path.

    Raises:
        InvalidFilenameComponentError: If the final filename is invalid.
        OutputBoundaryError: If the destination escapes ``output_root``.
    """
    root = Path(output_root).resolve()
    relative = Path(relative_path)
    if relative.is_absolute():
        raise OutputBoundaryError("output path must be relative to its output root")
    validate_filename_component(relative.name)
    candidate = (root / relative).resolve(strict=False)
    if not _is_relative_to(candidate, root):
        raise OutputBoundaryError("planned output escapes its output root")
    return str(candidate)


def validate_unique_output_paths(tasks: Sequence[tuple[str, str]]) -> None:
    """Fail a batch when two sources resolve to the same destination."""
    destinations: dict[str, str] = {}
    for source, output in tasks:
        key = os.path.normcase(str(Path(output).resolve(strict=False)))
        previous = destinations.get(key)
        if previous is not None and Path(previous).resolve() != Path(source).resolve():
            raise OutputCollisionError(
                f"multiple inputs map to the same output: {previous}, {source} -> {output}"
            )
        destinations[key] = source


@contextmanager
def atomic_output_path(output_path: str) -> Iterator[str]:
    """Yield a same-directory temporary path and atomically replace on success."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / (f".{target.stem}.{uuid.uuid4().hex}.tmp{target.suffix}")
    try:
        yield str(temporary)
        if not temporary.is_file():
            raise OSError("encoder did not create its planned output")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def atomic_write_bytes(output_path: str, data: bytes) -> None:
    """Write bytes through the shared atomic replacement boundary."""
    with atomic_output_path(output_path) as temporary:
        Path(temporary).write_bytes(data)


def atomic_copy_file(input_path: str, output_path: str) -> None:
    """Copy a file through the shared atomic replacement boundary."""
    with atomic_output_path(output_path) as temporary:
        shutil.copyfile(input_path, temporary)


def _normalize_ext(ext_or_format: str | None) -> str:
    """Normalize user extension input to '.ext' format."""
    if not ext_or_format:
        return ""
    return f".{ext_or_format.lower().lstrip('.')}"


def _resolve_relative_parent(input_file: Path, source_paths: Iterable[str]) -> Path:
    """Resolve relative parent folder against the closest input directory root."""
    dir_roots = _resolved_dirs(source_paths)
    if not dir_roots:
        return Path()

    matched_root: Path | None = None
    for root in dir_roots:
        if _is_relative_to(input_file, root) and (
            matched_root is None or len(str(root)) > len(str(matched_root))
        ):
            matched_root = root

    if matched_root is None:
        return Path()

    return input_file.relative_to(matched_root).parent


def _resolved_dirs(source_paths: Iterable[str]) -> list[Path]:
    """Resolve and return directory inputs only."""
    dirs: list[Path] = []
    for source in source_paths:
        path = Path(source)
        if path.is_dir():
            dirs.append(path.resolve())
    return dirs


def _is_relative_to(path: Path, root: Path) -> bool:
    """Return whether a path is located within a candidate parent path."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

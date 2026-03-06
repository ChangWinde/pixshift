"""Shared file collection and output path planning helpers."""

from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set


def collect_supported_files(
    input_paths: Sequence[str],
    supported_exts: Set[str],
    input_format: Optional[str] = None,
    recursive: bool = False,
) -> List[str]:
    """Collect unique files that match a supported extension."""
    files: List[str] = []
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


def plan_output_path(
    input_path: str,
    output_name: str,
    output_dir: Optional[str] = None,
    flatten: bool = False,
    source_paths: Optional[Iterable[str]] = None,
) -> str:
    """Plan destination path with optional structure preservation."""
    inp = Path(input_path).resolve()
    if not output_dir:
        return str(inp.parent / output_name)

    target_base = Path(output_dir)
    if flatten:
        return str(target_base / output_name)

    rel_parent = _resolve_relative_parent(inp, source_paths or [])
    return str(target_base / rel_parent / output_name)


def conversion_output_name(
    input_path: str,
    output_format: str,
    prefix: str = "",
    suffix: str = "",
) -> str:
    """Build output filename for format conversion."""
    inp = Path(input_path)
    out_ext = f".{output_format.lower().lstrip('.')}"
    return f"{prefix}{inp.stem}{suffix}{out_ext}"


def derivative_output_name(
    input_path: str,
    suffix: str,
) -> str:
    """Build output filename for same-format derivative operations."""
    inp = Path(input_path)
    return f"{inp.stem}{suffix}{inp.suffix.lower()}"


def _normalize_ext(ext_or_format: Optional[str]) -> str:
    """Normalize user extension input to '.ext' format."""
    if not ext_or_format:
        return ""
    return f".{ext_or_format.lower().lstrip('.')}"


def _resolve_relative_parent(input_file: Path, source_paths: Iterable[str]) -> Path:
    """Resolve relative parent folder against the closest input directory root."""
    dir_roots = _resolved_dirs(source_paths)
    if not dir_roots:
        return Path()

    matched_root: Optional[Path] = None
    for root in dir_roots:
        if _is_relative_to(input_file, root):
            if matched_root is None or len(str(root)) > len(str(matched_root)):
                matched_root = root

    if matched_root is None:
        return Path()

    return input_file.relative_to(matched_root).parent


def _resolved_dirs(source_paths: Iterable[str]) -> List[Path]:
    """Resolve and return directory inputs only."""
    dirs: List[Path] = []
    for source in source_paths:
        path = Path(source)
        if path.is_dir():
            dirs.append(path.resolve())
    return dirs


def _is_relative_to(path: Path, root: Path) -> bool:
    """Python 3.8-compatible Path.is_relative_to."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


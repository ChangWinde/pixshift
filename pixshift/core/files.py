"""Shared file collection and safe output planning helpers."""

import fnmatch
import os
import secrets
import shutil
import stat
import sys
import tempfile
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import (
    InvalidFilenameComponentError,
    OutputBoundaryError,
    OutputCollisionError,
)


@dataclass(frozen=True)
class SelectionFilters:
    """User-requested narrowing of a batch, applied during collection.

    Unlike the automatic generated-artifact exclusion, these filters are an
    explicit instruction, so they apply to named files as well as to files
    discovered by scanning a directory.
    """

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    min_bytes: int = 0
    max_bytes: int | None = None

    @property
    def active(self) -> bool:
        return bool(self.include or self.exclude or self.min_bytes or self.max_bytes)

    def accepts(self, path: Path) -> bool:
        """Whether ``path`` survives the filters."""
        if not self.active:
            return True
        # Match a glob against the full path and the bare name, so both
        # `--exclude '*/thumbs/*'` and `--exclude '*_draft.jpg'` read naturally.
        text = path.as_posix()
        name = path.name
        if self.include and not any(
            fnmatch.fnmatch(text, rule) or fnmatch.fnmatch(name, rule) for rule in self.include
        ):
            return False
        if any(fnmatch.fnmatch(text, rule) or fnmatch.fnmatch(name, rule) for rule in self.exclude):
            return False
        if self.min_bytes or self.max_bytes is not None:
            try:
                size = path.stat().st_size
            except OSError:
                return False
            if size < self.min_bytes:
                return False
            if self.max_bytes is not None and size > self.max_bytes:
                return False
        return True


def collect_supported_files(
    input_paths: Sequence[str],
    supported_exts: set[str],
    input_format: str | None = None,
    recursive: bool = False,
    selection: SelectionFilters | None = None,
) -> list[str]:
    """Collect unique files that match a supported extension."""
    files: list[str] = []
    normalized_filter = _normalize_ext(input_format) if input_format else None
    filters = selection or SelectionFilters()

    for path_str in input_paths:
        source = Path(path_str)
        if source.is_file():
            ext = source.suffix.lower()
            if not filters.accepts(source):
                continue
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
            # A directory argument authorises files below that directory, not
            # the target of a link that happens to live there. Explicit file
            # arguments remain authoritative and may still be symlinks.
            if item.is_symlink() or not item.is_file():
                continue
            ext = item.suffix.lower()
            if not filters.accepts(item):
                continue
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
            if any(
                candidate.parent == resolved.parent and candidate.stem == original_stem
                for candidate in candidates
            ):
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
    validate_filename_component(output_name)
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
    """Reject non-portable syntax in one generated filename component.

    PixShift plans outputs on one platform and may later materialise the same
    plan on another. Enforcing the Windows superset here avoids accepting names
    on POSIX that cannot be published on Windows or a Windows-backed share.
    """
    windows_reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{index}" for prefix in ("COM", "LPT") for index in range(1, 10)
    }
    device_stem = value.split(".", 1)[0].upper()
    if (
        not value
        or "\x00" in value
        or "/" in value
        or "\\" in value
        or any(character in '<>:"|?*' or ord(character) < 32 for character in value)
        or value.endswith((" ", "."))
        or device_stem in windows_reserved
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


def _output_collision_key(output: str) -> str:
    """Normalise an output path for collision detection.

    ``os.path.normcase`` lowercases on Windows but is identity on POSIX, so on
    macOS (case-insensitive APFS by default) ``Photo.webp`` and ``photo.webp``
    would otherwise pass the check and then clobber the same physical file.
    """
    key = os.path.normcase(str(Path(output).resolve(strict=False)))
    if sys.platform == "darwin":
        # Default APFS/HFS+ volumes compare canonically equivalent Unicode
        # spellings as one name. Normalise before folding so Café (NFC) and
        # Cafe\N{COMBINING ACUTE ACCENT} (NFD) cannot evade batch preflight.
        key = unicodedata.normalize("NFC", key).casefold()
    return key


def validate_unique_output_paths(tasks: Sequence[tuple[str, str]]) -> None:
    """Fail a batch when two sources resolve to the same destination.

    Also rejects a destination that is a *different* task's source. Writing
    ``a.jpg`` on top of ``b.jpg`` while ``b.jpg`` is still queued for reading
    destroys b's original bytes and makes the batch's result depend on task
    ordering. Rewriting a file in place (source == its own destination) stays
    allowed; that is the documented overwrite behaviour.
    """
    destinations: dict[str, str] = {}
    sources = {_output_collision_key(source): source for source, _ in tasks}
    for source, output in tasks:
        key = _output_collision_key(output)
        previous = destinations.get(key)
        if previous is not None and Path(previous).resolve() != Path(source).resolve():
            raise OutputCollisionError(
                f"multiple inputs map to the same output: {previous}, {source} -> {output}"
            )
        clashing_source = sources.get(key)
        if clashing_source is not None and key != _output_collision_key(source):
            raise OutputCollisionError(
                f"output would overwrite another input in the same batch: "
                f"{source} -> {output} (also an input)"
            )
        destinations[key] = source


def validate_aggregate_output_path(inputs: Sequence[str], output: str) -> None:
    """Reject an aggregate output that aliases any of its source paths.

    Aggregate commands intentionally map several inputs to one destination, so
    ``validate_unique_output_paths`` does not apply. Replacing one of those
    inputs after consuming it is still destructive and surprising, even with
    ``--overwrite``.
    """
    output_key = _output_collision_key(output)
    for input_path in inputs:
        if _output_collision_key(input_path) == output_key:
            raise OutputCollisionError(f"aggregate output is also an input: {output}")


@contextmanager
def atomic_output_path(output_path: str, *, overwrite: bool = True) -> Iterator[str]:
    """Yield a private candidate and publish it through a bound directory.

    ``overwrite=False`` enforces no-clobber at the commit point, closing the
    check/encode/replace race shared by long-running encoders. Existing regular
    targets keep their permission bits when overwritten. On POSIX every parent
    component is opened with ``O_NOFOLLOW`` and publication is relative to that
    directory descriptor, so replacing a planned parent with a symlink cannot
    redirect either staging or the final commit outside the selected tree. On
    Windows an open, non-delete-share handle pins every parent and the staging
    directory while reparse-point components are rejected.
    """
    if os.name == "nt":  # pragma: no cover - exercised on Windows CI
        with _atomic_output_path_windows(output_path, overwrite=overwrite) as windows_temporary:
            yield windows_temporary
        return

    target = Path(output_path).absolute()
    try:
        parent_fd = _open_directory_no_symlinks(target.parent)
    except OSError as error:
        raise OutputBoundaryError("output parent contains an unsafe path component") from error
    temporary_dir = Path(tempfile.mkdtemp(prefix="pixshift-output-"))
    with suppress(OSError):
        temporary_dir.chmod(0o700)
    temporary = temporary_dir / target.name
    stage_name = f".pixshift-stage-{secrets.token_hex(12)}"
    stage_created = False
    try:
        yield str(temporary)
        try:
            candidate_stat = temporary.lstat()
        except FileNotFoundError:
            raise OSError("encoder did not create its planned output") from None
        if not stat.S_ISREG(candidate_stat.st_mode):
            raise OSError("encoder output is not a regular file")
        if candidate_stat.st_size == 0:
            raise OSError("encoder created an empty output")

        try:
            target_stat = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            target_stat = None
        if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
            raise OSError("output_not_regular_file")
        output_mode = (
            stat.S_IMODE(target_stat.st_mode)
            if overwrite and target_stat is not None
            else stat.S_IMODE(candidate_stat.st_mode)
        )

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        stage_fd = os.open(stage_name, flags, 0o600, dir_fd=parent_fd)
        stage_created = True
        try:
            with (
                temporary.open("rb") as incoming,
                os.fdopen(stage_fd, "wb", closefd=False) as outgoing,
            ):
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            # ``fchmod`` is absent from the Windows type surface even though
            # this branch is POSIX-only; the dynamic lookup keeps mypy's
            # cross-platform analysis honest without weakening runtime use.
            os_module: Any = os
            os_module.fchmod(stage_fd, output_mode)
        finally:
            os.close(stage_fd)

        if overwrite:
            os.replace(
                stage_name,
                target.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            stage_created = False
        else:
            try:
                os.link(
                    stage_name,
                    target.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                raise FileExistsError("output_exists") from None
            os.unlink(stage_name, dir_fd=parent_fd)
            stage_created = False
        with suppress(OSError):
            os.fsync(parent_fd)
    finally:
        if stage_created:
            with suppress(OSError):
                os.unlink(stage_name, dir_fd=parent_fd)
        os.close(parent_fd)
        shutil.rmtree(temporary_dir, ignore_errors=True)


def _open_directory_no_symlinks(path: Path) -> int:
    """Open/create an absolute directory path one no-follow component at a time."""
    absolute = path.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor or os.sep, flags)
    try:
        for component in absolute.parts[1:]:
            if component in {"", ".", ".."}:
                raise OSError("unsafe output parent component")
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                with suppress(FileExistsError):
                    os.mkdir(component, 0o755, dir_fd=descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


_WINDOWS_FILE_ATTRIBUTE_DIRECTORY = 0x10
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _validate_windows_parent_chain(components: Iterable[tuple[str, int]]) -> None:
    """Reject Windows parent components that can redirect path traversal.

    ``attributes`` are the Win32 ``FILE_ATTRIBUTE_*`` bits read from an open
    handle. Keeping this policy separate from the system calls makes the
    fail-closed decision testable on every supported platform.
    """
    for _component, attributes in components:
        if attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
            raise OutputBoundaryError("output parent contains a reparse point")
        if not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY:
            raise OutputBoundaryError("output parent contains a non-directory component")


def _windows_directory_prefixes(path: Path) -> list[Path]:
    """Return an absolute Windows directory path one component at a time."""
    absolute = Path(os.path.abspath(path))
    if not absolute.anchor:
        raise OutputBoundaryError("output parent is not absolute")
    prefixes = [Path(absolute.anchor)]
    current = prefixes[0]
    for component in absolute.parts[1:]:
        if component in {"", ".", ".."}:
            raise OutputBoundaryError("output parent contains an unsafe path component")
        current /= component
        prefixes.append(current)
    return prefixes


def _open_windows_directory(path: Path) -> tuple[int, int]:
    """Open one directory without traversing a final reparse point."""
    import ctypes
    from ctypes import wintypes

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("file_attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    get_information.restype = wintypes.BOOL

    # Omitting FILE_SHARE_DELETE is intentional: while this handle is alive,
    # the directory cannot be renamed or replaced by a junction. Handles for
    # every ancestor are held until publication completes.
    handle = create_file(
        str(path),
        0x80,  # FILE_READ_ATTRIBUTES
        0x1 | 0x2,  # FILE_SHARE_READ | FILE_SHARE_WRITE
        None,
        3,  # OPEN_EXISTING
        0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]

    info = FileAttributeTagInfo()
    # FileAttributeTagInfo == 9 in FILE_INFO_BY_HANDLE_CLASS.
    if not get_information(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
        kernel32.CloseHandle(handle)
        raise error
    return int(handle), int(info.file_attributes)


def _close_windows_directory(handle: int) -> None:
    """Close a Win32 directory handle."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CloseHandle(wintypes.HANDLE(handle))


@contextmanager
def _open_windows_directory_chain(path: Path) -> Iterator[None]:
    """Create, validate, and bind every Windows output-parent component."""
    handles: list[int] = []
    try:
        try:
            for index, component in enumerate(_windows_directory_prefixes(path)):
                if index:
                    with suppress(FileExistsError):
                        os.mkdir(component)
                handle, attributes = _open_windows_directory(component)
                try:
                    _validate_windows_parent_chain([(str(component), attributes)])
                except Exception:
                    _close_windows_directory(handle)
                    raise
                handles.append(handle)
        except OutputBoundaryError:
            raise
        except OSError as error:
            raise OutputBoundaryError("output parent contains an unsafe path component") from error
        yield
    finally:
        for handle in reversed(handles):
            _close_windows_directory(handle)


@contextmanager
def _bind_windows_directory(path: Path) -> Iterator[None]:
    """Validate and hold one existing Windows directory against replacement."""
    handle, attributes = _open_windows_directory(path)
    try:
        _validate_windows_parent_chain([(str(path), attributes)])
        yield
    finally:
        _close_windows_directory(handle)


@contextmanager
def _atomic_output_path_windows(
    output_path: str, *, overwrite: bool
) -> Iterator[str]:  # pragma: no cover - exercised on Windows CI
    """Publish while Win32 handles bind every non-reparse parent component."""
    target = Path(output_path).absolute()
    with _open_windows_directory_chain(target.parent):
        original_mode: int | None = None
        try:
            target_stat = target.lstat()
        except FileNotFoundError:
            target_stat = None
        if target_stat is not None:
            if not stat.S_ISREG(target_stat.st_mode):
                raise OSError("output_not_regular_file")
            original_mode = stat.S_IMODE(target_stat.st_mode)

        temporary_dir = Path(tempfile.mkdtemp(prefix=".pixshift-output-", dir=target.parent))
        # mkdtemp is private by contract, but make the invariant explicit even
        # on platforms whose default ACL/umask policy is unusual.
        with suppress(OSError):
            temporary_dir.chmod(0o700)
        temporary = temporary_dir / target.name
        try:
            # The private staging directory is itself attacker-replaceable by
            # anyone who can write the output parent. Bind it before yielding
            # its path, otherwise it could be swapped for an outside junction.
            with _bind_windows_directory(temporary_dir):
                try:
                    yield str(temporary)
                    try:
                        candidate_stat = temporary.lstat()
                    except FileNotFoundError:
                        raise OSError("encoder did not create its planned output") from None
                    if not stat.S_ISREG(candidate_stat.st_mode):
                        raise OSError("encoder output is not a regular file")
                    if candidate_stat.st_size == 0:
                        raise OSError("encoder created an empty output")
                    # "rb+" rather than "rb": Windows' os.fsync (_commit)
                    # requires a write-capable handle and fails with EBADF on
                    # a read-only one.
                    with temporary.open("rb+") as stream:
                        os.fsync(stream.fileno())
                    if overwrite:
                        # Re-read at commit time: preserve the object actually
                        # being overwritten, not the stale pre-encode mode.
                        try:
                            commit_stat = target.lstat()
                        except FileNotFoundError:
                            commit_stat = None
                        if commit_stat is not None and not stat.S_ISREG(commit_stat.st_mode):
                            raise OSError("output_not_regular_file")
                        commit_mode = (
                            stat.S_IMODE(commit_stat.st_mode)
                            if commit_stat is not None
                            else original_mode
                        )
                        if commit_mode is not None:
                            temporary.chmod(commit_mode)
                    if overwrite:
                        os.replace(temporary, target)
                    else:
                        try:
                            os.rename(temporary, target)
                        except FileExistsError:
                            raise FileExistsError("output_exists") from None
                finally:
                    # Delete only the expected candidate while the staging
                    # directory remains bound. Never recursively delete an
                    # attacker-writable directory tree.
                    with suppress(OSError):
                        temporary.unlink()
        finally:
            # RemoveDirectory removes a junction itself rather than traversing
            # it if an attacker wins the small post-close cleanup race.
            with suppress(OSError):
                temporary_dir.rmdir()


def atomic_write_bytes(output_path: str, data: bytes, *, overwrite: bool = True) -> None:
    """Write bytes through the shared atomic replacement boundary."""
    with atomic_output_path(output_path, overwrite=overwrite) as temporary:
        Path(temporary).write_bytes(data)


def atomic_copy_file(input_path: str, output_path: str, *, overwrite: bool = True) -> None:
    """Copy a file through the shared atomic replacement boundary."""
    with atomic_output_path(output_path, overwrite=overwrite) as temporary:
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

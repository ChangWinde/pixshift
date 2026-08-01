"""Operation wrappers for image conversion workflows."""

from typing import Any

from ..converter import ConvertResult, PixShiftConverter, collect_files, generate_output_path


def collect_convert_files(
    input_paths: list[str], input_format: str | None, recursive: bool
) -> list[str]:
    """Collect candidate files for convert command."""
    return collect_files(input_paths, input_format, recursive)


def build_convert_tasks(
    files: list[str],
    output_format: str,
    output_dir: str | None,
    prefix: str,
    suffix: str,
    flatten: bool,
    source_paths: list[str],
) -> list[tuple[str, str]]:
    """Build input/output pairs for conversion."""
    tasks: list[tuple[str, str]] = []
    for file_path in files:
        out_path = generate_output_path(
            file_path,
            output_format,
            output_dir,
            prefix,
            suffix,
            flatten,
            source_paths=source_paths,
        )
        tasks.append((file_path, out_path))
    return tasks


def convert_one(
    input_path: str, output_path: str, converter_kwargs: dict[str, Any]
) -> ConvertResult:
    """Convert one file with provided converter options."""
    converter = PixShiftConverter(**converter_kwargs)
    return converter.convert_single(input_path, output_path)

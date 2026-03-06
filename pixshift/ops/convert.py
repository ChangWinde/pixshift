"""Operation wrappers for image conversion workflows."""

from typing import Dict, List, Optional, Tuple

from ..converter import PixShiftConverter, collect_files, generate_output_path


def collect_convert_files(input_paths: List[str], input_format: Optional[str], recursive: bool) -> List[str]:
    """Collect candidate files for convert command."""
    return collect_files(input_paths, input_format, recursive)


def build_convert_tasks(
    files: List[str],
    output_format: str,
    output_dir: Optional[str],
    prefix: str,
    suffix: str,
    flatten: bool,
    source_paths: List[str],
) -> List[Tuple[str, str]]:
    """Build input/output pairs for conversion."""
    tasks: List[Tuple[str, str]] = []
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


def convert_one(input_path: str, output_path: str, converter_kwargs: Dict) -> object:
    """Convert one file with provided converter options."""
    converter = PixShiftConverter(**converter_kwargs)
    return converter.convert_single(input_path, output_path)


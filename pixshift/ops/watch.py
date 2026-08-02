"""Operation wrappers for watch workflows."""

from collections.abc import Callable

from ..watch_engine import DirectoryWatcher, WatchConfig, collect_watch_files


def make_config(
    watch_dir: str,
    output_dir: str,
    output_format: str,
    quality: str,
    input_format: str | None,
    recursive: bool,
    interval: float,
    keep_exif: bool,
    overwrite: bool,
) -> WatchConfig:
    """Create watch configuration object."""
    return WatchConfig(
        watch_dir=watch_dir,
        output_dir=output_dir,
        output_format=output_format,
        quality=quality,
        input_format=input_format,
        recursive=recursive,
        interval=interval,
        keep_exif=keep_exif,
        overwrite=overwrite,
    )


def create_watcher(
    config: WatchConfig,
    on_new_file: Callable[..., None] | None = None,
    on_status: Callable[..., None] | None = None,
) -> DirectoryWatcher:
    """Create watch runner object."""
    return DirectoryWatcher(config=config, on_new_file=on_new_file, on_status=on_status)


def collect_files(config: WatchConfig) -> list[str]:
    """Collect files using the same exclusions as continuous watch mode."""
    return collect_watch_files(config)

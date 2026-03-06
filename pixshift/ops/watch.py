"""Operation wrappers for watch workflows."""

from ..watch_engine import DirectoryWatcher, WatchConfig


def make_config(
    watch_dir: str,
    output_dir: str,
    output_format: str,
    quality: str,
    input_format,
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


def create_watcher(config: WatchConfig, on_new_file=None, on_status=None) -> DirectoryWatcher:
    """Create watch runner object."""
    return DirectoryWatcher(config=config, on_new_file=on_new_file, on_status=on_status)


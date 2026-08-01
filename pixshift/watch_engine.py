"""
PixShift Watch Engine — 目录监控自动转换

功能:
  - 监控指定目录，有新图片自动转换
  - 支持指定输出格式和目录
  - 支持文件过滤（只监控特定格式）
  - 防重复处理（记录已处理文件）
  - 优雅退出（Ctrl+C）
"""

import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from .converter import (
    SUPPORTED_INPUT_FORMATS,
    PixShiftConverter,
    generate_output_path,
)
from .core.defaults import DEFAULT_WATCH_FORMAT, DEFAULT_WATCH_QUALITY

# ============================================================
#  数据结构
# ============================================================


@dataclass
class WatchConfig:
    """监控配置"""

    watch_dir: str = ""
    output_dir: str = ""
    output_format: str = DEFAULT_WATCH_FORMAT
    quality: str = DEFAULT_WATCH_QUALITY
    input_format: str | None = None
    recursive: bool = False
    interval: float = 2.0  # 扫描间隔（秒）
    keep_exif: bool = True
    overwrite: bool = False


@dataclass
class WatchStats:
    """监控统计"""

    files_processed: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    total_input_size: int = 0
    total_output_size: int = 0
    start_time: float = 0.0


# ============================================================
#  目录监控器
# ============================================================


class DirectoryWatcher:
    """
    目录监控器

    使用轮询方式监控目录变化（无需额外依赖）
    """

    def __init__(
        self,
        config: WatchConfig,
        on_new_file: Callable[..., None] | None = None,
        on_status: Callable[..., None] | None = None,
    ) -> None:
        self.config = config
        self.on_new_file = on_new_file
        self.on_status = on_status
        self.processed_files: set[str] = set()
        self.stats = WatchStats()
        self._running = False
        self._converter = PixShiftConverter(
            quality=config.quality,
            keep_exif=config.keep_exif,
            overwrite=config.overwrite,
        )

    def start(self) -> WatchStats:
        """开始监控"""
        self._running = True
        self.stats.start_time = time.time()

        # 注册信号处理
        original_sigint = signal.getsignal(signal.SIGINT)

        def _handle_sigint(signum: int, frame: FrameType | None) -> None:
            self._running = False
            if self.on_status:
                self.on_status("stop", "收到停止信号，正在退出...")

        signal.signal(signal.SIGINT, _handle_sigint)

        try:
            # 初始扫描：记录已有文件
            existing = self._scan_directory()
            self.processed_files = set(existing)

            if self.on_status:
                self.on_status("start", f"开始监控 {self.config.watch_dir}")
                self.on_status("info", f"已有 {len(existing)} 个文件，等待新文件...")

            # 主循环
            while self._running:
                current_files = set(self._scan_directory())
                new_files = current_files - self.processed_files

                for filepath in sorted(new_files):
                    if not self._running:
                        break

                    # 等待文件写入完成
                    if not self._wait_for_file(filepath):
                        continue

                    self._process_file(filepath)
                    self.processed_files.add(filepath)

                time.sleep(self.config.interval)

        finally:
            signal.signal(signal.SIGINT, original_sigint)

        return self.stats

    def stop(self) -> None:
        """停止监控"""
        self._running = False

    def _scan_directory(self) -> list[str]:
        """扫描目录中的图片文件"""
        return collect_watch_files(self.config)

    def _wait_for_file(self, filepath: str, timeout: float = 10.0) -> bool:
        """等待文件写入完成（大小不再变化）"""
        try:
            prev_size = -1
            waited = 0.0
            while waited < timeout:
                current_size = os.path.getsize(filepath)
                if current_size == prev_size and current_size > 0:
                    return True
                prev_size = current_size
                time.sleep(0.5)
                waited += 0.5
            return os.path.exists(filepath) and os.path.getsize(filepath) > 0
        except Exception:
            return False

    def _process_file(self, filepath: str) -> None:
        """处理单个新文件"""
        try:
            output_dir = self.config.output_dir or str(Path(self.config.watch_dir) / "converted")

            output_path = generate_output_path(
                filepath,
                self.config.output_format,
                output_dir=output_dir,
                source_paths=[self.config.watch_dir],
            )

            if os.path.isfile(output_path) and not self.config.overwrite:
                self.processed_files.add(filepath)
                self.stats.files_skipped += 1
                if self.on_new_file:
                    self.on_new_file("skipped", filepath)
                return

            if self.on_new_file:
                self.on_new_file("processing", filepath)

            result = self._converter.convert_single(filepath, output_path)

            if result.success:
                self.processed_files.add(str(Path(output_path).resolve()))
                self.stats.files_processed += 1
                self.stats.total_input_size += result.input_size
                self.stats.total_output_size += result.output_size

                if self.on_new_file:
                    self.on_new_file("success", filepath, result)
            else:
                self.stats.files_failed += 1
                if self.on_new_file:
                    self.on_new_file("failed", filepath, result)

        except Exception as e:
            self.stats.files_failed += 1
            if self.on_new_file:
                self.on_new_file("error", filepath, str(e))


def _is_within(path: Path, root: Path) -> bool:
    """Return whether ``path`` is equal to or below ``root``."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def collect_watch_files(config: WatchConfig) -> list[str]:
    """Collect watch inputs while excluding the generated-output subtree."""
    files: list[str] = []
    watch_path = Path(config.watch_dir).resolve()
    output_path = Path(config.output_dir or watch_path / "converted").resolve()
    output_is_subtree = output_path != watch_path and _is_within(output_path, watch_path)
    if not watch_path.is_dir():
        return files

    pattern = "**/*" if config.recursive else "*"
    for item in watch_path.glob(pattern):
        if not item.is_file():
            continue
        resolved_item = item.resolve()
        if output_is_subtree and _is_within(resolved_item, output_path):
            continue
        extension = item.suffix.lower()
        if config.input_format:
            target_extension = f".{config.input_format.lower().lstrip('.')}"
            if extension != target_extension:
                continue
        elif extension not in SUPPORTED_INPUT_FORMATS:
            continue
        files.append(str(resolved_item))
    return sorted(files)

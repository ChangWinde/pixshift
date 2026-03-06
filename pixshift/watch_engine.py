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
import sys
import time
import signal
from pathlib import Path
from typing import Optional, List, Set, Callable
from dataclasses import dataclass, field

from .converter import (
    SUPPORTED_INPUT_FORMATS,
    PixShiftConverter,
    generate_output_path,
    _human_size,
)


# ============================================================
#  数据结构
# ============================================================

@dataclass
class WatchConfig:
    """监控配置"""
    watch_dir: str = ""
    output_dir: str = ""
    output_format: str = "webp"
    quality: str = "max"
    input_format: Optional[str] = None
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
        on_new_file: Optional[Callable] = None,
        on_status: Optional[Callable] = None,
    ):
        self.config = config
        self.on_new_file = on_new_file
        self.on_status = on_status
        self.processed_files: Set[str] = set()
        self.stats = WatchStats()
        self._running = False
        self._converter = PixShiftConverter(
            quality=config.quality,
            keep_exif=config.keep_exif,
            overwrite=config.overwrite,
        )

    def start(self):
        """开始监控"""
        self._running = True
        self.stats.start_time = time.time()

        # 注册信号处理
        original_sigint = signal.getsignal(signal.SIGINT)

        def _handle_sigint(signum, frame):
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

    def stop(self):
        """停止监控"""
        self._running = False

    def _scan_directory(self) -> List[str]:
        """扫描目录中的图片文件"""
        files = []
        watch_path = Path(self.config.watch_dir)

        if not watch_path.is_dir():
            return files

        pattern = "**/*" if self.config.recursive else "*"

        for item in watch_path.glob(pattern):
            if not item.is_file():
                continue

            ext = item.suffix.lower()

            # 过滤格式
            if self.config.input_format:
                target_ext = f".{self.config.input_format.lower().lstrip('.')}"
                if ext != target_ext:
                    continue
            elif ext not in SUPPORTED_INPUT_FORMATS:
                continue

            files.append(str(item.resolve()))

        return files

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

    def _process_file(self, filepath: str):
        """处理单个新文件"""
        try:
            output_dir = self.config.output_dir or str(
                Path(self.config.watch_dir) / "converted"
            )

            output_path = generate_output_path(
                filepath,
                self.config.output_format,
                output_dir=output_dir,
            )

            if self.on_new_file:
                self.on_new_file("processing", filepath)

            result = self._converter.convert_single(filepath, output_path)

            if result.success:
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

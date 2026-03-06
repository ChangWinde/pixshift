"""Registration for convert command."""

import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from ..converter import (
    BatchResult,
    SUPPORTED_INPUT_FORMATS,
)
from ..ops import convert as convert_ops
from ..presenters.cli_presenters import print_failures, show_dry_run_table
from ..presenters.json_presenters import emit_json, emit_json_and_exit


def _convert_worker(args: Tuple[str, str, Dict]) -> object:
    """Multiprocessing worker for conversion."""
    input_path, output_path, converter_kwargs = args
    return convert_ops.convert_one(input_path, output_path, converter_kwargs)


def register_convert_command(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size,
) -> None:
    """Register convert command on root CLI group."""

    @cli_group.command("convert")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-t", "--to", "output_format", required=True,
                  help="[必填] 目标格式. 可选: png|jpg|webp|tiff|bmp|gif|heic|avif|pdf|ico|tga")
    @click.option("-f", "--from", "input_format", default=None,
                  help="只转换指定输入格式, 如 -f heic. 默认: 自动识别所有支持格式")
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(),
                  help="输出目录路径. 默认: 与输入文件同目录")
    @click.option("-q", "--quality", default="max",
                  type=click.Choice(["max", "high", "medium", "low", "web"], case_sensitive=False),
                  help="质量等级. 可选: max|high|medium|low|web. 默认: max(最高质量)")
    @click.option("-r", "--recursive", is_flag=True, default=False,
                  help="递归处理子目录中的所有图片. 默认: 仅当前目录")
    @click.option("--resize", default=None, type=str,
                  help="调整尺寸. 格式: WxH(如 1920x1080) 或 N%%(如 50%%). 默认: 不调整")
    @click.option("--max-size", default=None, type=int,
                  help="最大边长限制(px), 保持宽高比缩放, 如 2048. 默认: 不限制")
    @click.option("--overwrite", is_flag=True, default=False,
                  help="覆盖已存在的输出文件. 默认: 跳过已存在文件")
    @click.option("--prefix", default="",
                  help="输出文件名添加前缀, 如 --prefix thumb_. 默认: 无")
    @click.option("--suffix", default="",
                  help="输出文件名添加后缀, 如 --suffix _hd. 默认: 无")
    @click.option("--strip-alpha", is_flag=True, default=False,
                  help="移除透明通道, 用 --bg-color 指定的颜色填充. 默认: 保留透明通道")
    @click.option("--no-exif", is_flag=True, default=False,
                  help="不保留 EXIF 元数据(拍摄参数等). 默认: 保留")
    @click.option("--no-icc", is_flag=True, default=False,
                  help="不保留 ICC 颜色配置文件. 默认: 保留")
    @click.option("--no-orient", is_flag=True, default=False,
                  help="不根据 EXIF Orientation 自动旋转. 默认: 自动旋转")
    @click.option("-j", "--jobs", default=0, type=int,
                  help="并行进程数. 默认: 0(自动=CPU核心数)")
    @click.option("--flatten", is_flag=True, default=False,
                  help="所有输出文件放同一目录, 不保持子目录结构. 默认: 保持结构")
    @click.option("--dry-run", is_flag=True, default=False,
                  help="预览模式, 只列出将执行的操作, 不实际转换")
    @click.option("--bg-color", default="255,255,255",
                  help="透明通道替换背景色, 格式 R,G,B. 默认: 255,255,255(白色)")
    @click.option("--json", "as_json", is_flag=True, default=False,
                  help="以 JSON 输出结果（适合脚本调用）")
    def convert(
        inputs: tuple,
        output_format: str,
        input_format: Optional[str],
        output_dir: Optional[str],
        quality: str,
        recursive: bool,
        resize: Optional[str],
        max_size: Optional[int],
        overwrite: bool,
        prefix: str,
        suffix: str,
        strip_alpha: bool,
        no_exif: bool,
        no_icc: bool,
        no_orient: bool,
        jobs: int,
        flatten: bool,
        dry_run: bool,
        bg_color: str,
        as_json: bool,
    ) -> None:
        """🔄 转换图片格式 (支持单文件/目录/批量, 自动多核并行)"""
        if not as_json:
            console.print(f"\n{mini_logo} [bold]图片格式转换[/bold]\n")

        try:
            resize_tuple, resize_percent = _parse_resize(resize)
        except ValueError:
            if as_json:
                emit_json_and_exit({"command": "convert", "ok": False, "error": "invalid_resize"}, 1)
            console.print("[red]❌ resize 格式错误, 请使用 WxH 或 百分比%[/red]")
            sys.exit(1)

        try:
            bg_rgb = tuple(int(x.strip()) for x in bg_color.split(","))
            if len(bg_rgb) != 3:
                raise ValueError("bg-color requires 3 channels")
        except Exception:
            if as_json:
                emit_json_and_exit({"command": "convert", "ok": False, "error": "invalid_bg_color"}, 1)
            console.print("[red]❌ bg-color 格式错误, 请使用 R,G,B[/red]")
            sys.exit(1)

        if as_json:
            files = convert_ops.collect_convert_files(list(inputs), input_format, recursive)
        else:
            with console.status("[bold cyan]🔍 扫描文件中...[/bold cyan]"):
                files = convert_ops.collect_convert_files(list(inputs), input_format, recursive)

        if not files:
            if as_json:
                emit_json({
                    "command": "convert",
                    "ok": True,
                    "total": 0,
                    "message": "no_files",
                })
            else:
                console.print("[yellow]⚠️  未找到可转换的图片文件[/yellow]")
                if input_format:
                    console.print(f"   (筛选格式: .{input_format})")
                console.print(f"   支持的输入格式: {', '.join(sorted(SUPPORTED_INPUT_FORMATS))}")
            return

        tasks = convert_ops.build_convert_tasks(
            files=files,
            output_format=output_format,
            output_dir=output_dir,
            prefix=prefix,
            suffix=suffix,
            flatten=flatten,
            source_paths=list(inputs),
        )

        if dry_run:
            if as_json:
                emit_json({
                    "command": "convert",
                    "mode": "dry_run",
                    "ok": True,
                    "total": len(tasks),
                    "output_format": output_format.lower(),
                    "quality": quality,
                    "preview": [{"input": inp, "output": out} for inp, out in tasks[:50]],
                })
            else:
                show_dry_run_table(console, tasks, output_format.upper(), quality)
            return

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        if not as_json:
            console.print(f"  📁 找到 [bold green]{len(tasks)}[/bold green] 个文件")
            console.print(f"  🎯 目标格式: [bold cyan]{output_format.upper()}[/bold cyan]")
            console.print(f"  💎 质量等级: [bold]{quality}[/bold]")
            if output_dir:
                console.print(f"  📂 输出目录: [bold]{output_dir}[/bold]")
            if resize:
                console.print(f"  📐 调整大小: [bold]{resize}[/bold]")
            console.print()

        converter_kwargs: Dict = {
            "quality": quality,
            "resize": resize_tuple,
            "resize_percent": resize_percent,
            "max_size": max_size,
            "keep_exif": not no_exif,
            "keep_icc": not no_icc,
            "overwrite": overwrite,
            "strip_alpha": strip_alpha,
            "background_color": bg_rgb,
            "auto_orient": not no_orient,
        }

        if jobs <= 0:
            jobs = min(multiprocessing.cpu_count(), len(tasks))
        jobs = min(jobs, len(tasks))

        batch_result = BatchResult(total=len(tasks))
        start_time = time.time()
        worker_args = [(inp, out, converter_kwargs) for inp, out in tasks]

        if as_json:
            if jobs == 1 or len(tasks) == 1:
                for inp, out in tasks:
                    result = convert_ops.convert_one(inp, out, converter_kwargs)
                    batch_result.results.append(result)
                    if result.success:
                        batch_result.success += 1
                    else:
                        batch_result.failed += 1
            else:
                with ProcessPoolExecutor(max_workers=jobs) as executor:
                    futures = {
                        executor.submit(_convert_worker, arg): arg
                        for arg in worker_args
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        batch_result.results.append(result)
                        if result.success:
                            batch_result.success += 1
                        else:
                            batch_result.failed += 1
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=40),
                MofNCompleteColumn(),
                TextColumn("•"),
                TimeElapsedColumn(),
                TextColumn("•"),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("转换中", total=len(tasks))

                if jobs == 1 or len(tasks) == 1:
                    for inp, out in tasks:
                        result = convert_ops.convert_one(inp, out, converter_kwargs)
                        batch_result.results.append(result)
                        if result.success:
                            batch_result.success += 1
                        else:
                            batch_result.failed += 1
                        progress.advance(task_id)
                else:
                    with ProcessPoolExecutor(max_workers=jobs) as executor:
                        futures = {
                            executor.submit(_convert_worker, arg): arg
                            for arg in worker_args
                        }
                        for future in as_completed(futures):
                            result = future.result()
                            batch_result.results.append(result)
                            if result.success:
                                batch_result.success += 1
                            else:
                                batch_result.failed += 1
                            progress.advance(task_id)

        batch_result.total_duration = time.time() - start_time
        batch_result.total_input_size = sum(r.input_size for r in batch_result.results)
        batch_result.total_output_size = sum(r.output_size for r in batch_result.results if r.success)
        if as_json:
            errors = [
                {"input": r.input_path, "output": r.output_path, "error": r.error}
                for r in batch_result.results
                if not r.success
            ]
            payload = {
                "command": "convert",
                "ok": batch_result.failed == 0,
                "total": batch_result.total,
                "success": batch_result.success,
                "failed": batch_result.failed,
                "output_format": output_format.lower(),
                "quality": quality,
                "input_bytes": batch_result.total_input_size,
                "output_bytes": batch_result.total_output_size,
                "duration_sec": round(batch_result.total_duration, 4),
                "errors": errors,
            }
            if batch_result.failed > 0:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
        else:
            _show_convert_summary(console, batch_result, jobs, human_size)


def _parse_resize(resize: Optional[str]) -> Tuple[Optional[Tuple[int, int]], Optional[float]]:
    """Parse resize expression into tuple or percent."""
    if not resize:
        return None, None
    if "%" in resize:
        return None, float(resize.replace("%", ""))
    if "x" in resize.lower():
        parts = resize.lower().split("x")
        return (int(parts[0]), int(parts[1])), None
    raise ValueError("invalid resize expression")


def _show_convert_summary(console: Console, batch: BatchResult, jobs: int, human_size) -> None:
    """Render convert command summary panel."""
    console.print()
    failed = [r for r in batch.results if not r.success]
    if failed:
        errors = [f"{os.path.basename(r.input_path)}: {r.error}" for r in failed]
        print_failures(console, errors)

    ratio = ""
    if batch.total_input_size > 0 and batch.total_output_size > 0:
        pct = (batch.total_output_size / batch.total_input_size) * 100
        if pct < 100:
            ratio = (
                f"  📉 压缩率: [green]{pct:.1f}%[/green] "
                f"(节省 {human_size(batch.total_input_size - batch.total_output_size)})"
            )
        else:
            ratio = f"  📈 体积变化: [yellow]{pct:.1f}%[/yellow]"

    speed = ""
    if batch.total_duration > 0:
        fps = batch.success / batch.total_duration
        speed = f"  ⚡ 速度: [bold]{fps:.1f}[/bold] 张/秒 ({jobs} 核并行)"

    summary = (
        f"  ✅ 成功: [bold green]{batch.success}[/bold green]"
        f"  ❌ 失败: [bold red]{batch.failed}[/bold red]"
        f"  📊 总计: [bold]{batch.total}[/bold]\n"
        f"  📦 输入: {human_size(batch.total_input_size)}"
        f"  →  输出: {human_size(batch.total_output_size)}\n"
        f"{ratio}\n"
        f"{speed}\n"
        f"  ⏱️  耗时: [bold]{batch.total_duration:.2f}s[/bold]"
    )

    console.print(Panel(
        summary,
        title="[bold]📊 转换完成[/bold]",
        border_style="green" if batch.failed == 0 else "yellow",
        box=box.ROUNDED,
    ))
    console.print()


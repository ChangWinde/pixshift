"""Registration for convert command."""

import math
import multiprocessing
import os
import time
from collections.abc import Callable
from typing import Any

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
    SUPPORTED_INPUT_FORMATS,
    SUPPORTED_OUTPUT_FORMATS,
    BatchResult,
    ConvertResult,
)
from ..core.defaults import DEFAULT_CONVERT_QUALITY
from ..core.files import filter_generated_inputs, partition_existing_outputs
from ..core.parallel import bounded_worker_count
from ..ops import convert as convert_ops
from ..presenters.cli_presenters import print_failures, show_dry_run_table
from ..presenters.json_presenters import emit_json, emit_json_and_exit
from .common import (
    selection_filters_or_exit,
    selection_options,
    usage_error_or_exit,
    validate_affixes_or_exit,
    validate_tasks_or_exit,
)


def _convert_worker(args: tuple[str, str, dict[str, Any]]) -> ConvertResult:
    """Multiprocessing worker for conversion."""
    input_path, output_path, converter_kwargs = args
    return convert_ops.convert_one(input_path, output_path, converter_kwargs)


def _convert_indexed_worker(
    item: tuple[int, tuple[str, str, dict[str, Any]]],
) -> tuple[int, ConvertResult]:
    """Return the task index so unordered completion stays deterministic."""
    index, arguments = item
    return index, _convert_worker(arguments)


def _run_converter_tasks(
    worker_args: list[tuple[str, str, dict[str, Any]]],
    jobs: int,
    on_result: Callable[[], None] | None = None,
) -> list[ConvertResult]:
    """Run conversions in order and terminate workers promptly on cancellation."""
    if jobs <= 1 or len(worker_args) <= 1:
        results = []
        for arguments in worker_args:
            results.append(_convert_worker(arguments))
            if on_result is not None:
                on_result()
        return results
    ordered: list[ConvertResult | None] = [None] * len(worker_args)
    pool = multiprocessing.Pool(processes=jobs)
    try:
        for index, result in pool.imap_unordered(_convert_indexed_worker, enumerate(worker_args)):
            ordered[index] = result
            if on_result is not None:
                on_result()
        pool.close()
    except BaseException:
        pool.terminate()
        raise
    finally:
        pool.join()
    return [result for result in ordered if result is not None]


def register_convert_command(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register convert command on root CLI group."""

    @cli_group.command("convert")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "-t",
        "--to",
        "output_format",
        required=True,
        type=click.Choice(sorted(SUPPORTED_OUTPUT_FORMATS), case_sensitive=False),
        help="目标格式；选项按当前运行环境探测",
    )
    @click.option(
        "-f",
        "--from",
        "input_format",
        default=None,
        help="只转换指定输入格式, 如 -f heic. 默认: 自动识别所有支持格式",
    )
    @click.option(
        "-o",
        "--output",
        "output_dir",
        default=None,
        type=click.Path(),
        help="输出目录路径. 默认: 与输入文件同目录",
    )
    @click.option(
        "-q",
        "--quality",
        default=DEFAULT_CONVERT_QUALITY,
        type=click.Choice(["max", "high", "medium", "low", "web"], case_sensitive=False),
        help="质量等级. 默认: high(平衡质量、体积与速度); max 需显式选择",
    )
    @click.option(
        "-r",
        "--recursive",
        is_flag=True,
        default=False,
        help="递归处理子目录中的所有图片. 默认: 仅当前目录",
    )
    @click.option(
        "--resize",
        default=None,
        type=str,
        help="调整尺寸. 格式: WxH(如 1920x1080) 或 N%%(如 50%%). 默认: 不调整",
    )
    @click.option(
        "--max-size",
        default=None,
        type=click.IntRange(1),
        help="最大边长限制(px), 保持宽高比缩放, 如 2048. 默认: 不限制",
    )
    @click.option(
        "--overwrite",
        is_flag=True,
        default=False,
        help="覆盖已存在的输出文件. 默认: 跳过已存在文件",
    )
    @click.option("--prefix", default="", help="输出文件名添加前缀, 如 --prefix thumb_. 默认: 无")
    @click.option("--suffix", default="", help="输出文件名添加后缀, 如 --suffix _hd. 默认: 无")
    @click.option(
        "--strip-alpha",
        is_flag=True,
        default=False,
        help="移除透明通道, 用 --bg-color 指定的颜色填充. 默认: 保留透明通道",
    )
    @click.option(
        "--no-exif", is_flag=True, default=False, help="不保留 EXIF 元数据(拍摄参数等). 默认: 保留"
    )
    @click.option(
        "--no-icc", is_flag=True, default=False, help="不保留 ICC 颜色配置文件. 默认: 保留"
    )
    @click.option(
        "--color-space",
        default="preserve",
        type=click.Choice(["preserve", "srgb"], case_sensitive=False),
        help="色彩策略: preserve 保留源空间；srgb 经 ICC 转换为 sRGB",
    )
    @click.option(
        "--no-orient",
        is_flag=True,
        default=False,
        help="不根据 EXIF Orientation 自动旋转. 默认: 自动旋转",
    )
    @click.option(
        "-j",
        "--jobs",
        default=0,
        type=click.IntRange(0),
        help="并行进程数. 默认: 0(自动, 最多 8 个进程)",
    )
    @click.option(
        "--flatten",
        is_flag=True,
        default=False,
        help="所有输出文件放同一目录, 不保持子目录结构. 默认: 保持结构",
    )
    @click.option(
        "--dry-run", is_flag=True, default=False, help="预览模式, 只列出将执行的操作, 不实际转换"
    )
    @click.option(
        "--bg-color",
        default="255,255,255",
        help="透明通道替换背景色, 格式 R,G,B. 默认: 255,255,255(白色)",
    )
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    @selection_options
    def convert(
        inputs: tuple,
        output_format: str,
        input_format: str | None,
        output_dir: str | None,
        quality: str,
        recursive: bool,
        resize: str | None,
        max_size: int | None,
        overwrite: bool,
        prefix: str,
        suffix: str,
        strip_alpha: bool,
        no_exif: bool,
        no_icc: bool,
        color_space: str,
        no_orient: bool,
        jobs: int,
        flatten: bool,
        dry_run: bool,
        bg_color: str,
        include_globs: tuple[str, ...],
        exclude_globs: tuple[str, ...],
        min_file_size: str | None,
        as_json: bool,
    ) -> None:
        """转换图片格式，支持单文件、目录和批量并行处理。"""
        validate_affixes_or_exit(
            command="convert",
            as_json=as_json,
            values=(("prefix", prefix), ("suffix", suffix)),
        )
        if not as_json:
            console.print(f"\n{mini_logo} [bold]图片格式转换[/bold]\n")

        try:
            resize_tuple, resize_percent = _parse_resize(resize)
        except ValueError:
            usage_error_or_exit(
                command="convert",
                as_json=as_json,
                error="invalid_resize",
                detail="--resize expects WxH or a percentage like 50%",
                human_message="--resize 参数格式错误，请使用 WxH 或 50% 格式。",
            )

        if resize is not None and max_size is not None:
            usage_error_or_exit(
                command="convert",
                as_json=as_json,
                error="conflicting_options",
                detail="--resize and --max-size cannot be used together",
                human_message="--resize 与 --max-size 不能同时使用",
            )

        try:
            bg_rgb = tuple(int(x.strip()) for x in bg_color.split(","))
            if len(bg_rgb) != 3 or any(not 0 <= channel <= 255 for channel in bg_rgb):
                raise ValueError("bg-color requires 3 channels")
        except Exception:
            usage_error_or_exit(
                command="convert",
                as_json=as_json,
                error="invalid_bg_color",
                detail="--bg-color expects R,G,B with channels in 0-255",
                human_message="--bg-color 参数格式错误，请使用 R,G,B 格式。",
            )

        if as_json:
            files = convert_ops.collect_convert_files(
                list(inputs),
                input_format,
                recursive,
                selection_filters_or_exit(
                    command="convert",
                    as_json=as_json,
                    include_globs=include_globs,
                    exclude_globs=exclude_globs,
                    min_file_size=min_file_size,
                ),
            )
        else:
            with console.status("[bold cyan]正在扫描文件...[/bold cyan]"):
                files = convert_ops.collect_convert_files(
                    list(inputs),
                    input_format,
                    recursive,
                    selection_filters_or_exit(
                        command="convert",
                        as_json=as_json,
                        include_globs=include_globs,
                        exclude_globs=exclude_globs,
                        min_file_size=min_file_size,
                    ),
                )

        files, ignored_generated = filter_generated_inputs(
            files,
            list(inputs),
            output_root=output_dir,
            excluded_extension=output_format if input_format is None else None,
        )

        if not files:
            if as_json:
                emit_json(
                    {
                        "command": "convert",
                        "ok": True,
                        "total": 0,
                        "message": "no_files",
                        "ignored_generated": ignored_generated,
                    }
                )
            else:
                console.print("[yellow]未找到可转换的图片文件。[/yellow]")
                if input_format:
                    console.print(f"  筛选格式：.{input_format}")
                console.print(f"  支持的输入格式：{', '.join(sorted(SUPPORTED_INPUT_FORMATS))}")
            return

        if ignored_generated and not as_json:
            console.print(f"[dim]  已忽略 {ignored_generated} 个既有目标格式或生成文件[/dim]")

        tasks = convert_ops.build_convert_tasks(
            files=files,
            output_format=output_format,
            output_dir=output_dir,
            prefix=prefix,
            suffix=suffix,
            flatten=flatten,
            source_paths=list(inputs),
        )
        validate_tasks_or_exit(command="convert", as_json=as_json, tasks=tasks)
        all_tasks = tasks
        tasks, skipped_tasks = partition_existing_outputs(tasks, overwrite=overwrite)

        if dry_run:
            if as_json:
                skipped_outputs = {output for _, output in skipped_tasks}
                emit_json(
                    {
                        "command": "convert",
                        "mode": "dry_run",
                        "ok": True,
                        "total": len(all_tasks),
                        "pending": len(tasks),
                        "skipped": len(skipped_tasks),
                        "output_format": output_format.lower(),
                        "quality": quality,
                        "color_space": color_space.lower(),
                        "ignored_generated": ignored_generated,
                        "preview": [
                            {
                                "input": inp,
                                "output": out,
                                "action": "skip_existing" if out in skipped_outputs else "convert",
                            }
                            for inp, out in all_tasks
                        ],
                    }
                )
            else:
                show_dry_run_table(console, all_tasks, output_format.upper(), quality)
                if skipped_tasks:
                    console.print(f"[dim]  其中 {len(skipped_tasks)} 个已有输出将跳过[/dim]")
            return

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        if not as_json:
            console.print(f"  文件数: [bold green]{len(tasks)}[/bold green]")
            console.print(f"  目标格式: [bold cyan]{output_format.upper()}[/bold cyan]")
            console.print(f"  质量等级: [bold]{quality}[/bold]")
            if output_dir:
                console.print(f"  输出目录: [bold]{output_dir}[/bold]")
            if resize:
                console.print(f"  尺寸调整: [bold]{resize}[/bold]")
            console.print()

        converter_kwargs: dict = {
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
            "color_space": color_space.lower(),
        }

        jobs = bounded_worker_count(tasks, requested=jobs)

        batch_result = BatchResult(total=len(all_tasks), skipped=len(skipped_tasks))
        start_time = time.time()
        worker_args = [(inp, out, converter_kwargs) for inp, out in tasks]

        if as_json:
            batch_result.results = _run_converter_tasks(worker_args, jobs)
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=40),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("转换中", total=len(tasks))

                batch_result.results = _run_converter_tasks(
                    worker_args,
                    jobs,
                    on_result=lambda: progress.advance(task_id),
                )

        batch_result.success = sum(result.success for result in batch_result.results)
        batch_result.failed = len(batch_result.results) - batch_result.success

        batch_result.total_duration = time.time() - start_time
        batch_result.total_input_size = sum(r.input_size for r in batch_result.results)
        batch_result.total_output_size = sum(
            r.output_size for r in batch_result.results if r.success
        )
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
                "skipped": batch_result.skipped,
                "output_format": output_format.lower(),
                "quality": quality,
                "ignored_generated": ignored_generated,
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
            if batch_result.failed:
                raise click.exceptions.Exit(1)


def _parse_resize(resize: str | None) -> tuple[tuple[int, int] | None, float | None]:
    """Parse resize expression into tuple or percent."""
    if not resize:
        return None, None
    if "%" in resize:
        percent = float(resize.replace("%", ""))
        if not math.isfinite(percent) or percent <= 0:
            raise ValueError("resize percent must be positive")
        return None, percent
    if "x" in resize.lower():
        parts = resize.lower().split("x")
        if len(parts) != 2:
            raise ValueError("resize requires width and height")
        dimensions = (int(parts[0]), int(parts[1]))
        if dimensions[0] <= 0 or dimensions[1] <= 0:
            raise ValueError("resize dimensions must be positive")
        return dimensions, None
    raise ValueError("invalid resize expression")


def _show_convert_summary(
    console: Console,
    batch: BatchResult,
    jobs: int,
    human_size: Callable[[int], str],
) -> None:
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
                f"  压缩率: [green]{pct:.1f}%[/green] "
                f"(节省 {human_size(batch.total_input_size - batch.total_output_size)})"
            )
        else:
            ratio = f"  体积变化: [yellow]{pct:.1f}%[/yellow]"

    speed = ""
    if batch.total_duration > 0 and batch.success > 0:
        fps = batch.success / batch.total_duration
        speed = f"  速度: [bold]{fps:.1f}[/bold] 张/秒（{jobs} 个并行任务）"

    summary = (
        f"  成功: [bold green]{batch.success}[/bold green]"
        f"  失败: [bold red]{batch.failed}[/bold red]"
        f"  跳过: [bold yellow]{batch.skipped}[/bold yellow]"
        f"  总计: [bold]{batch.total}[/bold]\n"
        f"  输入: {human_size(batch.total_input_size)}；"
        f"输出: {human_size(batch.total_output_size)}\n"
        f"{ratio}\n"
        f"{speed}\n"
        f"  耗时: [bold]{batch.total_duration:.2f} 秒[/bold]"
    )

    console.print(
        Panel(
            summary,
            title="[bold]转换完成[/bold]",
            border_style="green" if batch.failed == 0 else "yellow",
            box=box.ROUNDED,
        )
    )
    console.print()

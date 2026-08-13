"""Registration for geometric transform commands: resize and rotate."""

from __future__ import annotations

import functools
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.table import Table

from ..converter import SUPPORTED_INPUT_FORMATS
from ..core.defaults import DEFAULT_CONVERT_QUALITY
from ..core.files import (
    collect_supported_files,
    derivative_output_name,
    filter_generated_inputs,
    partition_existing_outputs,
    plan_output_path,
)
from ..ops import transform as transform_ops
from ..presenters.cli_presenters import batch_progress
from ..presenters.json_presenters import emit_json, emit_json_and_exit
from .common import failure_entry, run_batch_tasks, usage_error_or_exit, validate_tasks_or_exit

_RESIZE_SUFFIX = "_resized"
_ROTATE_SUFFIX = "_rotated"


def _parse_size(size: str) -> tuple[int, int]:
    parts = size.lower().split("x")
    if len(parts) != 2:
        raise ValueError("size_must_be_WxH")
    width, height = int(parts[0]), int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError("size_must_be_positive")
    return width, height


def _build_tasks(
    files: list[str],
    *,
    suffix: str,
    output_dir: str | None,
    source_paths: list[str],
) -> list[tuple[str, str]]:
    tasks: list[tuple[str, str]] = []
    for path in files:
        name = derivative_output_name(path, suffix)
        destination = plan_output_path(
            path,
            name,
            output_dir=output_dir,
            flatten=False,
            source_paths=source_paths,
        )
        tasks.append((path, destination))
    return tasks


def register_transform_commands(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register resize and rotate commands on the root CLI group."""

    @cli_group.command("resize")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("--size", "size", default=None, type=str, help="目标尺寸 WxH，如 1280x720")
    @click.option(
        "--percent",
        "percent",
        default=None,
        type=click.FloatRange(min_open=True, min=0),
        help="按百分比缩放，如 50",
    )
    @click.option(
        "--max-size",
        "max_size",
        default=None,
        type=click.IntRange(1, 65536),
        help="最长边像素上限（不放大）",
    )
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option(
        "-q",
        "--quality",
        default=DEFAULT_CONVERT_QUALITY,
        type=click.Choice(["max", "high", "medium", "low", "web"]),
        help="重编码质量；默认 high",
    )
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--dry-run", is_flag=True, default=False, help="仅预览")
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    def resize_cmd(
        inputs: tuple[str, ...],
        size: str | None,
        percent: float | None,
        max_size: int | None,
        output_dir: str | None,
        quality: str,
        recursive: bool,
        overwrite: bool,
        dry_run: bool,
        as_json: bool,
    ) -> None:
        """批量缩放图片，保持原格式（生成 _resized 派生文件）。"""
        chosen = [option for option in (size, percent, max_size) if option is not None]
        if len(chosen) != 1:
            usage_error_or_exit(
                command="resize",
                as_json=as_json,
                error="conflicting_options",
                detail="exactly one of --size, --percent, --max-size is required",
                human_message="必须且只能指定 --size / --percent / --max-size 之一",
            )

        resize_tuple: tuple[int, int] | None = None
        if size is not None:
            try:
                resize_tuple = _parse_size(size)
            except ValueError:
                usage_error_or_exit(
                    command="resize",
                    as_json=as_json,
                    error="invalid_size",
                    detail="--size expects WxH, for example 1280x720",
                    human_message="--size 需要 WxH 格式，如 1280x720",
                )

        files = collect_supported_files(list(inputs), SUPPORTED_INPUT_FORMATS, recursive=recursive)
        files, ignored_generated = filter_generated_inputs(
            files,
            list(inputs),
            output_root=output_dir,
            generated_suffix=_RESIZE_SUFFIX,
        )
        if not files:
            if as_json:
                emit_json(
                    {
                        "command": "resize",
                        "ok": True,
                        "total": 0,
                        "message": "no_files",
                        "ignored_generated": ignored_generated,
                    }
                )
            else:
                console.print("[yellow]未找到可缩放的图片文件。[/yellow]")
            return

        tasks = _build_tasks(
            files, suffix=_RESIZE_SUFFIX, output_dir=output_dir, source_paths=list(inputs)
        )
        validate_tasks_or_exit(command="resize", as_json=as_json, tasks=tasks)
        all_tasks = tasks
        tasks, skipped_tasks = partition_existing_outputs(tasks, overwrite=overwrite)

        if dry_run:
            payload = {
                "command": "resize",
                "mode": "dry_run",
                "ok": True,
                "total": len(all_tasks),
                "pending": len(tasks),
                "skipped": len(skipped_tasks),
                "ignored_generated": ignored_generated,
                "preview": [{"input": inp, "output": out} for inp, out in all_tasks],
            }
            if as_json:
                emit_json(payload)
            else:
                console.print(
                    f"[cyan]预览（不执行）：{len(tasks)} 个待缩放，"
                    f"{len(skipped_tasks)} 个已有输出跳过[/cyan]"
                )
            return

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        converter_kwargs: dict[str, Any] = {"quality": quality, "overwrite": True}
        if resize_tuple is not None:
            converter_kwargs["resize"] = resize_tuple
        elif percent is not None:
            converter_kwargs["resize_percent"] = percent
        else:
            converter_kwargs["max_size"] = max_size

        start_time = time.time()
        results = []
        errors: list[dict[str, str]] = []
        input_bytes = 0
        output_bytes = 0
        success = 0
        worker = functools.partial(transform_ops.resize_one, converter_kwargs=converter_kwargs)
        with batch_progress(console, disable=as_json) as progress:
            task_id = progress.add_task("缩放中", total=len(tasks))
            outcomes = run_batch_tasks(tasks, worker, on_result=lambda: progress.advance(task_id))
        for (inp, out), result in zip(tasks, outcomes, strict=True):
            results.append((inp, out, result))
            if result.success:
                success += 1
                input_bytes += result.input_size
                output_bytes += result.output_size
            else:
                errors.append(failure_entry(inp, result.error, out))

        payload = {
            "command": "resize",
            "ok": not errors,
            "total": len(all_tasks),
            "success": success,
            "failed": len(errors),
            "skipped": len(skipped_tasks),
            "ignored_generated": ignored_generated,
            "quality": quality,
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
            "duration_sec": round(time.time() - start_time, 4),
            "errors": errors,
        }
        if as_json:
            if errors:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        console.print(f"\n{mini_logo} [bold]图片缩放[/bold]\n")
        table = Table(box=box.ROUNDED)
        table.add_column("输入", style="cyan")
        table.add_column("输出")
        table.add_column("大小")
        table.add_column("状态")
        for inp, out, result in results[:50]:
            table.add_row(
                Path(inp).name,
                Path(out).name,
                human_size(result.output_size) if result.success else "-",
                "[green]完成[/green]" if result.success else f"[red]{result.error}[/red]",
            )
        console.print(table)
        if len(results) > 50:
            console.print(f"[dim]... 还有 {len(results) - 50} 个文件[/dim]")
        console.print(f"\n成功 {success} · 跳过 {len(skipped_tasks)} · 失败 {len(errors)}")
        console.print()
        if errors:
            raise click.exceptions.Exit(1)

    @cli_group.command("rotate")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "--degrees",
        default=0,
        type=click.Choice(["0", "90", "180", "270"]),
        callback=lambda _ctx, _param, value: int(value),
        help="顺时针旋转角度",
    )
    @click.option(
        "--flip",
        default=None,
        type=click.Choice(["horizontal", "vertical"]),
        help="镜像翻转方向",
    )
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    def rotate_cmd(
        inputs: tuple[str, ...],
        degrees: int,
        flip: str | None,
        output_dir: str | None,
        recursive: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """批量旋转/翻转图片（生成 _rotated 派生文件；EXIF 方向先归一）。"""
        if degrees == 0 and flip is None:
            usage_error_or_exit(
                command="rotate",
                as_json=as_json,
                error="nothing_to_do",
                detail="provide --degrees and/or --flip",
                human_message="需要指定 --degrees 或 --flip",
            )

        files = collect_supported_files(list(inputs), SUPPORTED_INPUT_FORMATS, recursive=recursive)
        files, ignored_generated = filter_generated_inputs(
            files,
            list(inputs),
            output_root=output_dir,
            generated_suffix=_ROTATE_SUFFIX,
        )
        if not files:
            if as_json:
                emit_json(
                    {
                        "command": "rotate",
                        "ok": True,
                        "total": 0,
                        "message": "no_files",
                        "ignored_generated": ignored_generated,
                    }
                )
            else:
                console.print("[yellow]未找到可旋转的图片文件。[/yellow]")
            return

        tasks = _build_tasks(
            files, suffix=_ROTATE_SUFFIX, output_dir=output_dir, source_paths=list(inputs)
        )
        validate_tasks_or_exit(command="rotate", as_json=as_json, tasks=tasks)
        all_tasks = tasks
        tasks, skipped_tasks = partition_existing_outputs(tasks, overwrite=overwrite)

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        start_time = time.time()
        results = []
        errors: list[dict[str, str]] = []
        success = 0
        worker = functools.partial(
            transform_ops.rotate_one, degrees=degrees, flip=flip, overwrite=True
        )
        with batch_progress(console, disable=as_json) as progress:
            task_id = progress.add_task("旋转中", total=len(tasks))
            outcomes = run_batch_tasks(tasks, worker, on_result=lambda: progress.advance(task_id))
        for (inp, out), result in zip(tasks, outcomes, strict=True):
            results.append((inp, out, result))
            if result.success:
                success += 1
            else:
                errors.append(failure_entry(inp, result.error, out))

        payload = {
            "command": "rotate",
            "ok": not errors,
            "total": len(all_tasks),
            "success": success,
            "failed": len(errors),
            "skipped": len(skipped_tasks),
            "ignored_generated": ignored_generated,
            "degrees": degrees,
            "flip": flip or "",
            "duration_sec": round(time.time() - start_time, 4),
            "errors": errors,
        }
        if as_json:
            if errors:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        console.print(f"\n{mini_logo} [bold]图片旋转[/bold]\n")
        table = Table(box=box.ROUNDED)
        table.add_column("输入", style="cyan")
        table.add_column("输出")
        table.add_column("状态")
        for inp, out, result in results[:50]:
            table.add_row(
                Path(inp).name,
                Path(out).name,
                "[green]完成[/green]" if result.success else f"[red]{result.error}[/red]",
            )
        console.print(table)
        if len(results) > 50:
            console.print(f"[dim]... 还有 {len(results) - 50} 个文件[/dim]")
        console.print(f"\n成功 {success} · 跳过 {len(skipped_tasks)} · 失败 {len(errors)}")
        console.print()
        if errors:
            raise click.exceptions.Exit(1)

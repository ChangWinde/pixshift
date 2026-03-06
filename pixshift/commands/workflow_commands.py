"""Registration for high-frequency workflow commands."""

import os
import time
from typing import Callable, List, Optional, Tuple

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
)
from rich.table import Table

from ..compress_engine import COMPRESS_PRESETS
from ..core.files import derivative_output_name, plan_output_path
from ..core.models import OperationSummary
from ..ops import compress as compress_ops
from ..ops import dedup as dedup_ops
from ..ops import strip as strip_ops
from ..presenters.cli_presenters import print_failures, show_dry_run_table, size_ratio_text
from ..presenters.json_presenters import emit_json, emit_json_and_exit


def register_workflow_commands(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register compress/strip/dedup commands on the root CLI group."""

    @cli_group.command("compress")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(),
                  help="输出目录路径. 默认: 原目录")
    @click.option("-f", "--from", "input_format", default=None,
                  help="只处理指定输入格式, 如 -f jpg")
    @click.option("-p", "--preset", default="medium",
                  type=click.Choice(list(COMPRESS_PRESETS.keys()), case_sensitive=False),
                  help="压缩预设: lossless|high|medium|low|tiny. 默认: medium")
    @click.option("--quality", default=None, type=click.IntRange(1, 100),
                  help="自定义质量(1-100), 覆盖预设")
    @click.option("--target-size", default=None, type=str,
                  help="目标大小, 如 500KB/1MB")
    @click.option("--max-size", default=None, type=int,
                  help="最大边长限制(px), 如 2048")
    @click.option("-r", "--recursive", is_flag=True, default=False,
                  help="递归处理子目录. 默认: 仅当前目录")
    @click.option("--overwrite", is_flag=True, default=False,
                  help="覆盖已存在输出文件. 默认: 跳过")
    @click.option("--flatten", is_flag=True, default=False,
                  help="输出到同一目录, 不保留层级")
    @click.option("--dry-run", is_flag=True, default=False,
                  help="预览模式, 不实际压缩")
    @click.option("--json", "as_json", is_flag=True, default=False,
                  help="以 JSON 输出结果（适合脚本调用）")
    def compress_cmd(
        inputs: tuple,
        output_dir: Optional[str],
        input_format: Optional[str],
        preset: str,
        quality: Optional[int],
        target_size: Optional[str],
        max_size: Optional[int],
        recursive: bool,
        overwrite: bool,
        flatten: bool,
        dry_run: bool,
        as_json: bool,
    ) -> None:
        """🗜️  同格式压缩优化 (批量减小体积, 不改变格式)"""
        if not as_json:
            console.print(f"\n{mini_logo} [bold]图片压缩[/bold]\n")

        if as_json:
            files = compress_ops.collect_files(list(inputs), input_format, recursive)
        else:
            with console.status("[bold cyan]🔍 扫描文件中...[/bold cyan]"):
                files = compress_ops.collect_files(list(inputs), input_format, recursive)

        if not files:
            if as_json:
                emit_json({"command": "compress", "ok": True, "total": 0, "message": "no_files"})
            else:
                console.print("[yellow]⚠️  未找到可压缩的图片文件[/yellow]")
            return

        tasks = _build_derivative_tasks(
            files=files,
            output_dir=output_dir,
            suffix="_compressed",
            flatten=flatten,
            source_paths=list(inputs),
        )
        if dry_run:
            if as_json:
                emit_json({
                    "command": "compress",
                    "mode": "dry_run",
                    "ok": True,
                    "total": len(tasks),
                    "preview": [{"input": inp, "output": out} for inp, out in tasks[:50]],
                })
            else:
                show_dry_run_table(console, tasks, "same-format", preset)
            return

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        summary = OperationSummary()
        start_time = time.time()
        errors: List[str] = []

        if as_json:
            for inp, out in tasks:
                result = compress_ops.compress_one(
                    input_path=inp,
                    output_path=out,
                    quality=quality,
                    preset=preset,
                    target_size=target_size,
                    max_size=max_size,
                    overwrite=overwrite,
                )
                summary.register(result.input_size, result.output_size, result.success)
                if not result.success:
                    errors.append(f"{os.path.basename(inp)}: {result.error}")
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=40),
                MofNCompleteColumn(),
                TextColumn("•"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("压缩中", total=len(tasks))
                for inp, out in tasks:
                    result = compress_ops.compress_one(
                        input_path=inp,
                        output_path=out,
                        quality=quality,
                        preset=preset,
                        target_size=target_size,
                        max_size=max_size,
                        overwrite=overwrite,
                    )
                    summary.register(result.input_size, result.output_size, result.success)
                    if not result.success:
                        errors.append(f"{os.path.basename(inp)}: {result.error}")
                    progress.advance(task_id)

        duration = time.time() - start_time
        if as_json:
            payload = {
                "command": "compress",
                "ok": summary.failed == 0,
                "total": summary.total,
                "success": summary.success,
                "failed": summary.failed,
                "input_bytes": summary.total_input_size,
                "output_bytes": summary.total_output_size,
                "duration_sec": round(duration, 4),
                "errors": errors,
            }
            if summary.failed > 0:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
        else:
            print_failures(console, errors)
            ratio_text = size_ratio_text(summary.total_input_size, summary.total_output_size, human_size)
            console.print(Panel(
                f"  ✅ 成功: [bold green]{summary.success}[/bold green]\n"
                f"  ❌ 失败: [bold red]{summary.failed}[/bold red]\n"
                f"  📊 总计: [bold]{summary.total}[/bold]\n"
                f"  📦 输入: {human_size(summary.total_input_size)}"
                f"  →  输出: {human_size(summary.total_output_size)}\n"
                f"{ratio_text}\n"
                f"  ⏱️  耗时: [bold]{duration:.2f}s[/bold]",
                title="[bold]🗜️  压缩完成[/bold]",
                border_style="green" if summary.failed == 0 else "yellow",
                box=box.ROUNDED,
            ))
            console.print()

    @cli_group.command("strip")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(),
                  help="输出目录路径. 默认: 原目录")
    @click.option("--mode", default="privacy",
                  type=click.Choice(["privacy", "all", "gps", "device", "personal", "time"], case_sensitive=False),
                  help="清理模式. 默认: privacy")
    @click.option("-r", "--recursive", is_flag=True, default=False,
                  help="递归处理子目录. 默认: 仅当前目录")
    @click.option("--strip-icc", is_flag=True, default=False,
                  help="同时移除 ICC 色彩配置")
    @click.option("--no-keep-orientation", is_flag=True, default=False,
                  help="不应用原始方向信息")
    @click.option("--overwrite", is_flag=True, default=False,
                  help="覆盖已存在输出文件. 默认: 跳过")
    @click.option("--flatten", is_flag=True, default=False,
                  help="输出到同一目录, 不保留层级")
    @click.option("--dry-run", is_flag=True, default=False,
                  help="预览模式, 不实际写文件")
    @click.option("--json", "as_json", is_flag=True, default=False,
                  help="以 JSON 输出结果（适合脚本调用）")
    def strip_cmd(
        inputs: tuple,
        output_dir: Optional[str],
        mode: str,
        recursive: bool,
        strip_icc: bool,
        no_keep_orientation: bool,
        overwrite: bool,
        flatten: bool,
        dry_run: bool,
        as_json: bool,
    ) -> None:
        """🧼 清理图片元数据 (隐私优先、安全默认)"""
        if not as_json:
            console.print(f"\n{mini_logo} [bold]元数据清理[/bold]\n")

        if as_json:
            files = strip_ops.collect_files(list(inputs), recursive)
        else:
            with console.status("[bold cyan]🔍 扫描文件中...[/bold cyan]"):
                files = strip_ops.collect_files(list(inputs), recursive)

        if not files:
            if as_json:
                emit_json({"command": "strip", "ok": True, "total": 0, "message": "no_files"})
            else:
                console.print("[yellow]⚠️  未找到可清理元数据的图片文件[/yellow]")
            return

        tasks = _build_derivative_tasks(
            files=files,
            output_dir=output_dir,
            suffix="_clean",
            flatten=flatten,
            source_paths=list(inputs),
        )

        if dry_run:
            preview = []
            for file_path in files[:50]:
                meta = strip_ops.analyze_one(file_path)

                preview.append(
                    {
                        "file": file_path,
                        "has_exif": bool(meta.get("has_exif")),
                        "has_gps": bool(meta.get("has_gps")),
                    }
                )
            if as_json:
                emit_json({
                    "command": "strip",
                    "mode": "dry_run",
                    "ok": True,
                    "total": len(tasks),
                    "preview": preview,
                })
            else:
                table = Table(title="📋 元数据清理预览", box=box.ROUNDED)
                table.add_column("#", style="dim", width=5)
                table.add_column("文件", style="cyan")
                table.add_column("EXIF", style="yellow")
                table.add_column("GPS", style="magenta")
                for idx, item in enumerate(preview, 1):
                    table.add_row(
                        str(idx),
                        os.path.basename(item["file"]),
                        "yes" if item["has_exif"] else "no",
                        "yes" if item["has_gps"] else "no",
                    )
                if len(files) > 50:
                    table.add_row("...", f"(还有 {len(files) - 50} 个文件)", "", "")
                console.print(table)
                console.print("  [dim]去掉 --dry-run 执行实际清理[/dim]\n")
            return

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        mode_flags = _resolve_strip_mode(mode.lower())

        summary = OperationSummary()
        fields_removed = 0
        start_time = time.time()
        errors: List[str] = []

        if as_json:
            for inp, out in tasks:
                result = strip_ops.strip_one(
                    input_path=inp,
                    output_path=out,
                    strip_exif=mode_flags[0],
                    strip_gps=mode_flags[1],
                    strip_icc=strip_icc,
                    strip_device=mode_flags[2],
                    strip_personal=mode_flags[3],
                    strip_time=mode_flags[4],
                    keep_orientation=not no_keep_orientation,
                    overwrite=overwrite,
                )
                summary.register(result.input_size, result.output_size, result.success)
                if result.success and result.fields_removed > 0:
                    fields_removed += result.fields_removed
                if not result.success:
                    errors.append(f"{os.path.basename(inp)}: {result.error}")
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=40),
                MofNCompleteColumn(),
                TextColumn("•"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("清理中", total=len(tasks))
                for inp, out in tasks:
                    result = strip_ops.strip_one(
                        input_path=inp,
                        output_path=out,
                        strip_exif=mode_flags[0],
                        strip_gps=mode_flags[1],
                        strip_icc=strip_icc,
                        strip_device=mode_flags[2],
                        strip_personal=mode_flags[3],
                        strip_time=mode_flags[4],
                        keep_orientation=not no_keep_orientation,
                        overwrite=overwrite,
                    )
                    summary.register(result.input_size, result.output_size, result.success)
                    if result.success and result.fields_removed > 0:
                        fields_removed += result.fields_removed
                    if not result.success:
                        errors.append(f"{os.path.basename(inp)}: {result.error}")
                    progress.advance(task_id)

        duration = time.time() - start_time
        if as_json:
            payload = {
                "command": "strip",
                "ok": summary.failed == 0,
                "total": summary.total,
                "success": summary.success,
                "failed": summary.failed,
                "fields_removed": fields_removed,
                "input_bytes": summary.total_input_size,
                "output_bytes": summary.total_output_size,
                "duration_sec": round(duration, 4),
                "errors": errors,
            }
            if summary.failed > 0:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
        else:
            print_failures(console, errors)
            console.print(Panel(
                f"  ✅ 成功: [bold green]{summary.success}[/bold green]\n"
                f"  ❌ 失败: [bold red]{summary.failed}[/bold red]\n"
                f"  📊 总计: [bold]{summary.total}[/bold]\n"
                f"  🧾 清理字段: [bold]{fields_removed}[/bold]\n"
                f"  📦 输入: {human_size(summary.total_input_size)}"
                f"  →  输出: {human_size(summary.total_output_size)}\n"
                f"  ⏱️  耗时: [bold]{duration:.2f}s[/bold]",
                title="[bold]🧼 清理完成[/bold]",
                border_style="green" if summary.failed == 0 else "yellow",
                box=box.ROUNDED,
            ))
            console.print()

    @cli_group.command("dedup")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-r", "--recursive", is_flag=True, default=False,
                  help="递归处理子目录. 默认: 仅当前目录")
    @click.option("--hash-method", default="phash",
                  type=click.Choice(["phash", "ahash", "dhash"], case_sensitive=False),
                  help="哈希算法. 默认: phash")
    @click.option("--threshold", default=5, type=click.IntRange(0, 32),
                  help="相似度阈值(汉明距离). 默认: 5")
    @click.option("--delete", "apply_delete", is_flag=True, default=False,
                  help="执行删除建议中的重复文件")
    @click.option("--dry-run", is_flag=True, default=False,
                  help="与 --delete 一起使用时预览删除，不实际删文件")
    @click.option("--yes", is_flag=True, default=False,
                  help="跳过删除确认(与 --delete 一起使用)")
    @click.option("--json", "as_json", is_flag=True, default=False,
                  help="以 JSON 输出结果（适合脚本调用）")
    def dedup_cmd(
        inputs: tuple,
        recursive: bool,
        hash_method: str,
        threshold: int,
        apply_delete: bool,
        dry_run: bool,
        yes: bool,
        as_json: bool,
    ) -> None:
        """🧹 检测并清理重复/相似图片"""
        if not as_json:
            console.print(f"\n{mini_logo} [bold]重复图片检测[/bold]\n")

        if as_json:
            result = dedup_ops.analyze(
                input_paths=list(inputs),
                recursive=recursive,
                hash_method=hash_method,
                threshold=threshold,
            )
        else:
            with console.status("[bold cyan]🔍 分析中...[/bold cyan]"):
                result = dedup_ops.analyze(
                    input_paths=list(inputs),
                    recursive=recursive,
                    hash_method=hash_method,
                    threshold=threshold,
                )

        if result.error:
            if as_json:
                emit_json_and_exit({"command": "dedup", "ok": False, "error": result.error}, 1)
            else:
                console.print(f"[red]❌ 分析失败: {result.error}[/red]\n")
            return
        if result.duplicate_groups == 0:
            if as_json:
                emit_json({
                    "command": "dedup",
                    "ok": True,
                    "total_files": result.total_files,
                    "duplicate_groups": 0,
                    "duplicate_files": 0,
                    "recoverable_bytes": result.recoverable_size,
                    "duration_sec": round(result.duration, 4),
                })
            else:
                console.print("[green]✅ 未发现重复/相似图片[/green]\n")
            return

        if not as_json:
            table = Table(title="🧹 重复组预览", box=box.ROUNDED)
            table.add_column("#", style="dim", width=5)
            table.add_column("保留文件", style="green")
            table.add_column("重复数量", style="yellow", width=10)
            table.add_column("可回收", style="cyan", width=12)
            for idx, group in enumerate(result.groups[:30], 1):
                reclaim = 0
                for file_path, size in zip(group.files, group.sizes):
                    if file_path != group.keep:
                        reclaim += size
                table.add_row(
                    str(idx),
                    os.path.basename(group.keep),
                    str(len(group.duplicates)),
                    human_size(reclaim),
                )
            if len(result.groups) > 30:
                table.add_row("...", f"(还有 {len(result.groups) - 30} 组)", "", "")
            console.print(table)
            console.print()

            console.print(Panel(
                f"  📁 扫描文件: [bold]{result.total_files}[/bold]\n"
                f"  🔁 重复组: [bold yellow]{result.duplicate_groups}[/bold yellow]\n"
                f"  🗑️  可删文件: [bold]{result.duplicate_files}[/bold]\n"
                f"  💾 可回收空间: [bold green]{result.recoverable_size_human}[/bold green]\n"
                f"  ⏱️  耗时: [bold]{result.duration:.2f}s[/bold]",
                title="[bold]📊 去重分析[/bold]",
                border_style="yellow",
                box=box.ROUNDED,
            ))

        if not apply_delete:
            if as_json:
                emit_json({
                    "command": "dedup",
                    "ok": True,
                    "mode": "analyze",
                    "total_files": result.total_files,
                    "duplicate_groups": result.duplicate_groups,
                    "duplicate_files": result.duplicate_files,
                    "recoverable_bytes": result.recoverable_size,
                    "duration_sec": round(result.duration, 4),
                    "preview": [
                        {
                            "keep": group.keep,
                            "duplicates": group.duplicates,
                        }
                        for group in result.groups[:30]
                    ],
                })
            else:
                console.print("\n  [dim]使用 --delete 执行删除; 默认仅预览，确保安全[/dim]\n")
            return

        if dry_run:
            delete_result = dedup_ops.delete(result.groups, dry_run=True)
            if as_json:
                emit_json({
                    "command": "dedup",
                    "ok": True,
                    "mode": "delete_dry_run",
                    "would_delete": len(delete_result["deleted"]),
                    "keep": len(delete_result["kept"]),
                })
            else:
                console.print(Panel(
                    f"  🧪 预览删除: [bold yellow]{len(delete_result['deleted'])}[/bold yellow]\n"
                    f"  📌 保留文件: [bold]{len(delete_result['kept'])}[/bold]\n"
                    f"  [dim]去掉 --dry-run 才会实际删除[/dim]",
                    title="[bold]🧹 删除预览[/bold]",
                    border_style="yellow",
                    box=box.ROUNDED,
                ))
                console.print()
            return

        if not yes:
            if as_json:
                emit_json_and_exit(
                    {
                        "command": "dedup",
                        "ok": False,
                        "message": "confirmation_required",
                        "hint": "use --yes with --delete in --json mode",
                    },
                    1,
                )
            confirmed = click.confirm(
                f"确认删除 {result.duplicate_files} 个文件并回收约 {result.recoverable_size_human}?",
                default=False,
            )
            if not confirmed:
                if as_json:
                    emit_json_and_exit({"command": "dedup", "ok": False, "message": "delete_cancelled"}, 1)
                else:
                    console.print("  [yellow]已取消删除[/yellow]\n")
                return

        delete_result = dedup_ops.delete(result.groups, dry_run=False)
        if as_json:
            payload = {
                "command": "dedup",
                "ok": len(delete_result["errors"]) == 0,
                "mode": "delete",
                "deleted": len(delete_result["deleted"]),
                "kept": len(delete_result["kept"]),
                "errors": delete_result["errors"],
            }
            if delete_result["errors"]:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
        else:
            console.print(Panel(
                f"  ✅ 删除成功: [bold green]{len(delete_result['deleted'])}[/bold green]\n"
                f"  📌 保留文件: [bold]{len(delete_result['kept'])}[/bold]\n"
                f"  ❌ 删除失败: [bold red]{len(delete_result['errors'])}[/bold red]",
                title="[bold]🧹 删除完成[/bold]",
                border_style="green" if not delete_result["errors"] else "yellow",
                box=box.ROUNDED,
            ))
            if delete_result["errors"]:
                console.print("[bold red]失败详情:[/bold red]")
                for err in delete_result["errors"][:10]:
                    console.print(f"   {err}")
                if len(delete_result["errors"]) > 10:
                    console.print(f"   ... 还有 {len(delete_result['errors']) - 10} 个错误")
            console.print()


def _build_derivative_tasks(
    files: List[str],
    output_dir: Optional[str],
    suffix: str,
    flatten: bool,
    source_paths: List[str],
) -> List[Tuple[str, str]]:
    """Build input/output path pairs for derivative operations."""
    tasks: List[Tuple[str, str]] = []
    for file_path in files:
        out_name = derivative_output_name(file_path, suffix)
        out_path = plan_output_path(
            input_path=file_path,
            output_name=out_name,
            output_dir=output_dir,
            flatten=flatten,
            source_paths=source_paths,
        )
        tasks.append((file_path, out_path))
    return tasks


def _resolve_strip_mode(mode: str) -> Tuple[bool, bool, bool, bool, bool]:
    """Resolve strip mode to (strip_exif, strip_gps, strip_device, strip_personal, strip_time)."""
    strip_exif = mode == "all"
    strip_gps = mode in {"privacy", "gps"}
    strip_device = mode in {"privacy", "device"}
    strip_personal = mode in {"privacy", "personal"}
    strip_time = mode == "time"
    return strip_exif, strip_gps, strip_device, strip_personal, strip_time




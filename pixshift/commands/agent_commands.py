"""Registration for agent-facing commands: tools, apply, prep, manifest, hash."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import IO

import click
from rich import box
from rich.console import Console
from rich.table import Table

from ..core.defaults import DEFAULT_CONVERT_QUALITY
from ..core.tool_catalog import TOOL_CATALOG, catalog_payload
from ..ops import apply as apply_ops
from ..ops import hashing as hashing_ops
from ..ops import inventory as inventory_ops
from ..ops import prep as prep_ops
from ..presenters.json_presenters import emit_json, emit_json_and_exit
from .common import selection_filters_or_exit, selection_options, usage_error_or_exit

_HASH_ALGORITHMS = ["sha256", "sha1", "sha512", "blake2b", "md5"]


def register_agent_commands(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register commands that close the discover/plan/apply/verify loop."""

    @cli_group.command("tools")
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    def tools_cmd(as_json: bool) -> None:
        """列出 agent 可发现的工具目录（含副作用注解）。"""
        if as_json:
            emit_json(catalog_payload())
            return
        console.print(f"\n{mini_logo} [bold]工具目录[/bold]\n")
        table = Table(box=box.ROUNDED)
        table.add_column("工具", style="cyan", no_wrap=True)
        table.add_column("说明")
        table.add_column("只读", justify="center")
        table.add_column("破坏性", justify="center")
        table.add_column("幂等", justify="center")
        for entry in TOOL_CATALOG:
            notes = entry["annotations"]
            table.add_row(
                entry["name"],
                entry["description"],
                "是" if notes["readOnlyHint"] else "否",
                "[red]是[/red]" if notes["destructiveHint"] else "否",
                "是" if notes["idempotentHint"] else "否",
            )
        console.print(table)
        console.print("[dim]机器接口：pixshift tools --json[/dim]\n")

    @cli_group.command("apply")
    @click.option(
        "--plan",
        "plan_file",
        required=True,
        type=click.File("r", encoding="utf-8"),
        help="计划文件路径，使用 - 读取标准输入",
    )
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--dry-run", is_flag=True, default=False, help="仅预览将执行的步骤")
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    def apply_cmd(
        plan_file: IO[str],
        output_dir: str | None,
        overwrite: bool,
        dry_run: bool,
        as_json: bool,
    ) -> None:
        """执行 optimize/prep 产出的机器计划。"""
        raw = plan_file.read()
        try:
            steps = apply_ops.load_plan_document(raw)
        except json.JSONDecodeError as error:
            usage_error_or_exit(
                command="apply",
                as_json=as_json,
                error="invalid_plan_json",
                detail=str(error),
                human_message="计划文件不是有效 JSON。",
            )
        except ValueError as error:
            usage_error_or_exit(
                command="apply",
                as_json=as_json,
                error=str(error),
                detail=str(error),
                human_message=f"计划文件无效: {error}",
            )

        result = apply_ops.apply_plans(
            steps,
            output_dir=output_dir,
            overwrite=overwrite,
            dry_run=dry_run,
        )
        applied = sum(1 for step in result.steps if step.success and not step.skipped)
        skipped = sum(1 for step in result.steps if step.skipped)
        failed = sum(1 for step in result.steps if not (step.success or step.skipped))
        payload = {
            "command": "apply",
            "ok": result.ok,
            "total": len(result.steps),
            "applied": applied,
            "skipped": skipped,
            "failed": failed,
            "dry_run": dry_run,
            "error": result.error,
            "steps": [
                {
                    "input": step.input_path,
                    "plan_command": step.command,
                    "arguments": step.arguments,
                    "output": step.output_path,
                    "ok": step.success or step.skipped,
                    "skipped": step.skipped,
                    "error": step.error,
                    "detail": step.detail,
                }
                for step in result.steps
            ],
        }
        if as_json:
            if not result.ok:
                emit_json_and_exit(payload, 2 if result.rejected else 1)
            emit_json(payload)
            return
        console.print(f"\n{mini_logo} [bold]计划执行[/bold]\n")
        table = Table(box=box.ROUNDED)
        table.add_column("输入", style="cyan")
        table.add_column("动作")
        table.add_column("输出")
        table.add_column("状态")
        for step in result.steps[:50]:
            if step.skipped:
                status = "[yellow]跳过[/yellow]"
            elif step.success:
                status = "[green]完成[/green]" if not dry_run else "[green]可执行[/green]"
            else:
                status = f"[red]{step.error or '失败'}[/red]"
            table.add_row(
                Path(step.input_path).name,
                step.command,
                Path(step.output_path).name if step.output_path else "-",
                status,
            )
        console.print(table)
        if len(result.steps) > 50:
            console.print(f"[dim]... 还有 {len(result.steps) - 50} 个步骤[/dim]")
        console.print()
        if not result.ok:
            raise click.exceptions.Exit(2 if result.rejected else 1)

    @cli_group.command("prep")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "-o",
        "--output",
        "output_dir",
        required=True,
        type=click.Path(file_okay=False),
        help="输出目录",
    )
    @click.option(
        "-t",
        "--to",
        "output_format",
        default="webp",
        type=click.Choice(["webp", "jpg", "png", "avif"], case_sensitive=False),
        help="目标格式；默认 webp",
    )
    @click.option(
        "--max-size",
        default=2048,
        type=click.IntRange(16, 16384),
        help="最长边像素上限；默认 2048",
    )
    @click.option(
        "-q",
        "--quality",
        default=DEFAULT_CONVERT_QUALITY,
        type=click.Choice(["max", "high", "medium", "low", "web"]),
        help="编码质量；默认 high",
    )
    @click.option("--keep-metadata", is_flag=True, default=False, help="保留元数据（默认隐私清理）")
    @click.option(
        "--color-space",
        default="srgb",
        type=click.Choice(["preserve", "srgb"], case_sensitive=False),
        help="色彩策略；交付默认转换并嵌入 sRGB",
    )
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--dry-run", is_flag=True, default=False, help="仅预览")
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    @selection_options
    def prep_cmd(
        inputs: tuple[str, ...],
        output_dir: str,
        output_format: str,
        max_size: int,
        quality: str,
        keep_metadata: bool,
        color_space: str,
        recursive: bool,
        overwrite: bool,
        dry_run: bool,
        include_globs: tuple[str, ...],
        exclude_globs: tuple[str, ...],
        min_file_size: str | None,
        as_json: bool,
    ) -> None:
        """一键生成可交付资产：限宽转换 + 隐私清理 + 清单。"""
        result = prep_ops.prep_files(
            list(inputs),
            output_dir=output_dir,
            output_format=output_format.lower(),
            max_size=max_size,
            quality=quality,
            recursive=recursive,
            overwrite=overwrite,
            dry_run=dry_run,
            strip_privacy=not keep_metadata,
            color_space=color_space.lower(),
            selection=selection_filters_or_exit(
                command="prep",
                as_json=as_json,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                min_file_size=min_file_size,
            ),
        )
        success = sum(1 for item in result.items if item.success and not item.skipped)
        skipped = sum(1 for item in result.items if item.skipped)
        failed = sum(1 for item in result.items if not (item.success or item.skipped))
        payload = {
            "command": "prep",
            "ok": result.ok,
            "total": len(result.items),
            "success": success,
            "skipped": skipped,
            "failed": failed,
            "ignored_generated": result.ignored_generated,
            "output_dir": output_dir,
            "dry_run": dry_run,
            "items": prep_ops.prep_payload(result),
        }
        if as_json:
            if not result.ok:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return
        console.print(f"\n{mini_logo} [bold]资产准备[/bold]\n")
        table = Table(box=box.ROUNDED)
        table.add_column("输入", style="cyan")
        table.add_column("输出")
        table.add_column("大小")
        table.add_column("状态")
        for item in result.items[:50]:
            if item.skipped:
                status = "[yellow]跳过[/yellow]"
            elif item.success:
                status = "[green]完成[/green]" if not dry_run else "[green]待执行[/green]"
            else:
                status = f"[red]{item.error or '失败'}[/red]"
            table.add_row(
                Path(item.input_path).name,
                Path(item.output_path).name if item.output_path else "-",
                human_size(item.output_bytes) if item.output_bytes else "-",
                status,
            )
        console.print(table)
        if len(result.items) > 50:
            console.print(f"[dim]... 还有 {len(result.items) - 50} 个文件[/dim]")
        console.print()
        if not result.ok:
            raise click.exceptions.Exit(1)

    @cli_group.command("manifest")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    @selection_options
    def manifest_cmd(
        inputs: tuple[str, ...],
        recursive: bool,
        include_globs: tuple[str, ...],
        exclude_globs: tuple[str, ...],
        min_file_size: str | None,
        as_json: bool,
    ) -> None:
        """生成媒体目录清单：属性、内容哈希与敏感 EXIF 概览。"""
        result = inventory_ops.build_inventory(
            list(inputs),
            recursive=recursive,
            selection=selection_filters_or_exit(
                command="manifest",
                as_json=as_json,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                min_file_size=min_file_size,
            ),
        )
        payload = {
            "command": "manifest",
            "ok": result.ok,
            "total": len(result.items),
            "files": inventory_ops.inventory_payload(result),
        }
        if as_json:
            if not result.ok:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return
        console.print(f"\n{mini_logo} [bold]媒体清单[/bold]\n")
        table = Table(box=box.ROUNDED)
        table.add_column("文件", style="cyan")
        table.add_column("格式")
        table.add_column("尺寸")
        table.add_column("大小")
        table.add_column("敏感EXIF", justify="right")
        for item in result.items[:50]:
            dims = f"{item.width}x{item.height}" if item.width and item.height else "-"
            table.add_row(
                Path(item.path).name,
                item.format or "-",
                dims,
                human_size(item.bytes),
                str(len(item.sensitive_exif_keys)),
            )
        console.print(table)
        if len(result.items) > 50:
            console.print(f"[dim]... 还有 {len(result.items) - 50} 个文件[/dim]")
        console.print()
        if not result.ok:
            raise click.exceptions.Exit(1)

    @cli_group.command("hash")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option(
        "--algorithm",
        default="sha256",
        type=click.Choice(_HASH_ALGORITHMS),
        help="哈希算法；默认 sha256",
    )
    @click.option("--all-files", is_flag=True, default=False, help="包含非媒体文件")
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    @selection_options
    def hash_cmd(
        inputs: tuple[str, ...],
        recursive: bool,
        algorithm: str,
        all_files: bool,
        include_globs: tuple[str, ...],
        exclude_globs: tuple[str, ...],
        min_file_size: str | None,
        as_json: bool,
    ) -> None:
        """计算内容哈希，用于转换前后审计。"""
        result = hashing_ops.hash_paths(
            list(inputs),
            recursive=recursive,
            algorithm=algorithm,
            media_only=not all_files,
            selection=selection_filters_or_exit(
                command="hash",
                as_json=as_json,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                min_file_size=min_file_size,
            ),
        )
        payload = {
            "command": "hash",
            "ok": result.ok,
            "total": len(result.items),
            "algorithm": algorithm,
            "files": hashing_ops.hash_payload(result),
        }
        if as_json:
            if not result.ok:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return
        console.print(f"\n{mini_logo} [bold]内容哈希[/bold]\n")
        table = Table(box=box.ROUNDED)
        table.add_column("文件", style="cyan")
        table.add_column("大小")
        table.add_column(algorithm)
        for item in result.items[:50]:
            table.add_row(Path(item.path).name, human_size(item.bytes), item.digest)
        console.print(table)
        if len(result.items) > 50:
            console.print(f"[dim]... 还有 {len(result.items) - 50} 个文件[/dim]")
        console.print()
        if not result.ok:
            raise click.exceptions.Exit(1)

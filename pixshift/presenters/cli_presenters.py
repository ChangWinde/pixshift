"""Shared CLI presenter utilities."""

import os
from typing import Callable, List, Tuple

from rich import box
from rich.console import Console
from rich.table import Table


def show_dry_run_table(
    console: Console,
    tasks: List[Tuple[str, str]],
    target_label: str,
    quality_label: str,
) -> None:
    """Render a unified dry-run preview table."""
    table = Table(title="📋 预览模式 (Dry Run)", box=box.ROUNDED)
    table.add_column("#", style="dim", width=5)
    table.add_column("输入文件", style="cyan")
    table.add_column("→", style="dim", width=2)
    table.add_column("输出文件", style="green")

    for i, (inp, out) in enumerate(tasks, 1):
        table.add_row(str(i), os.path.basename(inp), "→", os.path.basename(out))
        if i >= 50:
            table.add_row("...", f"(还有 {len(tasks) - 50} 个文件)", "", "")
            break

    console.print(table)
    console.print(
        f"\n  共 [bold]{len(tasks)}[/bold] 个文件将被处理为 "
        f"[bold cyan]{target_label}[/bold cyan] (配置: {quality_label})"
    )
    console.print("  [dim]去掉 --dry-run 执行实际处理[/dim]\n")


def print_failures(console: Console, errors: List[str]) -> None:
    """Render top failed files with truncation."""
    if not errors:
        return
    console.print("[bold red]❌ 失败文件:[/bold red]")
    for msg in errors[:10]:
        console.print(f"   {msg}")
    if len(errors) > 10:
        console.print(f"   ... 还有 {len(errors) - 10} 个失败")
    console.print()


def size_ratio_text(total_in: int, total_out: int, human_size: Callable[[int], str]) -> str:
    """Build size ratio output line."""
    if total_in <= 0 or total_out <= 0:
        return ""
    pct = (total_out / total_in) * 100
    saved = total_in - total_out
    if saved >= 0:
        return f"  📉 体积比: [green]{pct:.1f}%[/green] (节省 {human_size(saved)})"
    return f"  📈 体积比: [yellow]{pct:.1f}%[/yellow] (增加 {human_size(-saved)})"


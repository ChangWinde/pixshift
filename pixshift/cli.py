"""
PixShift CLI - 命令行界面
"""

import sys
from collections.abc import Sequence
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from . import __version__
from .commands.advanced_commands import register_advanced_commands
from .commands.agent_commands import register_agent_commands
from .commands.convert_command import register_convert_command
from .commands.pdf_commands import register_pdf_commands
from .commands.system_commands import register_system_commands
from .commands.transform_commands import register_transform_commands
from .commands.verify_command import register_verify_command
from .commands.video_commands import register_video_commands
from .commands.workflow_commands import register_workflow_commands
from .converter import _human_size
from .logo import MINI_LOGO, get_banner
from .presenters.json_presenters import emit_json

console = Console()

# ============================================================
#  主命令组
# ============================================================


class JsonAwareGroup(click.Group):
    """Serialize Click parsing failures when automation explicitly requests JSON."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        """Run Click while preserving one machine-readable failure channel."""
        invocation_args = list(args) if args is not None else sys.argv[1:]
        if "--json" not in invocation_args:
            return super().main(
                args=invocation_args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=standalone_mode,
                windows_expand_args=windows_expand_args,
                **extra,
            )

        try:
            result = super().main(
                args=invocation_args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except click.ClickException as error:
            emit_json(
                {
                    "command": _command_identifier(invocation_args),
                    "ok": False,
                    "error": _click_error_code(error),
                    "detail": error.format_message(),
                }
            )
            if standalone_mode:
                raise SystemExit(error.exit_code) from None
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            # JSON is an automation boundary: an unexpected library or OS
            # exception must not turn into an empty stdout plus traceback.
            # Keep the classification stable and place volatile diagnostics
            # (paths, locale text, dependency messages) in ``detail``.
            emit_json(
                {
                    "command": _command_identifier(invocation_args),
                    "ok": False,
                    "error": "operation_failed",
                    "detail": str(error),
                }
            )
            if standalone_mode:
                raise SystemExit(1) from None
            return 1

        if standalone_mode and isinstance(result, int) and result != 0:
            raise SystemExit(result)
        return result


def _click_error_code(error: click.ClickException) -> str:
    """Map Click exceptions to stable machine error codes."""
    if isinstance(error, click.NoSuchOption):
        return "invalid_option"
    if isinstance(error, click.MissingParameter):
        return "missing_parameter"
    if isinstance(error, click.BadParameter):
        return "invalid_value"
    if isinstance(error, click.UsageError):
        return "usage_error"
    return "cli_error"


def _command_identifier(args: Sequence[str]) -> str:
    """Infer a bounded command identifier before Click has a valid context."""
    tokens = [
        argument for argument in args if argument != "--json" and not argument.startswith("-")
    ]
    if not tokens:
        return "cli"
    command = tokens[0]
    if command in {"pdf", "watermark", "video"} and len(tokens) > 1:
        return f"{command}.{tokens[1]}"
    return command


@click.group(cls=JsonAwareGroup, invoke_without_command=True)
@click.version_option(__version__, prog_name="PixShift")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """快速、安全、可自动化的图片与 PDF 工具。

    \b
    查看命令参数：pixshift COMMAND --help
    查看可用格式：pixshift formats
    自动化接口：支持 --json 的命令提供稳定字段和失败退出码
    """
    if ctx.invoked_subcommand is None:
        console.print(get_banner(__version__))
        console.print(
            Panel(
                "[bold]pixshift convert ./photos -t webp -r[/bold]\n"
                "[bold]pixshift compress ./photos -p medium -r[/bold]\n"
                "[bold]pixshift pdf merge ./photos -o album.pdf[/bold]",
                title="[bold cyan]快速开始[/bold cyan]",
                subtitle="pixshift --help  ·  pixshift formats",
                border_style="cyan",
            )
        )


# Register extracted workflow commands.
register_workflow_commands(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
    human_size=_human_size,
)

# Register extracted convert and system commands.
register_convert_command(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
    human_size=_human_size,
)
register_system_commands(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
)
register_pdf_commands(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
    human_size=_human_size,
)
register_advanced_commands(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
    human_size=_human_size,
)
register_agent_commands(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
    human_size=_human_size,
)
register_transform_commands(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
    human_size=_human_size,
)
register_video_commands(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
    human_size=_human_size,
)
register_verify_command(
    cli_group=cli,
    console=console,
    mini_logo=MINI_LOGO,
    human_size=_human_size,
)


# ============================================================
#  入口
# ============================================================


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

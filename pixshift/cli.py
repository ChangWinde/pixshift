"""
PixShift CLI - 命令行界面
"""

import click
from rich.console import Console

from . import __version__
from .logo import get_banner, MINI_LOGO
from .converter import _human_size
from .commands.convert_command import register_convert_command
from .commands.pdf_commands import register_pdf_commands
from .commands.advanced_commands import register_advanced_commands
from .commands.system_commands import register_system_commands
from .commands.workflow_commands import register_workflow_commands

console = Console()

# ============================================================
#  主命令组
# ============================================================

@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="PixShift")
@click.pass_context
def cli(ctx):
    """⚡ PixShift - 高效图片格式批量转换 & PDF 处理工具

    \b
    实际支持格式由运行时依赖自动探测（请使用 pixshift formats 查看）
    默认最高质量转换 | 自动批量处理 | 多核并行加速 | PDF 五合一
    ─────────────────────────────────────────────────────
    Commands (子命令):
      convert   🔄 核心转换命令, 支持单文件/目录/批量转换
      info      📋 查看图片详细信息 (尺寸/格式/EXIF等)
      formats   📑 列出所有支持的输入输出格式和质量预设
      compress  🗜️  同格式压缩优化（批量减小体积）
      strip     🧼 清理图片元数据（隐私保护）
      dedup     🧹 检测并清理重复/相似图片
      compare   🧪 对比两张图片质量（SSIM/PSNR/MSE）
      crop      ✂️ 批量裁剪（区域/比例/自动裁边）
      watermark 💧 添加文字或图片水印
      montage   🧩 多图网格拼接
      optimize  📈 智能格式推荐与体积评估
      watch     👀 监控目录自动转换
      doctor    🩺 检查运行环境和依赖是否就绪
    ─────────────────────────────────────────────────────
    PDF 子命令:
      pdf merge      📑 多图合并成 PDF (支持纸张/横向/边距/质量)
      pdf extract    📤 PDF 拆分为图片 (支持DPI/页码/格式选择)
      pdf compress   🗜️  PDF 压缩优化 (5级压缩预设/自定义质量)
      pdf concat     📎 多个 PDF 合并成一个
      pdf info       📊 查看 PDF 详细信息 (页数/尺寸/图片/元数据)
    ─────────────────────────────────────────────────────
    convert 参数速查:
      INPUTS              输入文件或目录, 支持多个, 如 a.png ./dir/
      -t, --to    FORMAT  [必填] 目标格式: png|jpg|webp|tiff|bmp|gif|heic|avif|pdf|ico|tga
      -f, --from  FORMAT  只转换指定输入格式, 如 -f heic (默认: 自动识别所有格式)
      -o, --output DIR    输出目录 (默认: 与输入文件同目录)
      -q, --quality LEVEL 质量等级 (默认: max)
                          可选: max(最高) | high(高) | medium(中) | low(低) | web(网页优化)
      -r, --recursive     递归处理子目录 (默认: 仅当前目录)
      -j, --jobs N        并行进程数 (默认: CPU核心数, 自动检测)
      --resize WxH|N%     调整尺寸, 如 --resize 1920x1080 或 --resize 50%
      --max-size N        最大边长限制, 保持比例缩放, 如 --max-size 2048
      --overwrite         覆盖已存在的输出文件 (默认: 跳过)
      --prefix TEXT       输出文件名添加前缀, 如 --prefix "thumb_"
      --suffix TEXT       输出文件名添加后缀, 如 --suffix "_hd"
      --strip-alpha       移除透明通道, 用背景色填充 (默认: 保留)
      --bg-color R,G,B    透明通道替换背景色 (默认: 255,255,255 白色)
      --no-exif           不保留 EXIF 元数据 (默认: 保留)
      --no-icc            不保留 ICC 颜色配置 (默认: 保留)
      --no-orient         不根据 EXIF 自动旋转 (默认: 自动旋转)
      --flatten           所有输出放同一目录, 不保持子目录结构
      --dry-run           预览模式, 只列出操作不实际转换
    ─────────────────────────────────────────────────────
    快速示例:
      pixshift convert photo.heic -t png           # 单文件转换
      pixshift convert ./photos/ -t png            # 整个目录批量转
      pixshift convert ./photos/ -t webp -q high   # 指定质量
      pixshift convert ./dir/ -f heic -t jpg       # 只转 HEIC 文件
      pixshift convert ./dir/ -t png -r -o ./out/  # 递归+输出目录
      pixshift convert *.png -t jpg --resize 50%   # 转换并缩放
      pixshift convert ./dir/ -t jpg -j 8          # 指定8进程并行
      pixshift info photo.heic --exif              # 查看图片信息
      pixshift formats                             # 查看支持格式
      pixshift doctor                              # 检查环境依赖
    ─────────────────────────────────────────────────────
    PDF 示例:
      pixshift pdf merge ./photos/ -o album.pdf          # 图片合并PDF
      pixshift pdf merge *.jpg -o out.pdf --page a4      # A4纸张
      pixshift pdf extract doc.pdf -o ./pages/           # PDF拆图片
      pixshift pdf extract doc.pdf --dpi 600 --pages 1-5 # 高清+指定页
      pixshift pdf compress big.pdf -o small.pdf         # 中度压缩
      pixshift pdf compress big.pdf --preset lossless    # 无损压缩
      pixshift pdf compress big.pdf --preset extreme     # 极限压缩
      pixshift pdf compress big.pdf --image-quality 70   # 自定义质量
      pixshift pdf concat a.pdf b.pdf -o merged.pdf      # 合并PDF
      pixshift pdf info document.pdf                     # 查看PDF信息
    """
    if ctx.invoked_subcommand is None:
        console.print(get_banner(__version__))
        console.print("  输入 [bold green]pixshift --help[/bold green] 查看完整参数说明\n")
        console.print("  [bold]快速开始 — 图片转换:[/bold]")
        console.print("    pixshift convert photo.heic -t png           [dim]# 单文件转换[/dim]")
        console.print("    pixshift convert ./photos/ -t png            [dim]# 批量转换目录[/dim]")
        console.print("    pixshift convert ./photos/ -t webp -q high   [dim]# 指定质量[/dim]")
        console.print("    pixshift convert ./dir/ -f heic -t jpg       [dim]# 只转 HEIC[/dim]")
        console.print()
        console.print("  [bold]快速开始 — PDF 处理:[/bold]")
        console.print("    pixshift pdf merge ./photos/ -o album.pdf    [dim]# 图片合并PDF[/dim]")
        console.print("    pixshift pdf extract doc.pdf -o ./pages/     [dim]# PDF拆为图片[/dim]")
        console.print("    pixshift pdf compress big.pdf -o small.pdf   [dim]# PDF压缩优化[/dim]")
        console.print("    pixshift pdf concat a.pdf b.pdf -o out.pdf   [dim]# 多PDF合并[/dim]")
        console.print("    pixshift pdf info document.pdf               [dim]# 查看PDF信息[/dim]")
        console.print()
        console.print("    pixshift info photo.heic                     [dim]# 查看图片信息[/dim]")
        console.print("    pixshift compress ./photos/ -p medium        [dim]# 同格式压缩[/dim]")
        console.print("    pixshift strip ./photos/ --mode privacy      [dim]# 清理隐私元数据[/dim]")
        console.print("    pixshift dedup ./photos/ -r                  [dim]# 查找重复图片[/dim]")
        console.print("    pixshift formats                             [dim]# 查看支持格式[/dim]")
        console.print("    pixshift doctor                              [dim]# 检查环境依赖[/dim]\n")


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


# ============================================================
#  入口
# ============================================================

def main():
    cli()


if __name__ == "__main__":
    main()

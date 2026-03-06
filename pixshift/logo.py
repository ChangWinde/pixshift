"""
PixShift ASCII Logo and Banner
"""

LOGO = r"""
[bold cyan]
  ██████╗ ██╗██╗  ██╗███████╗██╗  ██╗██╗███████╗████████╗
  ██╔══██╗██║╚██╗██╔╝██╔════╝██║  ██║██║██╔════╝╚══██╔══╝
  ██████╔╝██║ ╚███╔╝ ███████╗███████║██║█████╗     ██║
  ██╔═══╝ ██║ ██╔██╗ ╚════██║██╔══██║██║██╔══╝     ██║
  ██║     ██║██╔╝ ██╗███████║██║  ██║██║██║        ██║
  ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝╚═╝        ╚═╝
[/bold cyan]
[dim]  ⚡ High-Performance Image Format Converter  v{version}[/dim]
[dim]  ─────────────────────────────────────────────────────[/dim]
"""

MINI_LOGO = "[bold cyan]⚡ PixShift[/bold cyan]"

def get_banner(version: str) -> str:
    return LOGO.format(version=version)

"""
UI 美化模块 - 使用 rich 库提供更漂亮的终端界面
（兼容 GBK 终端，无生僻 Unicode 符号）
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.text import Text
from rich.align import Align

# 全局控制台实例
console = Console()


def print_banner_rich():
    """打印美化的启动界面（居中）"""
    content = Text()
    content.append("智能桌面助手", style="bold yellow")
    content.append(" v0.3.0", style="dim white")
    content.append("\n")
    content.append("AI Desktop Assistant", style="cyan")
    
    panel = Panel(
        Align.center(content),
        box=box.DOUBLE,
        border_style="cyan",
        padding=(1, 2),
        title="[bold yellow][AI][/bold yellow]",
        title_align="center"
    )
    console.print()
    console.print(panel)


def print_help_rich(sections):
    """打印美化的帮助信息"""
    main_table = Table(
        box=box.SIMPLE,
        border_style="cyan",
        title="[bold yellow]命令大全[/bold yellow]",
        title_justify="center",
        padding=(0, 1)
    )
    main_table.add_column("分类", style="bold green", width=12)
    main_table.add_column("命令", style="yellow", width=28)
    main_table.add_column("说明", style="white", width=42)

    for title, cmds in sections:
        first = True
        for cmd, desc in cmds:
            cat = title if first else ""
            main_table.add_row(cat, cmd, desc)
            first = False

    console.print()
    console.print(main_table)
    console.print()
    
    tip = Panel(
        "[bold yellow][i][/bold yellow] 也可以直接输入自然语言，AI 会自动理解你的意图\n"
        "[bold yellow][i][/bold yellow] 在聊天模式下直接说话即可，助手会自动调用工具",
        box=box.SIMPLE,
        border_style="bright_black",
        padding=(1, 2)
    )
    console.print(tip)


def print_success(msg: str):
    """成功信息"""
    console.print(f"[bold green][OK] {msg}[/bold green]")


def print_error(msg: str):
    """错误信息"""
    console.print(f"[bold red][ERROR] {msg}[/bold red]")


def print_warning(msg: str):
    """警告信息"""
    console.print(f"[bold yellow][!] {msg}[/bold yellow]")


def print_info(msg: str):
    """信息提示"""
    console.print(f"[bold cyan][i] {msg}[/bold cyan]")

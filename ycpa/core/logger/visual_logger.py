import logging
import os
import re
import sys

from rich import box
from rich.console import Console
from rich.highlighter import Highlighter
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.traceback import install as install_rich_traceback


class DatabaseHighlighter(Highlighter):
    PATTERNS = {
        r'\b(SELECT|INSERT|UPDATE|DELETE|COMMIT|ROLLBACK|BEGIN|CREATE|DROP|ALTER)\b': 'bold bright_cyan',
        r'\b(FROM|WHERE|JOIN|LEFT|RIGHT|INNER|AND|OR|NOT|IN|ORDER BY|GROUP BY|LIMIT|OFFSET)\b': 'bright_blue',
        r'\b(connected|SUCCESS|success)\b': 'bold green',
        r'\b(ERROR|error|disconnected)\b': 'bold red',
        r'\b(WARNING|warning)\b': 'bold yellow',
        r'\b\d+\b': 'bright_white',
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}': 'dim cyan',
        r'\d+(\.\d+)?(ms|s|m|h)': 'bright_yellow',
        r'\d+(\.\d+)?(MB|GB|KB)': 'bright_cyan',
    }
    def highlight(self, text: Text) -> None:
        for pattern, style in self.PATTERNS.items():
            for match in re.finditer(pattern, str(text)):
                text.stylize(style, match.start(), match.end())


console = Console()

def setup_rich_logging(log_level: str):
    install_rich_traceback(show_locals=True, width=120, extra_lines=3)
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(
            console=console,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            markup=True,
            highlighter=DatabaseHighlighter(),
            keywords=[],
        )]
    )


class VisualLogger:
    @staticmethod
    def banner(title: str):
        console.print()
        console.print(Panel(f"[bold yellow]{title}[/bold yellow]", border_style="bold cyan", box=box.DOUBLE))
        console.print()

    @staticmethod
    def config_table(settings):
        table = Table(title="Configuration", box=box.DOUBLE_EDGE,
                      title_style="bold magenta", border_style="bright_blue", header_style="bold cyan")
        table.add_column("Setting", style="cyan", no_wrap=True)
        table.add_column("Value",   style="green")
        table.add_column("Status",  style="yellow")

        is_prod = settings.ENVIRONMENT == "production"
        env_style = "bold red" if is_prod else "bold green"
        enable_docs = settings.DEBUG or not is_prod

        table.add_row("Environment", f"[{env_style}]{settings.ENVIRONMENT}[/{env_style}]",
                      "[red]PROD[/red]" if is_prod else "[green]DEV[/green]")
        table.add_row("Debug",     str(settings.DEBUG),
                      "[yellow]ON[/yellow]" if settings.DEBUG else "[green]OFF[/green]")
        table.add_row("Log Level", f"[bold yellow]{settings.LOG_LEVEL}[/bold yellow]", "[cyan]Active[/cyan]")
        table.add_row("API Docs",  "[green]/docs[/green]" if enable_docs else "[red]Disabled[/red]",
                      "[green]ON[/green]" if enable_docs else "[red]OFF[/red]")
        table.add_row("Python",    f"[bold green]{sys.version.split()[0]}[/bold green]", "[green]OK[/green]")
        table.add_row("PID",       f"[bold white]{os.getpid()}[/bold white]", "[white]Running[/white]")
        console.print(table)
        console.print()

    @staticmethod
    def middleware_table(middlewares: list[dict]):
        table = Table(title="Middleware Stack", box=box.DOUBLE_EDGE,
                      title_style="bold magenta", border_style="bright_blue", header_style="bold cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("Middleware", style="cyan")
        table.add_column("Status",     style="green")
        for idx, mw in enumerate(middlewares, 1):
            table.add_row(str(idx), mw["name"], mw["status"])
        console.print(table)
        console.print()

    @staticmethod
    def step(label: str, status: str = "running"):
        icons = {
            "running": "[cyan][...][/cyan]",
            "success": "[bold green][ OK][/bold green]",
            "error":   "[bold red][FAIL][/bold red]",
            "warning": "[bold yellow][WARN][/bold yellow]",
        }
        console.print(f"{icons.get(status, '')} {label}")

    @staticmethod
    def panel(message: str, title: str, style: str = "cyan"):
        console.print(Panel(
            f"[bold {style}]{message}[/bold {style}]",
            title=f"[bold white]{title}[/bold white]",
            border_style=style, box=box.ROUNDED
        ))
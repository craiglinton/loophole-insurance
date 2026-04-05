"""Utility for browsing and selecting template files from a directory."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table


def browse_and_select(directory: Path, label: str, console: Console) -> Path | None:
    """List files in a directory and let the user pick one.

    Returns the selected Path, or None if the user cancels.
    """
    if not directory.exists():
        console.print(f"[red]Directory {directory} not found.[/red]")
        return None

    files = sorted(
        f for f in directory.iterdir()
        if f.is_file() and f.suffix in (".txt", ".md")
    )

    if not files:
        console.print(f"[yellow]No template files found in {directory}/[/yellow]")
        console.print(f"[dim]Add .txt or .md files to this directory to use them.[/dim]")
        return None

    table = Table(title=f"Available {label} Templates")
    table.add_column("#", style="dim", width=4)
    table.add_column("File")
    table.add_column("Preview", style="dim", max_width=60)

    for i, f in enumerate(files, 1):
        # Read first ~80 chars as a preview
        try:
            preview = f.read_text()[:120].replace("\n", " ").strip()
            if len(f.read_text()) > 120:
                preview += "..."
        except Exception:
            preview = "(unable to read)"
        table.add_row(str(i), f.name, preview)

    console.print()
    console.print(table)
    console.print("[dim]Enter 0 to cancel[/dim]")

    choice = Prompt.ask(f"Select {label.lower()}", default="0")

    try:
        idx = int(choice)
    except ValueError:
        console.print("[red]Invalid selection.[/red]")
        return None

    if idx == 0:
        return None
    if idx < 1 or idx > len(files):
        console.print("[red]Invalid selection.[/red]")
        return None

    selected = files[idx - 1]
    console.print(f"[green]Selected:[/green] {selected.name}")
    return selected

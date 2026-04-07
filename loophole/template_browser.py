"""Utility for browsing and selecting template files from a directory."""

from __future__ import annotations

from pathlib import Path

import questionary
from rich.console import Console


def browse_and_select(directory: Path, label: str, console: Console) -> Path | None:
    """List files in a directory and let the user pick one with arrow keys.

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

    # Build choices with preview text
    choices = []
    for f in files:
        try:
            preview = f.read_text()[:80].replace("\n", " ").strip()
            if len(f.read_text()) > 80:
                preview += "..."
        except Exception:
            preview = ""
        display = f"{f.name}  ({preview})" if preview else f.name
        choices.append(questionary.Choice(title=display, value=str(f)))

    choices.append(questionary.Choice(title="Cancel", value=None))

    result = questionary.select(
        f"Select {label.lower()}:",
        choices=choices,
    ).ask()

    if result is None:
        return None

    selected = Path(result)
    console.print(f"[green]Selected:[/green] {selected.name}")
    return selected

import typer
from rich.console import Console

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command(name="create")
def create():
    """Create a new backup archive."""
    from app.backup import create_backup

    path = create_backup()
    console.print(f"[green]Backup created:[/green] {path}")


@app.command(name="list")
def list_backups():
    """List available backup archives."""
    from app.backup import list_backups as _list

    backups = _list()
    if not backups:
        console.print("No backups found.")
        return
    for path in backups:
        console.print(path)


@app.command(name="restore")
def restore(
    path: str = typer.Argument(..., help="Path to the backup .tar.gz archive."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Restore from a backup archive (DESTRUCTIVE)."""
    if not yes:
        typer.confirm(
            "This will overwrite the current database and config. Continue?",
            abort=True,
        )
    from app.backup import restore_backup

    restore_backup(path)
    console.print("[green]Restore completed.[/green]")

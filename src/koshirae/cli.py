"""Punto de entrada único: ``koshirae repo|mongo|watch``."""

from __future__ import annotations

import sys

import typer
from rich.console import Console

from koshirae import __version__
from koshirae.mongo.cli import app as mongo_app
from koshirae.mongo.cli import _hoist_global_flags
from koshirae.repo.cli import app as repo_app

err_console = Console(stderr=True)

app = typer.Typer(
    name="koshirae",
    help="[bold]koshirae[/] — repos, bases de datos y procesos desde una sola terminal.",
    no_args_is_help=True,
    add_completion=True,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(repo_app, name="repo", help="Repositorios de GitHub, GitLab y Bitbucket (GitKeeper).")
app.add_typer(mongo_app, name="mongo", help="MongoDB self-hosted y Atlas (Mangosta).")


def _version(value: bool) -> None:
    if value:
        print(f"koshirae {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: bool = typer.Option(False, "--version", "-V", callback=_version, is_eager=True,
                                 help="Muestra la versión."),
) -> None:
    """Koshirae agrupa tus herramientas de día a día."""


def _run(argv: list[str]) -> None:
    from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

    from koshirae.mongo.errors import MangostaError

    if argv[:1] == ["mongo"]:
        argv = ["mongo", *_hoist_global_flags(argv[1:])]
    try:
        app(args=argv, prog_name="koshirae")
    except MangostaError as e:
        err_console.print(f"[red]✗[/] {e}")
        sys.exit(1)
    except ServerSelectionTimeoutError as e:
        reason = str(e).split(" (configured timeouts")[0].split(", Timeout:")[0]
        err_console.print(f"[red]✗ No se pudo conectar a MongoDB:[/] {reason}")
        sys.exit(1)
    except PyMongoError as e:
        err_console.print(f"[red]✗ MongoDB:[/] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        err_console.print("\n[dim]Interrumpido[/]")
        sys.exit(130)


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main() -> None:
    _utf8()
    _run(sys.argv[1:])


def gk() -> None:
    """Atajo de siempre: ``gk`` == ``koshirae repo``."""
    _utf8()
    _run(["repo", *sys.argv[1:]])


def mgs() -> None:
    """Atajo de siempre: ``mgs`` == ``koshirae mongo``."""
    _utf8()
    _run(["mongo", *sys.argv[1:]])

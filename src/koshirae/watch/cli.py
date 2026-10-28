"""``koshirae watch``: comandos de vigilancia (antes GitMaster)."""

from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.markup import escape

from koshirae.watch import config as cfg
from koshirae.watch.errors import WatchError
from koshirae.watch.logger import logger
from koshirae.watch.models import Pm2Config, Project

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

app = typer.Typer(
    help="Vigila repos locales: git pull, build y reinicio de PM2 (GitMaster).",
    no_args_is_help=False,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)


def fail(message: str, code: int = 1) -> typer.Exit:
    err_console.print(f"[red]✗[/] {escape(message)}")
    return typer.Exit(code)


@app.callback()
def root(ctx: typer.Context) -> None:
    """Sin subcomando abre el panel interactivo."""
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty() and sys.stdin.isatty():
            tui()
        else:
            print(ctx.get_help())


@app.command()
def start() -> None:
    """Vigila los repositorios en continuo: pull, build y reinicio de PM2."""
    from koshirae.watch.watcher import watcher

    try:
        config = cfg.load_config()
    except WatchError as e:
        raise fail(str(e)) from e
    done = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: done.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: done.set())
    watcher.start(config)
    done.wait()
    console.print()
    logger.info("Recibida señal de detención. Cerrando temporizadores...")
    watcher.stop()


@app.command("check-now")
def check_now(project: Annotated[Optional[str], typer.Argument(help="Proyecto (por defecto, todos).")] = None) -> None:
    """Comprueba y actualiza ahora (todos o uno) y sale."""
    from koshirae.watch.watcher import watcher

    try:
        config = cfg.load_config()
    except WatchError as e:
        raise fail(str(e)) from e
    if project:
        found = config.find(project)
        if not found:
            raise fail(f"No se encontró el proyecto '{project}' en la configuración.")
        logger.info(f"Ejecutando comprobación forzada para '{found.name}'...")
        watcher.process_project(found)
    else:
        logger.info("Ejecutando comprobación forzada para todos los proyectos habilitados...")
        watcher.check_all(config)


@app.command("list")
def list_cmd() -> None:
    """Proyectos configurados y sus ajustes."""
    try:
        config = cfg.load_config()
    except WatchError as e:
        raise fail(str(e)) from e
    console.print("\n[bold cyan]=== Proyectos registrados ===[/]")
    console.print(f"Intervalo por defecto: [yellow]{config.default_interval_seconds}s[/]   [dim]({cfg.config_path()})[/]\n")
    if not config.projects:
        console.print("[dim]No hay proyectos configurados.[/]\n")
        return
    for i, p in enumerate(config.projects, 1):
        badge = "[green]\\[ACTIVO][/]" if p.enabled else "[red]\\[DESACTIVADO][/]"
        console.print(f"{i}. [bold magenta]{escape(p.name)}[/] {badge}")
        console.print(f"   Ruta:   {escape(p.path)}")
        console.print(f"   Rama:   [blue]{escape(p.branch or 'Auto-detectar')}[/]")
        console.print(f"   Tiempo: [yellow]{p.interval_seconds or config.default_interval_seconds}s[/]")
        console.print(f"   Build:  [dim]{escape(p.build_command or 'Ninguno')}[/]")
        pm = f"[magenta]{escape(p.pm2.process_name)} ({p.pm2.action})[/]" if p.pm2 else "[dim]Ninguno[/]"
        console.print(f"   PM2:    {pm}\n")


@app.command("pm2-status")
def pm2_status() -> None:
    """Procesos PM2 detectados y su estado."""
    from koshirae.watch import pm2

    procs = pm2.process_list()
    console.print("\n[bold magenta]=== Procesos PM2 detectados ===[/]")
    if not procs:
        console.print("[dim]No se encontraron procesos activos o PM2 no está en ejecución.[/]\n")
        return
    for p in procs:
        color = "green" if p.status == "online" else "yellow"
        console.print(f"• ID: [cyan]{p.pm_id}[/] | Nombre: [bold]{escape(p.name)}[/] | Estado: [{color}]{p.status}[/]")
    console.print()


@app.command()
def add(
    name: Annotated[str, typer.Option("--name", "-n", help="Nombre identificador del proyecto.")],
    path: Annotated[str, typer.Option("--path", "-p", help="Ruta local a la carpeta del repositorio.")],
    branch: Annotated[Optional[str], typer.Option("--branch", "-b", help="Rama a vigilar (por defecto, la actual).")] = None,
    interval: Annotated[Optional[int], typer.Option("--interval", "-i", min=1, help="Intervalo en segundos.")] = None,
    build: Annotated[Optional[str], typer.Option("--build", help="Comando de compilación, p. ej. 'pnpm run build'.")] = None,
    pm2: Annotated[Optional[str], typer.Option("--pm2", help="Proceso PM2 a reiniciar si está encendido.")] = None,
    deps: Annotated[bool, typer.Option("--deps/--no-deps", help="Instalar dependencias si cambian.")] = True,
) -> None:
    """Registra un proyecto nuevo (o actualiza uno con el mismo nombre)."""
    project = Project(
        name=name, path=path, branch=branch, interval_seconds=interval, install_deps_on_pull=deps,
        build_command=build, pm2=Pm2Config(pm2) if pm2 else None,
    )
    try:
        updated = cfg.add_project(project)
    except WatchError as e:
        raise fail(str(e)) from e
    console.print(f"\n[green]✔ Proyecto '{escape(name)}' {'actualizado' if updated else 'guardado'} en {Path(cfg.config_path()).name}.[/]\n")


@app.command()
def remove(name: Annotated[str, typer.Argument(help="Nombre del proyecto.")]) -> None:
    """Elimina un proyecto de la configuración."""
    try:
        removed = cfg.remove_project(name)
    except WatchError as e:
        raise fail(str(e)) from e
    if not removed:
        raise fail(f"No se encontró el proyecto '{name}' en la configuración.")
    console.print(f"[green]✔ Proyecto '{escape(name)}' eliminado.[/]")


@app.command("push-all")
def push_all(
    projects: Annotated[Optional[list[str]], typer.Argument(help="Proyectos (por defecto, todos).")] = None,
    message: Annotated[str, typer.Option("--message", "-m", help="Mensaje de commit.")] = "chore: sync changes",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="No pedir confirmación.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Solo mostrar el plan, sin tocar nada.")] = False,
) -> None:
    """Commit + push de todo lo que esté pendiente de subir."""
    from koshirae.watch.push import run_push_all

    try:
        code = run_push_all(cfg.load_config(), projects or [], message, yes, dry_run)
    except WatchError as e:
        raise fail(str(e)) from e
    raise typer.Exit(code)


@app.command()
def logs(
    projects: Annotated[Optional[list[str]], typer.Argument(help="Filtra por proyecto.")] = None,
    lines: Annotated[int, typer.Option("--lines", "-n", help="Entradas anteriores a mostrar.")] = 40,
    level: Annotated[Optional[str], typer.Option("--level", "-l", help="Niveles separados por comas (info,git,build,pm2,success,warn,error).")] = None,
    follow: Annotated[bool, typer.Option("--follow/--no-follow", help="Seguir en vivo.")] = True,
    raw: Annotated[bool, typer.Option("--raw", help="Texto plano, sin colores (para grep/pipes).")] = False,
) -> None:
    """Logs en vivo, con filtros por proyecto y nivel."""
    from koshirae.watch.logs import run_logs

    raise typer.Exit(run_logs(projects or [], lines, level, follow, raw))


@app.command("tui")
@app.command("ui", hidden=True)
def tui() -> None:
    """Panel interactivo con el estado de proyectos y PM2."""
    from koshirae.watch.tui import run_tui

    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        raise fail("La TUI necesita una terminal interactiva.")
    try:
        run_tui(cfg.load_config())
    except WatchError as e:
        raise fail(str(e)) from e

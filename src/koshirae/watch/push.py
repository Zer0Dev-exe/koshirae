"""``watch push-all``: commit + push de todo lo pendiente, con plan previo y confirmación."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from rich.console import Console
from rich.markup import escape

from koshirae.watch import gitops
from koshirae.watch.logger import logger
from koshirae.watch.models import Project, PushPlan, WatchConfig

console = Console(highlight=False)


@dataclass
class Entry:
    project: Project
    plan: PushPlan | None = None
    error: str | None = None

    @property
    def needs_work(self) -> bool:
        return bool(self.plan and not self.plan.skip and (self.plan.files or self.plan.ahead > 0))


def _analyze(project: Project) -> Entry:
    try:
        ok, reason = gitops.validate_repository(project)
        if not ok:
            return Entry(project, error=reason)
        return Entry(project, plan=gitops.get_push_plan(project))
    except Exception as e:  # noqa: BLE001
        return Entry(project, error=str(e))


def run_push_all(config: WatchConfig, names: list[str], message: str, yes: bool, dry_run: bool) -> int:
    """Devuelve el código de salida."""
    wanted = [n.lower() for n in names]
    unknown = [n for n in wanted if not any(p.name.lower() == n for p in config.projects)]
    if unknown:
        logger.error(f"Proyecto(s) no encontrado(s) en la configuración: {', '.join(unknown)}")
        return 1

    projects = [p for p in config.projects if p.enabled and (not wanted or p.name.lower() in wanted)]
    console.print(f"[dim]Analizando {len(projects)} proyecto(s)...[/]")
    if not projects:
        return 0
    with ThreadPoolExecutor(max_workers=min(8, len(projects))) as pool:
        entries = list(pool.map(_analyze, projects))

    width = max(8, *(len(e.project.name) for e in entries))
    console.print("\n[bold cyan]=== Plan de subida ===[/]\n")
    for e in entries:
        name = f"[bold]{escape(e.project.name.ljust(width))}[/]"
        if e.error:
            console.print(f"[red]✖[/] {name} [red]{escape(e.error)}[/]")
        elif e.plan.skip:
            console.print(f"[yellow]⚠[/] {name} [yellow]omitido: {escape(e.plan.skip)}[/]")
        elif not e.needs_work:
            console.print(f"[green]✔[/] {name} [dim]nada que subir[/]")
        else:
            parts = []
            if e.plan.files:
                parts.append(f"[yellow]{len(e.plan.files)} fichero(s) a commitear[/]")
            if e.plan.ahead > 0:
                parts.append(f"[blue]{e.plan.ahead} commit(s) sin subir[/]")
            console.print(f"[cyan]↑[/] {name} [dim]{escape(e.plan.branch)}[/]  " + " [dim]·[/] ".join(parts))
            for f in e.plan.files[:6]:
                console.print(f"    [dim]{escape(f)}[/]")
            if len(e.plan.files) > 6:
                console.print(f"[dim]    … y {len(e.plan.files) - 6} más[/]")

    todo = [e for e in entries if e.needs_work]
    if not todo:
        console.print("\n[green]No hay nada pendiente de subir.[/]\n")
        return 1 if any(e.error for e in entries) else 0
    if dry_run:
        console.print(f"\n[dim](--dry-run) Se subirían {len(todo)} proyecto(s). No se ha cambiado nada.[/]\n")
        return 0

    if not yes:
        if not sys.stdin.isatty():
            logger.error("Se necesita una terminal interactiva para confirmar. Usa --yes para omitir la confirmación.")
            return 1
        answer = input(f'\nSe hará commit ("{message}") y push de {len(todo)} proyecto(s) a su remoto. ¿Continuar? (s/N) ')
        if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
            console.print("[dim]Cancelado. No se ha cambiado nada.[/]\n")
            return 0

    console.print()
    failed = 0
    for e in todo:
        try:
            committed = gitops.commit_and_push(e.project, e.plan, message)
            logger.success("Commit y push completados." if committed else "Push completado.", e.project.name)
        except Exception as err:  # noqa: BLE001
            failed += 1
            logger.error("No se pudo subir:", err, e.project.name)

    if failed == 0:
        console.print(f"\n[green]✔ {len(todo)} proyecto(s) subidos.[/]\n")
    else:
        console.print(f"\n[red]{len(todo) - failed} subidos, {failed} con error.[/]\n")
    return 0 if failed == 0 else 1

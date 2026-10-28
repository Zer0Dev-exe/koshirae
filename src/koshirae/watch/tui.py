"""Panel interactivo (Textual) con el estado de los proyectos y de PM2."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Static

from koshirae.watch import gitops, pm2
from koshirae.watch.logger import logger
from koshirae.watch.models import Project, WatchConfig
from koshirae.watch.watcher import watcher

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@dataclass
class Row:
    project: Project
    phase: str = "idle"  # idle | checking | updating
    behind: int | None = None
    commit: str = ""
    branch: str = ""
    dirty: bool = False
    error: str | None = None
    checked_at: float | None = None


def ago(ts: float | None) -> str:
    if not ts:
        return "—"
    s = int(time.time() - ts)
    return f"hace {s}s" if s < 60 else f"hace {s // 60}m" if s < 3600 else f"hace {s // 3600}h"


class WatchApp(App[None]):
    TITLE = "koshirae watch"
    BINDINGS = [
        Binding("enter,u", "update", "Actualizar"),
        Binding("a", "update_all", "Actualizar todo"),
        Binding("r", "refresh", "Revisar"),
        Binding("q", "quit", "Salir"),
    ]
    CSS = "DataTable { height: 1fr; } #pm2 { height: auto; max-height: 10; padding: 0 1; color: $text-muted; }"

    def __init__(self, config: WatchConfig) -> None:
        super().__init__()
        self.config = config
        self.rows = [Row(p) for p in config.projects]
        self.pm2_list: list[pm2.Pm2Process] = []
        self.frame = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Static("", id="pm2")
        yield Footer()

    def on_mount(self) -> None:
        logger.quiet = True  # la consola de la TUI no se puede pisar; los logs se ven con `watch logs`
        table = self.query_one(DataTable)
        table.add_columns("Proyecto", "Rama", "Commit", "Estado", "PM2", "Revisado")
        self.set_interval(0.15, self._tick)
        self.set_interval(30, self.action_refresh)
        self.action_refresh()

    def on_unmount(self) -> None:
        logger.quiet = False

    # --- render ---------------------------------------------------------------------------------------------
    def _state(self, r: Row) -> Text:
        spin = SPINNER[self.frame % len(SPINNER)]
        if not r.project.enabled:
            return Text("desactivado", "dim")
        if r.phase == "checking":
            return Text(f"{spin} comprobando", "cyan")
        if r.phase == "updating":
            return Text(f"{spin} actualizando", "yellow")
        err = watcher.last_error(r.project.name) or r.error
        if err:
            return Text("✖ " + err.splitlines()[0][:60], "red")
        if watcher.has_pending(r.project.name):
            return Text("⚠ pipeline pendiente", "yellow")
        if r.behind is None:
            return Text("—", "dim")
        if r.behind > 0:
            return Text(f"↓ {r.behind} pendiente{'' if r.behind == 1 else 's'}", "yellow")
        return Text("✔ al día" + (" · cambios locales" if r.dirty else ""), "green")

    def _pm2_cell(self, r: Row) -> Text:
        cfg = r.project.pm2
        if not cfg:
            return Text("—", "dim")
        proc = next((p for p in self.pm2_list if p.name.lower() == cfg.process_name.lower()), None)
        if proc is None:
            return Text(f"{cfg.process_name} (no registrado)", "dim")
        return Text(f"{cfg.process_name} {proc.status}", "green" if proc.status == "online" else "yellow")

    def _tick(self) -> None:
        self.frame += 1
        self._render_rows()

    def _render_rows(self) -> None:
        table = self.query_one(DataTable)
        selected = table.cursor_row
        table.clear()
        for r in self.rows:
            table.add_row(
                Text(r.project.name, "bold"), r.branch or r.project.branch or "—", r.commit or "—",
                self._state(r), self._pm2_cell(r), ago(r.checked_at), key=r.project.name,
            )
        if self.rows:
            table.move_cursor(row=min(selected, len(self.rows) - 1))
        lines = [f"{p.pm_id:>3}  {p.name:<24} {p.status}" for p in self.pm2_list]
        self.query_one("#pm2", Static).update("PM2\n" + ("\n".join(lines) if lines else "sin procesos (¿pm2 instalado?)"))

    # --- trabajo en hilos -----------------------------------------------------------------------------------
    def _inspect(self, r: Row) -> None:
        r.phase = "checking"
        try:
            ok, reason = gitops.validate_repository(r.project)
            if not ok:
                r.error, r.behind = reason, None
                return
            status = gitops.check_for_updates(r.project)
            r.behind, r.commit, r.branch, r.error = status.commits_behind, status.current_commit[:7], status.branch, None
            r.dirty = gitops.tracked_changes(r.project.path)
        except Exception as e:  # noqa: BLE001
            r.error = str(e)
        finally:
            r.phase, r.checked_at = "idle", time.time()

    def _update(self, r: Row) -> None:
        r.phase = "updating"
        try:
            watcher.process_project(r.project)
        finally:
            r.phase = "idle"
        self._inspect(r)

    @work(thread=True, exclusive=True, group="refresh")
    def action_refresh(self) -> None:
        self.pm2_list = pm2.process_list()
        with ThreadPoolExecutor(max_workers=self.config.concurrency) as pool:
            list(pool.map(self._inspect, [r for r in self.rows if r.project.enabled]))

    @work(thread=True, group="update")
    def action_update(self) -> None:
        table = self.query_one(DataTable)
        if self.rows and 0 <= table.cursor_row < len(self.rows):
            self._update(self.rows[table.cursor_row])
            self.pm2_list = pm2.process_list()

    @work(thread=True, group="update")
    def action_update_all(self) -> None:
        todo = [r for r in self.rows if r.project.enabled and ((r.behind or 0) > 0 or watcher.has_pending(r.project.name))]
        with ThreadPoolExecutor(max_workers=self.config.concurrency) as pool:
            list(pool.map(self._update, todo))
        self.pm2_list = pm2.process_list()


def run_tui(config: WatchConfig) -> None:
    WatchApp(config).run()

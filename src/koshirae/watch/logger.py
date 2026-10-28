"""Log en consola y en fichero, con el mismo formato que GitMaster.

``[2026-10-20T20:06:14.835Z] [INFO] [Proyecto] mensaje`` (para que ``watch logs`` y los viejos logs sigan valiendo).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.markup import escape

from koshirae.watch.config import config_dir

LEVELS = ("INFO", "GIT", "BUILD", "PM2", "SUCCESS", "WARN", "ERROR")
STYLES = {
    "INFO": "cyan", "GIT": "blue", "BUILD": "yellow", "PM2": "bright_magenta",
    "SUCCESS": "green", "WARN": "bright_yellow", "ERROR": "red",
}


def log_file_path() -> Path:
    return config_dir() / "logs" / "gitmaster.log"


class Logger:
    def __init__(self) -> None:
        self.console = Console(highlight=False)
        self.err_console = Console(stderr=True, highlight=False)
        self.quiet = False  # la TUI lo activa para no pisar la pantalla
        self.listeners: list[Callable[[str, str, str | None], None]] = []
        self._lock = threading.Lock()

    def _write_file(self, level: str, message: str, project: str | None) -> None:
        utc = datetime.now(timezone.utc)
        now = utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"
        prefix = f"[{project}] " if project else ""
        try:
            path = log_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, path.open("a", encoding="utf-8") as f:
                f.write(f"[{now}] [{level}] {prefix}{message}\n")
        except OSError:
            pass  # log bloqueado: no es motivo para parar

    def log(self, level: str, message: str, project: str | None = None) -> None:
        self._write_file(level, message, project)
        for listener in self.listeners:
            listener(level, message, project)
        if self.quiet:
            return
        style = STYLES[level]
        stamp = datetime.now().strftime("%H:%M:%S")
        tag = f"[{style}]\\[{level}][/]"
        proj = f"[bold magenta]\\[{escape(project)}][/] " if project else ""
        body = escape(message)
        if level in ("SUCCESS", "WARN", "ERROR"):
            body = f"[{style}]{body}[/]"
        out = self.err_console if level in ("WARN", "ERROR") else self.console
        out.print(f"[dim]\\[{stamp}][/] {tag} {proj}{body}")

    def info(self, m: str, p: str | None = None) -> None: self.log("INFO", m, p)
    def git(self, m: str, p: str | None = None) -> None: self.log("GIT", m, p)
    def build(self, m: str, p: str | None = None) -> None: self.log("BUILD", m, p)
    def pm2(self, m: str, p: str | None = None) -> None: self.log("PM2", m, p)
    def success(self, m: str, p: str | None = None) -> None: self.log("SUCCESS", m, p)
    def warn(self, m: str, p: str | None = None) -> None: self.log("WARN", m, p)

    def error(self, m: str, err: object = None, p: str | None = None) -> None:
        detail = f" - {err}" if err else ""
        self.log("ERROR", m + detail, p)


logger = Logger()

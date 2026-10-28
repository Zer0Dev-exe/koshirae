"""``watch logs``: últimas entradas del log y seguimiento en vivo, con filtros."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.markup import escape

from koshirae.watch.logger import LEVELS, STYLES, log_file_path

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

# [2026-10-20T20:06:14.835Z] [INFO] [Proyecto] mensaje
LINE = re.compile(r"^\[(\d{4}-\d\d-\d\dT[^\]]+)\] \[(\w+)\] (?:\[([^\]]+)\] )?(.*)$")


@dataclass
class Entry:
    time: datetime
    level: str
    project: str | None
    message: str


def parse_entries(lines: list[str]) -> list[Entry]:
    """Las líneas sin cabecera (salida multilínea de un build) cuelgan de la entrada anterior."""
    entries: list[Entry] = []
    for line in lines:
        m = LINE.match(line)
        if m:
            when = datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).astimezone()
            entries.append(Entry(when, m.group(2), m.group(3), m.group(4)))
        elif entries:
            entries[-1].message += "\n" + line
    return entries


def format_entry(e: Entry, name_width: int) -> str:
    style = STYLES.get(e.level, "white")
    day = "" if e.time.date() == datetime.now().date() else f"[dim]{e.time:%m-%d} [/]"
    project = f"[bold magenta]{escape(e.project.ljust(name_width))}[/] " if e.project else ""
    first, *rest = e.message.split("\n")
    more = "".join(f"\n[dim]  │ {escape(line)}[/]" for line in rest)
    return f"{day}[dim]{e.time:%H:%M:%S}[/] [{style}]{e.level.ljust(7)}[/] {project}[{style}]{escape(first)}[/]{more}"


def format_raw(e: Entry) -> str:
    proj = f"[{e.project}] " if e.project else ""
    return f"[{e.time.astimezone().isoformat()}] [{e.level}] {proj}{e.message}"


def read_tail(file: Path, count: int, keep: Callable[[Entry], bool]) -> list[Entry]:
    """Lee desde el final hasta reunir ``count`` entradas que pasen el filtro (o llegar al principio)."""
    with file.open("rb") as f:
        size = f.seek(0, 2)
        chunk = 256 * 1024
        while True:
            length = min(size, chunk)
            f.seek(size - length)
            lines = f.read(length).decode("utf-8", errors="replace").split("\n")
            if length < size:
                lines = lines[1:]  # primera línea posiblemente cortada
            found = [e for e in parse_entries([l for l in lines if l]) if keep(e)]
            if len(found) >= count or length >= size:
                return found[-count:] if count > 0 else []
            chunk *= 4


def run_logs(projects: list[str], lines: int, level: str | None, follow: bool, raw: bool) -> int:
    file = log_file_path()
    if not file.exists():
        err_console.print(f"[yellow]Todavía no hay logs ({file}).[/]")
        return 0 if follow else 1

    levels: set[str] | None = None
    if level:
        wanted = [l.strip().upper() for l in level.split(",") if l.strip()]
        bad = [l for l in wanted if l not in LEVELS]
        if bad:
            err_console.print(f"[red]Nivel(es) no válido(s): {', '.join(bad)}. Disponibles: {', '.join(l.lower() for l in LEVELS)}[/]")
            return 1
        levels = set(wanted)
    names = {p.lower() for p in projects}

    def keep(e: Entry) -> bool:
        return (levels is None or e.level in levels) and (not names or (e.project is not None and e.project.lower() in names))

    width = max([8, 14, *(len(p) for p in projects)])

    def show(e: Entry) -> None:
        if raw:
            print(format_raw(e))
        else:
            console.print(format_entry(e, width))

    tail = read_tail(file, lines, keep)
    if not tail and not follow:
        err_console.print("[dim]Sin entradas que coincidan con el filtro.[/]")
    for e in tail:
        show(e)
    if not follow:
        return 0

    if err_console.is_terminal:
        err_console.print("[dim]── siguiendo logs en vivo · Ctrl+C para salir ──[/]")
    offset, partial = file.stat().st_size, ""
    try:
        while True:
            time.sleep(0.4)
            try:
                size = file.stat().st_size
            except OSError:
                continue
            if size < offset:  # fichero rotado o truncado
                offset, partial = 0, ""
            if size == offset:
                continue
            with file.open("rb") as f:
                f.seek(offset)
                data = f.read(size - offset).decode("utf-8", errors="replace")
            offset = size
            *complete, partial = (partial + data).split("\n")
            for e in parse_entries([l for l in complete if l]):
                if keep(e):
                    show(e)
    except KeyboardInterrupt:
        return 0

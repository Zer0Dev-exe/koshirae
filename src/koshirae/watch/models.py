"""Modelos de datos y validación de la configuración.

El fichero admite claves en español o en inglés (como GitMaster) y siempre se guarda en español.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from koshirae.watch.errors import ConfigError

DEPENDENCY_FILES = {"package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "pnpm-workspace.yaml"}


@dataclass
class Pm2Config:
    process_name: str
    action: str = "restart"  # restart | reload
    start_if_not_running: bool = False


@dataclass
class Project:
    name: str
    path: str
    branch: str | None = None
    remote: str = "origin"
    interval_seconds: int | None = None
    install_deps_on_pull: bool = True
    install_command: str = "pnpm install"
    build_command: str | None = None
    pm2: Pm2Config | None = None
    auto_stash: bool = False
    enabled: bool = True


@dataclass
class WatchConfig:
    default_interval_seconds: int = 60
    concurrency: int = 2
    projects: list[Project] = field(default_factory=list)

    def find(self, name: str) -> Project | None:
        return next((p for p in self.projects if p.name.lower() == name.lower()), None)


@dataclass
class UpdateCheck:
    has_updates: bool
    commits_behind: int
    current_commit: str
    remote_commit: str
    branch: str


@dataclass
class PullResult:
    commit_before: str
    commit_after: str
    changed_files: list[str]
    dependency_files_changed: bool


@dataclass
class PushPlan:
    branch: str
    files: list[str]
    ahead: int = 0
    behind: int = 0
    skip: str | None = None  # motivo por el que no se sube; si existe, se omite


def _first(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{label} debe ser un entero positivo (recibido: {value!r})")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{label} debe ser true o false (recibido: {value!r})")
    return value


def parse_pm2(raw: Any, where: str) -> Pm2Config | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}.pm2 debe ser un objeto o null")
    name = _first(raw, "nombreProceso", "processName")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("El nombre del proceso PM2 no puede estar vacío")
    action = _first(raw, "accion", "action", default="restart")
    if action not in ("restart", "reload"):
        raise ConfigError(f"{where}.pm2.accion debe ser 'restart' o 'reload' (recibido: {action!r})")
    start = _bool(_first(raw, "iniciarSiEstaApagado", "startIfNotRunning", default=False), f"{where}.pm2.iniciarSiEstaApagado")
    return Pm2Config(name, action, start)


def parse_project(raw: Any, index: int) -> Project:
    where = f"proyectos[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} debe ser un objeto")
    name = _first(raw, "nombre", "name")
    path = _first(raw, "ruta", "path")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("El nombre del proyecto no puede estar vacío")
    if not isinstance(path, str) or not path.strip():
        raise ConfigError(f"La ruta del proyecto '{name}' no puede estar vacía")
    interval = _first(raw, "intervaloSegundos", "intervalSeconds")
    build = _first(raw, "comandoBuild", "buildCommand")
    branch = _first(raw, "rama", "branch")
    return Project(
        name=name,
        path=path,
        branch=branch,
        remote=_first(raw, "remoto", "remote", default="origin"),
        interval_seconds=_positive_int(interval, f"{where}.intervaloSegundos") if interval is not None else None,
        install_deps_on_pull=_bool(
            _first(raw, "instalarDependencias", "instalarDependenciasTrasPull", "installDepsOnPull", default=True),
            f"{where}.instalarDependencias",
        ),
        install_command=_first(raw, "comandoInstalar", "installCommand", default="pnpm install"),
        build_command=build,
        pm2=parse_pm2(raw.get("pm2"), where),
        auto_stash=_bool(_first(raw, "guardarCambiosLocalesAuto", "autoStash", default=False), f"{where}.guardarCambiosLocalesAuto"),
        enabled=_bool(_first(raw, "activado", "habilitado", "enabled", default=True), f"{where}.activado"),
    )


def parse_config(raw: Any) -> WatchConfig:
    if not isinstance(raw, dict):
        raise ConfigError("La configuración debe ser un objeto JSON")
    interval = _first(raw, "intervaloPorDefectoSegundos", "intervaloGlobalSegundos", "defaultIntervalSeconds", default=60)
    concurrency = _first(raw, "concurrencia", "concurrency", default=2)
    projects = _first(raw, "proyectos", "projects", default=[])
    if not isinstance(projects, list):
        raise ConfigError("'proyectos' debe ser una lista")
    return WatchConfig(
        default_interval_seconds=_positive_int(interval, "intervaloPorDefectoSegundos"),
        concurrency=_positive_int(concurrency, "concurrencia"),
        projects=[parse_project(p, i) for i, p in enumerate(projects)],
    )


def to_spanish(config: WatchConfig) -> dict[str, Any]:
    return {
        "intervaloPorDefectoSegundos": config.default_interval_seconds,
        "concurrencia": config.concurrency,
        "proyectos": [
            {
                "nombre": p.name,
                "ruta": p.path,
                "rama": p.branch or "main",
                "intervaloSegundos": p.interval_seconds or config.default_interval_seconds,
                "instalarDependencias": p.install_deps_on_pull,
                "comandoInstalar": p.install_command or "pnpm install",
                "comandoBuild": p.build_command or "pnpm run build",
                "pm2": (
                    {
                        "nombreProceso": p.pm2.process_name,
                        "accion": p.pm2.action,
                        "iniciarSiEstaApagado": p.pm2.start_if_not_running,
                    }
                    if p.pm2
                    else None
                ),
                "guardarCambiosLocalesAuto": p.auto_stash,
                "activado": p.enabled,
            }
            for p in config.projects
        ],
    }

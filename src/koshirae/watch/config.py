"""Carga y guardado de la configuración de ``koshirae watch``.

Directorio: ``KOSHIRAE_WATCH_DIR`` o ``GITMASTER_DIR`` (para reutilizar tu GitMaster actual),
y si no ``<config del usuario>/koshirae/watch``. Admite ``config.jsonc`` y ``config.json``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from platformdirs import user_config_dir

from koshirae.watch.errors import ConfigError
from koshirae.watch.models import Pm2Config, Project, WatchConfig, parse_config, to_spanish

CONFIG_FILES = ("config.jsonc", "config.json")
_COMMENTS = re.compile(r'\\"|"(?:\\"|[^"])*"|(//.*|/\*[\s\S]*?\*/)')


def config_dir() -> Path:
    env = os.environ.get("KOSHIRAE_WATCH_DIR") or os.environ.get("GITMASTER_DIR")
    return Path(env).resolve() if env else Path(user_config_dir("koshirae")) / "watch"


def config_path() -> Path:
    for name in CONFIG_FILES:
        candidate = config_dir() / name
        if candidate.exists():
            return candidate
    return config_dir() / CONFIG_FILES[0]


def strip_comments(text: str) -> str:
    return _COMMENTS.sub(lambda m: "" if m.group(1) else m.group(0), text)


def default_config() -> WatchConfig:
    return WatchConfig(
        projects=[
            Project(
                name="ejemplo-proyecto",
                path=str(Path.home() / "proyectos" / "mi-proyecto"),
                branch="main",
                interval_seconds=60,
                build_command="pnpm run build",
                pm2=Pm2Config("mi-app"),
                enabled=False,
            )
        ]
    )


def load_config() -> WatchConfig:
    path = config_path()
    if not path.exists():
        config = default_config()
        save_config(config)
        return config
    try:
        return parse_config(json.loads(strip_comments(path.read_text(encoding="utf-8"))))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path.name} no es un JSON válido: {e}") from e
    except ConfigError as e:
        raise ConfigError(f"{path.name}: {e}") from e


def save_config(config: WatchConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(to_spanish(config), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def add_project(project: Project) -> bool:
    """Añade o actualiza un proyecto. Devuelve True si ya existía y se actualizó."""
    config = load_config()
    for i, existing in enumerate(config.projects):
        if existing.name.lower() == project.name.lower():
            config.projects[i] = project
            save_config(config)
            return True
    config.projects.append(project)
    save_config(config)
    return False


def remove_project(name: str) -> bool:
    config = load_config()
    kept = [p for p in config.projects if p.name.lower() != name.lower()]
    if len(kept) == len(config.projects):
        return False
    config.projects = kept
    save_config(config)
    return True

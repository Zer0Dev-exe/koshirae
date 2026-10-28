"""Control de PM2 (sin shell: los nombres de proceso van como argumentos)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from koshirae.watch.logger import logger
from koshirae.watch.models import Pm2Config


@dataclass
class Pm2Process:
    name: str
    pm_id: int
    status: str


def _run(*args: str) -> str:
    proc = subprocess.run(["pm2", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"pm2 {' '.join(args)} falló")
    return proc.stdout


def process_list() -> list[Pm2Process]:
    try:
        out = _run("jlist")
        start = out.find("[")  # pm2 puede imprimir avisos antes del JSON
        data = json.loads(out[start:]) if start >= 0 else []
    except FileNotFoundError:
        logger.warn("El comando 'pm2' no parece estar disponible en el PATH del sistema.")
        return []
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        return []
    if not isinstance(data, list):
        return []
    return [Pm2Process(i.get("name", "?"), i.get("pm_id", -1), (i.get("pm2_env") or {}).get("status", "unknown")) for i in data]


def find_process(identifier: str) -> Pm2Process | None:
    for proc in process_list():
        if proc.name.lower() == identifier.lower() or (identifier.isdigit() and proc.pm_id == int(identifier)):
            return proc
    return None


def handle_restart(cfg: Pm2Config, project_name: str) -> bool:
    """Reinicia el proceso solo si está online (o lo arranca si ``start_if_not_running``)."""
    name = cfg.process_name
    try:
        existing = find_process(name)
        if existing is None:
            if cfg.start_if_not_running:
                logger.pm2(f"El proceso '{name}' no existe en PM2. Intentando iniciar...", project_name)
                _run("start", name)
                logger.success(f"Proceso '{name}' iniciado en PM2.", project_name)
                return True
            logger.info(f"El proceso '{name}' no está registrado en PM2. No se requiere reinicio.", project_name)
            return False

        if existing.status != "online":
            if cfg.start_if_not_running:
                logger.pm2(f"El proceso '{name}' está en estado '{existing.status}'. Iniciando...", project_name)
                _run("start", str(existing.pm_id))
                logger.success(f"Proceso '{name}' iniciado en PM2.", project_name)
                return True
            logger.info(f"El proceso '{name}' no está encendido en PM2 (estado: {existing.status}). No se reinicia.", project_name)
            return False

        logger.pm2(f"Proceso '{name}' está encendido en PM2. Ejecutando {cfg.action}...", project_name)
        _run(cfg.action, str(existing.pm_id))
        logger.success(f"Proceso '{name}' reiniciado con éxito en PM2.", project_name)
        return True
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        logger.error(f"Error gestionando PM2 para '{name}':", e, project_name)
        return False

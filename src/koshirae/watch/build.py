"""Ejecución de comandos (install/build) en la carpeta de cada proyecto."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from koshirae.watch.errors import CommandError
from koshirae.watch.logger import logger

COMMAND_TIMEOUT = 15 * 60
MAX_OUTPUT = 200_000


def execute_command(command: str, cwd: str, project_name: str) -> str:
    """Ejecuta ``command`` con la shell del sistema (es la línea que escribió el usuario en su config)."""
    resolved = Path(cwd).expanduser().resolve()
    logger.build(f'Ejecutando: "{command}" en {resolved}', project_name)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command, cwd=str(resolved), shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=COMMAND_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandError(f'El comando "{command}" superó el límite de {COMMAND_TIMEOUT // 60} min.') from e
    except OSError as e:
        raise CommandError(f'No se pudo invocar el comando "{command}": {e}') from e

    output = (proc.stdout + proc.stderr)[-MAX_OUTPUT:]
    if proc.returncode != 0:
        raise CommandError(f"El comando falló con código de salida {proc.returncode}.\nSalida:\n{output.strip()}")
    logger.success(f"Comando finalizado con éxito ({time.monotonic() - start:.2f}s)", project_name)
    return output

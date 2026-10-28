"""Bucle de vigilancia: fetch → pull → install → build → pm2, con un hilo por proyecto."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from koshirae.watch import build, gitops, pm2
from koshirae.watch.logger import logger
from koshirae.watch.models import Project, WatchConfig


class Watcher:
    def __init__(self) -> None:
        self._active: set[str] = set()
        self._guard = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        # Pull hecho pero pipeline (install/build/pm2) fallido: se reintenta sin volver a hacer pull
        self.pending: dict[str, bool] = {}
        # Último error por proyecto, para no repetir el mismo aviso en cada tick
        self.last_errors: dict[str, str] = {}

    def last_error(self, name: str) -> str | None:
        return self.last_errors.get(name.lower())

    def has_pending(self, name: str) -> bool:
        return name.lower() in self.pending

    def process_project(self, project: Project) -> bool:
        """Devuelve True si hubo actualización y el pipeline terminó bien."""
        if not project.enabled:
            return False
        key = project.name.lower()
        with self._guard:
            if key in self._active:
                logger.warn("El proyecto ya tiene una comprobación o build en curso. Omitiendo tick.", project.name)
                return False
            self._active.add(key)
        try:
            ok, reason = gitops.validate_repository(project)
            if not ok:
                logger.warn(f"Configuración inválida: {reason}", project.name)
                return False

            install_deps = False
            if key in self.pending:
                logger.warn("Reintentando pipeline pendiente de una actualización anterior (build/instalación fallida).", project.name)
                install_deps = self.pending[key]
            else:
                status = gitops.check_for_updates(project)
                if not status.has_updates:
                    self.last_errors.pop(key, None)
                    logger.info(f"Al día (rama '{status.branch}', commit {status.current_commit[:7]})", project.name)
                    return False
                if key not in self.last_errors:
                    logger.git(
                        f"Novedad detectada: {status.commits_behind} commit(s) pendientes en '{status.branch}'. "
                        "Procediendo con actualización...", project.name,
                    )
                pulled = gitops.pull_updates(project)
                logger.success(
                    f"Pull completado ({pulled.commit_before[:7]} -> {pulled.commit_after[:7]}). "
                    f"Archivos modificados: {len(pulled.changed_files)}", project.name,
                )
                install_deps = pulled.dependency_files_changed
                self.pending[key] = install_deps

            if project.install_deps_on_pull and install_deps:
                cmd = project.install_command or "pnpm install"
                logger.build(f"Se detectaron cambios en archivos de dependencias. Ejecutando: {cmd}", project.name)
                build.execute_command(cmd, project.path, project.name)
                self.pending[key] = False

            if project.build_command and project.build_command.strip():
                logger.build(f'Iniciando build: "{project.build_command}"', project.name)
                build.execute_command(project.build_command, project.path, project.name)

            if project.pm2:
                pm2.handle_restart(project.pm2, project.name)

            self.pending.pop(key, None)
            self.last_errors.pop(key, None)
            logger.success("Pipeline de actualización completado exitosamente.", project.name)
            return True
        except Exception as e:  # noqa: BLE001 - un proyecto roto no debe parar a los demás
            message = str(e)
            if self.last_errors.get(key) != message:
                self.last_errors[key] = message
                logger.error("Error en ciclo de actualización (no se repetirá el aviso hasta que cambie):", message, project.name)
            return False
        finally:
            with self._guard:
                self._active.discard(key)

    def check_all(self, config: WatchConfig) -> None:
        enabled = [p for p in config.projects if p.enabled]
        if not enabled:
            logger.warn("No hay proyectos habilitados en la configuración.")
            return
        logger.info(f"Comprobando {len(enabled)} proyecto(s)...")
        with ThreadPoolExecutor(max_workers=min(config.concurrency, len(enabled))) as pool:
            list(pool.map(self.process_project, enabled))

    def _loop(self, project: Project, seconds: int) -> None:
        while not self._stop.wait(seconds):
            try:
                self.process_project(project)
            except Exception as e:  # noqa: BLE001
                logger.error("Error no controlado en el temporizador:", e, project.name)

    def start(self, config: WatchConfig) -> None:
        if self._threads:
            logger.warn("El watcher ya se encuentra en ejecución.")
            return
        self._stop.clear()
        logger.info(f"Iniciando vigilancia con {len(config.projects)} proyecto(s) configurado(s).")
        threading.Thread(target=self._initial, args=(config,), daemon=True).start()
        for project in config.projects:
            if not project.enabled:
                logger.info(f"Proyecto deshabilitado (no se vigilará): {project.name}")
                continue
            seconds = project.interval_seconds or config.default_interval_seconds or 60
            logger.info(f"Vigilando cada {seconds}s (rama: {project.branch or 'detectada'}, ruta: {project.path})", project.name)
            t = threading.Thread(target=self._loop, args=(project, seconds), daemon=True)
            t.start()
            self._threads.append(t)
        logger.success("Koshirae watch está activo y vigilando los repositorios.")

    def _initial(self, config: WatchConfig) -> None:
        try:
            self.check_all(config)
        except Exception as e:  # noqa: BLE001
            logger.error("Error en la comprobación inicial:", e)

    def stop(self, timeout: float = 300) -> None:
        self._stop.set()
        deadline = time.monotonic() + timeout
        while self._active and time.monotonic() < deadline:  # no dejar repos a medias
            logger.info(f"Esperando a que terminen {len(self._active)} proyecto(s) en curso...")
            time.sleep(2)
        self._threads = []
        logger.info("Koshirae watch detenido.")


watcher = Watcher()

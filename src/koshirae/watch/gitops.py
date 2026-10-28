"""Operaciones git sobre cada proyecto (sin shell: los argumentos van como lista)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from koshirae.watch.errors import CommandError
from koshirae.watch.logger import logger
from koshirae.watch.models import DEPENDENCY_FILES, Project, PullResult, PushPlan, UpdateCheck

GIT_TIMEOUT = 120
# Ficheros que nunca se suben automáticamente
SENSITIVE = re.compile(
    r"(^|/)(\.env(\.(?!example$|sample$|template$|dist$).*)?|id_rsa|id_ed25519|credentials(\.json)?|.*\.(pem|key|p12|pfx))$",
    re.IGNORECASE,
)


def git(path: str | Path, *args: str, check: bool = True) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(path), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=GIT_TIMEOUT, env=env,
        )
    except FileNotFoundError as e:
        raise CommandError("No encuentro git en el PATH") from e
    except subprocess.TimeoutExpired as e:
        raise CommandError(f"git {' '.join(args)} tardó más de {GIT_TIMEOUT}s") from e
    if check and proc.returncode != 0:
        raise CommandError((proc.stderr or proc.stdout).strip() or f"git {' '.join(args)} falló ({proc.returncode})")
    return proc.stdout.strip()


def validate_repository(project: Project) -> tuple[bool, str | None]:
    resolved = Path(project.path).expanduser().resolve()
    if not resolved.exists():
        return False, f"La carpeta no existe: {resolved}"
    try:
        git(resolved, "rev-parse", "--is-inside-work-tree")
    except CommandError:
        return False, f"El directorio no es un repositorio Git: {resolved}"
    return True, None


def status_entries(path: str | Path) -> list[tuple[str, str]]:
    """(XY, ruta) de `git status`, incluidos los ficheros sin seguimiento."""
    raw = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"], cwd=str(path), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT,
    )
    if raw.returncode != 0:
        raise CommandError(raw.stderr.strip() or "git status falló")
    parts = raw.stdout.split("\0")
    entries: list[tuple[str, str]] = []
    i = 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        xy, name = item[:2], item[3:]
        if "R" in xy or "C" in xy:
            i += 1  # en renombrados, la ruta original va en el siguiente campo
        entries.append((xy, name))
    return entries


def tracked_changes(path: str | Path) -> bool:
    """¿Hay cambios en ficheros rastreados (modificados, en el índice o borrados)?"""
    return any(xy != "??" and xy != "!!" for xy, _ in status_entries(path))


def current_branch(path: str | Path) -> str:
    name = git(path, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    return "" if name in ("", "HEAD") else name


def active_branch(project: Project) -> str:
    if project.branch and project.branch.strip():
        return project.branch.strip()
    return current_branch(project.path) or "main"


def check_for_updates(project: Project) -> UpdateCheck:
    branch = active_branch(project)
    remote = project.remote or "origin"
    try:
        git(project.path, "fetch", remote, branch)
    except CommandError as e:
        raise CommandError(f"Fallo al hacer git fetch {remote} {branch}: {e}") from e

    current = git(project.path, "rev-parse", "HEAD")
    remote_ref = f"{remote}/{branch}"
    try:
        remote_commit = git(project.path, "rev-parse", remote_ref)
    except CommandError:
        remote_commit = git(project.path, "rev-parse", "@{u}")

    try:
        behind = int(git(project.path, "rev-list", "--count", f"HEAD..{remote_ref}") or 0)
    except (CommandError, ValueError):
        behind = 1 if current != remote_commit else 0
    return UpdateCheck(behind > 0, behind, current, remote_commit, branch)


def pull_updates(project: Project) -> PullResult:
    branch = active_branch(project)
    remote = project.remote or "origin"
    remote_ref = f"{remote}/{branch}"
    before = git(project.path, "rev-parse", "HEAD")

    ahead = git(project.path, "rev-list", "--count", f"{remote_ref}..HEAD", check=False)
    if (int(ahead) if ahead.isdigit() else 0) > 0:
        local = git(project.path, "log", "--format=%h %s", f"{remote_ref}..HEAD")
        raise CommandError(
            f"La rama local '{branch}' ha divergido de {remote_ref}: tiene commits que el remoto no tiene y no se "
            f"puede hacer fast-forward. Commits locales:\n{local}\n"
            f"Si son versiones antiguas de commits ya reescritos en el remoto, guárdalos (git branch backup <hash>) y "
            f"alinea con 'git reset --hard {remote_ref}'. Si no, haz push o rebase manualmente."
        )

    stashed = False
    if tracked_changes(project.path):
        if not project.auto_stash:
            raise CommandError(
                "El repositorio tiene cambios locales modificados sin commitear y 'guardarCambiosLocalesAuto' está "
                "deshabilitado. Se omite pull para no sobreescribir trabajo."
            )
        logger.git("Cambios locales en archivos rastreados detectados. Aplicando stash temporal...", project.name)
        git(project.path, "stash", "push", "-m", "koshirae-auto-stash")
        stashed = True

    try:
        logger.git(f"Ejecutando git pull {remote} {branch}...", project.name)
        git(project.path, "pull", "--ff-only", remote, branch)
        after = git(project.path, "rev-parse", "HEAD")
        changed = git(project.path, "diff", "--name-only", before, after).splitlines() if before != after else []
    finally:
        if stashed:
            try:
                git(project.path, "stash", "pop")
                logger.git("Stash restaurado correctamente.", project.name)
            except CommandError as e:
                logger.warn(f"Atención: Fallo al restaurar el stash: {e}", project.name)

    deps = any(Path(f).name in DEPENDENCY_FILES for f in changed)
    return PullResult(before, after, changed, deps)


def get_push_plan(project: Project) -> PushPlan:
    remote = project.remote or "origin"
    entries = status_entries(project.path)
    branch = current_branch(project.path)
    files = [name for _, name in entries]
    plan = PushPlan(branch=branch, files=files)

    if not branch:
        plan.skip = "HEAD desacoplado (sin rama)"
        return plan
    if project.branch and project.branch != branch:
        plan.skip = f"está en '{branch}', se esperaba '{project.branch}'"
        return plan
    sensitive = [f for f in files if SENSITIVE.search(f)]
    if sensitive:
        plan.skip = f"contiene ficheros sensibles sin ignorar: {', '.join(sensitive)}"
        return plan

    try:
        git(project.path, "fetch", remote, branch)
    except CommandError as e:
        plan.skip = f"sin acceso al remoto '{remote}': {str(e).splitlines()[0]}"
        return plan

    try:
        ahead, behind = (int(n) for n in git(project.path, "rev-list", "--left-right", "--count", f"HEAD...{remote}/{branch}").split())
        plan.ahead, plan.behind = ahead, behind
    except (CommandError, ValueError):
        # La rama aún no existe en el remoto: todos sus commits son nuevos
        plan.ahead = int(git(project.path, "rev-list", "--count", "HEAD") or 0)

    if plan.behind > 0:
        plan.skip = f"va {plan.behind} commit(s) por detrás del remoto: haz pull antes"
    return plan


def commit_and_push(project: Project, plan: PushPlan, message: str) -> bool:
    """Devuelve True si hizo commit (además del push)."""
    remote = project.remote or "origin"
    committed = False
    if plan.files:
        git(project.path, "add", "-A")
        git(project.path, "commit", "-m", message)
        committed = True
    git(project.path, "push", remote, plan.branch)
    return committed

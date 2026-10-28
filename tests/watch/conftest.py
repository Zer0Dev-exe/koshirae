import subprocess
from pathlib import Path

import pytest

from koshirae.watch.models import Project


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KOSHIRAE_WATCH_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("GITMASTER_DIR", raising=False)
    for k, v in {"NAME": "t", "EMAIL": "t@t.t"}.items():
        monkeypatch.setenv(f"GIT_AUTHOR_{k}", v)
        monkeypatch.setenv(f"GIT_COMMITTER_{k}", v)
    from koshirae.watch.logger import logger
    from koshirae.watch.watcher import watcher

    logger.quiet = True
    watcher.pending.clear()
    watcher.last_errors.clear()


class Repos:
    """Remoto bare + clon del proyecto + segundo clon para publicar novedades."""

    def __init__(self, root: Path):
        self.remote = root / "remote.git"
        sh(root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.work = root / "work"
        self.other = root / "other"
        sh(root, "clone", "-q", str(self.remote), str(self.work))
        (self.work / "a.txt").write_text("1")
        sh(self.work, "add", "-A")
        sh(self.work, "commit", "-qm", "init")
        sh(self.work, "push", "-q", "origin", "HEAD:main")
        sh(root, "clone", "-q", str(self.remote), str(self.other))
        self.project = Project(name="demo", path=str(self.work), branch="main")

    def publish(self, name="b.txt", content="x", message="more"):
        (self.other / name).write_text(content)
        sh(self.other, "add", "-A")
        sh(self.other, "commit", "-qm", message)
        sh(self.other, "push", "-q", "origin", "HEAD:main")


@pytest.fixture
def repos(tmp_path):
    return Repos(tmp_path)

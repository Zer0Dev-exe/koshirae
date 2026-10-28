import pytest

from koshirae.watch import gitops
from koshirae.watch.errors import CommandError
from tests.watch.conftest import sh


def test_validate(repos, tmp_path):
    assert gitops.validate_repository(repos.project) == (True, None)
    ok, why = gitops.validate_repository(type(repos.project)(name="x", path=str(tmp_path / "nope")))
    assert not ok and "no existe" in why
    plain = tmp_path / "plain"; plain.mkdir()
    ok, why = gitops.validate_repository(type(repos.project)(name="x", path=str(plain)))
    assert not ok and "no es un repositorio" in why


def test_check_and_pull_fast_forward(repos):
    assert gitops.check_for_updates(repos.project).has_updates is False
    repos.publish("package.json", "{}", "deps")
    status = gitops.check_for_updates(repos.project)
    assert status.has_updates and status.commits_behind == 1
    pulled = gitops.pull_updates(repos.project)
    assert pulled.changed_files == ["package.json"] and pulled.dependency_files_changed
    assert (repos.work / "package.json").exists()


def test_pull_refuses_local_changes_without_autostash(repos):
    repos.publish()
    (repos.work / "a.txt").write_text("sucio")
    with pytest.raises(CommandError, match="cambios locales"):
        gitops.pull_updates(repos.project)
    assert (repos.work / "a.txt").read_text() == "sucio"


def test_pull_autostash_restores_work(repos):
    repos.publish()
    repos.project.auto_stash = True
    (repos.work / "a.txt").write_text("sucio")
    gitops.pull_updates(repos.project)
    assert (repos.work / "a.txt").read_text() == "sucio" and (repos.work / "b.txt").exists()


def test_untracked_files_do_not_block_pull(repos):
    repos.publish()
    (repos.work / "nuevo.log").write_text("x")
    assert gitops.pull_updates(repos.project).commit_before != gitops.git(repos.work, "rev-parse", "HEAD")


def test_pull_reports_divergence(repos):
    (repos.work / "local.txt").write_text("l"); sh(repos.work, "add", "-A"); sh(repos.work, "commit", "-qm", "local")
    repos.publish()
    with pytest.raises(CommandError, match="ha divergido"):
        gitops.pull_updates(repos.project)


def test_push_plan_and_push(repos):
    (repos.work / "n.txt").write_text("n")
    plan = gitops.get_push_plan(repos.project)
    assert plan.files == ["n.txt"] and plan.skip is None
    assert gitops.commit_and_push(repos.project, plan, "feat: n") is True
    assert sh(repos.other, "pull", "-q", "origin", "main") is not None and (repos.other / "n.txt").exists()
    assert gitops.get_push_plan(repos.project).files == []


def test_push_plan_skips_secrets_and_behind(repos):
    (repos.work / ".env").write_text("TOKEN=1")
    assert "sensibles" in gitops.get_push_plan(repos.project).skip
    (repos.work / ".env").unlink()
    (repos.work / ".env.example").write_text("TOKEN=")
    assert gitops.get_push_plan(repos.project).skip is None
    repos.publish()
    assert "por detrás" in gitops.get_push_plan(repos.project).skip


def test_push_plan_wrong_branch(repos):
    sh(repos.work, "checkout", "-q", "-b", "feature")
    assert "se esperaba 'main'" in gitops.get_push_plan(repos.project).skip


@pytest.mark.parametrize("name,sensitive", [
    (".env", True), (".env.production", True), (".env.example", False), ("a/id_rsa", True),
    ("certs/server.pem", True), ("credentials.json", True), ("src/environment.ts", False),
])
def test_sensitive_regex(name, sensitive):
    assert bool(gitops.SENSITIVE.search(name)) is sensitive

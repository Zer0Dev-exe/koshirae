import json

from koshirae.watch import pm2
from koshirae.watch.models import Pm2Config, WatchConfig
from koshirae.watch.watcher import watcher


def test_up_to_date_does_nothing(repos):
    assert watcher.process_project(repos.project) is False


def test_pipeline_runs_in_order(repos, monkeypatch):
    calls = []
    repos.publish("package.json", "{}", "deps")
    repos.project.install_command = "echo install"
    repos.project.build_command = "echo build"
    repos.project.pm2 = Pm2Config("demo")
    from koshirae.watch import build
    monkeypatch.setattr(build, "execute_command", lambda cmd, cwd, name: calls.append(cmd) or "")
    monkeypatch.setattr(pm2, "handle_restart", lambda cfg, name: calls.append("pm2") or True)
    assert watcher.process_project(repos.project) is True
    assert calls == ["echo install", "echo build", "pm2"]


def test_no_install_when_deps_unchanged(repos, monkeypatch):
    calls = []
    repos.publish()
    repos.project.build_command = "echo build"
    from koshirae.watch import build
    monkeypatch.setattr(build, "execute_command", lambda cmd, cwd, name: calls.append(cmd) or "")
    assert watcher.process_project(repos.project) is True and calls == ["echo build"]


def test_failed_build_retries_without_new_pull(repos):
    repos.publish()
    repos.project.build_command = "exit 3"
    assert watcher.process_project(repos.project) is False
    assert watcher.has_pending("demo") and "código de salida 3" in watcher.last_error("demo")
    repos.project.build_command = "true"  # arreglado: reintenta sin pull (ya está al día)
    assert watcher.process_project(repos.project) is True
    assert not watcher.has_pending("demo") and watcher.last_error("demo") is None


def test_dirty_repo_error_is_recorded_once(repos, capsys):
    repos.publish()
    (repos.work / "a.txt").write_text("sucio")
    assert watcher.process_project(repos.project) is False
    first = watcher.last_error("demo")
    assert "cambios locales" in first
    assert watcher.process_project(repos.project) is False and watcher.last_error("demo") == first


def test_disabled_and_invalid_paths(repos):
    repos.project.enabled = False
    assert watcher.process_project(repos.project) is False
    repos.project.enabled, repos.project.path = True, "/no/existe"
    assert watcher.process_project(repos.project) is False


def test_check_all_respects_concurrency(repos):
    watcher.check_all(WatchConfig(projects=[repos.project], concurrency=1))
    watcher.check_all(WatchConfig(projects=[]))  # sin habilitados: no falla


def _fake_run(monkeypatch, procs, seen):
    def run(*args):
        seen.append(args)
        return json.dumps(procs) if args[0] == "jlist" else ""
    monkeypatch.setattr(pm2, "_run", run)


def test_pm2_restarts_only_online(monkeypatch):
    seen = []
    _fake_run(monkeypatch, [{"name": "a", "pm_id": 3, "pm2_env": {"status": "online"}},
                            {"name": "b", "pm_id": 4, "pm2_env": {"status": "stopped"}}], seen)
    assert pm2.handle_restart(Pm2Config("a", "reload"), "p") is True and ("reload", "3") in seen
    assert pm2.handle_restart(Pm2Config("b"), "p") is False
    assert pm2.handle_restart(Pm2Config("zzz"), "p") is False
    assert pm2.handle_restart(Pm2Config("b", start_if_not_running=True), "p") is True and ("start", "4") in seen
    assert pm2.handle_restart(Pm2Config("zzz", start_if_not_running=True), "p") is True and ("start", "zzz") in seen


def test_pm2_missing_binary(monkeypatch):
    def boom(*a): raise FileNotFoundError
    monkeypatch.setattr(pm2, "_run", boom)
    assert pm2.process_list() == []


def test_pm2_name_is_not_shell_interpreted(monkeypatch):
    seen = []
    _fake_run(monkeypatch, [], seen)
    pm2.handle_restart(Pm2Config("x; rm -rf ~", start_if_not_running=True), "p")
    assert ("start", "x; rm -rf ~") in seen  # llega como un único argumento

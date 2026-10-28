from koshirae.watch import config as cfg
from koshirae.watch.logger import log_file_path, logger
from koshirae.watch.logs import parse_entries, read_tail, run_logs
from koshirae.watch.models import WatchConfig
from koshirae.watch.push import run_push_all
from tests.watch.conftest import sh


def test_log_roundtrip_and_multiline():
    logger.info("hola", "api")
    logger.error("falló", "boom\nlinea 2", "api")
    logger.success("ok")
    entries = parse_entries(log_file_path().read_text(encoding="utf-8").splitlines())
    assert [(e.level, e.project) for e in entries] == [("INFO", "api"), ("ERROR", "api"), ("SUCCESS", None)]
    assert entries[1].message.startswith("falló - boom")


def test_tail_filters(capsys):
    for i in range(30):
        logger.info(f"m{i}", "a" if i % 2 else "b")
    logger.error("x", None, "a")
    got = read_tail(log_file_path(), 5, lambda e: e.project == "a")
    assert len(got) == 5 and got[-1].level == "ERROR"
    assert run_logs(["a"], 3, "error,info", False, True) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 3 and all("[a]" in l for l in out)
    assert run_logs([], 3, "nope", False, True) == 1


def test_logs_without_file(capsys):
    assert run_logs([], 10, None, False, False) == 1


def test_push_all_dry_run_and_real(repos, capsys):
    config = WatchConfig(projects=[repos.project])
    assert run_push_all(config, [], "msg", True, True) == 0
    assert "No se ha cambiado nada" not in capsys.readouterr().out  # nada pendiente aún
    (repos.work / "n.txt").write_text("n")
    assert run_push_all(config, [], "msg", True, True) == 0
    assert "dry-run" in capsys.readouterr().out and not (repos.other / "n.txt").exists()
    assert run_push_all(config, [], "feat: n", True, False) == 0
    sh(repos.other, "pull", "-q", "origin", "main")
    assert (repos.other / "n.txt").exists()
    assert run_push_all(config, ["fantasma"], "m", True, False) == 1


def test_push_all_non_interactive_needs_yes(repos):
    (repos.work / "n.txt").write_text("n")
    assert run_push_all(WatchConfig(projects=[repos.project]), [], "m", False, False) == 1

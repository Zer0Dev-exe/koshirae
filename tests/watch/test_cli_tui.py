from typer.testing import CliRunner

from koshirae.cli import app
from koshirae.watch.models import WatchConfig
from koshirae.watch.tui import WatchApp

runner = CliRunner()


def test_cli_add_list_remove_and_check_now(repos):
    r = runner.invoke(app, ["watch", "add", "-n", "demo", "-p", str(repos.work), "-b", "main", "--build", "true"])
    assert r.exit_code == 0 and "guardado" in r.output
    assert "demo" in runner.invoke(app, ["watch", "list"]).output
    repos.publish()
    r = runner.invoke(app, ["watch", "check-now", "demo"])
    assert r.exit_code == 0 and (repos.work / "b.txt").exists()
    assert runner.invoke(app, ["watch", "check-now", "nope"]).exit_code == 1
    assert runner.invoke(app, ["watch", "remove", "demo"]).exit_code == 0
    assert runner.invoke(app, ["watch", "remove", "demo"]).exit_code == 1


def test_cli_push_all_dry_run(repos):
    runner.invoke(app, ["watch", "add", "-n", "demo", "-p", str(repos.work), "-b", "main"])
    (repos.work / "n.txt").write_text("n")
    r = runner.invoke(app, ["watch", "push-all", "--dry-run"])
    assert r.exit_code == 0 and "1 fichero(s) a commitear" in r.output


def test_cli_logs_after_check(repos):
    runner.invoke(app, ["watch", "add", "-n", "demo", "-p", str(repos.work), "-b", "main"])
    runner.invoke(app, ["watch", "check-now"])
    r = runner.invoke(app, ["watch", "logs", "--no-follow", "--raw", "-l", "info"])
    assert r.exit_code == 0 and "Al día" in r.output


async def test_tui_shows_state_and_updates(repos):
    repos.publish()
    app_ = WatchApp(WatchConfig(projects=[repos.project]))
    async with app_.run_test() as pilot:
        for _ in range(40):
            await pilot.pause(0.1)
            if app_.rows[0].behind is not None:
                break
        assert app_.rows[0].behind == 1
        await pilot.press("u")
        for _ in range(40):
            await pilot.pause(0.1)
            if (repos.work / "b.txt").exists() and app_.rows[0].phase == "idle":
                break
        assert (repos.work / "b.txt").exists() and app_.rows[0].behind == 0

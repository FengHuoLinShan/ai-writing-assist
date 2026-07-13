from pathlib import Path
from unittest.mock import patch

from watchfiles import Change

from scripts import dev_server


def test_serve_runs_uvicorn_without_nested_reload_supervisor() -> None:
    with patch.object(dev_server.uvicorn, "run", autospec=True) as run:
        dev_server._serve("127.0.0.1", 8123)

    run.assert_called_once_with(
        "app.main:app",
        host="127.0.0.1",
        port=8123,
        reload=False,
        log_level="info",
    )


def test_run_dev_server_uses_process_level_reload() -> None:
    reload_dirs = ["/repo/backend/app", "/repo/backend/modules"]
    with (
        patch.object(
            dev_server,
            "_existing_reload_dirs",
            autospec=True,
            return_value=reload_dirs,
        ),
        patch.object(dev_server, "run_process", autospec=True) as run_process,
    ):
        dev_server.run_dev_server("0.0.0.0", 8000, reload_enabled=True)

    args, kwargs = run_process.call_args
    assert list(args) == reload_dirs
    assert kwargs["target"] is dev_server._serve
    assert kwargs["args"] == ("0.0.0.0", 8000)
    assert kwargs["target_type"] == "function"
    assert kwargs["callback"] is dev_server._log_reload
    assert kwargs["debounce"] == 500
    assert kwargs["sigint_timeout"] == 10
    assert kwargs["sigkill_timeout"] == 2


def test_run_dev_server_without_reload_runs_one_process() -> None:
    with (
        patch.object(dev_server, "_serve", autospec=True) as serve,
        patch.object(dev_server, "run_process", autospec=True) as run_process,
    ):
        dev_server.run_dev_server("127.0.0.1", 8124, reload_enabled=False)

    serve.assert_called_once_with("127.0.0.1", 8124)
    run_process.assert_not_called()


def test_existing_reload_dirs_are_absolute_and_present() -> None:
    reload_dirs = dev_server._existing_reload_dirs()

    assert reload_dirs
    assert all(Path(path).is_absolute() for path in reload_dirs)
    assert all(Path(path).exists() for path in reload_dirs)


def test_log_reload_reports_the_changed_backend_paths(capsys) -> None:
    dev_server._log_reload(
        {
            (Change.modified, str(dev_server.BACKEND_ROOT / "modules/world/api.py")),
            (Change.added, str(dev_server.BACKEND_ROOT / "prompts/new.md")),
        }
    )

    output = capsys.readouterr().out
    assert "restarting complete server process" in output
    assert "modified:modules/world/api.py" in output
    assert "added:prompts/new.md" in output

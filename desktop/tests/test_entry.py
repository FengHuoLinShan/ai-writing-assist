import sys
from types import SimpleNamespace

from infrastructure.os_security import private_directory

from desktop.entry import desktop


def test_gui_creates_private_data_root_before_webview(monkeypatch, tmp_path):
    directory = tmp_path / "first-launch"
    monkeypatch.setenv("NOVELCRAFT_DESKTOP_DATA_DIR", str(directory))

    class Event:
        def __iadd__(self, callback):
            return self

    window = SimpleNamespace(events=SimpleNamespace(closed=Event()))

    def start(callback, **options):
        assert directory.is_dir()
        assert private_directory(directory) == directory
        assert options["storage_path"] == str(directory / "webview")
        assert sys.modules["webview"].settings["ALLOW_DOWNLOADS"] is True

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(
        create_window=lambda *args, **kwargs: window, start=start, settings={},
    ))
    desktop()

import multiprocessing
import os
from pathlib import Path

from infrastructure.os_security import open_private_file, private_directory, try_lock


def hold_lock(directory, ready):
    path = private_directory(Path(directory)) / "instance.lock"
    fd = open_private_file(path, write=True)
    assert try_lock(fd)
    ready.set()
    multiprocessing.Event().wait(30)
    os.close(fd)


def test_process_death_releases_private_lock(tmp_path):
    directory = private_directory(tmp_path / "private")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=hold_lock, args=(str(directory), ready))
    process.start()
    fd = None
    try:
        assert ready.wait(15)
        fd = open_private_file(directory / "instance.lock", write=True)
        assert not try_lock(fd)
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        assert try_lock(fd)
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
        if fd is not None:
            os.close(fd)

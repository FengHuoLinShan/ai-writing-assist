import os
import subprocess
from pathlib import Path

import pytest

from desktop.windows_process import WindowsDatabaseProcess


@pytest.mark.skipif(os.name != "nt", reason="Windows process ownership")
def test_native_process_identity_wait_and_termination():
    executable = Path(os.environ["SYSTEMROOT"]) / "System32/ping.exe"
    child = subprocess.Popen(
        [str(executable), "-n", "30", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    monitor = None
    try:
        with pytest.raises(RuntimeError, match="身份"):
            WindowsDatabaseProcess(child.pid, "wrong-executable.exe")
        assert child.poll() is None
        monitor = WindowsDatabaseProcess(child.pid, str(executable))
        assert monitor.poll() is None
        with pytest.raises(subprocess.TimeoutExpired):
            monitor.wait(timeout=0.01)
        monitor.terminate()
        assert monitor.wait(timeout=10) is not None
        child.wait(timeout=10)
    finally:
        if monitor:
            monitor.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)

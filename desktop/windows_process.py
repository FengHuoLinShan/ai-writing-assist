"""Monitor the exact database process started with pg_ctl's restricted token."""

import subprocess
from pathlib import Path


class WindowsDatabaseProcess:
    stdin = None

    def __init__(self, pid: int, executable: str):
        import win32api
        import win32con
        import win32event
        import win32process

        self.pid = pid
        self.api = win32api
        self.events = win32event
        self.process = win32process
        self.handle = win32api.OpenProcess(
            win32con.SYNCHRONIZE
            | win32con.PROCESS_QUERY_INFORMATION
            | win32con.PROCESS_VM_READ
            | win32con.PROCESS_TERMINATE,
            False,
            pid,
        )
        try:
            actual = Path(win32process.GetModuleFileNameEx(self.handle, 0))
            if actual.resolve() != Path(executable).resolve():
                raise RuntimeError("数据库进程身份不符，已停止启动。")
        except BaseException:
            self.handle.Close()
            raise

    def poll(self):
        if self.events.WaitForSingleObject(self.handle, 0) == self.events.WAIT_TIMEOUT:
            return None
        return self.process.GetExitCodeProcess(self.handle)

    def wait(self, timeout=None):
        milliseconds = self.events.INFINITE if timeout is None else int(timeout * 1000)
        if (
            self.events.WaitForSingleObject(self.handle, milliseconds)
            == self.events.WAIT_TIMEOUT
        ):
            raise subprocess.TimeoutExpired("postgres", timeout)
        return self.process.GetExitCodeProcess(self.handle)

    def terminate(self):
        self.api.TerminateProcess(self.handle, 1)

    kill = terminate

    def close(self):
        self.handle.Close()

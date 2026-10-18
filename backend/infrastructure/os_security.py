"""Private files and process locks on POSIX and Windows."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def user_identity() -> str:
    if os.name != "nt":
        return str(os.getuid())
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), 8)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(sid)
    finally:
        token.Close()


def _windows_security(path: Path, *, create: bool = False) -> None:
    import win32security as security

    flags = security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
    descriptor = security.GetFileSecurity(str(path), flags)
    identity = user_identity()
    trusted = {identity, "S-1-5-18", "S-1-5-32-544"}
    # Elevated Windows processes can create files owned by Administrators.
    owner = security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
    if owner not in trusted:
        raise ValueError("Private path has an untrusted owner")
    if create:
        acl = security.ACL()
        for value in (identity, "S-1-5-18", "S-1-5-32-544"):
            acl.AddAccessAllowedAceEx(
                security.ACL_REVISION,
                3 if path.is_dir() else 0,
                0x1F01FF,
                security.ConvertStringSidToSid(value),
            )
        descriptor.SetSecurityDescriptorDacl(1, acl, 0)
        security.SetFileSecurity(
            str(path),
            security.DACL_SECURITY_INFORMATION
            | security.PROTECTED_DACL_SECURITY_INFORMATION,
            descriptor,
        )
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        raise ValueError("Private path must have a restricted ACL")
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if ace[0][0] == security.ACCESS_DENIED_ACE_TYPE:
            continue
        if ace[0][0] != security.ACCESS_ALLOWED_ACE_TYPE or (
            security.ConvertSidToStringSid(ace[2])
            not in trusted
        ):
            raise ValueError("Private path permits another account")


def private_directory(path: Path) -> Path:
    created = not path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        raise ValueError("Private directory must not be a symlink")
    if os.name == "nt":
        _windows_security(path, create=created)
    elif info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private directory must be private and owned by this user")
    return path


def open_private_file(path: Path, *, write: bool = False, readable: bool = False) -> int:
    """Reject links and untrusted owners before consuming credentials or locks."""
    if path.is_symlink():
        raise ValueError("Private file must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT if write else os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Private file must be a regular file")
        if os.name == "nt":
            _windows_security(path)
        elif info.st_uid != os.getuid() or info.st_mode & (0o022 if readable else 0o077):
            raise ValueError("Private file has unsafe ownership or permissions")
        return fd
    except BaseException:
        os.close(fd)
        raise


def try_lock(fd: int) -> bool:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno not in {13, 36}:
                raise
            return False
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True

#!/usr/bin/env python3
"""Create and validate a directory used as a private filesystem boundary."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

PRIVATE_MODE = 0o700


def _is_private_directory(metadata: os.stat_result, owner_uid: int) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == owner_uid
        and stat.S_IMODE(metadata.st_mode) == PRIVATE_MODE
    )


def ensure_private_directory(directory: Path) -> bool:
    """Ensure *directory* is an owner-owned, non-symlinked 0700 directory.

    The descriptor remains open while path metadata is checked again, so a
    rename between opening the path and validating it is rejected.
    """

    descriptor = -1
    success = False
    try:
        try:
            os.mkdir(directory, PRIVATE_MODE)
        except FileExistsError:
            pass

        owner_uid = os.getuid()
        initial_metadata = os.lstat(directory)
        if stat.S_ISLNK(initial_metadata.st_mode) or not stat.S_ISDIR(
            initial_metadata.st_mode
        ):
            return success
        if initial_metadata.st_uid == owner_uid:
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(directory, flags)
            descriptor_metadata = os.fstat(descriptor)
            if stat.S_ISDIR(descriptor_metadata.st_mode) and (
                descriptor_metadata.st_uid == owner_uid
            ):
                if not _is_private_directory(descriptor_metadata, owner_uid):
                    os.fchmod(descriptor, PRIVATE_MODE)
                    descriptor_metadata = os.fstat(descriptor)

                path_metadata = os.lstat(directory)
                if not stat.S_ISLNK(path_metadata.st_mode) and _is_private_directory(
                    path_metadata, owner_uid
                ):
                    success = (
                        descriptor_metadata.st_dev,
                        descriptor_metadata.st_ino,
                    ) == (path_metadata.st_dev, path_metadata.st_ino)
    except OSError:
        success = False

    if descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError:
            success = False
    return success


def main(arguments: list[str]) -> int:
    if len(arguments) != 1 or not ensure_private_directory(Path(arguments[0])):
        print("Private directory is unsafe.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

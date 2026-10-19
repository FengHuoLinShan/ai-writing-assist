"""Local desktop implementation of the image store's narrow object operations."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path, PurePosixPath

from botocore.exceptions import ClientError

from infrastructure.os_security import private_directory


class LocalImageClient:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("Local image directory must be absolute")
        self.root = private_directory(root)

    def _bucket(self, bucket: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError("Invalid local image bucket")
        return private_directory(self.root / bucket)

    def _path(self, bucket: str, key: str) -> Path:
        parts = key.split("/")
        if not key or any(p in {"", ".", ".."} for p in parts) or "\\" in key:
            raise ValueError("Invalid local image key")
        if PurePosixPath(key).is_absolute() or any(":" in p for p in parts):
            raise ValueError("Invalid local image key")
        path = self._bucket(bucket)
        for part in parts:
            path /= part
            if path.is_symlink():
                raise ValueError("Local image paths must not contain symlinks")
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Local image path escapes storage")
        return path

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):  # noqa: N803
        path = self._path(Bucket, Key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(Body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def get_object(self, *, Bucket, Key):  # noqa: N803
        path = self._path(Bucket, Key)
        try:
            stream = path.open("rb")
        except FileNotFoundError as exc:
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchKey"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "GetObject",
            ) from exc
        return {"Body": stream, "ContentLength": os.fstat(stream.fileno()).st_size}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self._path(Bucket, Key).unlink(missing_ok=True)

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):  # noqa: N803
        root = self._bucket(Bucket)
        result = []
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("Local image paths must not contain symlinks")
            if path.is_file() and not path.name.startswith(".pending-"):
                key = path.relative_to(root).as_posix()
                if key.startswith(Prefix):
                    result.append({"Key": key})
                    if len(result) >= MaxKeys:
                        break
        return {"Contents": result}

    def list_object_versions(self, **kwargs):
        return {"Versions": [], "IsTruncated": False}

    def delete_objects(self, *, Bucket, Delete):  # noqa: N803
        for item in Delete["Objects"]:
            self.delete_object(Bucket=Bucket, Key=item["Key"])
        return {}

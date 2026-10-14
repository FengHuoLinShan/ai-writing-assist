"""Bind native text calls to a ChatGPT login, without persisting credentials."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path


def codex_login_identity() -> str:
    """Token refresh preserves identity; logout, API login and account changes do not."""
    path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o022
                or info.st_size > 131072
            ):
                raise ValueError("unsafe identity file")
            data = json.loads(stream.read(131073))
        tokens = data.get("tokens")
        if (
            data.get("auth_mode") != "chatgpt"
            or data.get("OPENAI_API_KEY")
            or not isinstance(tokens, dict)
            or not isinstance(tokens.get("account_id"), str)
            or not tokens["account_id"].strip()
        ):
            raise ValueError("unsupported login")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Codex 需要本机 ChatGPT 登录身份；请重新登录并验证连接") from exc
    return hashlib.sha256(
        (str(os.getuid()) + ":" + tokens["account_id"]).encode()
    ).hexdigest()

#!/usr/bin/python3
"""Record native CLI bytes without changing arguments, login or transport."""
# macOS /usr/bin/python3 may be 3.9, which has no datetime.UTC alias.
# ruff: noqa: UP017

import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

REAL_CLI = "/Users/tywww/.nvm/versions/node/v24.15.0/bin/codex"
ARTIFACTS = Path("/Users/tywww/.codex/private/g6b-recalibration-20261015/live")


def main():
    args = sys.argv[1:]
    if "exec" not in args:
        os.execv(REAL_CLI, [REAL_CLI, *args])
    os.umask(0o077)
    ARTIFACTS.mkdir(parents=True, exist_ok=True, mode=0o700)
    call = ARTIFACTS / uuid.uuid4().hex
    call.mkdir(mode=0o700)
    request = sys.stdin.buffer.read()
    model = args[args.index("-m") + 1] if "-m" in args else None
    expected = {"gpt-6-luna": "max", "gpt-6.1-sol": "xhigh"}.get(model)
    if expected is None or f'model_reasoning_effort="{expected}"' not in args:
        raise ValueError("G6b capture requires explicit Luna/max or Sol/xhigh")
    record = {
        "status": "pending",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "reasoning_effort": expected,
        "request_sha256": hashlib.sha256(request).hexdigest(),
        "argv": [REAL_CLI, *args],
    }
    for name, data in (
        ("request.bin", request),
        ("status.json", json.dumps(record).encode()),
    ):
        with (call / name).open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    # Preserve the native schema/instructions even after its temporary workspace closes.
    for flag, name in (("--output-schema", "schema.json"),):
        if flag in args:
            (call / name).write_bytes(Path(args[args.index(flag) + 1]).read_bytes())
    process = subprocess.Popen(
        [REAL_CLI, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def forward(source, target, name):
        with (call / name).open("xb") as saved:
            while True:
                chunk = source.read1(65536)
                if not chunk:
                    break
                saved.write(chunk)
                saved.flush()
                target.write(chunk)
                target.flush()
            os.fsync(saved.fileno())

    threads = [
        threading.Thread(
            target=forward, args=(process.stdout, sys.stdout.buffer, "stdout.bin")
        ),
        threading.Thread(
            target=forward, args=(process.stderr, sys.stderr.buffer, "stderr.bin")
        ),
    ]
    for thread in threads:
        thread.start()
    process.stdin.write(request)
    process.stdin.close()
    code = process.wait()
    for thread in threads:
        thread.join()
    record.update(
        status="native_exit",
        exit_code=code,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    with (call / "status.json").open("w") as stream:
        json.dump(record, stream)
        stream.flush()
        os.fsync(stream.fileno())
    return code


if __name__ == "__main__":
    sys.exit(main())

"""Select PR CI work; unknown paths run every gate, main always runs everything."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

GATES = frozenset({"backend", "postgresql", "frontend", "browser", "images"})


def classify(paths: list[str]) -> set[str]:
    selected: set[str] = set()
    for path in paths:
        if path == "README.md":
            selected.add("images")
        elif path.endswith(".md"):
            continue
        elif path in {
            "backend/Dockerfile",
            "frontend-console/Dockerfile",
        } or path.startswith("deploy/"):
            selected.update({"backend", "images"})
        elif path.startswith("backend/"):
            selected.update({"backend", "postgresql", "browser", "images"})
        elif path.startswith("frontend-console/"):
            selected.update({"frontend", "browser", "images"})
        else:
            selected.update(GATES)
    return selected


def changed_paths(base: str, head: str) -> list[str]:
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ValueError("Expected full base and head commit SHAs")
    # Disable rename detection so both old and new paths contribute to coverage.
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", base, head, "--"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return os.fsdecode(result.stdout).split("\0")[:-1]


def main() -> None:
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if event_name == "pull_request":
        pr = event["pull_request"]
        selected = classify(changed_paths(pr["base"]["sha"], pr["head"]["sha"]))
    elif event_name == "push" and event["ref"] == "refs/heads/main":
        selected = set(GATES)
    else:
        raise ValueError(f"Unsupported CI event: {event_name}")
    output = "".join(
        f"{gate}={str(gate in selected).lower()}\n" for gate in sorted(GATES)
    )
    # Write only after the complete diff has succeeded; failures cannot select nothing.
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(output)
    print(output, end="")


if __name__ == "__main__":
    main()

"""Pure V2 DAG validation and deterministic terminal-failure propagation."""

from __future__ import annotations

TERMINAL = frozenset({"succeeded", "failed", "blocked", "cancelled", "superseded"})


def validate_graph(items):
    if len(items) > 48:
        raise ValueError("Work graph exceeds the frozen run capacity")
    by_key = {item["key"]: item for item in items}
    if len(by_key) != len(items):
        raise ValueError("Duplicate logical work key")
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError("Cyclic work graph")
        if key in visited:
            return
        if key not in by_key:
            raise ValueError("Dependency is outside this run")
        visiting.add(key)
        dependencies = by_key[key]["dependencies"]
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("Repeated dependency")
        for dependency in dependencies:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in by_key:
        visit(key)


def ready_items(items):
    """Mutates only impossible pending items; all-terminal summaries still run."""
    validate_graph(items)
    by_key = {item["key"]: item for item in items}
    changed = True
    while changed:
        changed = False
        for item in items:
            if item["status"] != "pending" or item["dependency_policy"] == "all_terminal":
                continue
            if any(
                by_key[key]["status"] in TERMINAL - {"succeeded"}
                for key in item["dependencies"]
            ):
                item["status"] = "blocked"
                changed = True
    ready = []
    for item in items:
        acceptable = (
            TERMINAL if item["dependency_policy"] == "all_terminal" else {"succeeded"}
        )
        if item["status"] == "pending" and all(
            by_key[key]["status"] in acceptable for key in item["dependencies"]
        ):
            ready.append(item["key"])
    if (
        not ready
        and any(item["status"] == "pending" for item in items)
        and not any(item["status"] == "running" for item in items)
    ):
        raise ValueError("Pending work has no runnable dependency path")
    return ready

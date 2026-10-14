"""Freeze the author plan and model policy for new deterministic tasks."""

from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.model_limits import confirmed_scope_eligible


def run_budget_meta(run):
    mode = (run.reading_plan_json or {}).get("budget_mode", "bounded")
    if run.budget_remaining is None and (
        mode != "confirmed_scope" or not confirmed_scope_eligible(run.llm_snapshot_json)
    ):
        raise ValueError("confirmed scope requires a verified frozen Luna connection")
    return {
        "evolution_budget": {
            "mode": mode,
            "request_limit": run.budget_total,
            "snapshot": run.llm_snapshot_json,
            "fingerprint": content_hash(
                [
                    run.run_key,
                    run.owner_epoch,
                    run.reading_plan_json,
                    run.llm_snapshot_json,
                ]
            ),
        }
    }


def task_request_limit(task):
    total = ((task.meta or {}).get("evolution_budget") or {}).get("request_limit")
    return max(1, total) if total is not None else None


def task_budget_policy(task):
    budget = (task.meta or {}).get("evolution_budget")
    if not budget:
        return None  # Old queue rows had only the authoritative domain budget.
    if budget["mode"] == "bounded":
        if budget.get("request_limit") is None:
            raise ValueError("bounded tasks require a frozen allowance")
        return {"budget_mode": "bounded"}
    if (
        budget["mode"] != "confirmed_scope"
        or budget.get("request_limit") is not None
        or not confirmed_scope_eligible(budget.get("snapshot"))
    ):
        raise ValueError("invalid frozen scope model or authorization")
    return {"budget_mode": "confirmed_scope", "scope_fingerprint": budget["fingerprint"]}

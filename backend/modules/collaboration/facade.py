"""Stable background seams; Case remains the only execution authority."""

from modules.collaboration.cognition import (
    current_records as read_cognition_records,
)
from modules.collaboration.cognition import (
    read_head as read_cognition_head,
)
from modules.collaboration.cognition import (
    record_ref as cognition_record_ref,
)
from modules.collaboration.cognition import (
    revalidate_refs as revalidate_cognition_refs,
)
from modules.collaboration.creative_manifest import (
    collect_creative_manifest as collect_creative_manifest,
)
from modules.collaboration.creative_manifest import (
    collect_forecast_understanding as collect_forecast_understanding,
)
from modules.collaboration.creative_manifest import (
    creative_context_text as creative_context_text,
)
from modules.collaboration.creative_manifest import (
    inspect_cognition_freshness as inspect_cognition_freshness,
)
from modules.collaboration.creative_manifest import (
    project_creative_resources as project_creative_resources,
)
from modules.collaboration.creative_manifest import (
    revalidate_creative_manifest as revalidate_creative_manifest,
)

__all__ = [
    "read_cognition_records",
    "read_cognition_head",
    "cognition_record_ref",
    "revalidate_cognition_refs",
    "collect_creative_manifest",
    "collect_forecast_understanding",
    "creative_context_text",
    "inspect_cognition_freshness",
    "project_creative_resources",
    "revalidate_creative_manifest",
    "changed_cases",
    "submit_changed_case",
    "read_projected_run",
    "stop_unavailable_runs",
]


async def changed_cases(db, novel_id, case_ids, kind, identity):
    from modules.collaboration.proactive import changed_cases as inspect

    return await inspect(db, novel_id, case_ids, kind, identity)


async def submit_changed_case(db, novel_id, case_id):
    from modules.collaboration.proactive import submit_changed_case as submit

    return await submit(db, novel_id, case_id)


async def read_projected_run(db, novel_id, run_id):
    from modules.collaboration.views import run_view

    result = await run_view(db, novel_id, run_id)
    return {
        "id": run_id,
        "session_id": None,
        "status": "completed" if result["status"] == "partial" else result["status"],
        "result": {
            "answer": "创作试验结果已保留，请从原目标继续。",
            "case_id": result["case_id"],
        },
        "task_id": result["task_id"],
        "usage": result["usage"],
        "can_resume": False,
        "error": result["error_code"],
        "updated_at": None,
    }


async def stop_unavailable_runs(db):
    from modules.collaboration.maintenance import stop_unavailable_runs as stop

    return await stop(db)

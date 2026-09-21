"""Stable background seams; Case remains the only execution authority."""


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

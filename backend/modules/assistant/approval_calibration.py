"""Explicit, metered synthetic model calibration; never called by normal turns."""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.schemas import AIStepCallKind, LLMCallRequest, LLMMessage
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    current_ai_run_envelope,
    current_workflow_budget,
    managed_step_scope,
)
from modules.assistant.approval import JUDGE_INSTRUCTIONS, calibration_fingerprint
from modules.assistant.approval_cases import CASES, SUITE_HASH
from modules.assistant.approval_contracts import (
    APPROVAL_CAPABILITY,
    APPROVAL_POLICY,
    ApprovalJudgment,
)
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.models import AssistantApprovalCalibration
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    get_any_project_context,
    open_project_snapshot_llm_client,
    require_active_project,
)


async def calibrate_approval_model(db, novel_id: str, owner_id: str) -> dict:
    """Caller supplies an explicit calibration root, budget and durable ledger."""
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    project = await get_any_project_context(db, novel_id)
    if project is None or str(project.owner_id) != owner_id:
        raise NotFoundError("校准项目不可访问")
    envelope = current_ai_run_envelope()
    if envelope is None or current_workflow_budget() is None:
        raise ConflictError("校准必须有独立、明确授权的预算账本")
    root = envelope.snapshot()
    if (
        root.root_capability_id != APPROVAL_CAPABILITY
        or str(root.novel_id) != novel_id
        or root.requests_unknown
        or not root.usage_complete
        or root.request_limit is None
        or root.request_limit - root.requests_started < len(CASES)
        or root.deadline_at is None
    ):
        raise ConflictError("校准根能力、项目、剩余额度或用量状态不符合固定案例要求")
    snapshot = await build_project_llm_execution_snapshot(
        db, novel_id, purpose="approval_judgment"
    )
    model_hash = calibration_fingerprint(snapshot)
    query = select(AssistantApprovalCalibration).where(
        AssistantApprovalCalibration.novel_id == uuid.UUID(novel_id),
        AssistantApprovalCalibration.owner_id == uuid.UUID(owner_id),
        AssistantApprovalCalibration.model_fingerprint == model_hash,
        AssistantApprovalCalibration.policy_version == APPROVAL_POLICY,
    )
    row = await db.scalar(query.with_for_update())
    if row and row.receipt_json.get("status") in {"running", "unknown"}:
        raise ConflictError("原校准请求尚未有明确回执，请先核对；不能另开账本重试")
    previous = dict(row.receipt_json) if row else {}
    if row is None:
        row = AssistantApprovalCalibration(
            novel_id=uuid.UUID(novel_id),
            owner_id=uuid.UUID(owner_id),
            model_fingerprint=model_hash,
            policy_version=APPROVAL_POLICY,
            suite_hash=SUITE_HASH,
        )
        db.add(row)
    report = {
        "status": "running",
        "passed": False,
        "source": "live_model",
        "run_id": root.run_id,
        "model_fingerprint": model_hash,
        "suite_hash": SUITE_HASH,
        "case_count": len(CASES),
        "cases": [],
        "previous": {key: previous.get(key) for key in ("run_id", "status", "passed")},
    }
    row.receipt_json = report
    await db.commit()
    try:
        async with open_project_snapshot_llm_client(db, novel_id, snapshot) as client:
            for case in CASES:
                evidence = {
                    key: value
                    for key, value in case.items()
                    if key not in {"expected", "intent", "preserve"}
                }
                case_hash = fingerprint(
                    {"suite": SUITE_HASH, "case": evidence, "model": model_hash}
                )
                entry = {
                    "case_id": case["id"],
                    "fingerprint": case_hash,
                    "status": "pending",
                }
                report["cases"].append(entry)
                row.receipt_json = json.loads(json.dumps(report))
                await db.commit()
                payload = {
                    "author_task": {
                        "intent": case["intent"],
                        "preserve": case["preserve"],
                    },
                    "untrusted_evidence": evidence,
                    "fingerprint": case_hash,
                }
                async with asyncio.timeout(120):
                    with managed_step_scope(
                        AIManagedStepContext(
                            step_name=f"{APPROVAL_CAPABILITY}.calibration",
                            capability_id=APPROVAL_CAPABILITY,
                            call_kind=AIStepCallKind.structured,
                            profile_source=str(
                                client.runtime_scope.get("profile_source", "")
                            ),
                            profile_summary=client.profile_summary,
                            input_fingerprint=case_hash,
                        )
                    ):
                        judgment = await client.generate_structured(
                            LLMCallRequest(
                                messages=[
                                    LLMMessage(role="system", content=JUDGE_INSTRUCTIONS),
                                    LLMMessage(
                                        role="user",
                                        content=json.dumps(payload, ensure_ascii=False),
                                    ),
                                ],
                                max_tokens=1024,
                            ),
                            ApprovalJudgment.for_fingerprint(case_hash),
                            max_fix_attempts=0,
                            format_repair_attempts=0,
                            transport_retries=False,
                        )
                if (
                    judgment.fingerprint != case_hash
                    or envelope.snapshot().requests_unknown
                    or not envelope.snapshot().usage_complete
                ):
                    raise ConflictError("判断或用量回执不可验证")
                entry.update(
                    {
                        "status": "completed",
                        "decision": judgment.decision,
                        "expected": case["expected"],
                        "passed": judgment.decision == case["expected"],
                    }
                )
                row.receipt_json = json.loads(json.dumps(report))
                await db.commit()
    except asyncio.CancelledError:
        # Persisted pending and the caller's root ledger remain authoritative.
        raise
    except Exception as error:
        await db.rollback()
        row = await db.scalar(
            query.with_for_update().execution_options(populate_existing=True)
        )
        report["status"] = (
            "unknown"
            if envelope.snapshot().requests_unknown
            or not envelope.snapshot().usage_complete
            else "failed"
        )
        report["error_type"] = type(error).__name__
    else:
        report["status"] = "completed"
        report["passed"] = all(
            item.get("passed") is True for item in report["cases"]
        ) and len(report["cases"]) == len(CASES)
    report["envelope"] = envelope.snapshot().model_dump(mode="json")
    report["false_allow"] = sum(
        item.get("decision") == "allow" and item.get("expected") != "allow"
        for item in report["cases"]
    )
    report["false_block"] = sum(
        item.get("expected") == "allow" and item.get("decision") in {"ask", "deny"}
        for item in report["cases"]
    )
    row.receipt_json = report
    await db.commit()
    return report

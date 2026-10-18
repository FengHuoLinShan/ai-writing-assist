"""Explicit owner-bound synthetic approval calibration; default is read-only check.

python -m tools.approval_model_calibration --novel-id UUID --owner-id UUID
Add --execute --output-dir /absolute/private/new-directory for 18 real requests.
No manuscripts, credentials, provider overrides or automatic retries are accepted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bootstrap import register_container_services
from core.config import get_settings
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.assistant.approval_cases import CASES, SUITE_HASH
from modules.assistant.approval_contracts import APPROVAL_CAPABILITY
from modules.project.facade import build_project_llm_execution_snapshot


def private_output(path: Path) -> Path:
    repo = Path(__file__).resolve().parents[2]
    directory = path.expanduser().resolve()
    if not path.is_absolute() or directory.is_relative_to(repo):
        raise ValueError("校准账本目录必须是仓库外的绝对路径")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    directory.chmod(0o700)
    return directory


def write_checkpoint(directory, name, data):
    temporary = directory / (name + ".pending")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / name)


async def run(args):
    from infrastructure.llm.agent_runtime import AgentRunBudget
    from infrastructure.llm.workflow_budget import (
        AIRunEnvelope,
        ai_run_scope,
        new_ai_run_envelope,
        workflow_budget,
    )
    from modules.assistant.approval_calibration import calibrate_approval_model

    register_container_services(ignore_existing=True)
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            account = await db.get(Account, args.owner_id)
            if account is None or account.status != "active":
                raise ValueError("校准 owner 必须是当前可用账户")
            token = bind_principal(
                AccountPrincipal(
                    account_id=account.id,
                    status=account.status,
                    identity_type="email",
                    support_code=account.support_code,
                )
            )
            try:
                snapshot = await build_project_llm_execution_snapshot(
                    db, str(args.novel_id), purpose="approval_judgment"
                )
                profile = snapshot["profile"]
                summary = {
                    "mode": "execute" if args.execute else "check",
                    "model": {
                        key: profile.get(key)
                        for key in ("provider_id", "model", "reasoning_effort")
                    },
                    "case_count": len(CASES),
                    "suite_hash": SUITE_HASH,
                    "request_limit": len(CASES),
                    "token_limit": args.token_limit,
                }
                if not args.execute:
                    return summary
                if args.output_dir is None:
                    raise ValueError("真实校准需要新的私有账本目录")
                directory = private_output(args.output_dir)
                write_checkpoint(directory, "configuration.json", summary)

                async def save_envelope(value):
                    write_checkpoint(
                        directory, "envelope.json", value.model_dump(mode="json")
                    )

                async def save_budget(value):
                    write_checkpoint(directory, "budget.json", value)

                root = new_ai_run_envelope(
                    operation_id=str(uuid.uuid4()),
                    run_id=str(uuid.uuid4()),
                    root_capability_id=APPROVAL_CAPABILITY,
                    novel_id=str(args.novel_id),
                    request_limit=len(CASES),
                    token_limit=args.token_limit,
                    deadline_at=datetime.now(UTC) + timedelta(minutes=10),
                )
                await save_envelope(root.snapshot())
                root = AIRunEnvelope(root.snapshot(), on_change=save_envelope)
                budget = AgentRunBudget(policy_version="team_v1")
                await save_budget(budget.model_dump(mode="json"))
                with ai_run_scope(root), workflow_budget(budget, save_budget):
                    report = await calibrate_approval_model(
                        db, str(args.novel_id), str(args.owner_id)
                    )
                write_checkpoint(directory, "report.json", report)
                return {
                    **summary,
                    "status": report["status"],
                    "passed": report["passed"],
                    "false_allow": report["false_allow"],
                    "false_block": report["false_block"],
                    "report": str(directory / "report.json"),
                }
            finally:
                reset_principal(token)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--novel-id", type=uuid.UUID, required=True)
    parser.add_argument("--owner-id", type=uuid.UUID, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--token-limit", type=int, default=65_536)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not 1 <= args.token_limit <= 1_000_000:
        parser.error("--token-limit 必须为明确授权的 1–1000000 token 上限")
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        parser.exit(
            1,
            f"校准未完成（{type(error).__name__}）；请核对私有账本及当前账户/作品连接。\n",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("passed") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""One-shot setup using normal account verification and Project facades."""

import asyncio
import json
import os
from pathlib import Path

from app.bootstrap import register_container_services
from core.config import get_settings
from core.database import DatabaseManager
from modules.account.settings_service import SettingsService
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    create_author_project,
    open_project_llm_client,
    restore_project_llm_execution_settings,
)

PRIVATE = Path("/Users/tywww/.codex/private/g6b-recalibration-20261015/live")


async def main():
    os.umask(0o077)
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = PRIVATE / "setup-state.json"
    if state.exists():
        raise RuntimeError(
            "Setup already started; inspect its receipt before another verification"
        )
    settings = get_settings()
    assert settings.database_url.endswith(":65195/agent_e2e_g6b_calibration")
    assert settings.auth_mode == "local" and settings.app_env == "development"
    register_container_services()
    manager = DatabaseManager()
    manager.init()
    try:
        async with manager.session_factory() as db:
            project = await create_author_project(db, title="G6b 合成校准专用项目")
            await db.commit()
            record = {"project_id": str(project.project_id), "status": "verifying"}
            state.write_text(json.dumps(record, ensure_ascii=False, indent=2))
            await SettingsService().connect_account_llm_provider(db, "codex", None)
            await db.commit()
            snapshot = await build_project_llm_execution_snapshot(
                db, record["project_id"]
            )
            restored = await restore_project_llm_execution_settings(
                db, record["project_id"], snapshot
            )
            assert snapshot["profile"]["provider_id"] == "codex"
            assert snapshot["profile"]["model"] == "gpt-6-luna"
            assert snapshot["profile"]["connection_verified"]
            assert snapshot["profile"]["native_wrapper"]["version"] == "codex-text-v3"
            assert restored["llm"]["extra"]["reasoning_effort"] == "max"
            async with open_project_llm_client(db, record["project_id"]) as client:
                assert client.model_name == "gpt-6-luna"
                record["client_profile"] = client.profile_summary
            record.update(
                status="verified", snapshot=snapshot, effective_reasoning_effort="max"
            )
            (PRIVATE / "setup-result.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2)
            )
            state.write_text(
                json.dumps({"project_id": record["project_id"], "status": "verified"})
            )
            print(
                "Isolated owner connection and Project Luna/max snapshot verified",
                flush=True,
            )
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())

import json
import stat
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.account.facade import current_account_id
from tools import approval_model_calibration as cli


@pytest.mark.asyncio
@pytest.mark.parametrize("token_limit", [65_536, 262_144])
async def test_operator_check_verifies_bound_profile_without_running_model(
    db_session, test_project_id, monkeypatch, token_limit
):
    from modules.account.models import Account

    owner_id = uuid.UUID(str(current_account_id()))
    if await db_session.get(Account, owner_id) is None:
        db_session.add(
            Account(id=owner_id, status="active", support_code="calibration-test")
        )
        await db_session.flush()

    @asynccontextmanager
    async def session():
        yield db_session

    class Engine:
        async def dispose(self):
            pass

    monkeypatch.setattr(cli, "create_async_engine", lambda _url: Engine())
    monkeypatch.setattr(cli, "async_sessionmaker", lambda *_args, **_kw: session)
    monkeypatch.setattr(cli, "register_container_services", lambda **_kw: None)

    async def snapshot(_db, novel_id, *, purpose):
        assert novel_id == test_project_id and purpose == "approval_judgment"
        return {
            "profile": {
                "provider_id": "codex",
                "model": "gpt-6-luna",
                "reasoning_effort": "low",
            }
        }

    async def forbidden(*_args):
        pytest.fail("只读配置检查不能发送校准请求")

    monkeypatch.setattr(cli, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(
        "modules.assistant.approval_calibration.calibrate_approval_model", forbidden
    )
    result = await cli.run(
        SimpleNamespace(
            novel_id=uuid.UUID(test_project_id),
            owner_id=uuid.UUID(str(current_account_id())),
            execute=False,
            output_dir=None,
            token_limit=token_limit,
        )
    )
    assert result["mode"] == "check" and result["case_count"] == 18
    assert result["model"]["reasoning_effort"] == "low"
    assert result["token_limit"] == token_limit


def test_calibration_output_is_private_atomic_and_never_reuses_a_ledger(tmp_path):
    directory = cli.private_output(tmp_path / "private-ledger")
    cli.write_checkpoint(directory, "envelope.json", {"requests_started": 1})
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / "envelope.json").stat().st_mode) == 0o600
    assert json.loads((directory / "envelope.json").read_text())["requests_started"] == 1
    assert not list(directory.glob("*.pending"))
    with pytest.raises(FileExistsError):
        cli.private_output(directory)
    with pytest.raises(ValueError):
        cli.private_output(Path(__file__).resolve().parents[4] / "calibration-output")

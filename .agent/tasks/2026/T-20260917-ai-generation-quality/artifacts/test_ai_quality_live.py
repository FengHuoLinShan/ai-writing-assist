"""Explicit, synthetic-only live acceptance; never part of default CI."""

import asyncio
import json
import os
import time
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from infrastructure.llm.providers import OpenAIProvider
from infrastructure.tasks.facade import run_task_inline
from infrastructure.tasks.models import AsyncTask
from modules.account.settings_service import SettingsService
from modules.world.tests.test_world_cocreation_sessions import (
    _create_project,
    _create_session,
    _confirm_chat_context,
)

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(
        os.getenv("RUN_AI_QUALITY_LIVE") != "1" or not os.getenv("DEEPSEEK_API_KEY"),
        reason="explicit live acceptance and process credential required",
    ),
]
ART = Path(os.environ.get("AI_QUALITY_ARTIFACTS", "/tmp/ai-generation-quality-live"))
BASE_ART = ART
FIXTURES = (
    Path(__file__).resolve().parents[2]
    / ".agent/tasks/2026/T-20260917-ai-generation-quality/artifacts/synthetic-cases.json"
)


def require_offpeak_flash(model):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    peak = now.weekday() < 5 and (9 <= now.hour < 12 or 14 <= now.hour < 18)
    if peak or model != "deepseek-flash":
        raise RuntimeError("This cost estimate only supports off-peak deepseek-flash")


def load_case(case_id):
    frozen = json.loads(FIXTURES.read_text())
    case = frozen["cases"][case_id]

    def merge(base, patch):
        if isinstance(base, dict) and isinstance(patch, dict):
            return {**base, **{k: merge(base.get(k), v) for k, v in patch.items()}}
        return patch

    return {
        "checkpoint": merge(frozen["base_checkpoint"], case["checkpoint_overrides"]),
        "instruction": case["instruction"],
    }


@pytest.fixture
def measured_provider(monkeypatch, worker_id):
    global ART
    ART = BASE_ART / worker_id if worker_id != "master" else BASE_ART
    ART.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    paths = [
        "infrastructure/llm/client.py",
        "modules/world/services/worldbuilding/world_generation_center_service.py",
        "modules/world/services/worldbuilding/world_design_iteration.py",
        "modules/world/services/worldbuilding/cocreation_session_service.py",
        "modules/evidence/compilation/knowledge/workflow.py",
        "modules/evidence/compilation/knowledge/policies.py",
        "modules/story/generation.py",
        "modules/interaction/generation.py",
        "modules/interaction/prompts.py",
        "modules/world/tasks.py",
    ]
    (ART / "code-manifest.json").write_text(
        json.dumps(
            {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
            indent=2,
        )
    )
    original = OpenAIProvider.generate
    lock = asyncio.Lock()
    pending = 0.0
    calls = []

    async def generate(self, request):
        nonlocal pending
        require_offpeak_flash(request.model)
        # Pessimistic reservation: UTF-8 bytes bound prompt tokens, no cache discount.
        ceiling = (
            len(request.model_dump_json().encode())
            + 2000
            + 4 * (request.max_tokens or 131072)
        ) / 1e6
        async with lock:
            prior = (
                [
                    json.loads(line)
                    for line in (ART / "requests.jsonl").read_text().splitlines()
                ]
                if (ART / "requests.jsonl").exists()
                else []
            )
            spent = sum(r.get("estimated_yuan", 0) for r in prior)
            if any(
                r.get("unknown_charge") for r in prior
            ) or spent + pending + ceiling > float(
                os.environ.get("AI_QUALITY_CAP_YUAN", "15")
            ):
                raise RuntimeError("Live acceptance cost boundary reached")
            pending += ceiling
        started = time.monotonic()
        row = {"index": len(prior) + len(calls), "model": request.model}
        try:
            result = await original(self, request)
            if not (result.raw or {}).get("usage"):
                raise RuntimeError(
                    "Provider omitted usage; reconcile cost before retrying"
                )
            usage = result.usage.model_dump()
            raw_usage = (result.raw or {}).get("usage", {})
            hit = int(raw_usage.get("prompt_cache_hit_tokens", 0))
            row.update(
                usage=usage,
                cache_hit_tokens=hit,
                actual_model=result.model,
                estimated_yuan=(
                    max(0, usage["prompt_tokens"] - hit)
                    + 0.02 * hit
                    + 4 * usage["completion_tokens"]
                )
                / 1e6,
                output=result.content,
                messages=[
                    {"role": m.role, "content": m.content} for m in request.messages
                ],
            )
            return result
        except BaseException as exc:
            row.update(error=type(exc).__name__, unknown_charge=True)
            raise
        finally:
            row["seconds"] = round(time.monotonic() - started, 2)
            async with lock:
                pending -= ceiling
                calls.append(row)
                with (ART / "requests.jsonl").open("a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                "LIVE",
                row.get("actual_model"),
                row.get("usage"),
                row.get("estimated_yuan"),
                flush=True,
            )

    monkeypatch.setattr(OpenAIProvider, "generate", generate)
    return calls


@pytest.mark.parametrize(
    "case_id",
    os.environ.get("AI_QUALITY_CASES", "goal-misread,no-issue,information-flow").split(
        ","
    ),
)
async def test_world_design_real(async_client, db_session, measured_provider, case_id):
    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    fixture = load_case(case_id)
    novel_id = await _create_project(async_client, f"质量测试 {case_id}")
    session = await _create_session(async_client, novel_id)
    confirmation = await _confirm_chat_context(async_client, novel_id)
    checkpoint = fixture["checkpoint"]
    checkpoint["world_state"]["project"]["id"] = novel_id

    def rebind(value):
        if isinstance(value, dict):
            return {k: rebind(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rebind(v) for v in value]
        if isinstance(value, str) and value.startswith("confirmation:"):
            return f"confirmation:{confirmation}"
        return value

    checkpoint = rebind(checkpoint)
    saved = await async_client.post(
        "/api/world/design-checkpoints",
        json={"novel_id": novel_id, "checkpoint": checkpoint},
    )
    assert saved.status_code == 201, saved.text
    parent = saved.json()["id"]
    advanced = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/checkpoint",
        json={
            "novel_id": novel_id,
            "checkpoint_suggestion_id": parent,
            "expected_checkpoint_id": None,
        },
    )
    assert advanced.status_code == 200, advanced.text
    task_id = str(uuid.uuid4())
    payload = {
        "novel_id": novel_id,
        "session_id": session["id"],
        "operation_id": task_id,
        "expected_checkpoint_id": parent,
        "context_confirmation_id": confirmation,
        "workflow_preset": "world_core",
        "target": {"kind": "core_entity", "template": "none"},
        "messages": [{"role": "user", "content": fixture["instruction"]}],
        "mode": "design",
        "quality_mode": "pro",
        "session_action": "pressure",
        "action": "pressure",
        "parent_checkpoint_id": parent,
    }
    submitted = await async_client.post("/api/world/cocreation-turns/task", json=payload)
    assert submitted.status_code == 202, submitted.text
    artifact = {"case": case_id, "input": payload, "checkpoint": checkpoint}
    try:
        artifact["result"] = await run_task_inline(
            db_session, task_id=task_id, expected_task_type="world_cocreation_turn"
        )
    except Exception as exc:
        artifact["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        task = await db_session.get(AsyncTask, uuid.UUID(task_id))
        artifact["task_status"] = task.status
        artifact["task_result"] = task.result
        (ART / f"{case_id}.json").write_text(
            json.dumps(artifact, ensure_ascii=False, default=str, indent=2)
        )
    assert artifact["result"].get("review_summary", {}).get("status") in {
        "passed",
        "passed_with_open_questions",
    }, artifact["result"].get("review_summary")


@pytest.mark.parametrize(
    "kind",
    [
        "world_chat",
        "world_object",
        "story_card",
        "story_reaction",
        "story_script",
        "writing",
        "extraction",
    ],
)
async def test_text_capability_real(async_client, db_session, measured_provider, kind):
    from modules.project.facade import (
        open_project_llm_client,
        build_project_llm_execution_snapshot,
        restore_project_llm_execution_settings,
    )

    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    novel_id = await _create_project(async_client, f"文本质量测试 {kind}")
    instruction = "设计一名维护潮门的盐商，因最后一袋盐必须留给医院而拒绝一次高价运输；不得解决为凭空多出盐。给出具体选择、代价和下一步行动。"
    context = "原创潮汐港。潮门每次运货耗盐一袋，不能运送生命；机械旁路不耗盐但步行要两小时。林砂是守信但欠债的盐商，知道潮门规则。今天大雨，他只剩一袋盐，已承诺留给医院运送药品。船主愿出三倍价运输酒桶。"
    result = None
    if kind.startswith("world_"):
        action = (
            "world.generation.chat"
            if kind == "world_chat"
            else "world.generation.core_entity"
        )
        payload = {
            "novel_id": novel_id,
            "action": action,
            "task": instruction,
            "scope": "generation_center",
            "budget_tokens": 0,
        }
        preview = await async_client.post(
            "/api/evidence/compilation/compile", json=payload
        )
        assert preview.status_code == 200, preview.text
        confirmation = await async_client.post(
            "/api/evidence/compilation/confirm",
            json={
                **payload,
                "expected_context_fingerprint": preview.json()["context_fingerprint"],
            },
        )
        assert confirmation.status_code == 201, confirmation.text
        response = await async_client.post(
            "/api/world/generation-center/"
            + ("chat" if kind == "world_chat" else "suggestions"),
            json={
                "novel_id": novel_id,
                "source_context": {"kind": "project"},
                "target": {"kind": "core_entity", "template": "character"},
                "messages": [{"role": "user", "content": instruction}],
                "pasted_context": context,
                "context_confirmation_id": confirmation.json()["id"],
                "quality_mode": "fast",
            },
        )
        result = response.json()
        (ART / f"{kind}.json").write_text(
            json.dumps(result, ensure_ascii=False, default=str, indent=2)
        )
        assert response.status_code in {200, 201}, response.text
        assert result.get("knowledge_review", {}).get("status") == "passed", result.get(
            "knowledge_review"
        )
    elif kind.startswith("story_"):
        from modules.story.generation import StoryGenerationService

        actor = str(uuid.uuid4())
        scene = {
            "novel_id": novel_id,
            "scene_id": str(uuid.uuid4()),
            "situation": context,
            "characters": [
                {
                    "id": actor,
                    "name": "林砂",
                    "personality": "守信但欠债",
                    "knowledge": ["盐仅一袋，已承诺给医院"],
                }
            ],
        }
        async with open_project_llm_client(db_session, novel_id) as client:
            service = StoryGenerationService()
            kwargs = dict(
                context_markdown=context,
                scene_context=scene,
                additional_notes=instruction,
            )
            if kind == "story_card":
                output = await service.card_preview(client, character_id=actor, **kwargs)
            elif kind == "story_reaction":
                output = await service.reaction_preview(
                    client, character_ids=[actor], **kwargs
                )
            else:
                output = await service.script_preview(
                    client, character_ids=[actor], **kwargs
                )
        result = output.model_dump(mode="json")
        (ART / f"{kind}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        assert result["knowledge_review"]["status"] == "passed", result[
            "knowledge_review"
        ]
    elif kind == "writing":
        from modules.evidence.facade import confirm_context, bind_confirmed_action_result
        from modules.writing.services import WritingGenerationService

        task_id = str(uuid.uuid4())
        confirmation = await confirm_context(
            db_session,
            novel_id=novel_id,
            action="writing.generate",
            task=context + "请写约四百字的场景，展现林砂拒绝船主并保住医院药品运输。",
            scope="chapter",
            chapter_index=1,
        )
        await bind_confirmed_action_result(
            db_session,
            novel_id=novel_id,
            confirmation_id=confirmation.id,
            result_type="task",
            result_id=task_id,
            status="running",
        )
        snapshot = await build_project_llm_execution_snapshot(db_session, novel_id)
        db_session.task_checkpoint_enabled = True
        output = await WritingGenerationService().generate_candidate_for_task(
            db_session,
            novel_id=novel_id,
            chapter_index=1,
            title=None,
            instruction=context
            + "请写约四百字的场景，展现林砂拒绝船主并保住医院药品运输。",
            context_confirmation_id=confirmation.id,
            source_task_id=task_id,
            llm_execution_snapshot=snapshot,
        )
        result = output.model_dump(mode="json")
        (ART / f"{kind}.json").write_text(
            json.dumps(result, ensure_ascii=False, default=str, indent=2)
        )
        assert output.provenance_json["knowledge_review"]["status"] == "passed", (
            output.provenance_json["knowledge_review"]
        )
        assert len(output.content) > 100
    else:
        from modules.imports.entity_extraction.scene_entity_config import (
            phase2_project_settings_context,
        )
        from modules.imports.entity_extraction.scene_entity_llm_adapters import (
            call_llm_extraction,
        )

        snapshot = await build_project_llm_execution_snapshot(db_session, novel_id)
        settings = await restore_project_llm_execution_settings(
            db_session, novel_id, snapshot
        )
        source = "林砂是潮汐港的盐商。潮汐港的潮门每次运货消耗一袋盐，绝不能运送生命。林砂答应把最后一袋盐留给港口医院运输药品。船主提出三倍价运酒，他拒绝了。"
        with phase2_project_settings_context(settings, novel_id=novel_id):
            output = await call_llm_extraction(
                source, "", "", context_bundle={"current_scene_text": source}
            )
        result = output.model_dump(mode="json")
        (ART / f"{kind}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        assert result.get("knowledge_review", {}).get("status") == "passed", result
        assert result.get("entities"), result


@pytest.mark.parametrize(
    "capability,text,expected",
    [
        (
            "writing.generate",
            "林砂按住盐袋，挪开酒桶。他说：‘这袋盐要运药。’雨水从他的袖口滴落。",
            "pass",
        ),
        (
            "writing.generate",
            "林砂一眼认出船主就是皇家密探，当面叫破了他的秘密身份。",
            "blocked",
        ),
        (
            "world.generation.suggestion",
            "候选设计：盐商把拒绝卖盐的决定写成公开承诺，请作者选择是否保留这个发展方向。",
            "pass",
        ),
        ("world.ask", "原文已确认林砂有一个双胞胎弟弟，而且同为皇家密探。", "blocked"),
        (
            "world.generation.chat",
            "潮门不能运送生命。一个普通的雨天，阿棠抱着药箱挤过了潮门，抵达另一侧。",
            "blocked",
        ),
        (
            "interaction.story_generate",
            "你把随身工具箱放在柜台上，取出怀表检修。",
            "blocked",
        ),
        (
            "world.generation.design_iteration",
            "候选维持耗盐按开启时间同比例计算，每个开启日的时长相同；"
            "隔日开启相比每日开启，维持耗盐降至三分之一，因此可支撑三倍时间。"
            "以上比例仅为候选近似，待作者校准。",
            "blocked",
        ),
        (
            "world.generation.design_iteration",
            "候选维持耗盐按开启时间同比例计算，每个开启日的时长相同；"
            "隔日开启相比每日开启，长期平均维持耗盐降至一半。"
            "库存与每批耗盐尚未确定，故暂不能判断能否撑满七日。",
            "pass",
        ),
    ],
)
async def test_review_semantics_real(
    async_client, db_session, measured_provider, capability, text, expected
):
    from modules.project.facade import open_project_llm_client
    from modules.evidence.contracts import (
        KnowledgeSubject,
        KnowledgeSourceEntry,
        KnowledgeScopeReceipt,
        KnowledgeScopeBuild,
        KnowledgeDirectorPlan,
        KnowledgeDirectorDisposition,
        GovernedWorkflowHooks,
        require_capability_policy,
        run_knowledge_audit,
    )

    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    novel_id = await _create_project(async_client, "审查正反控制样本")
    policy = require_capability_policy(capability)
    source = KnowledgeSourceEntry(
        source_key="visible",
        source_type="synthetic",
        source_id="v1",
        content_hash="a" * 64,
        dimensions=policy.required_dimensions,
    )
    receipt = KnowledgeScopeReceipt(
        policy_version=1,
        capability=capability,
        novel_id=novel_id,
        subject=KnowledgeSubject(
            subject_type="reader" if capability.startswith("interaction.") else "author"
        ),
        included=(source,),
        scope_complete=True,
        authority_fingerprint="b" * 64,
        generator_fingerprint="a" * 64,
    )
    build = KnowledgeScopeBuild(
        receipt=receipt, generator_keys=("visible",), audit_only_keys=()
    )
    plan = KnowledgeDirectorPlan(
        policy_version=1,
        capability=capability,
        receipt_fingerprint=receipt.receipt_fingerprint(),
        dispositions=(
            KnowledgeDirectorDisposition(
                source_key="visible", disposition="required_for_generation"
            ),
        ),
    )

    async def unused(*args):
        return text

    visible = "潮门不能运送生命，每次运货消耗一袋盐。林砂是盐商，最后一袋盐已承诺留给医院运药。陌生船主要高价运酒。林砂不知船主的身份。原文没有提到林砂的兄弟。你是一位刚抵达港口的修表师，随身只有一封信，没有工具或其他行李。"
    if capability == "world.generation.design_iteration":
        visible = "作者要求提出一套独立候选设施的盐耗方案；库存、日耗量与按批耗量均未确定。设施每个开启日时长相同，维持耗盐与开启时间成正比。"
    hooks = GovernedWorkflowHooks(
        generate=unused,
        task_instruction="按允许的输出类型完成本轮内容，不能让林砂获知陌生人的秘密身份",
        generator_context=visible,
        authority_context=visible + "\n仅审查者可见：船主是皇家密探，林砂尚未得知。",
    )
    async with open_project_llm_client(db_session, novel_id) as client:
        audit = await run_knowledge_audit(
            client, policy=policy, scope_build=build, plan=plan, hooks=hooks, output=text
        )
    result = audit.to_dict()
    (ART / f"control-{capability}-{expected}.json").write_text(
        json.dumps(result, ensure_ascii=False, default=str, indent=2)
    )
    assert audit.verdict == expected, result

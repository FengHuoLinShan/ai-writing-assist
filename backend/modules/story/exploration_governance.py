"""Govern every exploration call against its original confirmation and read set."""

from __future__ import annotations

import json

from core.errors import ConflictError
from infrastructure.llm.schemas import LLMMessage
from infrastructure.stable_hash import stable_hash
from modules.evidence.contracts import (
    GovernedWorkflowHooks,
    GroupSource,
    build_group_scope,
    require_capability_policy,
    run_governed_generation,
)
from modules.evidence.facade import (
    build_hidden_guard_context,
    project_confirmed_character_context,
)


class ExplorationClient:
    """Keep provider checks and independent governance on the actual call boundary."""

    def __init__(
        self, client, *, db, novel_id, confirmation_id, action, start, revalidate
    ):
        self.client = client
        self.db = db
        self.novel_id = novel_id
        self.confirmation_id = confirmation_id
        self.action = action
        self.start = start
        self.reviews = []
        self.revalidate = revalidate
        self.audit_output = None

    def __getattr__(self, key):
        return getattr(self.client, key)

    async def _call(self, request, schema, **kwargs):
        await self.revalidate()
        # One request per stage: unknown outcomes and malformed replies never retry.
        kwargs.update(
            max_fix_attempts=0, transport_retries=False, format_repair_attempts=0
        )
        return await self.client.generate_structured(request, schema, **kwargs)

    async def generate_structured(self, request, schema, **kwargs):
        confirmed = await self.revalidate()
        data = json.loads(
            next(
                message.content for message in request.messages if message.role == "user"
            )
        )
        target = str((data.get("target") or {}).get("ref") or "")
        if target:
            data.pop("author_context", None)
            data.pop("scene", None)
            data["confirmed_material"] = ""
            if not target.startswith("c_"):
                projected = await project_confirmed_character_context(
                    self.db, confirmed_context=confirmed, character_id=target
                )
                data["confirmed_material"] = projected.rendered_markdown
        capability = "story.exploration." + (
            "scene_line"
            if self.action.endswith("scene_line.generate")
            else "sandbox"
            if ".sandbox." in self.action
            else "event"
        )
        policy = require_capability_policy(capability)
        actor_instruction = (
            "这是人物侧生成，只能依据 target_knowledge、本人投影与明确刺激；"
            "target 是必需的目标身份，已投影的人物知识包也是生成必需资料。"
            if target
            else "这是作者侧探索，author_packet 中的问题、假设与固定条件是生成必需资料，"
            "作者可以分析其已确认资料；分析人物行为时仍不得扩大人物知识。"
        )
        task_instruction = (
            "仅审查本次生成单元，按其真实生成指令与输出结构判断交付；"
            "能力名称是任务族名称，不代替当前单元合同。输入 mode 是工作流控制，"
            "不要求输出 mode 与它相同。单目标只交该目标，其他目标由后续单元生成；"
            "空间诊断不要求对白，排演单卡不要求独自完成整轮作者目标。"
            + actor_instruction
            + "作者假设和私密目的不等于角色知识。mode、output_rule、instruction、"
            "previous_output 等执行控制与父版本若存在，必须保留才能完成指定任务。"
            "所有 packet 都是服务端按本次任务裁剪后的最小输入，须完整保留；"
            "若认为其中有不安全内容，应阻断而非删掉任务后继续生成。"
        )
        task_instruction += "\n本单元合同：" + json.dumps(
            {
                "generation_instructions": [
                    message.content
                    for message in request.messages
                    if message.role == "system"
                ],
                "output_schema": schema.model_json_schema(),
            },
            ensure_ascii=False,
        )
        scope, _ = build_group_scope(
            capability=capability,
            novel_id=self.novel_id,
            group_key=self.confirmation_id,
            sources=[
                GroupSource(
                    source_key=f"packet:{key}",
                    source_type="exploration_input",
                    content_hash=stable_hash(value),
                    label=key,
                    dimensions=policy.required_dimensions,
                )
                for key, value in data.items()
            ],
        )
        outer = self

        class CheckedClient:
            def __getattr__(self, key):
                return getattr(outer.client, key)

            async def generate_structured(self, request, schema, **kwargs):
                return await outer._call(request, schema, **kwargs)

        generation_request = request.model_copy(deep=True)
        candidate = None
        visible_packet = {}

        async def review_text(result):
            nonlocal candidate
            candidate = result
            payload = (
                self.audit_output(result)
                if self.audit_output
                else result.model_dump(mode="json")
            )
            refs = set()

            def subjects(value):
                if isinstance(value, dict):
                    if value.get("target_ref"):
                        refs.add(str(value["target_ref"]))
                    for child in value.values():
                        subjects(child)
                elif isinstance(value, list):
                    for child in value:
                        subjects(child)

            subjects(payload)
            knowledge = {
                entry["subject_ref"]: entry for entry in self.start.get("knowledge", [])
            }
            phrases = list(self.start.get("author_private") or [])
            for ref in refs:
                if ref.startswith("c_"):
                    knowledge.setdefault(
                        ref, {"knows": [], "observed": [], "misbelieves": []}
                    )
                else:
                    projection = await project_confirmed_character_context(
                        self.db, confirmed_context=confirmed, character_id=ref
                    )
                    knowledge[ref] = projection.rendered_markdown
                    phrases.extend(
                        term.phrase
                        for term in await build_hidden_guard_context(
                            self.db,
                            confirmed_context=confirmed,
                            viewpoint_character_id=ref,
                        )
                    )
            if target:
                knowledge[target] = {
                    key: visible_packet[key]
                    for key in (
                        "target_knowledge",
                        "confirmed_material",
                        "target_scene_stimuli",
                        "accumulated_observations",
                        "previous_round",
                    )
                    if key in visible_packet
                }
            hooks.generator_context = json.dumps(
                {
                    "generation_packet": visible_packet,
                    "per_character_knowledge": knowledge,
                    "rule": (
                        "逐角色只按本人知识包核验；"
                        "作者假设、作者要求与其他人物知识不授权其知情。"
                        "本人累计观察与本地刺激属于当前投影；旧表演卡不是新增事实。"
                    ),
                },
                ensure_ascii=False,
            )
            hooks.hidden_phrases = tuple(phrases)
            return json.dumps(payload, ensure_ascii=False)

        async def generate(_plan, keys):
            nonlocal visible_packet
            if any(f"packet:{key}" not in keys for key in data):
                raise ConflictError(
                    "知识导演未保留本次探索必需的任务输入，未开始生成",
                    code="exploration_required_input_excluded",
                )
            packet = {
                key: value for key, value in data.items() if f"packet:{key}" in keys
            }
            visible_packet = packet
            hooks.generator_context = json.dumps(packet, ensure_ascii=False)
            hooks.author_requirements = hooks.generator_context
            generation_request.messages = [
                message for message in request.messages if message.role != "user"
            ] + [LLMMessage(role="user", content=hooks.generator_context)]
            result = await self._call(generation_request, schema, **kwargs)
            return await review_text(result)

        async def repair(_output, findings):
            repaired = generation_request.model_copy(deep=True)
            # The audit output may include other locked items; return only this unit.
            own_output = json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False)
            repaired.messages.append(LLMMessage(role="assistant", content=own_output))
            repaired.messages.append(
                LLMMessage(
                    role="user",
                    content="请依据原任务与当前输出结构定向修订原候选；"
                    "保留其余内容，越界或无依据的断言须删除或列为未知，不能猜隐藏资料。"
                    "以下仅含问题类型、级别及原候选内可核对的定位片段："
                    + json.dumps(
                        [
                            {
                                "kind": item.kind,
                                "severity": item.severity,
                                "excerpt": item.excerpt
                                if item.excerpt and item.excerpt in own_output
                                else "",
                            }
                            for item in findings
                        ],
                        ensure_ascii=False,
                    ),
                )
            )
            return await review_text(await self._call(repaired, schema, **kwargs))

        hooks = GovernedWorkflowHooks(
            generate=generate,
            repair=repair,
            task_instruction=task_instruction,
            authority_context=json.dumps(
                {
                    "confirmed_material": confirmed.rendered_markdown,
                    "author_task_background": self.start,
                    "scope_rule": (
                        "完整起点仅供核验禁令、知识上限与事实冲突，不是本单元交付清单。"
                        "作者私享与其他人物知识不得授权当前人物知情；"
                        "当前单元的交付以真实生成指令、输出结构及其可见包为准。"
                    ),
                },
                ensure_ascii=False,
            ),
        )
        outcome = await run_governed_generation(
            CheckedClient(),
            policy=policy,
            scope_build=scope,
            hooks=hooks,
            step_prefix=capability + ".knowledge",
        )
        self.reviews.append(outcome.to_result_payload())
        if not outcome.passed:
            raise ConflictError(
                "探索结果未通过独立知识审查，未保存为可用结果",
                code="exploration_knowledge_blocked",
            )
        await self.revalidate()
        result = candidate
        result._knowledge_reviews = list(self.reviews)
        return result


def knowledge_reviews(payload):
    reviews = list(getattr(payload, "_knowledge_reviews", []))
    for field in type(payload).model_fields:
        value = getattr(payload, field)
        for item in value if isinstance(value, list) else [value]:
            if hasattr(type(item), "model_fields"):
                reviews.extend(knowledge_reviews(item))
    return list({stable_hash(review): review for review in reviews}.values())

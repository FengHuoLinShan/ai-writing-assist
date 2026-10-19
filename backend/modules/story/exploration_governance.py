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
            hooks.generator_context = json.dumps(
                {
                    "generation_packet": visible_packet,
                    "per_character_knowledge": knowledge,
                    "rule": (
                        "逐角色只按本人知识包核验；"
                        "作者假设、作者要求与其他人物知识不授权其知情。"
                    ),
                },
                ensure_ascii=False,
            )
            hooks.hidden_phrases = tuple(phrases)
            return json.dumps(payload, ensure_ascii=False)

        async def generate(_plan, keys):
            nonlocal visible_packet
            packet = {
                key: value for key, value in data.items() if f"packet:{key}" in keys
            }
            visible_packet = packet
            hooks.generator_context = json.dumps(packet, ensure_ascii=False)
            generation_request.messages = [
                message for message in request.messages if message.role != "user"
            ] + [LLMMessage(role="user", content=hooks.generator_context)]
            result = await self._call(generation_request, schema, **kwargs)
            return await review_text(result)

        async def repair(_output, findings):
            repaired = generation_request.model_copy(deep=True)
            repaired.messages.append(
                LLMMessage(
                    role="user",
                    content="请只依据你的可见资料修正以下审查问题："
                    # Audit messages can quote author-only evidence.
                    + "；".join(item.kind for item in findings),
                )
            )
            return await review_text(await self._call(repaired, schema, **kwargs))

        hooks = GovernedWorkflowHooks(
            generate=generate,
            repair=repair,
            task_instruction="按指定输出结构完成本次探索；角色只能使用其可知包，作者假设和私密目的不等于角色知识。",
            author_requirements=json.dumps(self.start, ensure_ascii=False),
            authority_context=confirmed.rendered_markdown,
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

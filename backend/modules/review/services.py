"""
Review 业务逻辑层 — 结构复查核心

包含多个检查维度的方法，每个方法返回警告列表。
Review 不改正史，只输出问题和修改建议。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.models import ReviewReport
from modules.review.repositories import ReviewReportRepository
from modules.review.schemas import ReviewReportContext, ReviewWarning
from shared.enums import ReviewDecision


class ReviewService:
    """结构复查服务

    提供从 schema 校验到逻辑检查的全维度复查能力。
    """

    VALID_TARGET_TYPES = frozenset({
        "world_structure",
        "plot_structure",
        "chapter_cards",
        "memory_update",
        "entity_candidates",
        "geo_structure",
    })

    def __init__(self) -> None:
        self._repo = ReviewReportRepository()

    # ============================================================
    # 主入口
    # ============================================================

    async def run_all_checks(
        self,
        db: AsyncSession,
        novel_id: str,
        target_type: str,
        candidate_payload: dict[str, Any],
    ) -> ReviewReportContext:
        """运行所有检查维度，生成复查报告

        并行执行所有检查方法，汇总结果并生成决策。

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            target_type: 复查目标类型
            candidate_payload: 候选结构数据

        Returns:
            ReviewReportContext — 复查报告上下文
        """
        import asyncio

        # 并行执行所有检查
        results = await asyncio.gather(
            self._check_schema(target_type, candidate_payload),
            self._check_entity_references(
                db, novel_id, candidate_payload,
            ),
            self._check_early_reveal(
                db, novel_id, candidate_payload,
            ),
            self._check_character_knowledge(
                db, novel_id, candidate_payload,
            ),
            self._check_timeline(
                db, novel_id, candidate_payload,
            ),
            self._check_geo(
                db, novel_id, candidate_payload,
            ),
            self._check_duplicates(
                db, novel_id, candidate_payload,
            ),
        )

        (
            schema_warnings,
            entity_warnings,
            reveal_warnings,
            knowledge_warnings,
            timeline_warnings,
            geo_warnings,
            duplicate_warnings,
        ) = results

        # 汇总所有警告
        all_warnings = (
            schema_warnings
            + entity_warnings
            + reveal_warnings
            + knowledge_warnings
            + timeline_warnings
            + geo_warnings
            + duplicate_warnings
        )

        # 生成决策
        decision = self._decide(all_warnings)

        # 生成修改建议
        revision_instructions = self._generate_revision_instructions(
            decision,
            schema_warnings,
            entity_warnings,
            reveal_warnings,
            knowledge_warnings,
            timeline_warnings,
            geo_warnings,
            duplicate_warnings,
        )

        # 计算评分
        score = self._calculate_score(decision, all_warnings)

        # 序列化警告为 dict
        def _w_to_dict(w: ReviewWarning) -> dict:
            return w.model_dump()

        # 写入数据库
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(
            db,
            novel_id=nid,
            target_type=target_type,
            decision=decision,
            score=score,
            problems=[_w_to_dict(w) for w in all_warnings],
            conflict_warnings=[_w_to_dict(w) for w in timeline_warnings],
            early_reveal_warnings=[_w_to_dict(w) for w in reveal_warnings],
            character_knowledge_warnings=[
                _w_to_dict(w) for w in knowledge_warnings
            ],
            duplicate_entity_warnings=[
                _w_to_dict(w) for w in duplicate_warnings
            ],
            geo_warnings=[_w_to_dict(w) for w in geo_warnings],
            revision_instructions=revision_instructions,
        )

        return self._to_context(entity)

    async def get_report(
        self,
        db: AsyncSession,
        report_id: str,
    ) -> ReviewReportContext:
        """获取已存在的复查报告"""
        rid = self._parse_uuid(report_id, "report_id")
        entity = await self._repo.get(db, rid)
        if entity is None:
            from fastapi import HTTPException
            from fastapi import status as http_status

            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ReviewReport {report_id} not found",
            )
        return self._to_context(entity)

    # ============================================================
    # 检查方法
    # ============================================================

    async def _check_schema(
        self,
        target_type: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """检查 1: Schema 校验

        检查必填字段、枚举值合法性、UUID 格式等基础合规性。
        """
        warnings: list[ReviewWarning] = []

        # 检查必填字段
        required_fields_map = {
            "world_structure": ["world_entities", "relationships"],
            "plot_structure": ["plot_threads", "outline_arcs", "chapter_cards"],
            "chapter_cards": ["chapter_index", "chapter_goal", "main_conflict"],
            "memory_update": ["proposal_type", "payload"],
            "entity_candidates": ["name", "entity_type"],
            "geo_structure": ["locations", "edges"],
        }

        required = required_fields_map.get(target_type, [])

        if not target_type:
            # 尝试从 payload 内容推断 target_type
            if "world_entities" in candidate_payload:
                required = required_fields_map.get("world_structure", [])
            elif "plot_threads" in candidate_payload:
                required = required_fields_map.get("plot_structure", [])
            elif "proposal_type" in candidate_payload:
                required = required_fields_map.get("memory_update", [])
            elif "locations" in candidate_payload:
                required = required_fields_map.get("geo_structure", [])

        for field in required:
            if field not in candidate_payload:
                warnings.append(
                    ReviewWarning(
                        type="schema",
                        message=f"缺少必填字段: {field}",
                        severity="high",
                        location={"field": field},
                    )
                )

        # 检查 UUID 格式
        uuid_fields = ["novel_id", "arc_id", "thread_id"]
        for field in uuid_fields:
            value = candidate_payload.get(field)
            if value is not None and isinstance(value, str):
                if not self._is_valid_uuid(value):
                    warnings.append(
                        ReviewWarning(
                            type="schema",
                            message=f"字段 {field} 不是有效的 UUID: {value}",
                            severity="medium",
                            location={"field": field, "value": value},
                        )
                    )

        # 检查枚举值
        enum_checks = {
            "entity_type": [
                "location", "faction", "item", "event", "rule",
                "power_system", "secret", "legend", "resource", "character_ref",
            ],
            "knowledge_level": [
                "unknown", "rumor", "partial", "full", "false_belief",
            ],
        }

        for field, valid_values in enum_checks.items():
            value = candidate_payload.get(field)
            if value is not None and isinstance(value, str):
                if value not in valid_values:
                    warnings.append(
                        ReviewWarning(
                            type="schema",
                            message=f"字段 {field} 的值 '{value}' 不在合法范围内",
                            severity="medium",
                            location={"field": field, "value": value},
                        )
                    )

        # 检查 chapter_index 是否为正整数
        chapter_index = candidate_payload.get("chapter_index")
        if chapter_index is not None:
            if not isinstance(chapter_index, int) or chapter_index < 1:
                warnings.append(
                    ReviewWarning(
                        type="schema",
                        message=f"chapter_index 必须为正整数，收到: {chapter_index}",
                        severity="high",
                        location={"field": "chapter_index", "value": chapter_index},
                    )
                )

        return warnings

    async def _check_entity_references(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """检查 2: 实体引用检查

        检查候选结构中引用的实体/人物/剧情线是否存在于正史中。
        """
        warnings: list[ReviewWarning] = []

        # 收集所有引用的 ID
        referenced_ids: dict[str, list[str]] = {
            "entity": [],
            "character": [],
            "thread": [],
            "arc": [],
        }

        # 从 chapter_cards 中提取引用
        cards = candidate_payload.get("chapter_cards", [])
        if isinstance(cards, dict):
            cards = [cards]

        for card in cards:
            for field, ref_type in [
                ("involved_character_ids", "character"),
                ("involved_entity_ids", "entity"),
                ("related_thread_ids", "thread"),
            ]:
                ids = card.get(field, []) if isinstance(card, dict) else []
                if isinstance(ids, list):
                    referenced_ids[ref_type].extend(
                        i for i in ids if isinstance(i, str) and i.strip()
                    )

        # 从 plot_threads 中提取引用
        threads = candidate_payload.get("plot_threads", [])
        if isinstance(threads, dict):
            threads = [threads]

        for thread in threads if isinstance(threads, list) else []:
            if not isinstance(thread, dict):
                continue
            for field, ref_type in [
                ("related_character_ids", "character"),
                ("related_entity_ids", "entity"),
            ]:
                ids = thread.get(field, [])
                if isinstance(ids, list):
                    referenced_ids[ref_type].extend(
                        i for i in ids if isinstance(i, str) and i.strip()
                    )

        # 从 arcs 中提取引用
        arcs = candidate_payload.get("outline_arcs", [])
        if isinstance(arcs, dict):
            arcs = [arcs]

        for arc in arcs if isinstance(arcs, list) else []:
            if not isinstance(arc, dict):
                continue
            for field, ref_type in [
                ("related_character_ids", "character"),
                ("related_entity_ids", "entity"),
                ("related_thread_ids", "thread"),
            ]:
                ids = arc.get(field, [])
                if isinstance(ids, list):
                    referenced_ids[ref_type].extend(
                        i for i in ids if isinstance(i, str) and i.strip()
                    )

        # 去重
        for ref_type in referenced_ids:
            referenced_ids[ref_type] = list(set(
                i for i in referenced_ids[ref_type] if self._is_valid_uuid(i)
            ))

        # 验证实体引用 — 通过 world facade 批量验证
        if referenced_ids["entity"]:
            try:
                from modules.world.facade import get_world_context
                ctx = await get_world_context(
                    db, novel_id,
                    entity_ids=referenced_ids["entity"],
                    limit=len(referenced_ids["entity"]),
                )
                # 如果返回的实体数少于请求的 ID 数，说明有 ID 不存在
                found_ids = {e.entity_id for e in ctx.entities} if hasattr(ctx, "entities") else set()
                # get_world_context 可能返回 entities 列表或 entity_map
                if hasattr(ctx, "entity_map"):
                    found_ids = set(ctx.entity_map.keys())
                missing = set(referenced_ids["entity"]) - found_ids
                for mid in missing:
                    warnings.append(
                        ReviewWarning(
                            type="entity_reference",
                            message=f"引用的世界对象不存在: {mid}",
                            severity="high",
                            location={"entity_id": mid},
                        )
                    )
            except Exception:
                # 如果 facade 调用失败，降级检查（仅检查 UUID 格式）
                pass

        # 验证人物引用 — 通过 character facade
        if referenced_ids["character"]:
            try:
                from modules.character.facade import get_characters_context
                ctx = await get_characters_context(
                    db, novel_id,
                    character_ids=referenced_ids["character"],
                )
                found_ids = {c.character_id for c in ctx.characters} if hasattr(ctx, "characters") else set()
                if hasattr(ctx, "character_map"):
                    found_ids = set(ctx.character_map.keys())
                missing = set(referenced_ids["character"]) - found_ids
                for mid in missing:
                    warnings.append(
                        ReviewWarning(
                            type="entity_reference",
                            message=f"引用的人物不存在: {mid}",
                            severity="high",
                            location={"character_id": mid},
                        )
                    )
            except Exception:
                pass

        return warnings

    async def _check_early_reveal(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """检查 3: 提前揭示检查

        检查候选结构是否提前揭示了隐藏真相（hidden_truth）。
        只有在 payload 中标记了 reveal_level/visibility 的字段才检查。
        """
        warnings: list[ReviewWarning] = []

        # 检查 world_entities 中的提前揭示
        entities = candidate_payload.get("world_entities", [])
        if isinstance(entities, dict):
            entities = [entities]

        for i, entity in enumerate(
            entities if isinstance(entities, list) else []
        ):
            if not isinstance(entity, dict):
                continue

            hidden_truth = entity.get("hidden_truth")
            reveal_level = entity.get("reveal_level", "author_only")

            # 如果 hidden_truth 有内容且 reveal_level 是 author_only
            # 但在候选结构中出现在读者可见的位置，标记为警告
            chapter_index = candidate_payload.get("chapter_index")
            if hidden_truth and reveal_level == "author_only" and chapter_index:
                warnings.append(
                    ReviewWarning(
                        type="early_reveal",
                        message=(
                            f"世界对象 '{entity.get('name', 'unnamed')}' "
                            f"的 hidden_truth 在第 {chapter_index} 章被提前揭示。"
                            f"当前揭示层级: {reveal_level}"
                        ),
                        severity="high",
                        location={
                            "entity_index": i,
                            "entity_name": entity.get("name", ""),
                            "field": "hidden_truth",
                            "chapter_index": chapter_index,
                        },
                    )
                )

        # 检查 plot_threads 中的 hidden_truth 提前暴露
        threads = candidate_payload.get("plot_threads", [])
        if isinstance(threads, dict):
            threads = [threads]

        for i, thread in enumerate(
            threads if isinstance(threads, list) else []
        ):
            if not isinstance(thread, dict):
                continue

            hidden_truth = thread.get("hidden_truth")
            chapter_index = candidate_payload.get("chapter_index")
            if hidden_truth and chapter_index:
                visible_goal = thread.get("visible_goal", "")
                # 如果 hidden_truth 的内容在 visible_goal 中被暗示
                if visible_goal and any(
                    word in visible_goal
                    for word in hidden_truth.split()
                    if len(word) > 2
                ):
                    warnings.append(
                        ReviewWarning(
                            type="early_reveal",
                            message=(
                                f"剧情线 '{thread.get('name', 'unnamed')}' "
                                f"的 hidden_truth 在 visible_goal 中被暗示"
                            ),
                            severity="medium",
                            location={
                                "thread_index": i,
                                "thread_name": thread.get("name", ""),
                            },
                        )
                    )

        # 检查 reveal_plans 中的揭示阶段是否跳跃
        reveals = candidate_payload.get("reveal_plans", [])
        if isinstance(reveals, dict):
            reveals = [reveals]

        for i, reveal in enumerate(
            reveals if isinstance(reveals, list) else []
        ):
            if not isinstance(reveal, dict):
                continue

            stages = reveal.get("reveal_stages", [])
            if isinstance(stages, list) and len(stages) >= 2:
                # 检查章节跳跃过大
                chapters = [
                    s.get("chapter_index", 0)
                    for s in stages
                    if isinstance(s, dict) and s.get("chapter_index")
                ]
                for j in range(1, len(chapters)):
                    gap = chapters[j] - chapters[j - 1]
                    if gap > 20:
                        warnings.append(
                            ReviewWarning(
                                type="early_reveal",
                                message=(
                                    f"揭示计划 '{reveal.get('secret_summary', 'unnamed')[:50]}' "
                                    f"两个揭示阶段间隔 {gap} 章（{chapters[j-1]} → {chapters[j]}），"
                                    f"可能造成读者遗忘前文伏笔"
                                ),
                                severity="low",
                                location={
                                    "reveal_index": i,
                                    "from_chapter": chapters[j - 1],
                                    "to_chapter": chapters[j],
                                    "gap": gap,
                                },
                            )
                        )

        return warnings

    async def _check_character_knowledge(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """检查 4: 人物知识边界检查

        检查候选结构中角色是否知道不该知道的信息。
        需要获取角色的 character_knowledge 来验证。
        """
        warnings: list[ReviewWarning] = []

        # 收集候选结构中涉及的角色和可能被他们知道的信息
        character_ids: set[str] = set()
        entity_ids: set[str] = set()

        # 从章节卡收集
        cards = candidate_payload.get("chapter_cards", [])
        if isinstance(cards, dict):
            cards = [cards]

        for card in cards if isinstance(cards, list) else []:
            if not isinstance(card, dict):
                continue
            for cid in card.get("involved_character_ids", []):
                if isinstance(cid, str) and cid.strip():
                    character_ids.add(cid)
            for eid in card.get("involved_entity_ids", []):
                if isinstance(eid, str) and eid.strip():
                    entity_ids.add(eid)

        # 从 plot_threads 收集
        threads = candidate_payload.get("plot_threads", [])
        if isinstance(threads, dict):
            threads = [threads]

        for thread in threads if isinstance(threads, list) else []:
            if not isinstance(thread, dict):
                continue
            for cid in thread.get("related_character_ids", []):
                if isinstance(cid, str) and cid.strip():
                    character_ids.add(cid)

        if not character_ids:
            return warnings

        # 对每个角色，检查他们的知识边界
        try:
            from modules.character.facade import get_character_knowledge_context

            for cid in list(character_ids):
                if not self._is_valid_uuid(cid):
                    continue

                # 获取角色的知识边界
                knowledge_list = await get_character_knowledge_context(
                    db, novel_id, cid,
                    target_ids=list(entity_ids) if entity_ids else None,
                )

                for knowledge in knowledge_list:
                    # 检查角色是否有 false_belief 或 unknown 的知识
                    # 但在候选结构中这些知识被当作已知处理
                    if hasattr(knowledge, "knowledge_level"):
                        if knowledge.knowledge_level == "unknown":
                            # 角色不知道这件事
                            target_name = getattr(knowledge, "target_id", "unknown")
                            warnings.append(
                                ReviewWarning(
                                    type="character_knowledge",
                                    message=(
                                        f"角色 {cid[:8]}... 不知道目标 {target_name}，"
                                        f"但候选结构暗示他们了解相关信息"
                                    ),
                                    severity="high",
                                    location={
                                        "character_id": cid,
                                        "target_id": target_name,
                                        "knowledge_level": "unknown",
                                    },
                                )
                            )

        except Exception:
            pass

        # 额外检查：visible_progress 和 hidden_progress 是否混用
        for card in cards if isinstance(cards, list) else []:
            if not isinstance(card, dict):
                continue
            visible = card.get("visible_progress", [])
            hidden = card.get("hidden_progress", [])
            if isinstance(visible, list) and isinstance(hidden, list):
                overlap = set(str(v) for v in visible) & set(str(h) for h in hidden)
                if overlap:
                    warnings.append(
                        ReviewWarning(
                            type="character_knowledge",
                            message=(
                                f"章节 {card.get('chapter_index', '?')} 中 "
                                f"visible_progress 和 hidden_progress 存在重叠: "
                                f"{', '.join(str(o) for o in list(overlap)[:3])}"
                            ),
                            severity="medium",
                            location={
                                "chapter_index": card.get("chapter_index"),
                                "conflict_items": list(overlap),
                            },
                        )
                    )

        return warnings

    async def _check_timeline(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """检查 5: 时间线冲突检查

        检查候选结构与现有 timeline 的冲突。
        包括顺序矛盾、事件重复、角色位置冲突等。
        """
        warnings: list[ReviewWarning] = []

        try:
            from modules.timeline.facade import check_timeline_conflicts

            conflict_result = await check_timeline_conflicts(
                db, novel_id, candidate_payload,
            )

            # 处理返回的冲突警告
            # TimelineConflictWarning 有 description 和 severity 属性
            for conflict in conflict_result:
                warnings.append(
                    ReviewWarning(
                        type="timeline_conflict",
                        message=getattr(conflict, "description", str(conflict)),
                        severity=getattr(conflict, "severity", "medium"),
                        location={
                            "source_event_ids": getattr(conflict, "source_event_ids", []),
                        },
                    )
                )

        except Exception:
            # 本地回退检查

            # 检查 chapter_cards 中的顺序
            cards = candidate_payload.get("chapter_cards", [])
            if isinstance(cards, dict):
                cards = [cards]

            if isinstance(cards, list):
                indices = []
                for card in cards:
                    if isinstance(card, dict):
                        ci = card.get("chapter_index")
                        if isinstance(ci, int):
                            indices.append(ci)

                # 检查是否有重复的 chapter_index
                if len(indices) != len(set(indices)):
                    from collections import Counter
                    dupes = [
                        idx for idx, count in Counter(indices).items()
                        if count > 1
                    ]
                    for d in dupes:
                        warnings.append(
                            ReviewWarning(
                                type="timeline_conflict",
                                message=f"存在重复的章节索引: {d}",
                                severity="high",
                                location={"chapter_index": d},
                            )
                        )

                # 检查是否连续（允许有跳过的章节）
                if indices:
                    sorted_indices = sorted(indices)
                    gaps = []
                    for j in range(1, len(sorted_indices)):
                        gap = sorted_indices[j] - sorted_indices[j - 1]
                        if gap > 1:
                            gaps.append(
                                f"{sorted_indices[j-1]} → {sorted_indices[j]}（跳过 {gap-1} 章）"
                            )
                    if len(gaps) > 3:
                        warnings.append(
                            ReviewWarning(
                                type="timeline_conflict",
                                message=f"章节序列存在多处不连续跳转:\n" + "\n".join(gaps[:5]),
                                severity="low",
                                location={"gaps": gaps},
                            )
                        )

            # 检查 foreshadowing_plans 中 seed 和 payoff 的顺序
            foreshadowings = candidate_payload.get("foreshadowing_plans", [])
            if isinstance(foreshadowings, dict):
                foreshadowings = [foreshadowings]

            for i, fs in enumerate(
                foreshadowings if isinstance(foreshadowings, list) else []
            ):
                if not isinstance(fs, dict):
                    continue
                seed = fs.get("planned_seed_chapter")
                payoff = fs.get("planned_payoff_chapter")
                if isinstance(seed, int) and isinstance(payoff, int):
                    if seed >= payoff:
                        warnings.append(
                            ReviewWarning(
                                type="timeline_conflict",
                                message=(
                                    f"伏笔 '{fs.get('name', 'unnamed')}' "
                                    f"的埋设章节({seed}) >= 收束章节({payoff})"
                                ),
                                severity="high",
                                location={
                                    "foreshadowing_index": i,
                                    "seed_chapter": seed,
                                    "payoff_chapter": payoff,
                                },
                            )
                        )

        return warnings

    async def _check_geo(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """检查 6: 地理冲突检查

        检查地点引用是否一致，通行关系是否合理。
        """
        warnings: list[ReviewWarning] = []

        # 收集候选结构中的地点引用
        location_ids: set[str] = set()

        entities = candidate_payload.get("world_entities", [])
        if isinstance(entities, dict):
            entities = [entities]

        for entity in entities if isinstance(entities, list) else []:
            if not isinstance(entity, dict):
                continue
            if entity.get("entity_type") == "location":
                eid = entity.get("id", "")
                if eid and isinstance(eid, str):
                    location_ids.add(eid)

        cards = candidate_payload.get("chapter_cards", [])
        if isinstance(cards, dict):
            cards = [cards]

        for card in cards if isinstance(cards, list) else []:
            if not isinstance(card, dict):
                continue
            for eid in card.get("involved_entity_ids", []):
                if isinstance(eid, str) and eid.strip():
                    location_ids.add(eid)

        if not location_ids:
            return warnings

        # 检查地点是否存在及其通行关系
        for lid in list(location_ids):
            if not self._is_valid_uuid(lid):
                continue
            try:
                from modules.geo.facade import get_location_context
                await get_location_context(db, novel_id, lid, depth=0)
            except Exception:
                # 地点不存在或 geo 模块未就绪，标记为低严重度警告
                warnings.append(
                    ReviewWarning(
                        type="geo_conflict",
                        message=f"引用的地理地点 {lid[:8]}... 在地理系统中不存在",
                        severity="medium",
                        location={"location_id": lid},
                    )
                )

        return warnings

    async def _check_duplicates(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """检查 7: 重复检查

        检查候选结构中的对象/剧情线/章节是否与已有正史重复。
        """
        warnings: list[ReviewWarning] = []

        # 检查 chapter_cards 是否与已有章节卡重复
        cards = candidate_payload.get("chapter_cards", [])
        if isinstance(cards, dict):
            cards = [cards]

        if isinstance(cards, list):
            for card in cards:
                if not isinstance(card, dict):
                    continue
                ci = card.get("chapter_index")
                if isinstance(ci, int):
                    try:
                        from modules.outline.facade import get_chapter_card
                        existing = await get_chapter_card(db, novel_id, ci)
                        if existing is not None:
                            warnings.append(
                                ReviewWarning(
                                    type="duplicate",
                                    message=(
                                        f"第 {ci} 章已有章节卡 "
                                        f"'{existing.title or 'unnamed'}'，"
                                        f"候选将创建重复条目"
                                    ),
                                    severity="medium",
                                    location={
                                        "chapter_index": ci,
                                        "existing_card_id": existing.card_id,
                                    },
                                )
                            )
                    except Exception:
                        pass

        # 检查 world_entities 是否与已有对象名称重复
        entities = candidate_payload.get("world_entities", [])
        if isinstance(entities, dict):
            entities = [entities]

        for i, entity in enumerate(
            entities if isinstance(entities, list) else []
        ):
            if not isinstance(entity, dict):
                continue
            name = entity.get("name", "")
            if name:
                try:
                    from modules.world.facade import get_world_context
                    ctx = await get_world_context(
                        db, novel_id,
                        limit=50,
                    )
                    existing_names = []
                    if hasattr(ctx, "entities"):
                        existing_names = [
                            e.name for e in ctx.entities
                            if hasattr(e, "name") and e.name == name
                        ]
                    if hasattr(ctx, "entity_map"):
                        existing_names = [
                            e.get("name", "") for e in ctx.entity_map.values()
                            if isinstance(e, dict) and e.get("name") == name
                        ]
                    if existing_names:
                        warnings.append(
                            ReviewWarning(
                                type="duplicate",
                                message=f"世界对象名称 '{name}' 已存在",
                                severity="low",
                                location={
                                    "entity_index": i,
                                    "entity_name": name,
                                },
                            )
                        )
                except Exception:
                    pass

        # 检查 entity_candidates 中的名称相似性
        candidates_list = candidate_payload.get("entity_candidates", [])
        if isinstance(candidates_list, dict):
            candidates_list = [candidates_list]

        candidate_names = []
        for i, cand in enumerate(
            candidates_list if isinstance(candidates_list, list) else []
        ):
            if not isinstance(cand, dict):
                continue
            name = cand.get("name", "")
            if name:
                candidate_names.append((i, name))

        # 检查候选列表内部重复
        seen_names: dict[str, int] = {}
        for i, name in candidate_names:
            if name in seen_names:
                warnings.append(
                    ReviewWarning(
                        type="duplicate",
                        message=(
                            f"候选列表内部存在重复名称: '{name}' "
                            f"（索引 {seen_names[name]} 和 {i}）"
                        ),
                        severity="medium",
                        location={
                            "first_index": seen_names[name],
                            "second_index": i,
                            "name": name,
                        },
                    )
                )
            else:
                seen_names[name] = i

        return warnings

    # ============================================================
    # 辅助方法
    # ============================================================

    def _decide(
        self,
        warnings: list[ReviewWarning],
    ) -> str:
        """根据警告列表生成决策

        - reject: 存在 high 严重度的警告
        - major_revision: 存在 >3 个 medium 严重度的警告
        - minor_revision: 存在 medium 严重度的警告
        - pass: 无严重警告
        """
        critical = [w for w in warnings if w.severity == "high"]
        major = [w for w in warnings if w.severity == "medium"]

        if len(critical) > 0:
            return ReviewDecision.reject
        if len(major) > 3:
            return ReviewDecision.major_revision
        if len(major) > 0:
            return ReviewDecision.minor_revision
        return ReviewDecision.pass_

    def _calculate_score(
        self,
        decision: str,
        warnings: list[ReviewWarning],
    ) -> float:
        """计算综合评分 (0.0 - 1.0)

        基准分 1.0，每个 high 警告扣 0.3，每个 medium 扣 0.1，每个 low 扣 0.05。
        最低 0.0。
        """
        score = 1.0
        for w in warnings:
            if w.severity == "high":
                score -= 0.3
            elif w.severity == "medium":
                score -= 0.1
            elif w.severity == "low":
                score -= 0.05
        return max(0.0, round(score, 2))

    def _generate_revision_instructions(
        self,
        decision: str,
        schema_warnings: list[ReviewWarning],
        entity_warnings: list[ReviewWarning],
        reveal_warnings: list[ReviewWarning],
        knowledge_warnings: list[ReviewWarning],
        timeline_warnings: list[ReviewWarning],
        geo_warnings: list[ReviewWarning],
        duplicate_warnings: list[ReviewWarning],
    ) -> list[str]:
        """根据决策和警告生成修改建议"""
        instructions: list[str] = []

        if decision == ReviewDecision.reject:
            instructions.append("结构存在严重问题，建议重新生成候选。")

        if schema_warnings:
            instructions.append(
                f"修复 {len(schema_warnings)} 个 Schema 问题: "
                + "; ".join(w.message for w in schema_warnings[:3])
            )

        if entity_warnings:
            instructions.append(
                f"修复 {len(entity_warnings)} 个实体引用问题: "
                + "; ".join(w.message for w in entity_warnings[:3])
            )

        if reveal_warnings:
            instructions.append(
                f"处理 {len(reveal_warnings)} 个提前揭示警告: "
                + "; ".join(w.message for w in reveal_warnings[:3])
            )

        if knowledge_warnings:
            instructions.append(
                f"调整 {len(knowledge_warnings)} 个人物知识边界问题: "
                + "; ".join(w.message for w in knowledge_warnings[:3])
            )

        if timeline_warnings:
            instructions.append(
                f"解决 {len(timeline_warnings)} 个时间线冲突: "
                + "; ".join(w.message for w in timeline_warnings[:3])
            )

        if geo_warnings:
            instructions.append(
                f"修正 {len(geo_warnings)} 个地理冲突: "
                + "; ".join(w.message for w in geo_warnings[:3])
            )

        if duplicate_warnings:
            instructions.append(
                f"处理 {len(duplicate_warnings)} 个重复警告: "
                + "; ".join(w.message for w in duplicate_warnings[:3])
            )

        return instructions

    def _to_context(
        self,
        entity: ReviewReport,
    ) -> ReviewReportContext:
        """将 ORM 模型转为上下文对象"""
        return ReviewReportContext(
            report_id=str(entity.id),
            novel_id=str(entity.novel_id),
            target_type=entity.target_type,
            target_id=entity.target_id,
            decision=entity.decision,
            score=entity.score,
            problems=entity.problems or [],
            conflict_warnings=entity.conflict_warnings or [],
            early_reveal_warnings=entity.early_reveal_warnings or [],
            character_knowledge_warnings=(
                entity.character_knowledge_warnings or []
            ),
            duplicate_entity_warnings=entity.duplicate_entity_warnings or [],
            geo_warnings=entity.geo_warnings or [],
            revision_instructions=entity.revision_instructions or [],
        )

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            from fastapi import HTTPException
            from fastapi import status as http_status

            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )

    @staticmethod
    def _is_valid_uuid(value: str) -> bool:
        """检查字符串是否为有效的 UUID 格式"""
        try:
            uuid.UUID(hex=value)
            return True
        except (ValueError, AttributeError):
            return False

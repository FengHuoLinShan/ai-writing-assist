"""Deterministic synthetic long-form corpus for the G7a import-scan baseline.

All prose is program-generated from the fixed sentence templates below; it
contains no copyrighted or author-owned text. The generator is pure: one tier
spec always rebuilds byte-identical chapters, scenes, entities, and relations,
so baselines collected on different machines stay comparable by content hash.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

NAMESPACE = uuid.UUID("7f1d6c2e-54b9-4a71-9c30-8e40a7b0e111")
_TARGET_MENTION_COUNT = 12
_REVIEW_STATUSES = ("draft", "candidate", "conflicted")
_ENTITY_TYPES = ("character", "location", "faction", "item", "event")
_NAME_PREFIX = {
    "character": "临渊人",
    "location": "七号灯桥",
    "faction": "灰雾商会",
    "item": "黄铜罗盘",
    "event": "长夜集会",
}

# 合成语句模板：仅用于规模基线，不含任何真实作品文本。
_SENTENCES = (
    "旅人在河湾整理航行记录，核对灯桥与仓库的位置。",
    "风从山口吹来，守桥人交还昨日保存的铜哨。",
    "炉火边有人低声商量下一程的补给与船期。",
    "抄写员把潮汐表钉在木板上，提醒众人留意汛期。",
    "商队沿着旧堤前行，蹄声在雾里显得很远。",
    "孩子们在栈桥尽头数着返航的灯笼。",
    "老船匠用粉笔在甲板上画出修补的记号。",
    "账房先生合上册子，把钥匙交回柜台。",
)


@dataclass(frozen=True)
class TierSpec:
    """One scale tier: chapters drive entities/terms proportionally."""

    name: str
    chapters: int
    scenes_per_chapter: int
    canonical_entities: int
    review_entities: int
    relations: int
    chapter_chars: int = 3_000
    aliases_per_entity: int = 3

    @property
    def scene_count(self) -> int:
        return self.chapters * self.scenes_per_chapter

    @property
    def entity_count(self) -> int:
        return self.canonical_entities + self.review_entities

    @property
    def alias_term_count(self) -> int:
        return self.entity_count * self.aliases_per_entity

    def summary(self) -> dict:
        return {
            "name": self.name,
            "chapters": self.chapters,
            "scenes": self.scene_count,
            "canonical_entities": self.canonical_entities,
            "review_entities": self.review_entities,
            "aliases": self.alias_term_count,
            "relations": self.relations,
            "chapter_chars": self.chapter_chars,
        }


def chapter_equivalent_tiers() -> tuple[TierSpec, ...]:
    """Long-form chapter ladder: entities/terms scale with chapters."""

    def spec(chapters: int) -> TierSpec:
        return TierSpec(
            name=f"L{chapters}",
            chapters=chapters,
            scenes_per_chapter=3,
            canonical_entities=4 * chapters,
            review_entities=chapters,
            relations=2 * chapters,
        )

    return tuple(spec(value) for value in (10, 30, 60))


def density_probe_tiers() -> tuple[TierSpec, ...]:
    """Entity-density ladder probing the import-scan limit=10_000 boundary."""
    return (
        TierSpec(
            name="D2500",
            chapters=30,
            scenes_per_chapter=3,
            canonical_entities=2_500,
            review_entities=250,
            relations=60,
        ),
        TierSpec(
            name="D5000",
            chapters=30,
            scenes_per_chapter=3,
            canonical_entities=5_000,
            review_entities=500,
            relations=60,
        ),
        TierSpec(
            name="D10000",
            chapters=30,
            scenes_per_chapter=3,
            canonical_entities=9_600,
            review_entities=400,
            relations=60,
        ),
    )


def spec_by_name(name: str) -> TierSpec:
    for spec in (*chapter_equivalent_tiers(), *density_probe_tiers()):
        if spec.name == name:
            return spec
    raise KeyError(f"unknown G7a tier: {name}")


@dataclass(frozen=True)
class EntitySeed:
    key: str
    name: str
    entity_type: str
    status: str
    importance: float
    aliases: tuple[object, ...]
    summary: str
    public_info: str
    hidden_truth: str


@dataclass(frozen=True)
class SceneSeed:
    scene_index: int
    chapter_index: int
    part: int
    title: str
    goal: str
    core_conflict: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class RelationSeed:
    source_key: str
    target_key: str
    relation_type: str
    relation_kind: str
    status: str
    review_meta: dict


@dataclass(frozen=True)
class SyntheticNovel:
    spec: TierSpec
    novel_key: str
    chapter_texts: tuple[str, ...]
    scenes: tuple[SceneSeed, ...]
    entities: tuple[EntitySeed, ...]
    relations: tuple[RelationSeed, ...]
    mentioned_keys: frozenset[str]
    target_scene_index: int

    @property
    def novel_id(self) -> uuid.UUID:
        return ident(self.novel_key, "novel")

    @property
    def target_scene_id(self) -> uuid.UUID:
        return ident(self.novel_key, f"scene-{self.target_scene_index}")

    def content_digest(self) -> str:
        payload = "\n".join(self.chapter_texts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ident(novel_key: str, item_key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{novel_key}:{item_key}")


def build_novel(spec: TierSpec) -> SyntheticNovel:
    """Build one deterministic synthetic novel for a tier."""
    novel_key = f"g7a-{spec.name.casefold()}"
    entities = _build_entities(spec)
    mentioned = sorted(
        (item for item in entities if item.status == "canonical"),
        key=lambda item: (-item.importance, item.name),
    )[: min(_TARGET_MENTION_COUNT, spec.canonical_entities)]
    mentioned_keys = {item.key for item in mentioned}
    # 让最后一章的登场名单取自被提及实体，使前序证据回读路径被真实覆盖。
    chapter_intro_keys: list[list[str]] = [[] for _ in range(spec.chapters)]
    for index, item in enumerate(entities):
        chapter_intro_keys[index % spec.chapters].append(item.key)
    if len(mentioned) >= 2:
        # 让最后一章的登场名单取自被提及实体，使前序证据回读路径被真实覆盖。
        chapter_intro_keys[spec.chapters - 1] = list(
            dict.fromkeys(
                [
                    mentioned[0].key,
                    mentioned[1].key,
                    *chapter_intro_keys[spec.chapters - 1],
                ]
            )
        )
    name_by_key = {item.key: item.name for item in entities}

    chapter_texts = tuple(
        _build_chapter_text(
            spec,
            chapter_index,
            intro_names=[
                name_by_key[key] for key in chapter_intro_keys[chapter_index - 1]
            ],
            tail_names=(
                [item.name for item in mentioned]
                if chapter_index == spec.chapters
                else []
            ),
        )
        for chapter_index in range(1, spec.chapters + 1)
    )

    scenes: list[SceneSeed] = []
    scene_index = 0
    for chapter_index in range(1, spec.chapters + 1):
        text = chapter_texts[chapter_index - 1]
        bounds = _partition(len(text), spec.scenes_per_chapter)
        intro_names = [
            name_by_key[key] for key in chapter_intro_keys[chapter_index - 1]
        ]
        for part, (start, end) in enumerate(bounds, start=1):
            title = f"第{chapter_index}章-{part}段"
            if part == 1 and intro_names:
                title = f"{intro_names[0]}的记录"
            scenes.append(
                SceneSeed(
                    scene_index=scene_index,
                    chapter_index=chapter_index,
                    part=part,
                    title=title,
                    goal=f"推进第{chapter_index}章第{part}段的航路整理。",
                    core_conflict=f"补给与船期在第{chapter_index}章第{part}段出现分歧。",
                    start_offset=start,
                    end_offset=end,
                )
            )
            scene_index += 1

    target_scene_index = scene_index - 1
    relations = _build_relations(spec, mentioned, target_scene_index, spec.chapters)
    return SyntheticNovel(
        spec=spec,
        novel_key=novel_key,
        chapter_texts=chapter_texts,
        scenes=tuple(scenes),
        entities=tuple(entities),
        relations=tuple(relations),
        mentioned_keys=frozenset(mentioned_keys),
        target_scene_index=target_scene_index,
    )


def _build_entities(spec: TierSpec) -> list[EntitySeed]:
    entities: list[EntitySeed] = []
    for index in range(spec.entity_count):
        canonical = index < spec.canonical_entities
        entity_type = _ENTITY_TYPES[index % len(_ENTITY_TYPES)]
        name = f"{_NAME_PREFIX[entity_type]}{index:04d}"
        status = (
            "canonical"
            if canonical
            else _REVIEW_STATUSES[index % len(_REVIEW_STATUSES)]
        )
        importance = (
            ((index * 7) % 100) / 100 if canonical else ((index % 5) / 100 + 0.01)
        )
        aliases = (
            f"旧称{index:04d}",
            {
                "alias": f"别名{index:04d}",
                "type": "name",
                "kind": "name",
                "status": "active",
            },
            {
                "alias": f"待核{index:04d}",
                "type": "name",
                "kind": "name",
                "status": "candidate",
                "needs_review": True,
                "confidence": 0.0,
            },
        )[: max(1, spec.aliases_per_entity)]
        entities.append(
            EntitySeed(
                key=f"entity-{index:05d}",
                name=name,
                entity_type=entity_type,
                status=status,
                importance=round(importance, 4),
                aliases=aliases,
                summary=(
                    f"{name}是合成语料中的{entity_type}条目，仅用于导入扫描基线。" * 3
                ),
                public_info=f"{name}公开记录：航路、汛期与仓库位置均为程序生成。",
                hidden_truth=f"{name}的隐藏备注：合成数据，无真实设定。",
            )
        )
    return entities


def _build_chapter_text(
    spec: TierSpec,
    chapter_index: int,
    *,
    intro_names: list[str],
    tail_names: list[str],
) -> str:
    parts: list[str] = []
    if intro_names:
        parts.append("本章新登场：" + "、".join(intro_names) + "。")
    filler_target = max(0, spec.chapter_chars - sum(len(part) for part in parts))
    counter = 0
    filled = 0
    while filled < filler_target:
        sentence = _SENTENCES[(chapter_index * 7 + counter * 3) % len(_SENTENCES)]
        parts.append(sentence)
        filled += len(sentence)
        counter += 1
    if tail_names:
        parts.append("同行的还有" + "、".join(tail_names) + "，各自核对随身清单。")
    return "\n".join(parts)


def _build_relations(
    spec: TierSpec,
    mentioned: list[EntitySeed],
    target_scene_index: int,
    target_chapter: int,
) -> list[RelationSeed]:
    if not mentioned:
        return []
    total = len(mentioned)
    relations: list[RelationSeed] = []
    # (i, i+distance) 环上配对保证 canonical 唯一边约束不被重复键破坏。
    for distance in range(1, total):
        for index in range(total):
            if len(relations) >= spec.relations:
                return relations
            source = mentioned[index]
            target = mentioned[(index + distance) % total]
            if source.key == target.key:
                continue
            relations.append(
                RelationSeed(
                    source_key=source.key,
                    target_key=target.key,
                    relation_type="同渡",
                    relation_kind="social",
                    status="canonical",
                    review_meta={
                        "scene_index": max(
                            0, target_scene_index - 4 - (len(relations) % 5)
                        ),
                        "source_chapter_index": max(1, target_chapter - 1),
                    },
                )
            )
    return relations


def _partition(length: int, parts: int) -> list[tuple[int, int]]:
    bounds = [round(length * step / parts) for step in range(parts + 1)]
    return [
        (bounds[step], bounds[step + 1])
        for step in range(parts)
        if bounds[step] < bounds[step + 1]
    ]

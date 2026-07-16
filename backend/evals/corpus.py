"""Local corpus manifests without committing copyrighted source text."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PILOT_SOURCE_PATH = Path(
    "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt"
)
FULL_SOURCE_PATH = Path(
    "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt"
)
CORPUS_ID = "lotm-clown-v1"
BACKEND_ROOT = Path(__file__).resolve().parents[1]

_CHAPTER_HEADER = re.compile(
    r"(?m)^[ \t]*(第[零〇一二三四五六七八九十百千万两0-9]+章[^\r\n]*)[ \t]*$"
)


class ChapterSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_index: int = Field(ge=1)
    title: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_group_id: str


class CorpusSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_id: str = CORPUS_ID
    source_alias: str
    file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1)
    encoding: str = "utf-8"
    chapters: list[ChapterSnapshot]


class FixtureSourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: Literal["writing", "outline", "world"]
    logical_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1)


class FixtureSourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = "repository-fixture-sources"
    version: str = "v1"
    entries: list[FixtureSourceEntry]
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


_FIXTURE_SOURCES: tuple[tuple[str, str, str], ...] = (
    (
        "writing",
        "writing.synthetic-ten-chapters",
        "tests/fixtures/synthetic_ten_chapters.txt",
    ),
    (
        "outline",
        "outline.phase1a-scene-slicing",
        "tools/prompt_contracts/fixtures/phase1a_scene_slicing.json",
    ),
    (
        "outline",
        "outline.phase1b-scene-enrichment",
        "tools/prompt_contracts/fixtures/phase1b_scene_enrichment.json",
    ),
    (
        "outline",
        "outline.phase3-structure",
        "tools/prompt_contracts/fixtures/phase3_structure_simple.json",
    ),
    (
        "world",
        "world.phase2-extraction",
        "tools/prompt_contracts/fixtures/phase2_world_extraction.json",
    ),
    (
        "world",
        "world.phase2-alias-relation",
        "tools/prompt_contracts/fixtures/phase2_alias_relation.json",
    ),
    (
        "world",
        "world.generation.core_entity.structured",
        "tools/prompt_contracts/fixtures/world_generation_core_entity.json",
    ),
)


def source_path_for_variant(variant: str) -> Path:
    if variant == "pilot":
        return PILOT_SOURCE_PATH
    if variant in {"full", "v1"}:
        return FULL_SOURCE_PATH
    raise ValueError("variant must be pilot, full, or v1")


def build_corpus_snapshot(path: Path, *, source_alias: str) -> CorpusSnapshot:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    matches = list(_CHAPTER_HEADER.finditer(text))
    if not matches:
        raise ValueError(f"no chapter headers found in {source_alias}")

    chapters: list[ChapterSnapshot] = []
    for index, match in enumerate(matches, start=1):
        end_offset = matches[index].start() if index < len(matches) else len(text)
        content = text[match.start() : end_offset]
        chapters.append(
            ChapterSnapshot(
                chapter_index=index,
                title=match.group(1).strip(),
                start_offset=match.start(),
                end_offset=end_offset,
                content_hash=_sha256_text(content),
                source_group_id=source_group_id(index),
            )
        )

    return CorpusSnapshot(
        source_alias=source_alias,
        file_hash=hashlib.sha256(raw).hexdigest(),
        byte_size=len(raw),
        chapters=chapters,
    )


def load_corpus_snapshot(variant: str) -> CorpusSnapshot:
    path = source_path_for_variant(variant)
    return build_corpus_snapshot(path, source_alias=f"lotm-clown-{variant}")


def build_fixture_source_snapshot() -> FixtureSourceSnapshot:
    """Export stable repository fixture identities without copying payloads."""
    entries: list[FixtureSourceEntry] = []
    for module, logical_id, relative_path in _FIXTURE_SOURCES:
        raw = (BACKEND_ROOT / relative_path).read_bytes()
        entries.append(
            FixtureSourceEntry(
                module=module,
                logical_id=logical_id,
                relative_path=relative_path,
                content_hash=hashlib.sha256(raw).hexdigest(),
                byte_size=len(raw),
            )
        )
    identity_payload = [
        entry.model_dump(mode="json")
        for entry in sorted(entries, key=lambda item: item.logical_id)
    ]
    snapshot_hash = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return FixtureSourceSnapshot(entries=entries, snapshot_hash=snapshot_hash)


def source_group_id(chapter_index: int, *, block_size: int = 5) -> str:
    start = ((chapter_index - 1) // block_size) * block_size + 1
    end = start + block_size - 1
    return f"lotm-clown-ch{start:03d}-{end:03d}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

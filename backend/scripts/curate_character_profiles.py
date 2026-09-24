"""Fill empty author character fields from version-pinned quotations.

Operator-only local CLI. Defaults to dry-run; private packs/reports stay outside Git.
Each character and its Evidence links commit together, with a durable pack digest.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core.config import get_settings
from core.database import get_manager
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.evidence.facade import record_evidence_link
from modules.project.facade import get_project_context, require_active_project_exclusive
from modules.world.schemas import CharacterUpdate
from modules.world.services import CharacterService
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import list_manuscript_sources, read_manuscript_range


class Quotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: SourceRangeRefContract
    quote: str = Field(min_length=1)


class FieldFill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal[
        "role",
        "appearance",
        "personality",
        "desire",
        "fear",
        "weakness",
        "voice_style",
        "relationship_summary",
    ]
    value: str = Field(min_length=1, max_length=12000)
    sources: list[Quotation] = Field(min_length=1, max_length=20)


class ProfileCuration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: UUID
    name: str
    fills: list[FieldFill] = Field(min_length=1, max_length=8)


class CurationPack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    owner_id: UUID
    label: str = Field(min_length=1, max_length=200)
    profiles: list[ProfileCuration] = Field(min_length=1, max_length=50)


def pending_fields(current: dict, profile: ProfileCuration) -> dict[str, str]:
    """Idempotent fills never silently replace existing author text."""
    result = {}
    seen = set()
    for item in profile.fills:
        if item.field in seen:
            raise ValueError(f"Duplicate field: {item.field}")
        seen.add(item.field)
        old = current.get(item.field)
        if old not in (None, "", item.value):
            raise ValueError(f"Existing author field requires review: {item.field}")
        if old != item.value:
            result[item.field] = item.value
    return result


async def curate_profile(db, pack: CurationPack, profile: ProfileCuration, *, execute):
    novel_id = str(pack.project_id)
    await require_active_project_exclusive(db, novel_id)
    context = await get_project_context(db, novel_id)
    if context is None or str(context.owner_id) != str(pack.owner_id):
        raise ValueError("Project owner does not match the explicit curation pack")
    service = CharacterService()
    current = await service.get(db, str(profile.character_id), novel_id=novel_id)
    if current.name != profile.name:
        raise ValueError("Character identity changed")
    values = pending_fields(current.model_dump(), profile)
    digest = hashlib.sha256(profile.model_dump_json().encode()).hexdigest()
    # Re-read exact sources even on replay; stale material is never marked current.
    chapters = sorted(
        {s.source_ref.chapter_index for f in profile.fills for s in f.sources}
    )
    current_sources = {
        item.chapter_index: (str(item.id), item.content_hash)
        for item in await list_manuscript_sources(
            db, novel_id, chapters, content_mode="canonical"
        )
    }
    for fill in profile.fills:
        for source in fill.sources:
            if current_sources.get(source.source_ref.chapter_index) != (
                source.source_ref.draft_id,
                source.source_ref.source_hash,
            ):
                raise ValueError(
                    "Curation source is no longer the current published draft"
                )
            read = await read_manuscript_range(
                db, novel_id, source.source_ref, before=0, after=0
            )
            if read.text[read.highlight_start : read.highlight_end] != source.quote:
                raise ValueError("Quotation does not equal its pinned manuscript range")
    metadata = dict(current.meta or {})
    receipts = dict(metadata.get("curated_profiles") or {})
    if digest in receipts:
        if values:
            raise ValueError("Curation receipt no longer matches the character")
        return {
            "character_id": str(profile.character_id),
            "status": "already_applied",
            "digest": digest,
        }
    report = {
        "character_id": str(profile.character_id),
        "status": "dry_run",
        "fields": list(values),
        "digest": digest,
    }
    if not execute:
        return report
    evidence_ids = []
    for fill in profile.fills:
        for source in fill.sources:
            link = await record_evidence_link(
                db,
                novel_id=novel_id,
                target_ref={
                    "target_type": "character",
                    "target_id": str(profile.character_id),
                    "target_path": fill.field,
                },
                source_ref=source.source_ref,
                provenance={
                    "source": "curated",
                    "curation_digest": digest,
                    "label": pack.label,
                    "quote": source.quote,
                },
            )
            evidence_ids.append(link["id"])
    receipts[digest] = {
        "source": "curated",
        "label": pack.label,
        "owner_id": str(pack.owner_id),
        "evidence_ids": evidence_ids,
    }
    metadata.update(auto_materialized=False, curated_profiles=receipts)
    await service.update(
        db,
        str(profile.character_id),
        CharacterUpdate(**values, meta=metadata),
        novel_id=novel_id,
        expected_updated_at=current.updated_at,
        require_edit_baseline=True,
    )
    return {**report, "status": "applied", "evidence_ids": evidence_ids}


async def run(pack: CurationPack, *, execute: bool, report_path: Path):
    if get_settings().auth_mode != "local":
        raise ValueError("This operator CLI requires the existing local account mode")
    manager = get_manager()
    results = []
    token = bind_principal(AccountPrincipal(pack.owner_id, "active", "local", "local"))
    try:
        async with manager.session() as db:
            account = await db.scalar(select(Account).where(Account.id == pack.owner_id))
            if account is None or account.status != "active":
                raise ValueError("The curation owner is not an active local account")
        for profile in pack.profiles:
            async with manager.session() as db:
                result = await curate_profile(db, pack, profile, execute=execute)
            results.append(result)
            report_path.write_text(
                json.dumps(
                    {"project_id": str(pack.project_id), "results": results},
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        reset_principal(token)
        await manager.close()
    print(
        json.dumps({"profiles": len(results), "statuses": [r["status"] for r in results]})
    )


if __name__ == "__main__":
    from app.bootstrap import register_container_services

    register_container_services()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(
            CurationPack.model_validate_json(args.pack.read_text()),
            execute=args.execute,
            report_path=args.report,
        )
    )

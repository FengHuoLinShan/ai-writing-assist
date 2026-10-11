"""Synthetic, deterministic novel history; never reads manuscripts or calls LLMs."""

from uuid import UUID, uuid5

from sqlalchemy import select

from infrastructure.llm.collaboration import content_hash
from modules.evolution.contracts import SourceRevisionRef
from modules.evolution.ledger_contracts import LedgerClaim
from modules.evolution.models import (
    EvolutionFrozenAttempt,
    EvolutionReceiptRecord,
    EvolutionRun,
)
from modules.project.models import Project
from modules.story.outline_state.models import Scene
from modules.writing.models import WritingDraft


async def seed_history(db, novel_id, scenes, *, run_key="issue209-history"):
    nid = UUID(str(novel_id))
    project = await db.scalar(select(Project).where(Project.id == nid))
    db.add(
        EvolutionRun(
            novel_id=nid,
            run_key=run_key,
            mode="bootstrap",
            execution_mode="live",
            status="drained",
            project_owner_epoch=project.understanding_epoch,
            committed_scene_index=scenes - 1,
        )
    )
    await db.flush()
    claims = []
    for index in range(scenes):
        text = f"合成人物{index}在钟声响起时举起铜钥匙。"
        draft_id, scene_id = (
            uuid5(nid, f"{run_key}:{kind}:{index}") for kind in ("draft", "scene")
        )
        digest = content_hash(text)
        manifest = content_hash([run_key, index, text])
        attempt = content_hash([run_key, "attempt", index])
        previous = content_hash([run_key, "attempt", index - 1]) if index else None
        ref = SourceRevisionRef(
            novel_id=str(nid),
            source_kind="chapter_draft",
            draft_id=str(draft_id),
            content_hash=digest,
            chapter_identity=f"chapter:{index + 1}",
            start_offset=0,
            end_offset=len(text),
            range_hash=SourceRevisionRef.compute_range_hash(digest, 0, len(text)),
            source_revision=1,
            segmentation_version=1,
            source_visibility="working",
        ).model_dump(mode="json")
        observation = {
            "observation_id": content_hash([run_key, index, "observation"]),
            "predicate": text,
            "modality": "event_observed",
            "mentions": [],
            "source_ref": ref,
            "evidence_quotes": [{"quote": text, "source_ref": ref}],
        }
        dependency = {
            "run_key": run_key,
            "attempt_id": attempt,
            "scene_id": str(scene_id),
            "scene_index": index,
            "source_manifest_hash": manifest,
        }
        db.add(
            WritingDraft(
                id=draft_id,
                novel_id=nid,
                chapter_index=index + 1,
                content=text,
                content_hash=digest,
                status="draft",
            )
        )
        db.add(
            Scene(
                id=scene_id,
                novel_id=nid,
                scene_index=index,
                chapter_ids=[index + 1],
                scene_chunks=[],
                status="draft",
            )
        )
        db.add(
            EvolutionFrozenAttempt(
                novel_id=nid,
                run_key=run_key,
                attempt_key=attempt,
                owner_epoch=1,
                producer_version="issue209-synthetic-v1",
                source_manifest_hash=manifest,
                previous_receipt=previous,
                status="applied",
                payload_json={
                    "scene_id": str(scene_id),
                    "scene_index": index,
                    "scene_text": text,
                    "execution_mode": "live",
                    "compiled_observations": [observation],
                    "source_binding": {
                        "draft_id": str(draft_id),
                        "chapter_index": index + 1,
                        "content_hash": digest,
                        "start_offset": 0,
                        "end_offset": len(text),
                    },
                    "input_manifest": {
                        "run_key": run_key,
                        "scene_index": index,
                        "dependency_status": "committed",
                        "source_manifest_hash": manifest,
                        "previous_scene_attempt_id": previous,
                        "previous_observations": [],
                    },
                },
            )
        )
        db.add(
            EvolutionReceiptRecord(
                novel_id=nid,
                run_key=run_key,
                attempt_key=attempt,
                execution_status="succeeded",
                committed_scene_index=index,
                committed_source_revision=1,
                receipt_json={"synthetic": True},
            )
        )
        claims.append(
            LedgerClaim(
                category="clue",
                label=f"铜钥匙{index}",
                statement=text,
                confidence=0.8,
                method_fingerprint="a" * 64,
                dependencies=[dependency],
                evidence=[
                    {
                        "observation_id": observation["observation_id"],
                        "quote": text,
                        "position": {
                            "scene_id": str(scene_id),
                            "scene_index": index,
                            "chapter_index": index + 1,
                        },
                        "modality": "event_observed",
                        "source_ref": ref,
                    }
                ],
            )
        )
    await db.flush()
    return claims


def synthetic_descriptors(count, *, evidence_size=100):
    return [
        {
            "entry_id": f"theme-{index:06d}",
            "revision": 1,
            "category": "clue",
            "label": f"钥匙{index}",
            "subject_labels": [f"人物{index % 20}"],
            "statement": "有来源的合成线索。",
            "conditions": [],
            "conditions_semantics": "有源",
            "prior_review": {"verdict": "supported"},
            "evidence_observations": [
                {"observation_id": f"old-{index:06d}", "quotes": ["原句" * evidence_size]}
            ],
        }
        for index in range(count)
    ]

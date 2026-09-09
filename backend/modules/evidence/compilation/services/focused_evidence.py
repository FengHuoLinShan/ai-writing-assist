"""Bounded root-to-one-hop retrieval over the existing manuscript and World seams."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, replace

from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from core.errors import ConflictError, ValidationError
from infrastructure.llm.agent_step_harness import ContextBudget, run_managed_structured
from infrastructure.llm.prompt_loader import load_prompt
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.llm.token_estimation import estimate_token_count
from modules.evidence.compilation.contracts import VisibilityContextContract
from modules.evidence.compilation.evidence_repository import EvidenceLinkRepository
from modules.evidence.compilation.focused_contracts import (
    FocusedEvidenceContinuation,
    FocusedEvidenceItem,
    FocusedEvidenceRequest,
    FocusedEvidenceResult,
    FocusedEvidenceTarget,
    FocusedModel,
    normalize_focused_target_ref,
)
from modules.evidence.compilation.novel_evidence import NovelEvidenceService
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.project.facade import require_active_project
from modules.writing.contracts import ManuscriptScanCursor, SourceRangeRefContract
from modules.writing.facade import (
    build_manuscript_range_ref,
    get_manuscript_source_manifest,
    scan_manuscript_terms,
)
from shared.target_ref import normalize_target_ref

_ENTITY_TYPES = {"entity", "core_entity", "world_entity", "location", "character"}
NOMINATION_MAX_TOKENS = 32_768
NOMINATION_TIMEOUT_SECONDS = 600


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _ref(value: dict) -> dict:
    return normalize_focused_target_ref(value)


def _textless(item: FocusedEvidenceItem) -> FocusedEvidenceItem:
    return item.model_copy(update={"text": ""})


def _request_hash(request: FocusedEvidenceRequest) -> str:
    return _digest(request.model_dump(mode="json", exclude={"continuation"}))


def _visibility(request) -> VisibilityContextContract:
    options = request.compile_options
    chapter = options.visible_until_chapter
    if request.chapter_to is not None and options.reveal_mode != "author_full":
        chapter = (
            min(chapter, request.chapter_to)
            if chapter is not None
            else request.chapter_to
        )
    if chapter is None and (
        options.reveal_mode in {"reader", "character"} or options.scene_id
    ):
        chapter = options.chapter_index
    return VisibilityContextContract(
        mode=options.reveal_mode
        if options.reveal_mode in {"reader", "character"}
        else "author",
        cutoff_chapter=chapter,
        cutoff_scene_id=options.visible_until_scene_id,
        cutoff_offset=options.visible_until_offset,
        character_id=options.viewpoint_character_id,
    )


def _excluded(request, *, target_ref=None, source_ref=None) -> bool:
    options = request.compile_options
    if request.allowed_refs is not None:
        allowed = False
        for candidate in request.allowed_refs:
            if (
                target_ref
                and candidate.get("target_ref")
                and _ref(candidate["target_ref"]) == _ref(target_ref)
            ):
                allowed = True
            raw = candidate.get("source_ref")
            source = (
                asdict(source_ref)
                if isinstance(source_ref, SourceRangeRefContract)
                else source_ref
            )
            if (
                source
                and raw
                and source["draft_id"] == raw.get("draft_id")
                and source["source_hash"] == raw.get("source_hash")
            ):
                allowed = allowed or (
                    raw["start_offset"] <= source["start_offset"]
                    and source["end_offset"] <= raw["end_offset"]
                )
        if not allowed:
            return True
    if target_ref:
        target = _ref(target_ref)
        for family, identifiers in options.excluded_asset_ids.items():
            family = (
                "entity"
                if family in _ENTITY_TYPES or family in {"world_entities", "characters"}
                else family
            )
            if family == target["target_type"] and target["target_id"] in identifiers:
                return True
        for raw in options.excluded_refs:
            candidate = (
                raw.get("target_ref")
                if raw.get("kind") == "target"
                else raw
                if "target_type" in raw
                else None
            )
            if (
                candidate
                and _ref(candidate)["target_type"] == target["target_type"]
                and _ref(candidate)["target_id"] == target["target_id"]
            ):
                return True
    if source_ref:
        source = (
            asdict(source_ref)
            if isinstance(source_ref, SourceRangeRefContract)
            else source_ref
        )
        if source["draft_id"] in options.excluded_asset_ids.get("writing_draft", []):
            return True
        for raw in options.excluded_refs:
            candidate = (
                raw.get("source_ref")
                if raw.get("kind") == "source_range"
                else raw
                if "draft_id" in raw
                else None
            )
            if (
                candidate
                and candidate.get("draft_id") == source["draft_id"]
                and (
                    int(candidate.get("start_offset", 0)) < source["end_offset"]
                    and int(candidate.get("end_offset", 0)) > source["start_offset"]
                )
            ):
                return True
    return False


class NeighborNomination(FocusedModel):
    root_key: str = Field(max_length=255)
    evidence_key: str = Field(max_length=255)
    name: str = Field(min_length=1, max_length=200)
    relation: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=1000)


class NeighborNominations(FocusedModel):
    neighbors: list[NeighborNomination] = Field(default_factory=list, max_length=128)


_CHARACTER_RANGE_WARNING = (
    "部分原文无法证明已被当前角色获知，已省略；仅保留可验证的已知资料，"
    "本次查阅不构成完整角色知识审查。"
)


class _CharacterRangeUnprovenError(ValidationError):
    pass


class FocusedEvidenceService:
    def __init__(
        self, *, evidence_service=None, terms_loader=None, neighbors_loader=None
    ):
        self.evidence = evidence_service or NovelEvidenceService()
        self.terms_loader = terms_loader
        self.neighbors_loader = neighbors_loader
        self._active_manifest = None
        self._visible_terms = {}
        self._nomination_available = True

    async def _terms(self, db, request, **kwargs):
        if self.terms_loader is None:
            from modules.world.facade import get_focused_world_terms

            loader = get_focused_world_terms
        else:
            loader = self.terms_loader
        return await loader(
            db,
            novel_id=request.novel_id,
            include_review=request.compile_options.include_pending_objects,
            **kwargs,
        )

    @staticmethod
    def _bounded(visibility):
        return visibility.mode != "author" or any(
            value is not None
            for value in (
                visibility.cutoff_chapter,
                visibility.cutoff_scene_id,
                visibility.cutoff_offset,
            )
        )

    async def _term_visible(self, db, request, visibility, term):
        """Prove an identity label from the same visible, version-bound manuscript."""
        if term in self._visible_terms:
            return self._visible_terms[term]
        if self._active_manifest is None:
            rows = await self._manifest(
                db, request, visibility, request.compile_options.source_manifest
            )
            self._active_manifest = {row["draft_id"]: row["source_hash"] for row in rows}
        cursor = None
        while True:
            page = await scan_manuscript_terms(
                db,
                request.novel_id,
                [term],
                source_manifest=self._active_manifest,
                content_mode=request.compile_options.content_mode,
                chapter_from=request.chapter_from,
                chapter_to=request.chapter_to,
                cursor=cursor,
                visible_end_offsets={visibility.cutoff_chapter: visibility.cutoff_offset}
                if visibility.cutoff_chapter and visibility.cutoff_offset is not None
                else {},
                allowed_ranges=[
                    ref["source_ref"]
                    for ref in request.allowed_refs
                    if ref.get("source_ref")
                ]
                if request.allowed_refs is not None
                else None,
                chapters_per_batch=100,
                limit=10,
                max_chars=20000,
            )
            if any(
                not _excluded(request, source_ref=hit.source_ref) for hit in page.hits
            ):
                self._visible_terms[term] = True
                return True
            cursor = page.cursor
            if cursor is None:
                self._visible_terms[term] = False
                return False

    @staticmethod
    def _field_view(item, target_ref):
        path = target_ref.get("target_path") or ""
        if not path:
            return item
        value = item
        try:
            for segment in path.split("."):
                name, *index = segment.rstrip("]").split("[")
                value = value[name]
                if index:
                    value = value[int(index[0])]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        if value is None:
            return None
        return {
            "content": value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False),
            "status": item.get("status") or "canonical",
            "source_hash": _digest({"target": target_ref, "value": value}),
        }

    async def _inspect(self, db, request, visibility, target_ref):
        if _excluded(request, target_ref=target_ref):
            return None
        target_ref = _ref(target_ref)
        bounded = self._bounded(visibility)
        effective_visibility = visibility
        if bounded and target_ref["target_type"] == "world_bible_page":
            return None
        if (
            bounded
            and target_ref["target_type"] == "outline_scene"
            and visibility.mode == "author"
        ):
            effective_visibility = replace(visibility, mode="reader")
        result = await self.evidence.inspect(
            db,
            novel_id=request.novel_id,
            target_ref=target_ref,
            content_mode=request.compile_options.content_mode,
            visibility=effective_visibility,
        )
        if not result.get("visible"):
            return None
        item = dict(result.get("item") or {})
        is_scene = target_ref["target_type"] == "outline_scene"
        knowledge = visibility.mode == "character" and item.get(
            "knowledge_level"
        ) not in {None, "public_default", "unknown"}
        if (
            not is_scene
            and not knowledge
            and item.get("status") not in {"canonical", "confirmed"}
            and not (
                request.compile_options.include_pending_objects
                and visibility.mode == "author"
            )
        ):
            return None
        if bounded and target_ref["target_type"] == "entity":
            if knowledge:
                # Existing CharacterKnowledge returns only its time-bound known content.
                item["status"] = "canonical"
                return self._field_view(item, target_ref)
            name = str(item.get("name") or "")
            if not name or not await self._term_visible(db, request, visibility, name):
                return None
            # Current profiles have no historical field versions.
            # Only the identity proven in visible manuscript text can cross this boundary.
            identity = {
                key: item[key]
                for key in ("entity_id", "entity_type", "name", "status")
                if key in item
            }
            return self._field_view(identity, target_ref)
        if request.compile_options.reveal_mode != "author_full":
            item.pop("hidden_truth", None)
        return self._field_view(item, target_ref)

    async def _owners(self, db, request, terms):
        owners = {term.strip().casefold(): [] for term in terms}
        skip = 0
        while True:
            page = await self._terms(db, request, names=terms, skip=skip, limit=256)
            for entity in page.get("entities", []):
                for term in entity.get("terms", []):
                    key = term.strip().casefold()
                    if key in owners:
                        owners[key].append(str(entity["id"]))
            if page.get("next_skip") is None:
                if page.get("truncated"):
                    raise ValidationError("identity terms are incomplete")
                break
            skip = page["next_skip"]
        return {term: sorted(set(ids)) for term, ids in owners.items()}

    async def _capture_target(self, db, request, state, target):
        if not target.target_ref or target.key in state.identity_snapshots:
            return
        if _ref(target.target_ref)["target_type"] != "entity":
            state.identity_snapshots[target.key] = {"source_hash": target.source_hash}
            return
        page = await self._terms(db, request, entity_ids=[target.target_ref["target_id"]])
        entity = next(
            (
                item
                for item in page["entities"]
                if str(item["id"]) == target.target_ref["target_id"]
            ),
            None,
        )
        if entity is None:
            raise ConflictError("focused identity disappeared")
        terms = list(entity.get("terms") or [entity["name"]])
        state.identity_snapshots[target.key] = {
            "id": entity["id"],
            "name": entity["name"],
            "entity_type": entity.get("entity_type"),
            "terms": terms,
            "owners": await self._owners(db, request, terms),
            "source_hash": entity.get("source_hash") or _digest(entity),
        }

    async def _validate_targets(self, db, request, state, visibility):
        for target in state.targets:
            if not target.target_ref:
                continue
            item = await self._inspect(db, request, visibility, target.target_ref)
            if item is None:
                raise ConflictError("focused target identity is no longer available")
            frozen = state.identity_snapshots.get(target.key)
            if not frozen:
                raise ConflictError("focused target identity checkpoint is incomplete")
            if _ref(target.target_ref)["target_type"] != "entity":
                if str(item.get("source_hash") or _digest(item)) != frozen["source_hash"]:
                    raise ConflictError("focused target source changed")
                continue
            rows = await self._terms(
                db, request, entity_ids=[target.target_ref["target_id"]]
            )
            current = next(
                (
                    row
                    for row in rows["entities"]
                    if str(row["id"]) == target.target_ref["target_id"]
                ),
                None,
            )
            if current is None:
                raise ConflictError("focused target identity disappeared")
            if request.continuation_target_policy == "strict":
                if (current.get("source_hash") or _digest(current)) != frozen[
                    "source_hash"
                ]:
                    raise ConflictError("focused target source changed")
            else:
                if any(
                    current.get(field) != frozen.get(field)
                    for field in ("id", "name", "entity_type")
                ):
                    raise ConflictError("focused target identity changed")
                terms = {term.strip().casefold() for term in current.get("terms", [])}
                if not {term.strip().casefold() for term in frozen["terms"]}.issubset(
                    terms
                ):
                    raise ConflictError("focused target search terms changed")
            if await self._owners(db, request, frozen["terms"]) != frozen["owners"]:
                raise ConflictError("focused target term ownership changed")

    async def _graph_snapshot(self, db, request, roots, loader):
        rows = []
        skip = 0
        while True:
            page = await loader(
                db,
                novel_id=request.novel_id,
                entity_ids=roots,
                include_review=request.compile_options.include_pending_objects,
                skip=skip,
                limit=256,
            )
            rows.extend(
                (str(edge["id"]), edge["source_hash"])
                for edge in page.get("relations", [])
            )
            if page.get("next_skip") is None:
                if page.get("truncated"):
                    raise ValidationError("neighbor identity checkpoint is incomplete")
                return _digest(rows)
            skip = page["next_skip"]

    async def _target(
        self,
        db,
        request,
        visibility,
        *,
        key,
        name=None,
        target_ref=None,
        depth=0,
        root_keys=None,
    ):
        candidates, truncated = [], False
        if target_ref and _ref(target_ref)["target_type"] != "entity":
            item = await self._inspect(db, request, visibility, target_ref)
            if item is None:
                return None
            label = str(item.get("title") or item.get("name") or "资料")
            return FocusedEvidenceTarget(
                key=key,
                name=label,
                target_ref=_ref(target_ref),
                depth=depth,
                root_keys=root_keys or [key],
                resolution="resolved",
                terms=[label],
                source_hash=str(item.get("source_hash") or _digest(item)),
            )
        kwargs = (
            {"entity_ids": [_ref(target_ref)["target_id"]]}
            if target_ref
            else {"names": [name]}
        )
        values = await self._terms(db, request, **kwargs)
        truncated = bool(values.get("truncated"))
        for entity in values.get("entities", []):
            ref = {
                "target_type": "entity",
                "target_id": str(entity["id"]),
                "target_path": _ref(target_ref).get("target_path", "")
                if target_ref
                else "",
            }
            item = await self._inspect(db, request, visibility, ref)
            if item is not None:
                if (
                    self._bounded(visibility)
                    and name
                    and name.casefold() != str(entity["name"]).casefold()
                ):
                    known = str(item.get("content") or "")
                    if name not in known or entity["name"] not in known:
                        continue
                candidates.append((entity, ref, item))
        if target_ref and not candidates:
            return None
        if len(candidates) == 1 and not truncated:
            entity, ref, item = candidates[0]
            proven_name = name or str(item.get("name") or "")
            if not proven_name and entity["name"] in str(item.get("content") or ""):
                proven_name = entity["name"]
            safe_terms = (
                list(entity.get("terms") or [entity["name"]])
                if not self._bounded(visibility)
                else [proven_name]
            )
            owners = await self._owners(db, request, safe_terms)
            proof_terms = [
                term
                for term in safe_terms
                if owners.get(term.strip().casefold()) == [str(entity["id"])]
            ]
            return FocusedEvidenceTarget(
                key=key,
                name=str(
                    proven_name
                    or ("已选对象" if self._bounded(visibility) else entity["name"])
                ),
                target_ref=ref,
                depth=depth,
                root_keys=root_keys or [key],
                resolution="resolved",
                terms=list(dict.fromkeys([name] if name else []))
                + [term for term in safe_terms if term and term != name],
                source_hash=str(entity.get("source_hash") or ""),
                proof_terms=proof_terms,
            )
        return FocusedEvidenceTarget(
            key=key,
            name=name or "未知对象",
            depth=depth,
            root_keys=root_keys or [key],
            resolution="ambiguous" if candidates or truncated else "unresolved",
            identity_candidates=[ref for _, ref, _ in candidates],
            terms=[name] if name else [],
            proof_terms=[name] if name and not (candidates or truncated) else [],
        )

    async def _manifest(self, db, request, visibility, manifest=None):
        end = request.chapter_to
        if visibility.cutoff_chapter is not None:
            end = (
                min(end, visibility.cutoff_chapter) if end else visibility.cutoff_chapter
            )
        return await get_manuscript_source_manifest(
            db,
            request.novel_id,
            content_mode=request.compile_options.content_mode,
            chapter_from=request.chapter_from,
            chapter_to=end,
            source_manifest=manifest,
        )

    async def _character_range_proven(self, db, request, visibility, ref, text):
        from modules.world.facade import get_character_knowledge_entries

        rows = await get_character_knowledge_entries(db, request.novel_id)
        repository = EvidenceLinkRepository()
        for row in rows:
            if (
                str(row.get("character_id")) != str(visibility.character_id)
                or row.get("status") not in {"canonical", "confirmed"}
                or row.get("knowledge_level") != "full"
                or row.get("known_content") != text
            ):
                continue
            # This existing projection checks owner, role, and conservative learned time.
            inspected = await self.evidence.inspect(
                db,
                novel_id=request.novel_id,
                target_ref={
                    "target_type": "character_knowledge",
                    "target_id": str(row["id"]),
                },
                content_mode=request.compile_options.content_mode,
                visibility=visibility,
            )
            if (
                not inspected.get("visible")
                or (inspected.get("item") or {}).get("known_content") != text
            ):
                continue
            for path in ("known_content", ""):
                target = normalize_target_ref(
                    {
                        "target_type": "character_knowledge",
                        "target_id": str(row["id"]),
                        "target_path": path,
                    }
                )
                links = await repository.list_for_target(
                    db,
                    novel_id=uuid.UUID(request.novel_id),
                    target_hash=target.target_hash(),
                    claim_path="known_content",
                    statuses=("active",),
                )
                if any(
                    link.precision == "range" and link.source_ref == asdict(ref)
                    for link in links
                ):
                    return True
        return False

    async def _candidate(
        self, db, request, visibility, item, manifest, state, *, required=False
    ):
        try:
            value = await self._read(db, request, visibility, item, manifest)
        except _CharacterRangeUnprovenError:
            state.coverage.character_ranges_omitted += 1
            state.warnings = list(
                dict.fromkeys([*state.warnings, _CHARACTER_RANGE_WARNING])
            )
            if required:
                state.blockers = list(
                    dict.fromkeys(
                        [
                            *state.blockers,
                            "所选原文无法证明对当前角色可见，未加入本次资料。 ",
                        ]
                    )
                )
            return None
        if visibility.mode == "character" and item.source_ref:
            state.coverage.character_ranges_verified += 1
        return value

    async def _read(self, db, request, visibility, item, manifest):
        if item.source_ref:
            ref = item.source_ref
            if manifest.get(ref.draft_id) != ref.source_hash or _excluded(
                request, source_ref=ref
            ):
                raise ValidationError("evidence is outside the frozen source selection")
            result = await self.evidence.read(
                db,
                novel_id=request.novel_id,
                source_ref=ref,
                visibility=visibility,
                before=0,
                after=0,
            )
            text = result["text"]
            if "highlight_start" in result and "highlight_end" in result:
                text = text[result["highlight_start"] : result["highlight_end"]]
            if hashlib.sha256(text.encode()).hexdigest() != ref.range_hash:
                raise ValidationError("original-text read does not match its exact range")
            if visibility.mode == "character" and not await self._character_range_proven(
                db, request, visibility, ref, text
            ):
                raise _CharacterRangeUnprovenError("当前角色的精确原文知识范围无法证明")
            return item.model_copy(
                update={
                    "text": text,
                    "source_hash": ref.source_hash,
                    "status": ref.content_mode,
                }
            )
        if item.target_ref:
            target_ref = _ref(item.target_ref)
            item = item.model_copy(
                update={
                    "target_ref": target_ref,
                    "selection_ref": {"kind": "target", "target_ref": target_ref},
                }
            )
            inspected = await self._inspect(db, request, visibility, item.target_ref)
            if inspected is None:
                raise ValidationError("target evidence is no longer visible")
            source_hash = _digest(inspected)
            if item.source_hash and item.source_hash != source_hash:
                raise ConflictError("target evidence changed; search again")
            text = "\n".join(
                str(inspected.get(field) or "")
                for field in (
                    "name",
                    "title",
                    "summary",
                    "public_info",
                    "content",
                    "hidden_truth",
                    "reader_reveal_content",
                    "synopsis",
                    "summary_text",
                    "goal",
                    "core_conflict",
                    "must_happen",
                    "must_not_happen",
                )
            )
            return item.model_copy(
                update={
                    "text": text,
                    "source_hash": source_hash,
                    "status": inspected.get("status") or "canonical",
                }
            )
        raise ValidationError("focused evidence requires a validated source reference")

    async def _metadata_item(self, db, request, visibility, target):
        if not target.target_ref:
            return None
        selection = {"kind": "target", "target_ref": target.target_ref}
        return await self._read(
            db,
            request,
            visibility,
            FocusedEvidenceItem(
                key=f"target:{_digest(target.target_ref)}",
                title=target.name,
                target_ref=target.target_ref,
                selection_ref=selection,
                target_keys=[target.key],
                match_basis="metadata",
            ),
            {},
        )

    async def _nominate(self, db, request, state, visibility, client, before_llm):
        if request.max_depth == 0 or not state.pending_nomination:
            return
        if not self._nomination_available:
            state.coverage.nomination_failed = True
            state.coverage.stop_reason = "model_unavailable"
            state.warnings = list(
                dict.fromkeys(
                    [
                        *state.warnings,
                        "模型暂不可用，已保留字面与数据库查阅结果；"
                        "连接模型后可继续核对直接关联。",
                    ]
                )
            )
            return
        packet, consumed, chars = [], 0, 0
        for receipt in state.pending_nomination:
            item = await self._candidate(
                db, request, visibility, receipt, state.source_manifest, state
            )
            if item is None:
                consumed += 1
                continue
            if packet and chars + len(item.text) > request.limits.nomination_characters:
                break
            packet.append(item)
            chars += len(item.text)
            consumed += 1
        if not packet:
            state.pending_nomination = state.pending_nomination[consumed:]
            return
        roots = {target.key: target for target in state.targets if target.depth == 0}
        payload = {
            "question": request.question,
            "roots": [{"key": key, "name": target.name} for key, target in roots.items()],
            "evidence": [
                {"key": item.key, "root_keys": item.target_keys, "text": item.text}
                for item in packet
            ],
        }
        if before_llm:
            await before_llm()
        from modules.project.facade import open_project_llm_client

        async def generate(active):
            from modules.evidence.compilation.services.retrieval_query_planner import (
                _query_planner_request_extra,
            )

            request_extra = _query_planner_request_extra(active)
            if request_extra:
                request_extra["reasoning_effort"] = "low"
            return await run_managed_structured(
                active,
                LLMCallRequest(
                    model=active.model_name,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=load_prompt("focused_evidence_neighbors")
                            + "\n\n输出 JSON Schema：\n"
                            + json.dumps(
                                NeighborNominations.model_json_schema(),
                                ensure_ascii=False,
                            ),
                        ),
                        LLMMessage(
                            role="user", content=json.dumps(payload, ensure_ascii=False)
                        ),
                    ],
                    temperature=0,
                    max_tokens=NOMINATION_MAX_TOKENS,
                    extra=request_extra,
                ),
                NeighborNominations,
                step_name="evidence.focused_neighbors",
                max_fix_attempts=1,
                transport_retries=False,
                read_only=True,
                timeout=NOMINATION_TIMEOUT_SECONDS,
                context_budget=ContextBudget(
                    max_input_chars=100000, max_output_chars=40000
                ),
            )

        try:
            if client is None:
                async with open_project_llm_client(
                    db, request.novel_id, timeout_override=NOMINATION_TIMEOUT_SECONDS - 60
                ) as active:
                    output = await generate(active)
            else:
                output = await generate(client)
        except SQLAlchemyError:
            raise
        except Exception:
            self._nomination_available = False
            state.coverage.nomination_failed = True
            state.coverage.stop_reason = "nomination_failed"
            state.warnings = list(
                dict.fromkeys(
                    [
                        *state.warnings,
                        "直接关联对象的查阅未完成，可继续查阅；现有证据仍可查看。 ",
                    ]
                )
            )
            return
        state.coverage.nomination_failed = False
        state.warnings = [
            warning
            for warning in state.warnings
            if not warning.startswith(
                (
                    "模型暂不可用",
                    "直接关联对象的查阅未完成",
                )
            )
        ]
        lookup = {item.key: item for item in packet}
        existing = {
            target.target_ref["target_id"]
            if target.target_ref
            else target.name.casefold(): target
            for target in state.targets
        }
        for proposed in output.neighbors:
            item = lookup.get(proposed.evidence_key)
            if (
                item is None
                or proposed.root_key not in roots
                or proposed.root_key not in item.target_keys
            ):
                continue
            name = proposed.name.strip()
            if (
                not name
                or name not in item.text
                or proposed.quote not in item.text
                or name not in proposed.quote
                or item.text.count(proposed.quote) != 1
                or not any(
                    term in proposed.quote
                    for term in roots[proposed.root_key].proof_terms
                )
            ):
                continue
            target = await self._target(
                db,
                request,
                visibility,
                key=f"neighbor:{_digest(name.casefold())[:24]}",
                name=name,
                depth=1,
                root_keys=[proposed.root_key],
            )
            if target is None:
                continue
            identity = (
                target.target_ref["target_id"]
                if target.target_ref
                else target.name.casefold()
            )
            if identity in existing:
                old = existing[identity]
                if old.depth == 1:
                    old.root_keys = list(
                        dict.fromkeys([*old.root_keys, proposed.root_key])
                    )
                continue
            if item.source_ref:
                source = asdict(item.source_ref)
                offset = item.text.index(proposed.quote)
                source.update(
                    start_offset=source["start_offset"] + offset,
                    end_offset=source["start_offset"] + offset + len(proposed.quote),
                    range_hash=hashlib.sha256(proposed.quote.encode()).hexdigest(),
                )
                target.direct_evidence_refs = [
                    {
                        "root_key": proposed.root_key,
                        "source_ref": source,
                        "relation": proposed.relation,
                        "basis": "literal_quote",
                        "quote": proposed.quote,
                    }
                ]
            else:
                target.direct_evidence_refs = [
                    {
                        "root_key": proposed.root_key,
                        "target_ref": item.target_ref,
                        "source_hash": item.source_hash,
                        "relation": proposed.relation,
                        "basis": "target_evidence",
                        "quote": proposed.quote,
                    }
                ]
            state.targets.append(target)
            await self._capture_target(db, request, state, target)
            existing[identity] = target
        state.pending_nomination = state.pending_nomination[consumed:]

    async def retrieve(
        self,
        db,
        request: FocusedEvidenceRequest,
        *,
        llm_client=None,
        before_llm=None,
        nomination_enabled=True,
    ):
        request = FocusedEvidenceRequest.model_validate(request)
        self._active_manifest = None
        self._visible_terms = {}
        self._nomination_available = nomination_enabled
        await require_active_project(db, request.novel_id)
        visibility, cursor_warnings = await self.evidence.resolve_visibility_cursor(
            db,
            novel_id=request.novel_id,
            content_mode=request.compile_options.content_mode,
            visibility=_visibility(request),
        )
        request_hash = _request_hash(request)
        frozen = (
            request.continuation.source_manifest
            if request.continuation
            else request.compile_options.source_manifest
        )
        descriptors = await self._manifest(db, request, visibility, frozen)
        manifest = {row["draft_id"]: row["source_hash"] for row in descriptors}
        self._active_manifest = manifest
        if request.continuation:
            state = request.continuation.model_copy(deep=True)
            if (
                state.request_fingerprint != request_hash
                or state.source_fingerprint != _digest(manifest)
            ):
                raise ConflictError(
                    "focused search continuation no longer matches its scope"
                )
            await self._validate_targets(db, request, state, visibility)
            expected_world = _digest(
                {"identities": state.identity_snapshots, "graph": state.graph_fingerprint}
            )
            if state.world_fingerprint != expected_world:
                raise ConflictError("focused world checkpoint fingerprint changed")
            if state.graph_fingerprint is not None:
                if self.neighbors_loader is None:
                    from modules.world.facade import get_focused_world_neighbors

                    loader = get_focused_world_neighbors
                else:
                    loader = self.neighbors_loader
                root_ids = [
                    t.target_ref["target_id"]
                    for t in state.targets
                    if t.depth == 0
                    and t.target_ref
                    and t.target_ref["target_type"] == "entity"
                ]
                if (
                    await self._graph_snapshot(db, request, root_ids, loader)
                    != state.graph_fingerprint
                ):
                    raise ConflictError(
                        "focused root adjacency changed; restart this search"
                    )
        else:
            targets = []
            for index, root in enumerate(request.roots):
                target = await self._target(
                    db,
                    request,
                    visibility,
                    key=root.key or f"root:{index}",
                    name=root.name,
                    target_ref=root.target_ref,
                )
                if target:
                    targets.append(target)
            state = FocusedEvidenceContinuation(
                request_fingerprint=request_hash,
                source_manifest=manifest,
                source_fingerprint=_digest(manifest),
                targets=targets,
                warnings=list(cursor_warnings),
            )
        for target in state.targets:
            await self._capture_target(db, request, state, target)
        state.coverage.total_chapters = max(
            state.coverage.total_chapters, len(descriptors)
        )
        output = []
        remaining = request.limits.characters_per_batch

        # A failed/budget-split nomination resumes before reading further chapters.
        if state.pending_nomination:
            await self._nominate(db, request, state, visibility, llm_client, before_llm)
            if state.pending_nomination and self._nomination_available:
                return self._result(
                    request,
                    state,
                    output,
                    "nomination_failed"
                    if state.coverage.nomination_failed
                    else "nomination_budget",
                )

        if state.phase == "done" and any(
            target.depth == 1 and target.key not in state.completed_target_keys
            for target in state.targets
        ):
            state.phase = "neighbors"
            state.scan_target_keys = None
            state.chapter_position = state.start_offset = state.metadata_position = 0

        # Pins use the same source, visibility and exclusion gates as recalled material.
        while state.pinned_position < len(request.compile_options.pinned_refs):
            raw = request.compile_options.pinned_refs[state.pinned_position]
            if len(output) >= request.limits.evidence_per_batch:
                return self._result(request, state, output, "evidence_budget")
            item = FocusedEvidenceItem(
                key=f"pin:{_digest(raw)}",
                selection_ref=raw,
                match_basis="pinned",
                source_ref=raw.get("source_ref"),
                target_ref=raw.get("target_ref"),
            )
            if _excluded(request, target_ref=item.target_ref, source_ref=item.source_ref):
                raise ValidationError("a required pin was explicitly excluded")
            item = await self._candidate(
                db, request, visibility, item, manifest, state, required=True
            )
            if item is None:
                state.pinned_position += 1
                continue
            if len(item.text) > remaining:
                raise ValidationError("required pinned evidence exceeds this read budget")
            output.append(item)
            remaining -= len(item.text)
            state.pinned_position += 1

        while state.allowed_position < len(request.allowed_refs or []):
            raw = request.allowed_refs[state.allowed_position]
            if len(output) >= request.limits.evidence_per_batch:
                return self._result(request, state, output, "retained_sources_budget")
            item = FocusedEvidenceItem(
                key=f"allowed:{_digest(raw)}",
                selection_ref=raw,
                source_ref=raw.get("source_ref"),
                target_ref=raw.get("target_ref"),
                match_basis="literal" if raw.get("source_ref") else "metadata",
            )
            if _excluded(request, target_ref=item.target_ref, source_ref=item.source_ref):
                state.allowed_position += 1
                continue
            item = await self._candidate(db, request, visibility, item, manifest, state)
            if item is None:
                state.allowed_position += 1
                continue
            if len(item.text) > remaining:
                if not output:
                    raise ValidationError(
                        "retained source exceeds the configured read budget"
                    )
                return self._result(request, state, output, "retained_sources_budget")
            item.target_keys = [
                target.key
                for target in state.targets
                if target.depth == 0 and any(term in item.text for term in target.terms)
            ]
            output.append(item)
            remaining -= len(item.text)
            state.allowed_position += 1

        if state.phase == "neighbors" and state.scan_target_keys is None:
            state.scan_target_keys = [
                target.key
                for target in state.targets
                if target.depth == 1 and target.key not in state.completed_target_keys
            ]
            if state.scan_target_keys:
                state.coverage.total_chapters = max(
                    state.coverage.total_chapters,
                    state.coverage.scanned_chapters + len(descriptors),
                )
        selected = [target for target in state.targets if target.depth == 0]
        if state.phase == "neighbors":
            selected = [
                target
                for target in state.targets
                if target.key in (state.scan_target_keys or [])
            ]
        while state.metadata_position < len(selected) and state.phase != "graph":
            target = selected[state.metadata_position]
            item = (
                await self._metadata_item(db, request, visibility, target)
                if "world" in request.sources
                else None
            )
            if item:
                if (
                    len(output) >= request.limits.evidence_per_batch
                    or len(item.text) > remaining
                ):
                    if not output:
                        raise ValidationError(
                            "one object evidence exceeds the configured read budget"
                        )
                    return self._result(request, state, output, "evidence_budget")
                output.append(item)
                remaining -= len(item.text)
            state.metadata_position += 1

        if (
            state.phase == "roots"
            and not state.semantic_done
            and request.limits.semantic_top_k
            and "manuscript" in request.sources
        ):
            from modules.evidence.indexing.facade import retrieve

            query = " ".join([request.question, *(target.name for target in selected)])[
                :2000
            ]
            try:
                bundle = await retrieve(
                    db,
                    request.novel_id,
                    query,
                    content_mode=request.compile_options.content_mode,
                    source_manifest=manifest,
                    visible_until_chapter=visibility.cutoff_chapter,
                    top_k=request.limits.semantic_top_k,
                    rerank=False,
                )
                for chunk in bundle.chunks:
                    if (
                        len(output) >= request.limits.evidence_per_batch
                        or remaining < 2000
                    ):
                        break
                    if (
                        not chunk.source_id
                        or chunk.start_offset is None
                        or chunk.end_offset is None
                    ):
                        continue
                    source = await build_manuscript_range_ref(
                        db,
                        request.novel_id,
                        draft_id=chunk.source_id,
                        start_offset=chunk.start_offset,
                        end_offset=chunk.end_offset,
                        content_mode=request.compile_options.content_mode,
                    )
                    if _excluded(request, source_ref=source):
                        continue
                    item = await self._candidate(
                        db,
                        request,
                        visibility,
                        FocusedEvidenceItem(
                            key=f"range:{_digest(asdict(source))}",
                            source_ref=source,
                            source_hash=source.source_hash,
                            match_basis="semantic",
                            selection_ref={
                                "kind": "source_range",
                                "source_ref": asdict(source),
                            },
                        ),
                        manifest,
                        state,
                    )
                    if item is None:
                        continue
                    if len(item.text) > remaining:
                        continue
                    item.target_keys = [
                        t.key
                        for t in selected
                        if any(
                            term.casefold() in item.text.casefold() for term in t.terms
                        )
                    ]
                    output.append(item)
                    remaining -= len(item.text)
                    if request.max_depth and item.target_keys:
                        state.pending_nomination.append(_textless(item))
                state.warnings = list(dict.fromkeys([*state.warnings, *bundle.warnings]))
            except SQLAlchemyError:
                raise
            except (ValueError, ValidationError, ConflictError):
                state.warnings = list(
                    dict.fromkeys(
                        [*state.warnings, "语义补充资料不可用，继续逐章查阅原文。 "]
                    )
                )
            state.semantic_done = True

        if (
            state.phase == "roots"
            and not state.outline_done
            and "outline" in request.sources
        ):
            while state.outline_position < len(selected):
                if len(output) >= request.limits.evidence_per_batch:
                    return self._result(request, state, output, "outline_budget")
                found = await self.evidence.search(
                    db,
                    novel_id=request.novel_id,
                    query=selected[state.outline_position].name,
                    content_mode=request.compile_options.content_mode,
                    visibility=visibility,
                    scopes=["outline"],
                    include_pending_objects=False,
                    chapter_from=request.chapter_from,
                    chapter_to=request.chapter_to,
                    top_k=min(20, request.limits.evidence_per_batch),
                )
                hits = found.get("hits", [])
                for index in range(state.outline_hit_position, len(hits)):
                    raw = hits[index]
                    target_ref = raw.get("target_ref")
                    if not target_ref or _excluded(request, target_ref=target_ref):
                        state.outline_hit_position = index + 1
                        continue
                    item = await self._read(
                        db,
                        request,
                        visibility,
                        FocusedEvidenceItem(
                            key=f"target:{_digest(target_ref)}",
                            target_ref=target_ref,
                            title=raw.get("title", "剧情资料"),
                            selection_ref={"kind": "target", "target_ref": target_ref},
                            target_keys=[selected[state.outline_position].key],
                            match_basis="metadata",
                        ),
                        manifest,
                    )
                    if (
                        len(output) >= request.limits.evidence_per_batch
                        or len(item.text) > remaining
                    ):
                        if not output:
                            raise ValidationError(
                                "one Scene exceeds the configured read budget"
                            )
                        return self._result(request, state, output, "outline_budget")
                    output.append(item)
                    remaining -= len(item.text)
                    state.outline_hit_position = index + 1
                state.outline_position += 1
                state.outline_hit_position = 0
                state.warnings = list(
                    dict.fromkeys([*state.warnings, *found.get("warnings", [])])
                )
            state.outline_done = True
        if "manuscript" not in request.sources and state.phase in {"roots", "neighbors"}:
            state.completed_target_keys = list(
                dict.fromkeys(
                    [*state.completed_target_keys, *(target.key for target in selected)]
                )
            )
            state.phase = (
                "graph" if state.phase == "roots" and request.max_depth else "done"
            )
            if state.pending_nomination:
                await self._nominate(
                    db, request, state, visibility, llm_client, before_llm
                )
                if state.pending_nomination and self._nomination_available:
                    return self._result(request, state, output, "nomination_budget")

        if state.phase in {"roots", "neighbors"}:
            terms_to_targets = {}
            for target in selected:
                for term in target.terms:
                    terms_to_targets.setdefault(term.casefold(), []).append(target.key)
            if remaining >= 2000 and len(output) < request.limits.evidence_per_batch:
                scan = await scan_manuscript_terms(
                    db,
                    request.novel_id,
                    [term for target in selected for term in target.terms],
                    source_manifest=manifest,
                    content_mode=request.compile_options.content_mode,
                    cursor=ManuscriptScanCursor(
                        state.chapter_position, state.start_offset
                    ),
                    chapter_from=request.chapter_from,
                    chapter_to=request.chapter_to,
                    visible_end_offsets={
                        visibility.cutoff_chapter: visibility.cutoff_offset
                    }
                    if visibility.cutoff_chapter and visibility.cutoff_offset is not None
                    else {},
                    allowed_ranges=[
                        ref["source_ref"]
                        for ref in request.allowed_refs
                        if ref.get("source_ref")
                    ]
                    if request.allowed_refs is not None
                    else None,
                    chapters_per_batch=request.limits.chapters_per_batch,
                    limit=request.limits.evidence_per_batch - len(output),
                    max_chars=remaining,
                )
                for hit in scan.hits:
                    if _excluded(request, source_ref=hit.source_ref):
                        continue
                    target_keys = list(
                        dict.fromkeys(
                            key
                            for term in hit.terms
                            for key in terms_to_targets.get(term.casefold(), [])
                        )
                    )
                    ref = asdict(hit.source_ref)
                    item = await self._candidate(
                        db,
                        request,
                        visibility,
                        FocusedEvidenceItem(
                            key=f"range:{_digest(ref)}",
                            title=hit.title or f"第{hit.source_ref.chapter_index}章",
                            source_ref=hit.source_ref,
                            selection_ref={"kind": "source_range", "source_ref": ref},
                            target_keys=target_keys,
                            match_count=hit.match_count,
                        ),
                        manifest,
                        state,
                    )
                    if item is None:
                        continue
                    output.append(item)
                    state.coverage.matched_occurrences += hit.match_count
                    if state.phase == "roots" and request.max_depth:
                        state.pending_nomination.append(_textless(item))
                state.coverage.scanned_chapters += len(scan.scanned_chapters)
                if scan.cursor:
                    state.chapter_position, state.start_offset = (
                        scan.cursor.chapter_position,
                        scan.cursor.start_offset,
                    )
                else:
                    state.completed_target_keys = list(
                        dict.fromkeys(
                            [
                                *state.completed_target_keys,
                                *(target.key for target in selected),
                            ]
                        )
                    )
                    state.phase = (
                        "graph"
                        if state.phase == "roots" and request.max_depth
                        else "done"
                    )
                    state.chapter_position = state.start_offset = 0
                    state.scan_target_keys = None
                if state.pending_nomination:
                    await self._nominate(
                        db, request, state, visibility, llm_client, before_llm
                    )
                if scan.cursor or (
                    state.pending_nomination and self._nomination_available
                ):
                    return self._result(
                        request,
                        state,
                        output,
                        "nomination_failed"
                        if state.coverage.nomination_failed
                        else "read_budget",
                    )
            else:
                return self._result(request, state, output, "read_budget")

        if state.phase == "graph":
            if self._bounded(visibility) and "world" in request.sources:
                state.warnings = list(
                    dict.fromkeys(
                        [
                            *state.warnings,
                            "库内关系缺少当前时点的原文证明，未沿关系扩展；"
                            "仍查阅可见原文中的直接关联。",
                        ]
                    )
                )
            if not self._bounded(visibility) and "world" in request.sources:
                if self.neighbors_loader is None:
                    from modules.world.facade import get_focused_world_neighbors

                    loader = get_focused_world_neighbors
                else:
                    loader = self.neighbors_loader
                root_ids = [
                    target.target_ref["target_id"]
                    for target in state.targets
                    if target.depth == 0
                    and target.target_ref
                    and target.target_ref["target_type"] == "entity"
                ]
                fingerprint = await self._graph_snapshot(db, request, root_ids, loader)
                if (
                    state.graph_fingerprint is not None
                    and state.graph_fingerprint != fingerprint
                ):
                    raise ConflictError(
                        "focused root adjacency changed; restart this search"
                    )
                state.graph_fingerprint = fingerprint
                batch = await loader(
                    db,
                    novel_id=request.novel_id,
                    entity_ids=root_ids,
                    include_review=request.compile_options.include_pending_objects,
                    skip=state.graph_skip,
                    limit=request.limits.neighbors_per_batch,
                )
                roots_by_id = {
                    t.target_ref["target_id"]: t.key
                    for t in state.targets
                    if t.depth == 0 and t.target_ref
                }
                known = {t.target_ref["target_id"] for t in state.targets if t.target_ref}
                for edge in batch.get("relations", []):
                    ends = [str(edge["source_id"]), str(edge["target_id"])]
                    roots = [roots_by_id[end] for end in ends if end in roots_by_id]
                    if not roots:
                        continue
                    for entity_id in ends:
                        if entity_id in known:
                            continue
                        target = await self._target(
                            db,
                            request,
                            visibility,
                            key=f"neighbor:{entity_id}",
                            target_ref={"target_type": "entity", "target_id": entity_id},
                            depth=1,
                            root_keys=roots,
                        )
                        if target:
                            target.direct_evidence_refs = [
                                {
                                    "relation_id": str(edge["id"]),
                                    "source_hash": edge["source_hash"],
                                    "root_keys": roots,
                                    "basis": "canonical_relation",
                                }
                            ]
                            state.targets.append(target)
                            await self._capture_target(db, request, state, target)
                            known.add(entity_id)
                if batch.get("next_skip") is not None:
                    state.graph_skip = batch["next_skip"]
                    return self._result(request, state, output, "neighbor_budget")
                if batch.get("truncated"):
                    raise ValidationError(
                        "neighbor source truncated without a continuation"
                    )
            state.phase = (
                "neighbors" if any(t.depth == 1 for t in state.targets) else "done"
            )
            state.metadata_position = 0
            state.coverage.total_chapters = len(descriptors) * (
                2 if state.phase == "neighbors" else 1
            )
            if state.phase == "neighbors":
                return self._result(request, state, output, "next_layer")
        if state.phase == "done" and any(
            target.depth == 1 and target.key not in state.completed_target_keys
            for target in state.targets
        ):
            state.phase = "neighbors"
            state.scan_target_keys = None
            state.metadata_position = state.chapter_position = state.start_offset = 0
        return self._result(
            request,
            state,
            output,
            "model_unavailable"
            if state.pending_nomination
            else "next_frontier_batch"
            if state.phase != "done"
            else None,
        )

    @staticmethod
    def _result(request, state, items, reason):
        unique = {}
        for item in items:
            key = _digest(item.selection_ref) if item.selection_ref else item.key
            prior = unique.get(key)
            if prior:
                item.target_keys = list(
                    dict.fromkeys([*prior.target_keys, *item.target_keys])
                )
                if prior.match_basis == "pinned":
                    prior.target_keys = item.target_keys
                    continue
            unique[key] = item
        items = list(unique.values())
        state.world_fingerprint = _digest(
            {"identities": state.identity_snapshots, "graph": state.graph_fingerprint}
        )
        coverage = state.coverage
        coverage.returned_evidence += len(items)
        coverage.read_characters += sum(len(item.text) for item in items)
        coverage.phase = state.phase
        coverage.complete = state.phase == "done" and not state.pending_nomination
        coverage.stop_reason = None if coverage.complete else reason
        compiled = _compile_packet(request, items)
        compiled["blockers"] = list(
            dict.fromkeys([*compiled["blockers"], *state.blockers])
        )
        return FocusedEvidenceResult(
            targets=state.targets,
            evidence=items,
            source_manifest=state.source_manifest,
            source_fingerprint=state.source_fingerprint,
            world_fingerprint=state.world_fingerprint,
            request_fingerprint=state.request_fingerprint,
            coverage=coverage.model_copy(deep=True),
            warnings=state.warnings,
            selection_refs=[item.selection_ref for item in items if item.selection_ref],
            continuation=None if coverage.complete else state,
            compiled_context=compiled,
            blockers=state.blockers,
        )

    async def revalidate(self, db, request, result):
        self._visible_terms = {}
        self._active_manifest = result.source_manifest
        await require_active_project(db, request.novel_id)
        visibility, _ = await self.evidence.resolve_visibility_cursor(
            db,
            novel_id=request.novel_id,
            content_mode=request.compile_options.content_mode,
            visibility=_visibility(request),
        )
        await self._manifest(db, request, visibility, result.source_manifest)
        if result.request_fingerprint != _request_hash(
            request
        ) or result.source_fingerprint != _digest(result.source_manifest):
            raise ConflictError("focused evidence scope fingerprint changed")
        for item in result.evidence:
            await self._read(db, request, visibility, item, result.source_manifest)
        return True

    async def hydrate(self, db, request, result):
        await self.revalidate(db, request, result)
        visibility, _ = await self.evidence.resolve_visibility_cursor(
            db,
            novel_id=request.novel_id,
            content_mode=request.compile_options.content_mode,
            visibility=_visibility(request),
        )
        result = result.model_copy(deep=True)
        result.evidence = [
            await self._read(db, request, visibility, item, result.source_manifest)
            for item in result.evidence
        ]
        result.compiled_context = _compile_packet(request, result.evidence)
        result.compiled_context["blockers"] = list(
            dict.fromkeys([*result.compiled_context["blockers"], *result.blockers])
        )
        return result


def _compile_packet(request, evidence):
    sections = []
    for pinned in (True, False):
        items = []
        for item in evidence:
            if (item.match_basis == "pinned") != pinned:
                continue
            source = {"type": "manuscript", "id": item.key}
            if item.source_ref:
                source["source_ref"] = asdict(item.source_ref)
            elif item.target_ref:
                source = {
                    "type": item.target_ref["target_type"],
                    "id": item.target_ref["target_id"],
                }
            source["source_hash"] = item.source_hash
            items.append(
                ContextItem(
                    key=item.key,
                    title=item.title,
                    content=item.text,
                    token_count=estimate_token_count(item.text),
                    preview=item.text[:160],
                    source=source,
                    selection_ref=item.selection_ref,
                    status=item.status,
                    selection_state="author_pinned" if pinned else "automatic",
                    can_exclude=not pinned,
                    activation_reason=f"focused:{item.match_basis}",
                )
            )
        if not items:
            continue
        content = "\n".join(item.content for item in items)
        sections.append(
            ContextSection(
                key="focused_pins" if pinned else "focused_evidence",
                tier=Tier.P0 if pinned else Tier.P2,
                title="专项查阅资料",
                content=content,
                token_count=estimate_token_count(content),
                status="mixed",
                items=items,
                sources=[item.source for item in items],
                truncatable_per_item=not pinned,
                can_exclude=not pinned,
            )
        )
    return (
        CompiledContext(
            sections=sections,
            total_tokens=sum(section.token_count for section in sections),
            budget_tokens=request.compile_options.budget_tokens,
        )
        .enforce_budget()
        .model_dump(mode="json")
    )

"""Explicit generic-fact research using the existing egress and web-read gates."""

from uuid import UUID, uuid4, uuid5

from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.llm.agent_runtime import AgentBudgetError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.native_search import private_text_fragments
from infrastructure.llm.web_search import (
    WebReadError,
    read_public_page,
    require_search_snapshot,
    search_public_fact,
)
from modules.collaboration.contracts import ResourceSnapshot
from modules.collaboration.models import CollaborationArtifact, CollaborationRun
from modules.project.facade import get_project_context


async def collect_web(
    db,
    novel_id,
    run_id,
    questions,
    manifest,
    *,
    grant,
    snapshot,
    budget,
    checkpoint,
    fence,
):
    if not grant.allow_web or manifest.subject.kind != "author":
        raise ConflictError("本次没有公开资料查证权限", code="GRANT_SCOPE_CONFLICT")
    query_hash = content_hash([manifest.fingerprint, questions, snapshot])
    saved = await db.scalar(
        select(CollaborationArtifact).where(
            CollaborationArtifact.novel_id == UUID(novel_id),
            CollaborationArtifact.run_id == UUID(run_id),
            CollaborationArtifact.kind == "research_sources",
            CollaborationArtifact.payload_json["query_hash"].as_string() == query_hash,
        )
    )
    if saved:
        if saved.output_hash != content_hash(saved.payload_json):
            raise ConflictError("原查证回执校验失败", code="ARTIFACT_CORRUPT")
        values = saved.payload_json
    else:
        project = await get_project_context(db, novel_id)
        protected = [project.title, *(source.label for source in manifest.resources)]
        previous = (
            await db.scalars(
                select(CollaborationArtifact).where(
                    CollaborationArtifact.novel_id == UUID(novel_id),
                    CollaborationArtifact.run_id == UUID(run_id),
                )
            )
        ).all()
        observed = [*manifest.resources]
        for artifact in previous:
            observed += [
                ResourceSnapshot.model_validate(value)
                for value in artifact.manifest_json.get("resources", [])
                if value.get("kind") != "external_reference"
            ]
        private = [
            text for source in observed for text in private_text_fragments(source.content)
        ]
        owner_run = await db.get(CollaborationRun, UUID(run_id))
        private += list(private_text_fragments(owner_run.request_json))
        protected += [source.label for source in observed]
        for source in observed:
            for key in ("name", "title", "alias"):
                value = source.content.get(key)
                if isinstance(value, str):
                    protected.append(value)
        values = {
            "query_hash": query_hash,
            "sources": [],
            "omissions": [],
            "coverage": "只引用实际读取的网页正文；搜索摘要不作为事实证据。",
        }
        await db.commit()

        async def reserve():
            await fence()
            require_search_snapshot(snapshot)
            budget.reserve(web=1)
            await checkpoint(budget.model_dump(mode="json"))

        for question in questions:
            try:
                require_search_snapshot(snapshot)
                result = await search_public_fact(
                    question,
                    snapshot=snapshot,
                    before_request=reserve,
                    protected_terms=protected,
                    private_texts=private,
                )
                for hit in result["hits"][:2]:
                    page = await read_public_page(
                        hit["url"], before_request=reserve, protected_terms=protected
                    )
                    text = page["text"][:2000]
                    source = ResourceSnapshot(
                        kind="external_reference",
                        id=uuid5(UUID(run_id), page["url"]),
                        revision=page["text_hash"],
                        source_hash=page["content_hash"],
                        label=page["title"],
                        content={
                            **page,
                            "text": text,
                            "coverage": "本次回读正文的前 2000 字以内",
                            "excerpted": True,
                        },
                        read_range=(0, len(text)),
                        range_hash=content_hash(text),
                    )
                    if not any(
                        value["id"] == str(source.id) for value in values["sources"]
                    ):
                        values["sources"].append(source.model_dump(mode="json"))
                if result["omissions"]:
                    values["omissions"].append(
                        "部分搜索渠道未完成，未把未读内容作为不存在。"
                    )
            except WebReadError as error:
                values["omissions"].append(str(error))
            except AgentBudgetError:
                values["omissions"].append("本轮公开资料请求额度已用完；保留已读出处。")
                break
        await fence(lock=True)
        db.add(
            CollaborationArtifact(
                id=uuid4(),
                novel_id=UUID(novel_id),
                run_id=UUID(run_id),
                kind="research_sources",
                manifest_json=manifest.model_dump(mode="json"),
                payload_json=values,
                output_hash=content_hash(values),
            )
        )
        await db.commit()
    return manifest.model_copy(
        update={
            "resources": [
                *manifest.resources,
                *(ResourceSnapshot.model_validate(value) for value in values["sources"]),
            ],
            "query_receipt": {
                **(manifest.query_receipt or {}),
                "web": {"coverage": values["coverage"], "omissions": values["omissions"]},
            },
        }
    )

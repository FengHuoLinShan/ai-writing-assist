"""Freeze each reading point before unlocking the following prose."""

import json
from uuid import UUID, uuid5

from core.errors import ConflictError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.contracts import CognitionSelection
from modules.collaboration.models import CollaborationArtifact
from modules.story.contracts import ReadingNode


def reading_segments(manifest, grant):
    segments = []
    for source in sorted(
        manifest.resources, key=lambda item: (item.chapter_index or 0, item.key)
    ):
        if source.kind != "writing_draft" or source.chapter_index is None:
            raise ValidationError("盲读只能按章读取所选正文")
        prose = source.content.get("content", "")
        stops = list(grant.reading_stops.get(source.key, []))
        if stops and stops[-1] > len(prose):
            raise ValidationError("阅读停点超出当前正文")
        if not stops or stops[-1] != len(prose):
            stops.append(len(prose))
        start = 0
        for end in stops:
            if end > start:
                text = prose[start:end]
                segments.append(
                    source.model_copy(
                        update={
                            "label": f"第 {source.chapter_index} 章",
                            "content": {"content": text},
                            "read_range": (start, end),
                            "range_hash": content_hash(text),
                        }
                    )
                )
            start = end
    if not segments or len(segments) > 8:
        raise ValidationError("一次盲读需要一至八个阅读停点，请缩小范围")
    return segments


async def freeze_reading(db, novel_id, run_id, manifest, grant, *, call, audit, fence):
    trail = []
    for index, source in enumerate(reading_segments(manifest, grant)):
        identity = uuid5(UUID(run_id), f"reading-point:{index}")
        prior = await db.get(CollaborationArtifact, identity)
        local = manifest.model_copy(
            update={"resources": [source], "cognition": CognitionSelection()}
        )
        if prior is not None:
            if (
                prior.novel_id != UUID(novel_id)
                or prior.output_hash != content_hash(prior.payload_json)
                or prior.manifest_json != local.model_dump(mode="json")
                or prior.payload_json.get("prior_hash") != content_hash(trail)
            ):
                raise ConflictError("历史阅读回执已变化，不能重写原来的猜测")
            trail.append(prior.payload_json)
            continue
        payload = {"prior_reading": trail, "prose": source.content["content"]}
        node = await call(
            ReadingNode,
            "你第一次按顺序读到这段正文。只知道之前冻结的认知和本段正文。"
            "区分知道、猜测和未解问题；后续揭示只能对照，不能修改过去记录。"
            "每条依据必须逐字引用本段正文；不使用作者目标、标题或外部作品记忆。",
            payload,
            capability="collaboration.investigate",
            reserve=5,
        )
        if any(
            belief.excerpt not in source.content["content"]
            for belief in [*node.known, *node.guesses, *node.newly_revealed]
        ):
            raise ConflictError("读者判断引用了尚未读到的文字", code="UNKNOWN_EVIDENCE")
        review = await audit(
            node.model_dump_json(),
            local,
            "检查读者判断是否由当前已读文字支持。猜测只能保留为猜测。",
            capability="collaboration.investigate",
            source_context=json.dumps(payload, ensure_ascii=False),
        )
        if review["status"] != "passed":
            raise ConflictError("该阅读点未通过出处复核", code="OUTPUT_REJECTED")
        result = {
            "point": index + 1,
            "source_key": source.key,
            "read_range": list(source.read_range),
            "range_hash": source.range_hash,
            "prior_hash": content_hash(trail),
            "beliefs": node.model_dump(mode="json"),
            "summary": (
                f"第 {source.chapter_index} 章第 {source.read_range[1]} 字时的阅读记录"
            ),
            "knowledge_review": {"status": review["status"], "review": review["review"]},
        }
        await fence(lock=True)
        db.add(
            CollaborationArtifact(
                id=identity,
                novel_id=UUID(novel_id),
                run_id=UUID(run_id),
                kind="reading_point",
                manifest_json=local.model_dump(mode="json"),
                payload_json=result,
                output_hash=content_hash(result),
            )
        )
        await db.commit()
        trail.append(result)
    return trail

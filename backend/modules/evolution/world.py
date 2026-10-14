"""Sequential World/alias/relation candidates in the Scene receipt transaction."""

import json
from copy import deepcopy
from functools import partial
from uuid import NAMESPACE_URL, uuid5

from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.profiles import DEEPSEEK_THINKING_MODELS
from modules.evidence.contracts import GroupSource
from modules.evidence.facade import build_group_audit_request, materialize_group_audit
from modules.evolution.consumer_reuse import semantic_manifest
from modules.imports import facade as imports

WORLD_AUDIT_INPUT_CHAR_LIMIT = 45_000
# shortcut: cap quote matches at 64; lift with bounded exact-occurrence selection.
WORLD_AUDIT_SOURCE_OCCURRENCE_LIMIT = 64
WORLD_AUDIT_INSTRUCTION = (
    "独立核对长期世界对象、别名和关系提案。逐字引用只证明定位；"
    "核对类型、身份、关系方向及每个描述字段的语义蕴含。传闻不得变成"
    "客观事实；角色当前不知道的事实不可写成其知识；同名不能证明同一人。"
    "不可靠身份、超范围否定或凭空补出的事实均以major finding阻断。"
    "findings.kind仅用missing_required、unsupported_fact、"
    "out_of_scope_knowledge、premature_reveal、irrelevant_content、"
    "conflict、unchecked；blocker/major/minor只填severity，不能填kind。"
    "核对world身份候选声明时只用initial_world_identity_context，"
    "relations用context；二轮新增/查到的候选不是第一轮已经提供的资料，"
    "不得据二轮引用映射否定第一轮的未提供声明。"
    "这是分阶段组合提案：world.entities 中的 aliases 为未填占位，"
    "实际别名以 relations.aliases 单独承载，两者不构成矛盾。"
    "空关系候选只说明本次资料未提供历史记录，不能证明历史上首次建立。"
)


def _world_group_issue(reason):
    return {
        "candidate_over_capacity": "单个候选超过本次审查容量，需作者核对。",
        "source_occurrence_limit": "引文对应位置过多，无法确定审查范围，需作者核对。",
        "source_range_unavailable": "无法绑定精确原文范围，需作者核对。",
        "source_quote_not_found": "候选引文不在本场正文中，需作者核对。",
        "budget_exhausted": "本轮额度已用完，此组尚未审查。",
        "audit_failed": "此组独立审查未完成；结果和费用记录已保留。",
    }.get(reason, "此组尚未完成独立审查，需作者核对。")


def _known_format_failure(error) -> bool:
    receipt = error.receipt or {}
    details = receipt.get("attempts_detail") or []
    return bool(
        (receipt.get("usage") or {}).get("usage_complete") is True
        and details
        and details[-1].get("error_kind")
        in {"invalid_json", "truncated_json", "schema_validation"}
    )


def _deferred_world_result(context, stage: str) -> dict:
    return {
        "world": {"entities": [], "delta_events": [], "uncertain_items": []},
        "relations": {"aliases": [], "relations": [], "uncertain_items": []},
        "context": context,
        "review": {
            "status": "blocked",
            "review_kind": "extraction_deferred",
            "issues": [{"message": f"{stage}格式失败；结果和费用已保留，需另行核对。"}],
        },
    }


def request_spec(request, schema):
    return {
        "request": request.model_dump(mode="json", exclude_unset=True),
        "schema_name": schema.__name__,
        "schema_hash": content_hash(schema.model_json_schema()),
    }


def materialize_world_audit_group(planned, result):
    scope = {
        key: planned["scope"][key]
        for key in ("capability", "novel_id", "group_key", "output", "sources")
    }
    scope["sources"] = [
        GroupSource(
            **{
                **item,
                "dimensions": tuple(item.get("dimensions") or ()),
            }
        )
        for item in scope["sources"]
    ]
    return materialize_group_audit(**scope, result=result)


def _claim_quotes(path, item):
    if path == "entities":
        quotes = [item.get("quote"), *(item.get("evidence_quotes") or [])]
        quotes.extend(
            quote
            for values in (item.get("field_evidence") or {}).values()
            for quote in values
        )
    elif path == "delta_events":
        quotes = (item.get("meta") or {}).get("evidence_quotes") or []
    else:
        quotes = item.get("evidence_quotes") or []
    ordered = list(dict.fromkeys(str(value).strip() for value in quotes if value))
    return [
        quote
        for quote in ordered
        if not any(quote != other and quote in other for other in ordered)
    ]


def _scene_source_chunks(source, scene_text):
    chunks, cursor = [], 0
    ranges = source.ranges()
    for index, item in enumerate(ranges):
        start = item.start_offset
        end = item.end_offset
        if end is None:
            if index != len(ranges) - 1:
                return None
            end = start + len(scene_text) - cursor
        length = end - start
        if length < 0:
            return None
        chunks.append((cursor, cursor + length, item))
        cursor += length
    return chunks if cursor == len(scene_text) else None


def _map_scene_interval(chunks, start, end):
    mapped, covered = [], 0
    for local_start, local_end, source in chunks:
        left, right = max(start, local_start), min(end, local_end)
        if right <= left:
            continue
        absolute_start = source.start_offset + left - local_start
        absolute_end = source.start_offset + right - local_start
        mapped.append(
            {
                "chapter_index": source.chapter_index,
                "draft_id": source.draft_id,
                "content_hash": source.content_hash,
                "start_offset": absolute_start,
                "end_offset": absolute_end,
            }
        )
        covered += right - left
    return mapped if covered == end - start else None


def _semantic_source_interval(interval):
    # Chapter versions are host guards; the model consumes these exact excerpts.
    return {
        **interval,
        "occurrences": [
            {
                **item,
                **{
                    key: [
                        {
                            field: value
                            for field, value in source.items()
                            if field not in {"draft_id", "content_hash"}
                        }
                        for source in item[key]
                    ]
                    for key in ("quote_ranges", "source_ranges")
                },
            }
            for item in interval["occurrences"]
        ],
    }


def _quote_source(scene_text, chunks, quote):
    positions, cursor = [], 0
    while (position := scene_text.find(quote, cursor)) >= 0:
        positions.append(position)
        cursor = position + 1
        if len(positions) > WORLD_AUDIT_SOURCE_OCCURRENCE_LIMIT:
            return None, None, "source_occurrence_limit"
    if not positions:
        return None, None, "source_quote_not_found"

    occurrences = []
    for position in positions:
        quote_ranges = _map_scene_interval(chunks, position, position + len(quote))
        if quote_ranges is None:
            return None, None, "source_range_unavailable"
        excerpt_start = max(0, position - 120)
        excerpt_end = min(len(scene_text), position + len(quote) + 120)
        excerpt_ranges = _map_scene_interval(chunks, excerpt_start, excerpt_end)
        if excerpt_ranges is None:
            return None, None, "source_range_unavailable"
        occurrences.append(
            {
                "scene_offsets": [position, position + len(quote)],
                "quote_ranges": quote_ranges,
                "source_ranges": excerpt_ranges,
                "excerpt": scene_text[excerpt_start:excerpt_end],
            }
        )

    semantic = _semantic_source_interval({"quote": quote, "occurrences": occurrences})
    digest = content_hash(semantic)
    source_key = f"scene_quote_{digest[:20]}"
    return (
        GroupSource(
            source_key=source_key,
            source_type="prior_prose",
            source_id=json.dumps(
                [item["source_ranges"] for item in semantic["occurrences"]],
                ensure_ascii=False,
                sort_keys=True,
            ),
            content_hash=digest,
            label="本场逐字原文",
            dimensions=("prior_prose",),
        ),
        {"source_key": source_key, "quote": quote, "occurrences": occurrences},
        None,
    )


def _world_claim_units(world, relations, context):
    """Keep claims together only when their resolved World identity connects them."""
    new_refs = context.get("_new_entity_refs") or {}
    new_ref_by_index = {index: ref for ref, index in new_refs.items()}
    entity_ref_map = context.get("_entity_ref_map") or {}
    candidates = {
        item["prompt_ref"]: item
        for item in context.get("identity_candidates", [])
        if item.get("prompt_ref")
    }
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = find(parent[node])
        return parent[node]

    def union(left, right):
        left, right = find(left), find(right)
        if left == right:
            return
        first, second = sorted((left, right))
        parent[second] = first

    def node_for_ref(ref):
        if ref in new_refs:
            return entity_nodes[new_refs[ref]]
        entity_id = entity_ref_map.get(ref)
        return f"entity:{entity_id}" if entity_id else f"ref:{ref}"

    def identity_query_keys(entity_type, name):
        return {
            (query["entity_type"], query["name"])
            for query in context.get("_identity_queries", [])
            if query.get("entity_type") == entity_type and query.get("name") == name
        }

    entity_nodes = []
    for index, entity in enumerate(world.get("entities", [])):
        new_ref = new_ref_by_index.get(index)
        if new_ref:
            node = f"ref:{new_ref}"
        elif entity.get("suggested_action") == "link_to_existing":
            matches = {
                entity_ref_map[ref]
                for ref, candidate in candidates.items()
                if ref in entity_ref_map
                and candidate.get("entity_type") == entity.get("entity_type")
                and candidate.get("name") == entity.get("suggested_existing_entity_name")
            }
            node = f"entity:{next(iter(matches))}" if len(matches) == 1 else ""
        else:
            node = ""
        node = node or f"entity_candidate:{index}"
        entity_nodes.append(node)
        find(node)

    duplicate_new: dict[tuple[str, str], list[str]] = {}
    for index, entity in enumerate(world.get("entities", [])):
        if entity.get("suggested_action") == "create_new":
            duplicate_new.setdefault(
                (entity.get("entity_type", ""), entity.get("name", "")), []
            ).append(entity_nodes[index])
    for nodes in duplicate_new.values():
        for node in nodes[1:]:
            union(nodes[0], node)

    units = []

    def add(path, index, item, nodes, refs=(), query_keys=()):
        nodes = set(nodes) or {f"claim:{path}:{index}"}
        for node in nodes:
            find(node)
        units.append(
            {
                "path": path,
                "index": index,
                "nodes": nodes,
                "refs": set(refs),
                "query_keys": set(query_keys),
                "quotes": _claim_quotes(path, item),
            }
        )

    for index, entity in enumerate(world.get("entities", [])):
        new_ref = new_ref_by_index.get(index)
        refs = {new_ref} if new_ref else set()
        if entity.get("suggested_action") == "link_to_existing":
            refs.update(
                ref
                for ref, candidate in candidates.items()
                if entity_ref_map.get(ref) == entity_nodes[index].removeprefix("entity:")
                and candidate.get("entity_type") == entity.get("entity_type")
            )
        query_keys = identity_query_keys(
            entity.get("entity_type", ""), entity.get("name", "")
        )
        add("entities", index, entity, {entity_nodes[index]}, refs, query_keys)

    for index, item in enumerate(world.get("delta_events", [])):
        meta = item.get("meta") or {}
        name = meta.get("subject_name", "")
        matches = [
            position
            for position, entity in enumerate(world.get("entities", []))
            if entity.get("name") == name
        ]
        query_matches = [
            query
            for query in context.get("_identity_queries", [])
            if query.get("name") == name and len(query.get("matches") or []) == 1
        ]
        nodes = {entity_nodes[matches[0]]} if len(matches) == 1 else set()
        refs = set()
        keys = set()
        if len(query_matches) == 1 and not nodes:
            query = query_matches[0]
            keys.add((query["entity_type"], query["name"]))
            nodes.add(f"entity:{query['matches'][0][0]}")
            refs.update(
                ref
                for ref, entity_id in entity_ref_map.items()
                if entity_id == query["matches"][0][0]
            )
        if len(matches) == 1:
            entity = world["entities"][matches[0]]
            keys.update(identity_query_keys(entity.get("entity_type", ""), name))
            ref = new_ref_by_index.get(matches[0])
            if ref:
                refs.add(ref)
        if not nodes:
            nodes = {f"delta:{index}"}
        add("delta_events", index, item, nodes, refs, keys)

    for index, item in enumerate(world.get("uncertain_items", [])):
        mention = item.get("mention_name")
        matches = [
            position
            for position, entity in enumerate(world.get("entities", []))
            if mention and entity.get("name") == mention
        ]
        node = entity_nodes[matches[0]] if len(matches) == 1 else f"uncertain:{index}"
        add("world_uncertain_items", index, item, {node})

    for path in ("aliases", "relations", "relation_uncertain_items"):
        output_key = "uncertain_items" if path == "relation_uncertain_items" else path
        for index, item in enumerate(relations.get(output_key, [])):
            if path == "aliases":
                refs = {item.get("entity_ref", "")}
            elif path == "relations":
                refs = {item.get("source_ref", ""), item.get("target_ref", "")}
            else:
                refs = set(item.get("related_refs") or [])
            refs.discard("")
            nodes = {node_for_ref(ref) for ref in refs}
            if path in {"relations", "relation_uncertain_items"} and len(nodes) > 1:
                ordered = sorted(nodes)
                for node in ordered[1:]:
                    union(ordered[0], node)
            query_keys = {
                (candidates[ref]["entity_type"], candidates[ref]["name"])
                for ref in refs
                if ref in candidates
            }
            add(path, index, item, nodes, refs, query_keys)

    grouped = {}
    for unit in units:
        root = min(find(node) for node in unit["nodes"])
        grouped.setdefault(root, []).append(unit)
    for component in grouped.values():
        component_refs = set().union(*(unit["refs"] for unit in component))
        component_queries = set().union(*(unit["query_keys"] for unit in component))
        entity_ids = {
            entity_ref_map[ref] for ref in component_refs if ref in entity_ref_map
        }
        component_refs.update(
            ref for ref, entity_id in entity_ref_map.items() if entity_id in entity_ids
        )
        for ref in component_refs:
            candidate = candidates.get(ref)
            if candidate:
                component_queries.add(
                    (candidate.get("entity_type", ""), candidate.get("name", ""))
                )
        for query in context.get("_identity_queries", []):
            if (query.get("entity_type"), query.get("name")) in component_queries:
                matched_ids = {match[0] for match in query.get("matches") or []}
                component_refs.update(
                    ref
                    for ref, entity_id in entity_ref_map.items()
                    if entity_id in matched_ids
                )
        for unit in component:
            unit["component_refs"] = component_refs
            unit["component_queries"] = component_queries
    return [
        sorted(component, key=lambda unit: (unit["path"], unit["index"]))
        for _, component in sorted(grouped.items())
    ]


def _identity_review_context(context, refs, query_keys):
    queries = [
        item
        for item in context.get("_identity_queries", [])
        if (item.get("entity_type"), item.get("name")) in query_keys
    ]
    matched_ids = {match[0] for item in queries for match in (item.get("matches") or [])}
    selected_refs = set(refs)
    entity_ref_map = context.get("_entity_ref_map") or {}
    selected_refs.update(
        ref for ref, entity_id in entity_ref_map.items() if entity_id in matched_ids
    )
    identities = [
        item
        for item in context.get("identity_candidates", [])
        if item.get("prompt_ref") in selected_refs
    ]
    result = {"identity_candidates": identities, "identity_queries": queries}
    relation_candidates = [
        item
        for item in context.get("relation_candidates", [])
        if item.get("source_ref") in selected_refs
        and item.get("target_ref") in selected_refs
    ]
    if relation_candidates:
        result["relation_candidates"] = relation_candidates
        if context.get("relation_history_scope"):
            result["relation_history_scope"] = context["relation_history_scope"]
    return result


def _selected_world_output(world, relations, members):
    selected = {(item["path"], item["index"]) for item in members}
    return {
        "world": {
            key: [
                item
                for index, item in enumerate(world.get(key, []))
                if (key, index) in selected
            ]
            for key in ("entities", "delta_events", "uncertain_items")
        },
        "relations": {
            key: [
                item
                for index, item in enumerate(relations.get(key, []))
                if (member_key, index) in selected
            ]
            for key, member_key in (
                ("aliases", "aliases"),
                ("relations", "relations"),
                ("uncertain_items", "relation_uncertain_items"),
            )
        },
    }


def _make_world_audit_group(
    *,
    members,
    world,
    relations,
    context,
    initial_context,
    source,
    scene_text,
    novel_id,
    attempt_id,
    grouped: bool,
):
    group_units = members if grouped else []
    members = [
        {"path": item["path"], "index": item["index"]}
        for item in (group_units or members)
    ]
    output = _selected_world_output(world, relations, members)
    if grouped:
        refs = set().union(*(set(item.get("component_refs", ())) for item in group_units))
        query_keys = set().union(
            *(set(item.get("component_queries", ())) for item in group_units)
        )
        required_refs = set().union(*(item["refs"] for item in group_units))
        apply_query_keys = set().union(*(item["query_keys"] for item in group_units))
    else:
        refs = set(context.get("_entity_ref_map", {}))
        refs.update(context.get("_new_entity_refs", {}))
        query_keys = {
            (item.get("entity_type", ""), item.get("name", ""))
            for item in context.get("_identity_queries", [])
        }
        required_refs = refs
        apply_query_keys = query_keys
    source_objects, source_intervals, source_errors = {}, {}, []
    chunks = _scene_source_chunks(source, scene_text) if grouped else None
    if grouped and chunks is None:
        source_errors.append("source_range_unavailable")
    if grouped:
        for item in group_units:
            for quote in item.get("quotes", []):
                if quote in source_intervals:
                    continue
                source_obj, interval, error = _quote_source(scene_text, chunks, quote)
                if error:
                    source_errors.append(error)
                    continue
                source_objects[source_obj.source_key] = source_obj
                source_intervals[source_obj.source_key] = interval
        review_context = {
            "source_intervals": [
                _semantic_source_interval(item) for item in source_intervals.values()
            ],
            "initial_world_identity_context": _identity_review_context(
                initial_context, refs, query_keys
            ),
            "context": _identity_review_context(context, refs, query_keys),
        }
        source_values = sorted(source_objects.values(), key=lambda item: item.source_key)
        source_values.append(
            GroupSource(
                source_key="scene_context",
                source_type="imported_assets",
                content_hash=content_hash(review_context),
                dimensions=("world_entities", "imported_assets"),
            )
        )
        group_key = "world-audit:" + content_hash(
            [
                novel_id,
                members,
                output,
                review_context,
                [item.__dict__ for item in source_values],
            ]
        )
        scope = {
            "capability": "imports.entity_extraction",
            "novel_id": novel_id,
            "group_key": group_key,
            "output": json.dumps(output, ensure_ascii=False, sort_keys=True),
            "sources": source_values,
            "task_instruction": WORLD_AUDIT_INSTRUCTION,
            "context": json.dumps(review_context, ensure_ascii=False, sort_keys=True),
        }
    else:
        review_context = {
            "initial_world_identity_context": {
                key: initial_context[key]
                for key in ("identity_candidates", "_entity_ref_map", "_identity_queries")
            },
            "context": context,
        }
        scope = {
            "capability": "imports.entity_extraction",
            "novel_id": novel_id,
            "group_key": attempt_id,
            "output": json.dumps(
                {"world": world, "relations": relations},
                ensure_ascii=False,
                sort_keys=True,
            ),
            "sources": [
                GroupSource(
                    source_key="scene_source",
                    source_type="prior_prose",
                    content_hash=content_hash(scene_text),
                    dimensions=("prior_prose",),
                ),
                GroupSource(
                    source_key="scene_context",
                    source_type="imported_assets",
                    content_hash=content_hash(review_context),
                    dimensions=("world_entities", "imported_assets"),
                ),
            ],
            "task_instruction": WORLD_AUDIT_INSTRUCTION,
            "context": json.dumps(
                {"scene_text": scene_text, **review_context}, ensure_ascii=False
            ),
        }
    if grouped and source_errors:
        spec, input_chars = None, 0
    else:
        request, schema = build_group_audit_request(**scope)
        spec = request_spec(request, schema)
        input_chars = sum(
            len(message.get("content") or "") for message in spec["request"]["messages"]
        )
    frozen_scope = {
        **scope,
        "sources": [
            {
                **item.__dict__,
                "dimensions": list(item.dimensions),
            }
            for item in scope["sources"]
        ],
    }
    return {
        "group_id": content_hash({"members": members, "group_key": scope["group_key"]})[
            :20
        ],
        "members": members,
        "identity_refs": sorted(refs),
        "query_keys": [list(item) for item in sorted(query_keys)],
        "required_refs": sorted(required_refs),
        "apply_query_keys": [list(item) for item in sorted(apply_query_keys)],
        "candidate_count": len(members),
        "audit_input_chars": input_chars,
        "spec": spec,
        "scope": frozen_scope,
        "source_read_set": list(source_intervals.values()),
        "deferred_reason": source_errors[0] if source_errors else None,
    }


def prepare_world_audit_groups(*, payload, source, run, novel_id, attempt_id):
    """Freeze bounded per-identity audits only for the model with a measured cap."""
    prepared = payload["relations_preparation"]
    world, relations, context = (
        prepared["world"],
        payload.get("scene_relations", {}).get(
            "result", {"aliases": [], "relations": [], "uncertain_items": []}
        ),
        prepared["context"],
    )
    initial = payload["world_preparation"]["context"]
    model = ((run.llm_snapshot_json or {}).get("profile") or {}).get("model")
    native = payload.get("world_version") == 3
    if model not in DEEPSEEK_THINKING_MODELS and not native:
        members = [
            {"path": path, "index": index}
            for path, items in (
                ("entities", world.get("entities", [])),
                ("delta_events", world.get("delta_events", [])),
                ("world_uncertain_items", world.get("uncertain_items", [])),
                ("aliases", relations.get("aliases", [])),
                ("relations", relations.get("relations", [])),
                ("relation_uncertain_items", relations.get("uncertain_items", [])),
            )
            for index, _ in enumerate(items)
        ]
        group = _make_world_audit_group(
            members=members,
            world=world,
            relations=relations,
            context=context,
            initial_context=initial,
            source=source,
            scene_text=payload["scene_text"],
            novel_id=novel_id,
            attempt_id=attempt_id,
            grouped=False,
        )
        return {"version": "full-package-v1", "groups": [group]}

    def over_capacity(group):
        if native and group["spec"]:
            from modules.evolution.input_budget import fits

            return not fits(
                run.llm_snapshot_json, "scene_world_review_group", group["spec"]
            )
        return group["audit_input_chars"] > WORLD_AUDIT_INPUT_CHAR_LIMIT

    units_by_component = _world_claim_units(world, relations, context)
    groups = []
    for component in units_by_component:
        current = []
        for unit in component:
            candidate = [*current, unit]
            group = _make_world_audit_group(
                members=candidate,
                world=world,
                relations=relations,
                context=context,
                initial_context=initial,
                source=source,
                scene_text=payload["scene_text"],
                novel_id=novel_id,
                attempt_id=attempt_id,
                grouped=True,
            )
            if group["deferred_reason"]:
                if current:
                    groups.append(
                        _make_world_audit_group(
                            members=current,
                            world=world,
                            relations=relations,
                            context=context,
                            initial_context=initial,
                            source=source,
                            scene_text=payload["scene_text"],
                            novel_id=novel_id,
                            attempt_id=attempt_id,
                            grouped=True,
                        )
                    )
                    current = []
                group = _make_world_audit_group(
                    members=[unit],
                    world=world,
                    relations=relations,
                    context=context,
                    initial_context=initial,
                    source=source,
                    scene_text=payload["scene_text"],
                    novel_id=novel_id,
                    attempt_id=attempt_id,
                    grouped=True,
                )
                group["spec"] = None
                group["deferred_reason"] = (
                    group["deferred_reason"] or "source_unavailable"
                )
                groups.append(group)
                continue
            if over_capacity(group):
                if current:
                    groups.append(
                        _make_world_audit_group(
                            members=current,
                            world=world,
                            relations=relations,
                            context=context,
                            initial_context=initial,
                            source=source,
                            scene_text=payload["scene_text"],
                            novel_id=novel_id,
                            attempt_id=attempt_id,
                            grouped=True,
                        )
                    )
                    current = []
                group = _make_world_audit_group(
                    members=[unit],
                    world=world,
                    relations=relations,
                    context=context,
                    initial_context=initial,
                    source=source,
                    scene_text=payload["scene_text"],
                    novel_id=novel_id,
                    attempt_id=attempt_id,
                    grouped=True,
                )
                if over_capacity(group):
                    group["spec"] = None
                    group["deferred_reason"] = "candidate_over_capacity"
                    groups.append(group)
                else:
                    current = [unit]
                continue
            current = candidate
        if current:
            groups.append(
                _make_world_audit_group(
                    members=current,
                    world=world,
                    relations=relations,
                    context=context,
                    initial_context=initial,
                    source=source,
                    scene_text=payload["scene_text"],
                    novel_id=novel_id,
                    attempt_id=attempt_id,
                    grouped=True,
                )
            )
    groups.sort(key=lambda item: item["group_id"])
    return {
        "version": "object-source-token-groups-v2"
        if native
        else "object-source-groups-v1",
        "groups": groups,
        **({"context_snapshot": deepcopy(run.llm_snapshot_json)} if native else {}),
    }


def world_group_apply_inputs(result, group, resolved_new_refs=()):
    """Project only one passed audit group into the existing adoption gate."""
    selected = {(item["path"], item["index"]) for item in group["members"]}
    world = result["world"]
    relations = result["relations"]
    original_context = result["context"]
    original_new_refs = original_context.get("_new_entity_refs") or {}
    original_new_ids = original_context.get("_new_entity_ids") or {}
    refs = set(group.get("identity_refs", []))
    required_refs = set(group.get("required_refs", refs))
    resolved = set(resolved_new_refs) & required_refs
    selected_entity_refs = {
        ref for ref, index in original_new_refs.items() if ("entities", index) in selected
    }
    required_new_refs = required_refs & set(original_new_refs)
    if required_new_refs - selected_entity_refs - resolved:
        return None

    entities = []
    for index, item in enumerate(world.get("entities", [])):
        if ("entities", index) in selected:
            entities.append(item)
        else:
            entities.append(
                {
                    **item,
                    "suggested_action": "ignore",
                    "summary": "",
                    "public_info": "",
                    "hidden_truth": "",
                    "quote": None,
                    "evidence_quotes": [],
                    "field_evidence": {},
                    "aliases": None,
                }
            )
    scoped_world = {
        "entities": entities,
        "delta_events": [
            item
            for index, item in enumerate(world.get("delta_events", []))
            if ("delta_events", index) in selected
        ],
        "uncertain_items": [
            item
            for index, item in enumerate(world.get("uncertain_items", []))
            if ("world_uncertain_items", index) in selected
        ],
    }
    scoped_relations = {
        key: [
            item
            for index, item in enumerate(relations.get(key, []))
            if (member_key, index) in selected
        ]
        for key, member_key in (
            ("aliases", "aliases"),
            ("relations", "relations"),
            ("uncertain_items", "relation_uncertain_items"),
        )
    }
    context = deepcopy(original_context)
    query_keys = {
        tuple(item) for item in group.get("apply_query_keys", group.get("query_keys", []))
    }
    query_keys.update(
        (item.get("entity_type"), item.get("name"))
        for index, item in enumerate(world.get("entities", []))
        if ("entities", index) in selected
    )
    for ref in resolved:
        index = original_new_refs.get(ref)
        if index is None or ref not in original_new_ids:
            continue
        entity = world["entities"][index]
        entity_id = original_new_ids[ref]
        query_keys.add((entity.get("entity_type"), entity.get("name")))
        context.setdefault("_entity_ref_map", {})[ref] = str(entity_id)
        identity_candidates = context.get("identity_candidates", [])
        if not any(item.get("prompt_ref") == ref for item in identity_candidates):
            context.setdefault("identity_candidates", []).append(
                {
                    "prompt_ref": ref,
                    "name": entity["name"],
                    "entity_type": entity["entity_type"],
                    "aliases": [],
                }
            )
    resolved_identity = {
        (
            world["entities"][original_new_refs[ref]].get("entity_type"),
            world["entities"][original_new_refs[ref]].get("name"),
        ): [
            (
                str(original_new_ids[ref]),
                world["entities"][original_new_refs[ref]].get("name"),
            )
        ]
        for ref in resolved
        if ref in original_new_refs and ref in original_new_ids
    }
    for key in ("_identity_queries", "_initial_identity_queries"):
        if key in context:
            context[key] = [
                {
                    **item,
                    "matches": resolved_identity.get(
                        (item.get("entity_type"), item.get("name")),
                        item.get("matches", []),
                    ),
                }
                for item in context[key]
                if (item.get("entity_type"), item.get("name")) in query_keys
            ]
    context["_new_entity_refs"] = {
        ref: index
        for ref, index in original_new_refs.items()
        if ref in selected_entity_refs and ref not in resolved
    }
    context["_new_entity_ids"] = {
        ref: entity_id
        for ref, entity_id in original_new_ids.items()
        if ref in context["_new_entity_refs"]
    }
    context["_entity_ref_map"] = {
        ref: entity_id
        for ref, entity_id in context.get("_entity_ref_map", {}).items()
        if ref in required_refs
    }
    context["identity_candidates"] = [
        item
        for item in context.get("identity_candidates", [])
        if item.get("prompt_ref") in required_refs
    ]
    context["_identity_queries"] = [
        item
        for item in context.get("_identity_queries", [])
        if (item.get("entity_type"), item.get("name")) in query_keys
    ]
    if "_initial_identity_queries" in context:
        context["_initial_identity_queries"] = [
            item
            for item in context["_initial_identity_queries"]
            if (item.get("entity_type"), item.get("name")) in query_keys
        ]
    if "relation_candidates" in context:
        context["relation_candidates"] = [
            item
            for item in context["relation_candidates"]
            if item.get("source_ref") in refs and item.get("target_ref") in refs
        ]
    return {
        "world": scoped_world,
        "relations": scoped_relations,
        "context": context,
        "review": {"status": "passed"},
    }


async def freeze_value(db, store, frozen, key, prepare):
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    if key not in frozen.payload:
        value = await prepare(frozen.payload)
        frozen = frozen.model_copy(update={"payload": {**frozen.payload, key: value}})
        await store.replace_frozen_payload(frozen)
    await db.commit()
    return frozen


async def finish_scene_world(db, store, frozen, source, call):
    if frozen.payload.get("world_version", 0) not in {1, 2, 3} or frozen.payload.get(
        "world_result"
    ):
        return frozen
    from modules.evolution.pipeline import _run_scene_call

    async def prepare_world(payload):
        terms = [
            (mention["entity_type"], mention["surface"])
            for item in payload["compiled_observations"]
            for mention in item["mentions"]
            if mention.get("entity_type")
        ]
        context = await imports.prepare_scene_world_context(db, frozen.novel_id, terms)
        context.update(
            committed_parent=semantic_manifest(payload["input_manifest"]),
            _current_scene_text=payload["scene_text"],
        )
        return {
            "context": context,
            "call": request_spec(
                *imports.build_scene_world_request(payload["scene_text"], context)
            ),
        }

    frozen = await freeze_value(db, store, frozen, "world_preparation", prepare_world)

    async def execute(**inputs):
        return await call("execute_world_request", **inputs)

    async def run_call(current, key, spec, *, method=None):
        return await _run_scene_call(
            db,
            store,
            current,
            source,
            journal_key=key,
            inputs={
                "method": method or f"imports.{key}.v1",
                "attempt_id": frozen.attempt_id,
                "source_manifest_hash": frozen.source_manifest_hash,
                "previous_receipt": frozen.previous_receipt,
                **spec,
            },
            call_inputs=spec,
            call=execute,
            session_gate=getattr(call, "session_gate", None),
        )

    from modules.evolution.state_review import SceneCallFailedError

    try:
        frozen = await run_call(
            frozen, "scene_world", frozen.payload["world_preparation"]["call"]
        )
    except SceneCallFailedError as error:
        if not _known_format_failure(error):
            raise

        async def defer_world(payload):
            return _deferred_world_result(
                payload["world_preparation"]["context"], "世界资料抽取"
            )

        return await freeze_value(db, store, frozen, "world_result", defer_world)

    async def prepare_relations(payload):
        first = payload["world_preparation"]["context"]
        world = imports.materialize_scene_world(
            payload["scene_text"], first, payload["scene_world"]["result"]
        )
        terms = [
            (item["entity_type"], item["name"]) for item in first["_identity_queries"]
        ]
        terms += [(item["entity_type"], item["name"]) for item in world["entities"]]
        context = await imports.prepare_scene_world_context(db, frozen.novel_id, terms)
        context.update(
            committed_parent=semantic_manifest(payload["input_manifest"]),
            _current_scene_text=payload["scene_text"],
        )
        context["_initial_identity_queries"] = first["_identity_queries"]
        context = imports.prepare_scene_relations_context(context, world)
        if payload["world_version"] in {2, 3}:
            context.update(await relation_history(store, frozen, context))
        if payload["world_version"] in {2, 3}:
            context["_new_entity_ids"] = {
                ref: str(
                    uuid5(
                        NAMESPACE_URL,
                        json.dumps(
                            [
                                "evolution:world",
                                frozen.novel_id,
                                frozen.run_id,
                                frozen.attempt_id,
                                ref,
                            ]
                        ),
                    )
                )
                for ref in context["_new_entity_refs"]
            }
        return {
            "context": context,
            "world": world,
            "call": request_spec(
                *imports.build_scene_relations_request(payload["scene_text"], context)
            )
            if context["identity_candidates"]
            else None,
        }

    frozen = await freeze_value(
        db, store, frozen, "relations_preparation", prepare_relations
    )
    prepared = frozen.payload["relations_preparation"]
    if prepared["call"]:
        try:
            frozen = await run_call(frozen, "scene_relations", prepared["call"])
        except SceneCallFailedError as error:
            if not _known_format_failure(error):
                raise

            async def defer_relations(payload):
                return _deferred_world_result(
                    payload["relations_preparation"]["context"], "别名关系抽取"
                )

            return await freeze_value(db, store, frozen, "world_result", defer_relations)
    relations = (frozen.payload.get("scene_relations") or {}).get(
        "result", {"aliases": [], "relations": [], "uncertain_items": []}
    )
    has_claims = any(
        prepared["world"].get(key) for key in ("entities", "delta_events")
    ) or any(relations.get(key) for key in ("aliases", "relations"))
    if has_claims:

        async def prepare_review(payload):
            run = await store.load_run(frozen.run_id)
            return prepare_world_audit_groups(
                payload=payload,
                source=source,
                run=run,
                novel_id=frozen.novel_id,
                attempt_id=frozen.attempt_id,
            )

        frozen = await freeze_value(
            db, store, frozen, "world_review_preparation", prepare_review
        )
        spec = frozen.payload["world_review_preparation"]
        if spec != await prepare_review(frozen.payload):
            raise ConflictError(
                "世界审查冻结范围或方法已变化，旧结果保留且不能重新盖章",
                code="scene_world_review_scope_changed",
            )
        from modules.evolution.pipeline import SamplePendingReconciliationError
        from modules.evolution.state_review import settled_output_failure

        # Validate every persisted review before admitting any independent peer.
        for planned in spec["groups"]:
            key = f"scene_world_review_group_{planned['group_id']}"
            journal = frozen.payload.get(key) or {}
            if (
                journal
                and journal.get("stage") != "sampled"
                and not settled_output_failure(journal)
            ):
                raise SamplePendingReconciliationError(
                    key, "preserve original world review"
                )
            if journal and journal.get("input_hash") != content_hash(
                {
                    "method": "imports.scene_world_review.group.v3",
                    "attempt_id": frozen.attempt_id,
                    "source_manifest_hash": frozen.source_manifest_hash,
                    "previous_receipt": frozen.previous_receipt,
                    **planned["spec"],
                }
            ):
                raise ConflictError("世界审查冻结输入已变化")
        from modules.evolution.ready import drain_ready
        from modules.evolution.state_review import (
            SceneCallFailedError,
            settled_output_failure,
        )
        from modules.evolution.store import BudgetExhaustedError

        async def audit(planned):
            key = f"scene_world_review_group_{planned['group_id']}"
            if planned.get("deferred_reason"):
                return
            journal = frozen.payload.get(key) or {}
            if journal.get("stage") == "sampled" or settled_output_failure(journal):
                return
            try:
                await run_call(
                    frozen,
                    key,
                    planned["spec"],
                    method="imports.scene_world_review.group.v3",
                )
            except BudgetExhaustedError:
                return
            except SceneCallFailedError as error:
                if not settled_output_failure(
                    {"stage": "failed", "paid_call_receipt": error.receipt}
                ):
                    raise

        parallelism = getattr(call, "discovery_parallelism", 1)
        if parallelism > 1:
            await drain_ready(
                [partial(audit, group) for group in spec["groups"]], parallelism
            )
            frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        review_groups = []
        budget_exhausted = False
        for planned in spec["groups"]:
            group = {
                key: planned[key]
                for key in (
                    "group_id",
                    "members",
                    "identity_refs",
                    "query_keys",
                    "required_refs",
                    "apply_query_keys",
                    "candidate_count",
                    "audit_input_chars",
                )
            }
            journal_key = f"scene_world_review_group_{planned['group_id']}"
            journal = frozen.payload.get(journal_key) or {}
            if planned.get("deferred_reason"):
                group.update(
                    status="blocked",
                    review_kind=planned["deferred_reason"],
                    issues=[{"message": _world_group_issue(planned["deferred_reason"])}],
                )
                review_groups.append(group)
                continue
            if journal.get("stage") == "failed":
                if not settled_output_failure(journal):
                    from modules.evolution.pipeline import (
                        SamplePendingReconciliationError,
                    )

                    raise SamplePendingReconciliationError(
                        journal_key,
                        "审查调用费用未核清，先核对请求与费用，不能继续推进",
                    )
                group.update(
                    status="blocked",
                    review_kind="audit_failed",
                    issues=[{"message": _world_group_issue("audit_failed")}],
                )
                review_groups.append(group)
                continue
            if budget_exhausted and journal.get("stage") != "sampled":
                group.update(
                    status="blocked",
                    review_kind="budget_exhausted",
                    issues=[{"message": _world_group_issue("budget_exhausted")}],
                )
                review_groups.append(group)
                continue
            if journal.get("stage") != "sampled":
                try:
                    frozen = await run_call(
                        frozen,
                        journal_key,
                        planned["spec"],
                        method="imports.scene_world_review.group.v3",
                    )
                except BudgetExhaustedError:
                    budget_exhausted = True
                    group.update(
                        status="blocked",
                        review_kind="budget_exhausted",
                        issues=[{"message": _world_group_issue("budget_exhausted")}],
                    )
                    review_groups.append(group)
                    continue
                except SceneCallFailedError:
                    frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
                    if not settled_output_failure(frozen.payload.get(journal_key) or {}):
                        raise
                    group.update(
                        status="blocked",
                        review_kind="audit_failed",
                        issues=[{"message": _world_group_issue("audit_failed")}],
                    )
                    review_groups.append(group)
                    continue
            journal = frozen.payload.get(journal_key) or {}
            group_review = materialize_world_audit_group(planned, journal["result"])
            group.update(
                status=group_review["status"],
                review_kind=(
                    "completed" if group_review["status"] == "passed" else "blocked"
                ),
                review=group_review,
                issues=group_review.get("issues", []),
            )
            review_groups.append(group)
        issues = [issue for group in review_groups for issue in group.get("issues", [])]
        all_passed = all(group["status"] == "passed" for group in review_groups)
        review = {
            "status": "passed" if all_passed else "blocked",
            "review_kind": (
                "grouped_audit"
                if all_passed
                else "capacity_deferred"
                if review_groups
                and all(
                    group["review_kind"]
                    in {
                        "candidate_over_capacity",
                        "source_occurrence_limit",
                        "source_range_unavailable",
                        "source_quote_not_found",
                    }
                    for group in review_groups
                )
                else "partial_group_review"
            ),
            "audit_input_chars": sum(
                group["audit_input_chars"] for group in review_groups
            ),
            "groups": review_groups,
            "issues": issues,
        }
    else:
        review = None

    async def finish(payload):
        return {
            "world": prepared["world"],
            "relations": relations,
            "context": prepared["context"],
            "review": review,
        }

    return await freeze_value(db, store, frozen, "world_result", finish)


async def relation_history(store, frozen, context):
    """Only actual committed prefix rows may contribute historical relation text."""
    from modules.evolution.contracts import EvolutionReceipt

    refs = {entity_id: ref for ref, entity_id in context["_entity_ref_map"].items()}
    pairs = await store.load_committed_pairs(
        frozen.run_id, descending=True, limit=64, relation_entity_ids=list(refs)
    )
    candidates, mapping = [], {}
    for receipt_row, row in pairs:
        if receipt_row.committed_scene_index >= frozen.payload["scene_index"]:
            continue
        receipt = EvolutionReceipt.model_validate(receipt_row.receipt_json)
        saved = {
            item["id"]
            for item in receipt.world_result_refs
            if item["type"] == "entity_relation"
        }
        for relation in row.payload_json.get("world_materialization", {}).get(
            "relations", []
        ):
            if relation["id"] not in saved or relation["novel_id"] != frozen.novel_id:
                continue
            if relation["source_id"] not in refs or relation["target_id"] not in refs:
                continue
            ref = f"relation_{relation['id']}"
            if ref in mapping:
                continue
            candidates.append(
                {
                    "prompt_ref": ref,
                    "source_ref": refs[relation["source_id"]],
                    "target_ref": refs[relation["target_id"]],
                    **{
                        key: relation[key]
                        for key in (
                            "relation_type",
                            "relation_kind",
                            "description",
                            "quote",
                            "status",
                            "claim_status",
                            "directionality",
                        )
                    },
                    "scene_index": receipt_row.committed_scene_index,
                    "source_receipt": {
                        "run_key": receipt.run_id,
                        "attempt_id": receipt.attempt_id,
                    },
                }
            )
            mapping[ref] = {
                key: relation[key]
                for key in (
                    "id",
                    "novel_id",
                    "source_id",
                    "target_id",
                    "relation_type",
                )
            }
    return {
        "relation_candidates": candidates,
        "relation_history_scope": (
            "最近至多64个相关已提交场景；缺少前例不能据此断言首次建立"
        ),
        "_relation_ref_map": mapping,
    }


def bind_scene_identities(payload):
    """Bind only independently reviewed, same-Scene candidates before state review."""
    from modules.evolution.state_gate import gate_scene_events

    world = payload["world_result"]
    observations = deepcopy(payload["compiled_observations"])
    context = world["context"]
    new_ids = context.get("_new_entity_ids", {})
    review = world.get("review") or {}
    if review.get("groups"):
        new_refs = context.get("_new_entity_refs", {})
        passed_refs = {
            ref
            for group in review["groups"]
            if group.get("status") == "passed"
            for ref in group.get("identity_refs", [])
            if ref in new_refs
            and {"path": "entities", "index": new_refs[ref]} in group.get("members", [])
        }
    else:
        passed_refs = set(new_ids) if review.get("status") == "passed" else set()
    candidates = {
        (item["entity_type"], item["name"]): new_ids[item["prompt_ref"]]
        for item in context["identity_candidates"]
        if item["prompt_ref"] in passed_refs and item["prompt_ref"] in new_ids
    }
    resolutions, outcomes = [], {}
    for observation in observations:
        for mention in observation["mentions"]:
            entity_id = candidates.get((mention["entity_type"], mention["surface"]))
            resolution = mention.get("resolution")
            if entity_id and (resolution or {}).get("outcome") in {None, "new_candidate"}:
                resolution = mention["resolution"] = {
                    "mention_id": mention["mention_id"],
                    "surface": mention["surface"],
                    "outcome": "reuse",
                    "resolved_entity_id": entity_id,
                    "rationale": "本场独立审查通过的新候选，身份与状态须同事务提交",
                }
            if resolution:
                resolutions.append(resolution)
                outcome = resolution["outcome"]
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
        attribution = observation.get("utterance_attribution") or {}
        speaker = attribution.get("speaker_resolution") or {}
        speaker_surface = attribution.get("speaker_surface")
        if (
            attribution.get("kind") == "direct_dialogue"
            and speaker_surface
            and speaker.get("outcome") in {None, "new_candidate"}
        ):
            speaker_identities = {
                mention["resolution"]["resolved_entity_id"]
                for mention in observation["mentions"]
                if mention.get("surface") == speaker_surface
                and mention.get("entity_type") == "character"
                and (mention.get("resolution") or {}).get("outcome") == "reuse"
                and mention["resolution"].get("resolved_entity_id")
            }
            if len(speaker_identities) == 1:
                attribution["speaker_resolution"] = dict(
                    next(
                        mention["resolution"]
                        for mention in observation["mentions"]
                        if mention.get("surface") == speaker_surface
                        and mention.get("entity_type") == "character"
                        and (mention.get("resolution") or {}).get("outcome") == "reuse"
                        and mention["resolution"].get("resolved_entity_id")
                    )
                )
    applied, gated = gate_scene_events(payload["proposed_scene_events"], observations)
    return {
        "compiled_observations": observations,
        "identity_resolutions": resolutions,
        "identity_outcomes": outcomes,
        "scene_events": applied,
        "gated_scene_events": gated,
    }

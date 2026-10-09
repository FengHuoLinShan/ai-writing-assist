"""S4 按预算编译的确定性裁剪契约（M1 契约 S3/S4 拆分）。

固定 continue/break 两类让位语义、必需项优先与同材料多预算复用；
这些是切片 3 持久缓存「完整材料按次重编译」的行为前提。
"""

from infrastructure.llm.token_estimation import estimate_token_count
from modules.evidence.compilation.services.interaction_source_material import (
    InteractionSourceMaterial,
    compile_source_material,
    excerpt_block,
    identity_block,
    reference_block,
)


def _read(title: str, text: str, chapter: int = 1) -> dict:
    return {
        "title": title,
        "text": text,
        "source_ref": {
            "draft_id": f"draft-{title}",
            "chapter_index": chapter,
            "start_offset": 0,
            "end_offset": len(text),
        },
    }


def _material() -> InteractionSourceMaterial:
    reference_blocks = {
        "player": reference_block(
            {"label": "角色甲", "entity_type": "character"}, "玩家身份"
        ),
        "pinned": reference_block({"label": "灯塔", "entity_type": "location"}, "已固定"),
        "optA": reference_block(
            {"label": "超长资料" + "细节" * 500, "entity_type": "item"}, "本轮提到"
        ),
        "optB": reference_block(
            {"label": "雾渡港", "entity_type": "location"}, "本轮提到"
        ),
    }
    player_read = _read("第一章", "角色甲推开仓库门。")
    return InteractionSourceMaterial(
        identity_block=identity_block(
            {"chapter_title": "第一章", "label": "开局"}, {"label": "玩家"}
        ),
        reference_order=("player", "pinned", "optA", "optB"),
        mandatory_keys=frozenset({"player", "pinned"}),
        reference_blocks=reference_blocks,
        reference_reasons={
            "player": "玩家身份",
            "pinned": "已固定",
            "optA": "本轮提到",
            "optB": "本轮提到",
        },
        reference_labels={
            "player": "角色甲",
            "pinned": "灯塔",
            "optA": "超长资料",
            "optB": "雾渡港",
        },
        knowledge_block="",
        mandatory_reads=(player_read,),
        excerpt_reads=(
            _read("第二章", "超长证据" + "正文" * 300),
            _read("第三章", "短证据。"),
        ),
        warnings=("w1",),
    )


def _tokens(*blocks: str) -> int:
    return estimate_token_count("\n\n".join(blocks))


def test_mandatory_blocks_keep_priority_and_order() -> None:
    material = _material()
    budget = _tokens(
        material.identity_block,
        material.reference_blocks["player"],
        material.reference_blocks["pinned"],
        excerpt_block(material.mandatory_reads[0]),
    )

    packet = compile_source_material(material, budget_tokens=budget)

    assert packet.blockers == ()
    assert "角色甲" in packet.rendered
    assert "灯塔" in packet.rendered
    assert "超长资料" not in packet.rendered
    assert "雾渡港" not in packet.rendered
    assert [item["reference_key"] for item in packet.included_refs[:2]] == [
        "player",
        "pinned",
    ]
    assert packet.included_refs[-1]["reason"] == "原文片段关联"
    assert list(packet.source_refs) == [dict(material.mandatory_reads[0]["source_ref"])]


def test_optional_references_overflow_skips_but_continues() -> None:
    material = _material()
    mandatory_base = [
        material.identity_block,
        material.reference_blocks["player"],
        material.reference_blocks["pinned"],
        excerpt_block(material.mandatory_reads[0]),
    ]
    budget = _tokens(*mandatory_base, material.reference_blocks["optB"])

    packet = compile_source_material(material, budget_tokens=budget)

    assert packet.blockers == ()
    assert "超长资料" not in packet.rendered
    assert "雾渡港" in packet.rendered
    assert "雾渡港" in {item["label"] for item in packet.included_refs}


def test_excerpt_overflow_stops_all_later_excerpts() -> None:
    material = _material()
    mandatory_base = [
        material.identity_block,
        material.reference_blocks["player"],
        material.reference_blocks["pinned"],
        excerpt_block(material.mandatory_reads[0]),
    ]
    budget = _tokens(*mandatory_base, material.reference_blocks["optB"])
    budget += _tokens(excerpt_block(material.excerpt_reads[1]))

    packet = compile_source_material(material, budget_tokens=budget)

    assert packet.blockers == ()
    assert "超长证据" not in packet.rendered
    # 可选资料是 continue 语义，原文证据是 break 语义：长证据挡住后续短证据。
    assert "短证据" not in packet.rendered
    assert list(packet.source_refs) == [dict(material.mandatory_reads[0]["source_ref"])]


def test_mandatory_overflow_blocks_with_empty_packet() -> None:
    packet = compile_source_material(_material(), budget_tokens=8)

    assert packet.rendered == ""
    assert packet.included_refs == ()
    assert packet.source_refs == ()
    assert packet.blockers == ("已固定的作品资料超出可用篇幅，请减少固定项",)


def test_same_material_compiles_per_budget_without_reordering() -> None:
    material = _material()
    tight = _tokens(
        material.identity_block,
        material.reference_blocks["player"],
        material.reference_blocks["pinned"],
        excerpt_block(material.mandatory_reads[0]),
    )
    roomy = _tokens(
        material.identity_block,
        material.reference_blocks["player"],
        material.reference_blocks["pinned"],
        material.reference_blocks["optB"],
        excerpt_block(material.mandatory_reads[0]),
        excerpt_block(material.excerpt_reads[0]),
    )

    small = compile_source_material(material, budget_tokens=tight)
    large = compile_source_material(material, budget_tokens=roomy)

    # 去掉外层 fence 后比较：小预算包是大预算包的块级前缀
    small_body = small.rendered.removesuffix("\n</SOURCE_REFERENCE_DATA>")
    assert small_body in large.rendered
    assert "雾渡港" not in small.rendered
    assert "雾渡港" in large.rendered
    assert large.rendered.index("角色甲") < large.rendered.index("灯塔")
    assert large.rendered.index("灯塔") < large.rendered.index("雾渡港")

"""组合根操作注册表等价性快照（AO-5 第二批 / ADR-0031）。

领域插件文件自 AO-5 第二批起只导出纯数据 ``OPERATIONS_SPEC``，由
``app/assistant_operation_registry`` 物化为 ``AssistantOperation`` 后经
``app.bootstrap`` 注册。本测试把注册产物的运行期契约（操作名集合、label、
permission、revision、参数 schema 指纹）钉住：任何字段漂移都会失败，
改动必须是有意识的契约变更并同步本快照。快照取自解环前工作树
（109d8af97，AO-5 第一批之后）的 ``assistant.operations`` 实测值，两边
逐字段 diff 为零（含 prepare/apply/read_result 函数对象与完整 JSON
schema）。
"""

from core.container import reset
from modules.assistant.evidence_tools import fingerprint


def setup_function():
    reset()


def teardown_function():
    reset()


# name → (label, permission, revision, schema_json_schema 指纹)
OPERATION_SNAPSHOT = {
    "world.add_alias": (
        "附加对象别名",
        "confirm",
        "1",
        "ba5d3367f14ed5297574749dc2d8c639ccc83ac62b9c14fbbe61884a3498fb43",
    ),
    "world.add_relation": (
        "连接已有对象",
        "confirm",
        "1",
        "df03981f85c9d9d6f24039046687367030e2234eb7b16b17dfd91dc53b4fc81c",
    ),
    "world.adopt_package": (
        "采用已核对的世界资料方案",
        "confirm",
        "1",
        "4eaea77a15fcf5c31f74cdeda84647fa261c3cb83c9ca61a3e6cae1ec69df876",
    ),
    "world.create_entity": (
        "创建世界对象",
        "confirm",
        "1",
        "4e6c3c0e2d6d0688cc57eed99a388b5f975d80ce044748f38901a8815e2a107c",
    ),
    "world.edit_entity": (
        "修改世界对象",
        "confirm",
        "1",
        "c64528871690a5431612f666e727b92127e5933a164e784df4d543501b02d67f",
    ),
    "world.create_page_draft": (
        "保存世界资料工作稿",
        "confirm",
        "1",
        "adf52616c8a6a8c66826d45fb87c1f1bfc507055053aefde7f77fe1e34338662",
    ),
    "project.scan_duplicates": (
        "查找相似资料",
        "suggest",
        "1",
        "aab4f9e80bef684e524a4cce03b46a747abd0e26a97bc46af9f80b1182ac13b3",
    ),
    "story.edit_information_plan": (
        "修改伏笔与揭示安排",
        "confirm",
        "1",
        "4356fc8a1aaa4cb44b3538e9179fb5ab641eb607a24549bafcfedae031f1b3fe",
    ),
    "world.edit_page_draft": (
        "编辑资料标题、正文与条目",
        "confirm",
        "1",
        "050e26916e41e552914a0536a74c56ce66e7ff6e848d9b20d3ebb272fc1cc213",
    ),
    "world.publish_page_draft": (
        "发布资料工作稿",
        "confirm",
        "1",
        "b8236d9a66ca813f4528b88ee6f65c84c1139638c2048df53d4313646916254e",
    ),
    "world.restore_page_revision": (
        "从资料历史继续编辑",
        "confirm",
        "1",
        "5e3ad91dee2f847c59c7b453e750ef3ed71c2942dad7437dbbe36f4f39b07607",
    ),
    "world.prepare_package": (
        "准备可独立校验和采用的世界资料包",
        "confirm",
        "1",
        "42b2183da68724b39e41c56d22f337270807642b6e431a05ef25b8610dc21a4b",
    ),
    "world.apply_page_suggestion": (
        "将整页建议保存为工作稿",
        "confirm",
        "1",
        "1de6c4e1720b36854c02f74e9ed1580db8290f03556e2bf6a6dcc5e811594eb0",
    ),
    "world.save_checkpoint": (
        "保存并继续世界讨论阶段成果",
        "confirm",
        "1",
        "0fd055177fa681b753c95fc0c0e1137d736edda7f719ddf148c50f3089860b00",
    ),
    "writing.review_team": (
        "复核深度审稿调查线索",
        "suggest",
        "1",
        "39150f2e6baff8344fad5613b38d4fea3af1dd53ce0b9a3f8db429f1a77433d4",
    ),
    "writing.review_world": (
        "核对人工正文与世界设定（不签署人物知识边界）",
        "suggest",
        "1",
        "0583d7f90da0a2808b53cc158ee2ecaed4e1acb1c53551d36cba6f7ebf8c927b",
    ),
    "writing.new_chapter": (
        "追加章节工作稿",
        "confirm",
        "1",
        "cc3db9d799dfa422e9412ddda17fa420cd8a6bba6195df20b10e8d8480f7838e",
    ),
    "writing.review": (
        "独立审查正文",
        "suggest",
        "1",
        "0583d7f90da0a2808b53cc158ee2ecaed4e1acb1c53551d36cba6f7ebf8c927b",
    ),
    "writing.revise": (
        "按精确范围修订正文",
        "confirm",
        "1",
        "ea9a26eb790d2a9fb4896afce382232ebfb9e6cb380e153d87c3cea9abf61faf",
    ),
    "writing.generate_candidate": (
        "生成或续写正文候选",
        "suggest",
        "1",
        "bb11474ad7c44b3934c63912245533a413c2a13725483298a95c19d3e810bd80",
    ),
    "writing.targeted_revision": (
        "按已选审稿问题返修",
        "suggest",
        "1",
        "3ff0b2f2a15042fc0669b2610430579c9ceb6cf21c6082cce591533f89f7c629",
    ),
    "writing.adopt_candidate": (
        "采用经过审查的正文候选",
        "confirm",
        "1",
        "d8ff7e9fce3419b468a731a5b1861eaf63853dfa825491afdb15ebca4f38af77",
    ),
    "writing.restore_version": (
        "从已采用的历史版本继续写",
        "confirm",
        "1",
        "d8ff7e9fce3419b468a731a5b1861eaf63853dfa825491afdb15ebca4f38af77",
    ),
    "project.update_task": (
        "更新或完成作者待办",
        "confirm",
        "1",
        "51e0c609c4b26d94738d7a6e6586153a521f6dedd3ea47fdfbbfdd3cc951dd9a",
    ),
    "project.add_task": (
        "记录作者待办",
        "confirm",
        "1",
        "bfdf8879b8d52dd94b18baad4cf76565d978c46ad9fe37d4b842d9535d03e7cd",
    ),
    "story.save_outline": (
        "保存并采用总纲方案",
        "confirm",
        "1",
        "ee854706b30f5852747418da229299bb0f9609ca5fb3d72283e51f310cde214f",
    ),
    "story.create_scenes": (
        "追加场景规划",
        "confirm",
        "1",
        "77c3f8ff202a8b211d06572526484664c4e1fd13cd33b5f5afb0b090d9e95708",
    ),
    "story.save_card": (
        "保存场景人物卡",
        "confirm",
        "1",
        "964adf60134153e7798d686e46b4dc7f2e49ce2bb6e375905ca0617f9263e08d",
    ),
    "story.save_script": (
        "保存场景剧本",
        "confirm",
        "1",
        "d4c90c75068daaf6a48f8c62d34ce1b8b034bd3d0d7b88e367e8a124f25d514c",
    ),
    "story.edit_scene": (
        "修改场景结构",
        "confirm",
        "1",
        "2e0b34277a7c6af8efb5eb3ba1b66ed9885fa5c010227c3b2ffe6ad37b01d706",
    ),
    "story.plan_structure": (
        "规划剧情线、篇章、场景及伏笔推进",
        "suggest",
        "1",
        "57bc974f09e872ca1843deece844435d8e2572350f2353757e67e239c2311eea",
    ),
    "story.adopt_structure": (
        "采用原结构规划包",
        "confirm",
        "1",
        "609805de188b4a2182cb52f761e6917d89d2a5d0ffcfd4f9745820cd9f2160f0",
    ),
    "story.create_information_plan": (
        "保存选定的信息安排",
        "confirm",
        "1",
        "e58229886d0365b534b111f4c46ac98a9422047979318ff97c997777aa751711",
    ),
    "story.create_thread": (
        "规划新剧情线",
        "confirm",
        "1",
        "d277eeae5b6bae9562cedf5daee9b63e51f17708ce48f86c1aefc559faefd342",
    ),
    "story.create_arc": (
        "规划新篇章",
        "confirm",
        "1",
        "2773abd0ca02ebf7173b8d2deff963ce7efa4eed6426f3728b6b1c584aca8014",
    ),
    "imports.accept_review": (
        "采用明确选中的整理结果",
        "confirm",
        "1",
        "16634c46aadd6291e8d62ba32ebf63d47bd24673a01f038484368ccd64d1d78a",
    ),
    "imports.resolve_review": (
        "查证并整理已有导入候选，只保留关键决定",
        "confirm",
        "1",
        "5170129f9bd22142d45ce62b5fef9f1c41e8fcd89a55450f8d2711a67167e686",
    ),
    "imports.complete_targets": (
        "按原范围对指定对象专项查漏",
        "confirm",
        "1",
        "10b73d9c311b6c82cc931d26c8392ddbb5a27f6c303aa320856d95e394a2d7ee",
    ),
    "imports.resume": (
        "继续原授权的整理流程",
        "confirm",
        "1",
        "645c6d6e67685c454d49c1c6ec82d55f9572689222c06c1f42e799799190e438",
    ),
    "imports.organize": (
        "整理已有正文",
        "confirm",
        "1",
        "34c80520557ecdf2a5f4296a57f4205f910d32320320d88a9e5aae022d914058",
    ),
    "evidence.focused_search": (
        "按明确问题补查当前授权作品资料",
        "confirm",
        "1",
        "9e5841f5dd78eadef581c8b0df71538072ef789e4053db583253e62ee7ac5ec6",
    ),
    "map.add_known_location": (
        "把已知地点加入地图（保留未知位置）",
        "confirm",
        "1",
        "7dbb5c4b7f4103786255067bbe3fc9540bb42246d6631dbcf66237facc49a206",
    ),
    "map.edit_feature_label": (
        "修改图元名称或备注",
        "confirm",
        "1",
        "0be10bad381f6bc9680d60ff4be7e9eda7c9b068046cbb3ac940b0a88163b150",
    ),
    "map.create_node": (
        "创建空白地图",
        "confirm",
        "1",
        "061686f1c3f683f833a391f1515de6fea596a0403a38f357390d53b5bc54e5e7",
    ),
    "map.review_revision": (
        "处理已有地图版本",
        "confirm",
        "1",
        "d91dc3adc0b113d0daffdfb3a5fd3aaf95235adfca2eb68b228346caf99c1e98",
    ),
    "world.review": (
        "复核世界资料",
        "suggest",
        "1",
        "34140fb9d80c080108ed1dcf0467636f5fa31c3bb076e830a1f6648711683a7f",
    ),
}


def test_bootstrap_operation_catalog_matches_snapshot():
    from app.bootstrap import register_container_services
    from core.container import get

    register_container_services()
    catalog = get("assistant.operations")
    assert set(catalog) == set(OPERATION_SNAPSHOT)
    mismatches = {
        name: {
            "actual": (
                operation.label,
                operation.permission,
                operation.revision,
                fingerprint(operation.schema.model_json_schema()),
            ),
            "expected": OPERATION_SNAPSHOT[name],
        }
        for name, operation in catalog.items()
        if (
            operation.label,
            operation.permission,
            operation.revision,
            fingerprint(operation.schema.model_json_schema()),
        )
        != OPERATION_SNAPSHOT[name]
    }
    assert not mismatches, mismatches


def test_registry_materializes_spec_fields_and_rejects_unknown_fields():
    import pytest

    from app.assistant_operation_registry import (
        project_dedup_operations,
        writing_operations,
    )
    from modules.assistant.contracts import AssistantOperation

    revise = writing_operations["writing.revise"]
    assert isinstance(revise, AssistantOperation)
    # 纯数据 spec 的缺省字段必须落在 AssistantOperation 原默认值上。
    assert revise.permission == "confirm" and revise.read_result is None
    scan = project_dedup_operations["project.scan_duplicates"]
    assert scan.permission == "suggest" and callable(scan.read_result)

    from app.assistant_operation_registry import _materialize

    with pytest.raises(ValueError, match="未知字段"):
        _materialize({"x.bad": {"label": "坏声明", "nope": 1}})


def test_assistant_facade_di_keys_resolve():
    from app.bootstrap import register_container_services
    from core.container import get

    register_container_services()
    for key in (
        "assistant.mark_task_local_approved",
        "assistant.inspect_discussion",
        "assistant.submit_comment_proposals",
        "assistant.mark_editorial_ready",
    ):
        assert callable(get(key))

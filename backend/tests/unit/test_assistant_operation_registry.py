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
    "map.prepare_tray_placement": (
        "准备托盘地点放置入口（由作者选点）",
        "read",
        "1",
        "eb2c87e328aa537139a57b79240dc17319a67e067aad0d254705964d9ebecd48",
    ),
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
        "3",
        "49f68df03e44dbf6c08f24e4f2329850152ff0d83ab41f45e026eec8e6b96642",
    ),
    "story.adopt_structure": (
        "采用原结构规划包",
        "confirm",
        "2",
        "bab8d7f08d12fe4169d3d7888e26b5e78a66e5b5730ba2fe5a032da2f2c6a230",
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
        "657072d928d4057f92652ede400155475a7f913444bb6aebcc71b2f6a334b051",
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
    "world.draft_opening_skeleton": (
        "起草新书开篇世界观骨架",
        "suggest",
        "1",
        "253869e5f597bb89fda0767550471e2fcb4514e914096bf071d8461151f0a44b",
    ),
    "world.vocabulary.create": (
        "新增项目词条",
        "confirm",
        "1",
        "3ece646f70048936a149deee43067404dfe09b6951564b5a5dd77f417b6b3276",
    ),
    "world.vocabulary.edit": (
        "编辑或改名项目词条",
        "confirm",
        "1",
        "b0576f8867a8917fdedf7ba3c34a332749ce8cbdfdeed29370fe8441251c6115",
    ),
    "world.vocabulary.archive": (
        "归档项目词条",
        "confirm",
        "1",
        "f87f822a0f1d1c120f3fc9ab1c4eb16f5040926b5a76a8cca0984f18be1b9739",
    ),
    "world.vocabulary.restore": (
        "恢复项目词条",
        "confirm",
        "1",
        "f87f822a0f1d1c120f3fc9ab1c4eb16f5040926b5a76a8cca0984f18be1b9739",
    ),
    "world.vocabulary.merge": (
        "合并项目词条",
        "confirm",
        "1",
        "07f482189b4c1c401005405951f7aa26932d436b9fc3be341ff59c9df1cf50e4",
    ),
    "world.vocabulary.split": (
        "拆分项目词条",
        "confirm",
        "1",
        "92ee8d18bf4defcbbecd11ab70fab05f4285d3a76b602103bc89b9e251904cb6",
    ),
    "world.vocabulary.apply_presets": (
        "复制题材预设词条",
        "confirm",
        "1",
        "8067271a5b2798ef8bc6cab105941b58ac267ea3410c1cb1d5f86f67cb0e434e",
    ),
}


# Map enhancement v6 adds new names; historical entries retain their fingerprints.
OPERATION_SNAPSHOT.update(
    {
        "assistant.silence_spatial_advisory": (
            "静默这一条空间提醒",
            "confirm",
            "1",
            "f2bf04ee2fe269255a6f123b00a2c1d0803def47d99587b28a8db06678b11d1e",
        ),
        "evolution.prepare_spatial_reading": (
            "准备空间发现阅读授权预览",
            "confirm",
            "1",
            "1c7251ee14a9925fb78b65f353b806398960259014c199cb5b272fcde2e0d781",
        ),
        "evolution.prepare_spatial_rescan": (
            "准备空间补扫授权预览",
            "confirm",
            "1",
            "678c25ac32e9651b29916458fca9d0e83ed70036aa72af3f26ac55b3eb196675",
        ),
        "map.edit_spatial_structure": (
            "编辑空间、关系或行程",
            "confirm",
            "1",
            "90aa2b611611e07cc436ad1d5a736996b911fc1088e306d2685059535fa0cf95",
        ),
        "map.merge_nodes": (
            "合并两个已保存的地图节点",
            "confirm",
            "2",
            "2c04c4b212a0dda6e4c71a0dd64688599bd566b9c9e3cdad9d8922c088cecce9",
        ),
        "map.preview_node_merge": (
            "准备地图节点合并候选",
            "confirm",
            "1",
            "2c04c4b212a0dda6e4c71a0dd64688599bd566b9c9e3cdad9d8922c088cecce9",
        ),
        "map.review_auto_draft_group": (
            "按空间或层级审核自动草图",
            "confirm",
            "1",
            "3ac0b9c84c66e0856b332827c6ac0ab31493f75ff9492ce5d3f5f381d68abc7b",
        ),
        "map.review_spatial_clues": (
            "审核空间线索",
            "confirm",
            "1",
            "be91cdd4ab7db2bf1d9ef67bd6dfb5daad875e6f55c220b4a1816bc87acea337",
        ),
        "map.update_node": (
            "移动或改名地图节点",
            "confirm",
            "1",
            "de83bb98ac25d3e8b0e352d13b6849c340dede8e467045f35bebff0e3317591c",
        ),
        "assistant.notice.mute_category": (
            "静默这一类提醒",
            "confirm",
            "1",
            "21330dd4d44f49119544c5e900fa099574ba6f6bc89ff1b984bbce500ec3bd2b",
        ),
        "assistant.notice.set_disposition": (
            "处理提醒",
            "confirm",
            "1",
            "2800f7f6c80fb20ac0ab98c0e8080d6ab0bd92a584368fa89bdd44137db00a9a",
        ),
        "assistant.notice.unmute_category": (
            "恢复这一类提醒",
            "confirm",
            "1",
            "21330dd4d44f49119544c5e900fa099574ba6f6bc89ff1b984bbce500ec3bd2b",
        ),
        "world.dossier.entry.create": (
            "新增对象档案条目",
            "confirm",
            "1",
            "1621cab68c2573e27dda545a5bd3cfe356c145d05c7c7cb79ee8c7177b3d8746",
        ),
        "world.dossier.entry.edit": (
            "修订对象档案条目",
            "confirm",
            "1",
            "0bae31d9664252c31020b2bd7b5db6aee09f5d9f5d11530300bf06f4db745d56",
        ),
        "world.dossier.entry.restore": (
            "恢复对象档案历史版本",
            "confirm",
            "1",
            "b4169b8499b5f94b51fef9ed0dad43b05adc3ec62d4414d1bbf06875dc60cb65",
        ),
        "world.dossier.history.read": (
            "读取对象档案历史",
            "read",
            "1",
            "5556705289373ce29fc0458583b2da5b775b0083bd867e34f10af9223e4d1368",
        ),
        "world.dossier.read": (
            "读取对象档案",
            "read",
            "1",
            "c6fa145e02df9d5ee1a91df7998c6db46d6f3dc7caa7072f63eacf44159e7f59",
        ),
        "world.dossier.template.edit": (
            "修订对象档案模板",
            "confirm",
            "2",
            "c4ff8a3587de5a80460cbd51b7eb16cf63886b87133b467763b923ed56371d43",
        ),
        "world.dossier.template.read": (
            "读取对象档案模板",
            "read",
            "1",
            "f701fcd49fdb3a4ac35e21066d7905bc8c271b89d84289a46bf61428f5e749e8",
        ),
    }
)


A1_FIRST_WAVE_OPERATIONS = {
    "world.entity.transition_type",
    "world.entity.fuse",
    "world.history.set_note",
    "world.entity.restore_revision",
    "story.scene.reorder",
    "story.scene.merge",
    "story.scene.split",
    "writing.chapter.rename",
    "writing.chapter.mark_editorial_ready",
    "writing.comment.set_status",
    "writing.conflict_check.create",
    "evidence.project.search",
    "evidence.source.read",
    "evidence.knowledge.preview_scope",
    "evolution.prepare_reading",
}

C2_OBJECT_CONSUMER_OPERATIONS = {
    "evidence.object_dossier_brief.read",
    "story.character_card.generate",
    "story.reaction.generate",
}
C4_SCENE_DIRECTOR_OPERATIONS = {
    "story.scene_director.preview",
    "story.scene_director.start",
    "story.scene_director.continue_preview",
    "story.scene_director.continue",
    "story.scene_director.history",
    "story.scene_director.check_consistency",
    "story.scene_director.advance",
    "story.scene_director.save_reference",
}
C0C_VALIDITY_OPERATIONS = {
    "project.object_validity_settings.read",
    "project.object_validity_settings.edit",
    "story.custom_text_state.confirm",
    "story.map_declaration_state.confirm",
    "world.relations.read",
}
A3_AUTHOR_OPERATIONS = {
    "interaction.author.journeys.list",
    "interaction.author.journey.settings",
    "interaction.author.journey.rename",
    "interaction.author.journey.archive",
    "interaction.author.journey.restore",
    "interaction.summary.refresh",
    "collaboration.workspace.create",
    "collaboration.workspace.edit",
    "collaboration.workspace.inspect",
    "collaboration.workspace.seal",
    "collaboration.workspace.check",
    "collaboration.workspace.atomic_adopt",
}
C4_TRANSFER_OPERATIONS = {"story.scene_director.transfer_world_candidate"}
C5_WORLD_PROGRESSION_OPERATIONS = {
    "story.world_progression.history",
    "story.world_progression.compare",
    "story.world_progression.preview",
    "story.world_progression.start",
    "story.world_progression.advance",
    "story.world_progression.resume",
    "story.world_progression.preview_hook",
    "story.world_progression.adopt_hook",
    "story.world_progression.read_continuous_authorization",
}
C0_DOSSIER_INTERCHANGE_OPERATIONS = {
    "world.dossier.template.borrowed.read",
    "world.dossier.template.borrowed.edit",
    "world.dossier.manifest.preview",
    "world.dossier.manifest.apply",
}
# Preserve the pre-C0c snapshot above. These seven contracts were deliberately
# versioned after the response or nested request shape changed.
C0C_REVISED_SNAPSHOT = {
    "world.dossier.read": (
        "读取对象档案",
        "read",
        "2",
        "c6fa145e02df9d5ee1a91df7998c6db46d6f3dc7caa7072f63eacf44159e7f59",
    ),
    "world.dossier.history.read": (
        "读取对象档案历史",
        "read",
        "2",
        "5556705289373ce29fc0458583b2da5b775b0083bd867e34f10af9223e4d1368",
    ),
    "world.dossier.template.read": (
        "读取对象档案模板",
        "read",
        "2",
        "f701fcd49fdb3a4ac35e21066d7905bc8c271b89d84289a46bf61428f5e749e8",
    ),
    "world.dossier.entry.create": (
        "新增对象档案条目",
        "confirm",
        "2",
        "8948846dc0937dfedfdd6b71a5304b4e5220a05f51003e5ab4515cb74b3b9ab9",
    ),
    "world.dossier.entry.edit": (
        "修订对象档案条目",
        "confirm",
        "2",
        "9635228d35bf69ac98d3af12a780456b33e2adf186d4953aac9fa6bf3aa9e817",
    ),
    "world.dossier.entry.restore": (
        "恢复对象档案历史版本",
        "confirm",
        "2",
        "b4169b8499b5f94b51fef9ed0dad43b05adc3ec62d4414d1bbf06875dc60cb65",
    ),
    "world.dossier.template.edit": (
        "修订对象档案模板",
        "confirm",
        "3",
        "ddd8aecd41124a23a4b56a6fba78f0b566defe95ee6dcfbe911a3dfd2d4c13ca",
    ),
}


def _pre_c0c_manifest():
    from modules.assistant.operations import operation_manifest

    excluded = (
        C0C_VALIDITY_OPERATIONS
        | A3_AUTHOR_OPERATIONS
        | C4_TRANSFER_OPERATIONS
        | C5_WORLD_PROGRESSION_OPERATIONS
        | C0_DOSSIER_INTERCHANGE_OPERATIONS
    )
    frozen = {
        name: value
        for name, value in operation_manifest().items()
        if name not in excluded
    }
    for name in C0C_REVISED_SNAPSHOT:
        old = OPERATION_SNAPSHOT[name]
        frozen[name] = {**frozen[name], "schema_hash": old[3], "revision": old[2]}
    return frozen


def test_bootstrap_operation_catalog_matches_snapshot():
    from app.bootstrap import register_container_services
    from core.container import get

    register_container_services()
    catalog = get("assistant.operations")
    assert set(catalog) == (
        set(OPERATION_SNAPSHOT)
        | A1_FIRST_WAVE_OPERATIONS
        | C2_OBJECT_CONSUMER_OPERATIONS
        | C4_SCENE_DIRECTOR_OPERATIONS
        | C0C_VALIDITY_OPERATIONS
        | A3_AUTHOR_OPERATIONS
        | C4_TRANSFER_OPERATIONS
        | C5_WORLD_PROGRESSION_OPERATIONS
        | C0_DOSSIER_INTERCHANGE_OPERATIONS
    )
    mismatches = {
        name: {
            "actual": (
                operation.label,
                operation.permission,
                operation.revision,
                fingerprint(operation.schema.model_json_schema()),
            ),
            "expected": C0C_REVISED_SNAPSHOT.get(name, OPERATION_SNAPSHOT[name]),
        }
        for name, operation in catalog.items()
        if name in OPERATION_SNAPSHOT
        if (
            operation.label,
            operation.permission,
            operation.revision,
            fingerprint(operation.schema.model_json_schema()),
        )
        != C0C_REVISED_SNAPSHOT.get(name, OPERATION_SNAPSHOT[name])
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


def test_catalog_v2_metadata_and_trace_inventory_match_runtime_schemas():
    from app.bootstrap import register_container_services
    from core.container import get
    from modules.assistant.operations import operation_manifest

    register_container_services()
    operations = get("assistant.operations")
    manifest = operation_manifest()
    assert (
        len(operations)
        == len(manifest)
        == len(OPERATION_SNAPSHOT)
        + len(A1_FIRST_WAVE_OPERATIONS)
        + len(C2_OBJECT_CONSUMER_OPERATIONS)
        + len(C4_SCENE_DIRECTOR_OPERATIONS)
        + len(C0C_VALIDITY_OPERATIONS)
        + len(A3_AUTHOR_OPERATIONS)
        + len(C4_TRANSFER_OPERATIONS)
        + len(C5_WORLD_PROGRESSION_OPERATIONS)
        + len(C0_DOSSIER_INTERCHANGE_OPERATIONS)
    )
    assert set(operations) == set(manifest)
    for op_id, operation in operations.items():
        frozen = manifest[op_id]
        assert frozen["metadata"]["op_id"] == op_id
        assert frozen["metadata_hash"] == fingerprint(frozen["metadata"])
        assert operation.trace_rule.parameter_fields == tuple(
            operation.schema.model_fields
        )
        assert set(frozen) == {
            "schema_hash",
            "revision",
            "op_version",
            "metadata_hash",
            "metadata",
            "schema",
        }


def test_v8_additions_do_not_appear_in_a_frozen_v7_directory():
    from app.bootstrap import register_container_services
    from modules.assistant.operations import resolve_operations

    register_container_services()
    frozen_v7 = {
        name: value
        for name, value in _pre_c0c_manifest().items()
        if name
        not in A1_FIRST_WAVE_OPERATIONS
        | C2_OBJECT_CONSUMER_OPERATIONS
        | C4_SCENE_DIRECTOR_OPERATIONS
    }
    resolved = resolve_operations(frozen_v7, allow_stale=True)
    assert set(resolved) == set(OPERATION_SNAPSHOT) - set(C0C_REVISED_SNAPSHOT)
    assert not (set(resolved) & A1_FIRST_WAVE_OPERATIONS)


def test_v9_additions_do_not_appear_in_a_frozen_v8_directory():
    from app.bootstrap import register_container_services
    from modules.assistant.operations import resolve_operations

    register_container_services()
    frozen_v8 = {
        name: value
        for name, value in _pre_c0c_manifest().items()
        if name not in C2_OBJECT_CONSUMER_OPERATIONS | C4_SCENE_DIRECTOR_OPERATIONS
    }
    resolved = resolve_operations(frozen_v8, allow_stale=True)
    assert (
        set(resolved)
        == (set(OPERATION_SNAPSHOT) - set(C0C_REVISED_SNAPSHOT))
        | A1_FIRST_WAVE_OPERATIONS
    )


def test_v10_additions_do_not_appear_in_a_frozen_v9_directory():
    from app.bootstrap import register_container_services
    from modules.assistant.operations import resolve_operations

    register_container_services()
    frozen_v9 = {
        name: value
        for name, value in _pre_c0c_manifest().items()
        if name not in C4_SCENE_DIRECTOR_OPERATIONS
    }
    resolved = resolve_operations(frozen_v9, allow_stale=True)
    assert set(resolved) == (
        (set(OPERATION_SNAPSHOT) - set(C0C_REVISED_SNAPSHOT))
        | A1_FIRST_WAVE_OPERATIONS
        | C2_OBJECT_CONSUMER_OPERATIONS
    )


def test_c0c_revised_operations_fail_closed_for_old_frozen_manifests():
    import pytest

    from app.bootstrap import register_container_services
    from core.errors import ConflictError
    from modules.assistant.operations import resolve_operations

    register_container_services()
    frozen_v10 = _pre_c0c_manifest()
    assert not set(resolve_operations(frozen_v10, allow_stale=True)) & set(
        C0C_REVISED_SNAPSHOT
    )
    with pytest.raises(ConflictError, match="工具版本不可用"):
        resolve_operations(frozen_v10)


def test_v12_author_operations_do_not_enter_a_frozen_v11_directory():
    from app.bootstrap import register_container_services
    from modules.assistant.operations import operation_manifest, resolve_operations

    register_container_services()
    frozen_v11 = {
        name: value
        for name, value in operation_manifest().items()
        if name
        not in (
            A3_AUTHOR_OPERATIONS
            | C4_TRANSFER_OPERATIONS
            | C5_WORLD_PROGRESSION_OPERATIONS
            | C0_DOSSIER_INTERCHANGE_OPERATIONS
        )
    }
    assert not (set(resolve_operations(frozen_v11)) & A3_AUTHOR_OPERATIONS)
    assert set(operation_manifest()) - set(frozen_v11) == (
        A3_AUTHOR_OPERATIONS
        | C4_TRANSFER_OPERATIONS
        | C5_WORLD_PROGRESSION_OPERATIONS
        | C0_DOSSIER_INTERCHANGE_OPERATIONS
    )


def test_v13_transfer_is_r3_and_absent_from_a_frozen_v12_directory():
    from app.bootstrap import register_container_services
    from core.container import get
    from modules.assistant.operations import operation_manifest, resolve_operations

    register_container_services()
    manifest = operation_manifest()
    frozen_v12 = {
        name: value
        for name, value in manifest.items()
        if name
        not in (
            C4_TRANSFER_OPERATIONS
            | C5_WORLD_PROGRESSION_OPERATIONS
            | C0_DOSSIER_INTERCHANGE_OPERATIONS
        )
    }
    assert set(manifest) - set(frozen_v12) == (
        C4_TRANSFER_OPERATIONS
        | C5_WORLD_PROGRESSION_OPERATIONS
        | C0_DOSSIER_INTERCHANGE_OPERATIONS
    )
    assert not (set(resolve_operations(frozen_v12)) & C4_TRANSFER_OPERATIONS)
    operation = get("assistant.operations")[
        "story.scene_director.transfer_world_candidate"
    ]
    assert operation.permission == "confirm"
    assert operation.risk_level == "R3"
    assert operation.fee_category == "free"


def test_inline_operation_metadata_requires_an_explicit_schema_trace_policy():
    import pytest

    from app.assistant_operation_registry import _materialize

    class Args:
        model_fields = {"value": object()}

    async def prepare(*_args, **_kwargs):
        return {}

    async def apply(*_args, **_kwargs):
        return {}

    with pytest.raises(ValueError, match="留痕字段"):
        _materialize(
            {
                "sample.write": {
                    "label": "写入",
                    "schema": Args,
                    "prepare": prepare,
                    "apply": apply,
                    "op_version": "1",
                    "description": "写入示例",
                    "risk_level": "R2",
                    "fee_category": "free",
                    "reversibility": "restore",
                    "preconditions": (),
                    "produces": ("sample",),
                    "target_type": "sample",
                    "ai_available": True,
                    "transaction_mode": "single_transaction",
                    "trace_rule": {"parameter_fields": (), "mode": "per_call"},
                }
            }
        )


def test_assistant_facade_di_keys_resolve():
    from app.bootstrap import register_container_services
    from core.container import get

    register_container_services()
    for key in (
        "assistant.inspect_discussion",
        "assistant.submit_comment_proposals",
        "assistant.mark_editorial_ready",
    ):
        assert callable(get(key))

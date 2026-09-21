"""Versioned review methods; instructions never extend the registered tool set."""

REVIEW_METHODS = {
    "continuity-v1": (
        "连续性方法 v1：先列当前版本、分支、剧情截止点和必要证据，再核对事件先后、"
        "状态变化、否定条件和因果。主动寻找反证；没有查到不等于不存在。"
        "输出候选问题、支持与反对的精确引用、已检查范围和未解决项。"
    ),
    "character-knowledge-v1": (
        "人物知识方法 v1：逐项追踪人物在截止点之前如何获得信息。区分客观事实、"
        "人物信念、推断和谎言；没有实际知识资料时明确未检查知识边界。"
        "核对人工纠正和选中分支，禁止将作者全知资料当作角色已知。"
    ),
    "world-rules-v1": (
        "世界规则方法 v1：提取已采用规则的前提、成本、例外与适用时间；检查具体"
        "行为是否同时满足这些条件，并寻找能推翻冲突判断的证据。"
        "作者有意保留的歧义列为待决，不以成员票数、置信度或模型身份裁决。"
    ),
}


def review_methods(blueprint, role):
    keys = []
    if blueprint == "deep_review":
        keys = {
            "facts": ["continuity-v1", "world-rules-v1"],
            "characters": ["character-knowledge-v1"],
            "narrative": ["continuity-v1"],
        }.get(role, [])
    elif blueprint == "world_stress" and role == "rules":
        keys = ["world-rules-v1"]
    return {key: REVIEW_METHODS[key] for key in keys}

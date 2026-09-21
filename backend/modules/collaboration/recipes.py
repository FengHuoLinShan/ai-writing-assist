"""Task recipes constrain work types; they do not grant data or tool access."""

from core.errors import ValidationError
from modules.collaboration.contracts import Recipe

RECIPES = {
    "revision": Recipe(
        id="revision",
        label="试改与比较",
        questions=[
            "问题有哪些竞争解释？前文是否已有反证？",
            "保留原文，并比较两种不同的局部修法",
        ],
        capabilities=["investigate", "countercheck", "revise", "test", "compare"],
        required_checks=["作者保留项", "来源与事实", "修改后的直接后果"],
    ),
    "deep_review": Recipe(
        id="deep_review",
        label="查清正文问题",
        questions=["当前问题是否有可回读证据？", "是否存在有意留白、错误信念或反证？"],
        capabilities=["investigate", "countercheck", "compare"],
        required_checks=["出处支持", "文学选择与事实区分"],
    ),
    "world_stress": Recipe(
        id="world_stress",
        label="世界规则试验",
        questions=["规则在哪些具体条件下产生反例？", "比较保留规则与两种修法的直接后果"],
        capabilities=["investigate", "countercheck", "revise", "test", "compare"],
        required_checks=["规则前提", "人物不会自动知道新规则", "正文直接依赖"],
    ),
    "blind_reader": Recipe(
        id="blind_reader",
        label="按阅读进度检查",
        questions=["在当前已读内容下，哪些理解有支持，哪些仍未知？"],
        capabilities=["investigate", "countercheck", "compare"],
        required_checks=["无后见资料", "读者猜测不作为作者计划"],
    ),
    "research": Recipe(
        id="research",
        label="专题查证",
        questions=["哪些判断已有出处？", "寻找替代解释和未覆盖部分"],
        capabilities=["investigate", "countercheck", "compare"],
        required_checks=["来源独立性", "引文支持与覆盖"],
    ),
    "import_consult": Recipe(
        id="import_consult",
        label="导入会诊",
        questions=["疑难候选有哪些相互竞争的解释？", "列出必要的最小身份决定，保留歧义"],
        capabilities=["investigate", "countercheck", "compare"],
        required_checks=["不自动合并身份", "原组与指纹不扩张"],
    ),
}


def get_recipe(recipe_id):
    if recipe_id not in RECIPES:
        raise ValidationError("请选择已支持的创作任务", code="RECIPE_UNSUPPORTED")
    return RECIPES[recipe_id]

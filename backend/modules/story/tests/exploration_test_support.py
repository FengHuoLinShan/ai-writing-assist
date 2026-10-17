"""Synthetic exploration responses shared by SQLite worker and API tests.

按 system prompt 识别动作（sandbox/diagnose/bridge/scene_line），返回
P0 §4 合法 payload 夹具；支持强制失败与隐藏短语注入（canonical guard）。
"""

from __future__ import annotations

import json

from infrastructure.llm.schemas import LLMCallResponse, LLMUsage


def sandbox_payload(question: str = "重力减半后面包师的一天？") -> dict:
    return {
        "question": question,
        "focus": "",
        "influence_chain": [
            {
                "condition": "揉面时间不变",
                "mechanism": "重力降低让面团发酵更快",
                "effect": "面包更松软，出炉提前",
                "affected_refs": ["c_baker"],
                "holds_when": "炉温可以照常维持",
                "unknown": "精确发酵速率未知",
            }
        ],
        "preconditions": ["城镇居民接受这一小时的不便"],
        "unknowns": ["重力恢复瞬间的气流影响"],
        "warnings": [],
    }


def event_payload(mode: str = "diagnose") -> dict:
    if mode == "diagnose":
        return {
            "mode": "diagnose",
            "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
            "gaps": [
                {
                    "description": "缺少信使获知收信人行踪的来源",
                    "why_needed": "解释为何能精准送达",
                    "possible_fix_hint": "有人在城门口认出了收信人",
                }
            ],
            "unknowns": ["信使当天的实际路线"],
            "warnings": [],
        }
    if mode == "info_gap":
        # M2 事件信息差：逐主体列知识边界与缺失接触路径；不补全未发生信息。
        return {
            "mode": "diagnose",
            "original_excerpt": "证人没看到交接，却准确说出接头暗号",
            "gaps": [
                {
                    "description": "证人与交接现场之间缺少接触路径",
                    "why_needed": "没有接触就无法得知暗号",
                }
            ],
            "info_boundary": [
                {
                    "subject_ref": "c_witness",
                    "subject_description": "证人",
                    "knows": ["接头暗号的内容"],
                    "not_known": ["交接发生的地点与时间"],
                    "missing_contact_path": True,
                },
                {
                    "subject_description": "接头人",
                    "knows": [],
                    "not_known": ["证人已听闻暗号"],
                    "missing_contact_path": False,
                },
            ],
            "unknowns": [],
            "warnings": [],
        }
    if mode == "goal":
        # M2 事件导向：最小行动—响应—后果链与代价；无解时给 unsolvable。
        return {
            "mode": "goal",
            "original_excerpt": "指定结果：信使当天把信送到本人手里",
            "goal_path": {
                "goal": "信使当天把信送到本人手里",
                "steps": [
                    {
                        "action": "信使向守门人出示驿站登记摘录",
                        "condition": "登记摘录写明收信人当日进城",
                        "response": "守门人指认唯一的同姓进城者",
                        "consequence": "信使当场完成投递",
                        "cost_or_risk": "信使暴露了自己的任务",
                    }
                ],
                "rule_constraints": ["禁止巧合", "角色性格不得突变"],
                "unsolvable": None,
            },
            "unknowns": [],
            "warnings": [],
        }
    if mode == "goal_unsolvable":
        return {
            "mode": "goal",
            "original_excerpt": "指定结果：信使当天把信送到本人手里",
            "goal_path": {
                "goal": "信使当天把信送到本人手里",
                "steps": [
                    {
                        "action": "信使请求守门人配合指认收信人",
                        "condition": "守门人有配合的动机",
                        "response": "守门人拒绝或敷衍",
                        "consequence": "投递失败",
                        "cost_or_risk": "信使被守门人记恨",
                    }
                ],
                "rule_constraints": ["禁止巧合"],
                "unsolvable": {
                    "reason": "在不引入巧合的前提下守门人没有配合动机",
                    "missing": ["守门人的合作动机"],
                },
            },
            "unknowns": [],
            "warnings": [],
        }
    return {
        "mode": "bridge",
        "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
        "gaps": [],
        "bridge_candidates": [
            {
                "steps": ["驿站登记簿标注了收信人当日进城", "信使在城门口逐一致问"],
                "required_conditions": ["收信人走的是主城门"],
                "cost_or_risk": "多花半天时间问询",
                "holds": True,
            }
        ],
        "unsolvable": None,
        "unknowns": [],
        "warnings": [],
    }


def scene_line_payload(
    target_ref: str = "c_b", line: str = "你要是累了就先回去吧。"
) -> dict:
    return {
        "target_ref": target_ref,
        "line": line,
        "rationale": "目标只看得到对方疲惫，不知道失业的事。",
        "action": "把伞往对方那边偏了偏",
        "knowledge_basis": ["observed:对方脚步发沉"],
        "withheld": ["对方失业的传闻（自己并不知道）"],
        "unknowns": ["对方是否愿意倾诉"],
        "warnings": [],
    }


class ExplorationOfflineProvider:
    """按 system prompt 判别动作并返回合法夹具响应的离线 provider。"""

    name = "offline-exploration"

    def __init__(self):
        self.calls = 0
        self.requests = []
        self.fail_next = False
        self.override: dict | None = None

    async def generate(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.fail_next:
            self.fail_next = False
            raise TimeoutError("offline synthetic unknown charge")
        if self.override is not None:
            payload = self.override
        else:
            system = request.messages[0].content
            user = json.loads(
                next(
                    message.content
                    for message in request.messages
                    if message.role == "user"
                )
            )
            if "沙盘推演器" in system:
                payload = sandbox_payload(
                    (user.get("author_packet") or {}).get("question")
                    or "合成沙盘问题？"
                )
            elif "信息差分析器" in system:
                payload = event_payload("info_gap")
            elif "导向路径规划器" in system:
                # 无解变体由测试通过 override 注入，这里默认给可行路径。
                payload = event_payload("goal")
            elif "事件诊断器" in system:
                payload = event_payload("diagnose")
            elif "事件补桥器" in system:
                payload = event_payload("bridge")
            elif "对白试探器" in system:
                mode = str(user.get("mode") or "start")
                base = scene_line_payload(
                    str((user.get("target") or {}).get("ref") or "c_b")
                )
                if mode == "revise" and user.get("previous_line"):
                    base["line"] = "你累了就先回去吧，别硬撑着。" + "（修订）"
                elif mode == "detail":
                    base["rationale"] = base["rationale"] + "（更详细）"
                payload = base
            else:  # pragma: no cover - 防御
                raise AssertionError(f"未知探索动作 prompt: {system[:40]}")
        return LLMCallResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            model="deepseek-flash",
            provider=self.name,
            usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )

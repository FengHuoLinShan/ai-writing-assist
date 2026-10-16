"""Synthetic Director responses shared by SQLite workflow and PostgreSQL worker tests."""

import json

from infrastructure.llm.schemas import LLMCallResponse, LLMUsage


class DirectorOfflineProvider:
    name = "offline-director"
    calls = 0
    fail_next = False

    def __init__(self, actor_id):
        self.actor_id = actor_id
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise TimeoutError("offline synthetic unknown charge")
        data = json.loads(
            next(
                message.content
                for message in reversed(request.messages)
                if message.role == "user"
            )
        )
        rewriting = "只重写" in request.messages[0].content
        if self.calls % 4 == 1 and not rewriting:
            payload = {"kind": "observe", "action": "听门外风声", "effect": "none"}
        elif self.calls % 4 == 2 and not rewriting:
            payload = {
                "outcomes": [
                    {"intent_id": item["intent_id"], "outcome": "succeeded"}
                    for item in data["intents"]
                ]
            }
        elif self.calls % 4 == 3 or rewriting:
            payload = {
                "character_id": self.actor_id,
                "action": "停下脚步",
                "expression": "眉间收紧",
                "body_language": "侧身倾听",
                "voice_and_dialogue": "低声说：等等。",
                "subtext": "判断门外是谁",
                "motive_and_emotion": "谨慎",
                "trigger_and_defense": "风声骤停",
                "attention": "门外",
                "ignored": "桌面",
                "change_from_previous": "初次",
                "basis": [{"source_kind": "director_inference", "note": "合成候选"}],
            }
        else:
            payload = {
                "materials": [
                    {
                        "material_id": "north-gate-wind",
                        "category": "environment",
                        "content": "北门的风声突然停了",
                        "senses": ["sound"],
                        "source_kind": "director_inference",
                    }
                ],
                "recommended_angles": [
                    {
                        "angle_id": "close",
                        "label": "阿澄视角",
                        "viewpoint_kind": "character",
                        "viewpoint_character_id": self.actor_id,
                        "narrative_distance": "close",
                        "focus": "门外",
                        "detail_and_pacing": "放慢",
                        "material_ids": ["north-gate-wind"],
                    },
                    {
                        "angle_id": "wide",
                        "label": "全知视角",
                        "viewpoint_kind": "omniscient",
                        "narrative_distance": "omniscient",
                        "focus": "全场",
                        "detail_and_pacing": "简洁",
                        "material_ids": ["north-gate-wind"],
                    },
                ],
                "alternatives": [
                    {
                        "alternative_id": "a",
                        "label": "谨慎",
                        "branch_instruction": "维持沉默",
                        "divergence": "conservative",
                    },
                    {
                        "alternative_id": "b",
                        "label": "行动",
                        "branch_instruction": "走向北门",
                        "divergence": "balanced",
                    },
                ],
            }
        return LLMCallResponse(
            content=json.dumps(payload, ensure_ascii=False),
            finish_reason="stop",
            model="deepseek-flash",
            provider=self.name,
            usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )

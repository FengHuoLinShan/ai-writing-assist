"""复审后重新冻结的独立合成来源族；不改旧M0/已见holdout材料。"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from evals.rp_cost_baseline import _Fixture
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.project.models import Project
from modules.world.models import CoreEntity
from modules.writing.facade import create_published_draft_only


@dataclass(frozen=True)
class Family:
    key: str
    stage: str
    cast: tuple[str, str, str, str]
    place: str
    item: str
    secret: str
    rule: str
    voice: str
    history: str

    @property
    def recap(self):
        a, b, c, d = self.cast
        return (
            f"{a}是{self.item}的所有者，目前由{b}保管；交接不改变所有权。"
            f"{self.rule}。{self.secret}完整内容只有{c}知道，{a}不知。"
            f"{self.voice}。{self.history}。{d}只是追查者，没有拿到物品或秘密。"
        )

    def input(self, turn):
        a, b, c, d = self.cast
        actions = [
            f"我向{b}索要{self.item}，先听对方的条件。",
            f"我向{c}交谈，依照他一贯的说话习惯试探秘密，只问可公开的部分。",
            "我逐项核对开启条件，不满足就先停下。",
            f"我打听{d}的动向，区分传闻与目击。",
            "我核对自己亲历的往事记录，回忆当年的交接，再比较今天的说法。",
            "我保留退路，提出下一步的交换条件。",
        ]
        action = actions[(turn - 1) % len(actions)]
        return f"第{turn}步玩家选择：{action}只推进眼前这一小步。"

    @property
    def judge_ground_truth(self):
        chapters = 12 if self.stage == "dev" else 36
        facts = [
            f"第{number}章：" + self.chapter(number)
            for number in range(1, chapters + 1)
        ]
        return (
            self.recap
            + "\n以下是审核用的起点前逐章原文，不代表角色全部知情；"
            + "原有秘密/角色知识边界仍适用。\n"
            + "\n".join(facts)
        )

    def chapter(self, number):
        a, b, c, d = self.cast
        # 关键证据分章，不将完整真相重复进每章或玩家输入。
        important = {
            1: (
                f"{a}回到{self.place}，以本名登记；{b}、{c}、{d}也在本地。"
                f"{self.item}是需要核对的旧物。"
            ),
            2: (
                f"{a}是{self.item}的所有者，委托{b}保管。"
                "交接没有赠送、没有改产权；保管与所有权分开。"
            ),
            3: f"{a}曾听{c}交谈：{self.voice}。这只是说话习惯，没有透露任何秘密内容。",
            5: (
                f"{c}独自在封闭屋内记下{self.secret}的实际细节：{self.secret_canary}。"
                "没有其他人物在场或知情。"
            ),
            7: (
                f"{a}在{self.place}查到开启条件记录：{self.rule}。"
                "这里没有记载今日条件已经满足。"
            ),
            9: f"{a}亲历的往事记录：{self.history}。后来没有第二次交接。",
            10: (
                f"{a}在{self.place}见到{d}向守门人询问时间，"
                f"但{d}没有取得物品，也没有获得秘密。"
            ),
            37: (
                f"未来记录：{a}获得尚未公开的凭据{self.future_canary}。"
                "这发生在本次冻结起点之后。"
            ),
        }
        observer = a if number % 3 == 0 else b
        detail = important.get(
            number,
            f"{observer}整理第{number}次普通登记，{d}在等候区查看天气；没有新的交接或揭示。",
        )
        if number == 5:
            observer = c
        beats = [
            f"{self.place}第{number}日的登记写着纸张、灯火和门窗状况，刻度旁留着第{i}处旧痕。"
            for i in range(14)
        ]
        return "\n\n".join(
            [
                detail,
                f"{observer}整理本章可见记录。",
                *beats,
                f"这是{self.key}的第{number}处记录；没有发生新的物品交接，也没有公开秘密。",
            ]
        )

    @property
    def secret_canary(self):
        return f"隐情凭据-{self.key}-未公开"

    @property
    def future_canary(self):
        return f"未来凭据-{self.key}-截止后"


FAMILIES = (
    Family(
        "dev-port",
        "dev",
        ("陆遥", "林栩", "苏霁", "彭野"),
        "灰潮港",
        "赤铜钥匙",
        "地下潮道的入口",
        "开锁须钥匙、月圆与准确口令，缺一不可",
        "苏霁不直接回答旅客，只把公开告示挂在窗边",
        "三年前陆遥仅委托林栩保管，并未赠送",
    ),
    Family(
        "dev-water",
        "dev",
        ("汪岚", "陶桑", "贺露", "佟朔"),
        "旱原水站",
        "蓝釉阀柄",
        "第二口备用井的位置",
        "开阀须蓝釉阀柄、两人签字和足量净水，不能用身份替代实物",
        "陶桑先报价再解释，贺露只核对可公开的数字",
        "汪岚当年借出阀柄，净水额度仍属于水站",
    ),
    Family(
        "dev-rail",
        "dev",
        ("席舟", "骆延", "陈序", "姚谦"),
        "北环调度房",
        "银调度令",
        "夜班事故的真实见证者",
        "行车须调度令、空闲轨道和双岗确认，紧急请求不豁免",
        "陈序使用短句，拒绝替别人断言动机",
        "席舟曾让骆延代管令牌，一趟货车因此等待了整夜",
    ),
    Family(
        "dev-clinic",
        "dev",
        ("许稚", "杜翎", "孟芷", "袁仲"),
        "雪线诊所",
        "冷柜封签",
        "药剂失效的批次",
        "开柜须封签、稳定低温与医生签字，所有权不能替代签字",
        "孟芷只回答自己亲自测量过的事项",
        "杜翎替许稚保存封签，却无权决定药剂用途",
    ),
    Family(
        "dev-market",
        "dev",
        ("程荔", "马榆", "秦冬", "尤禾"),
        "汐灯集市",
        "白瓷通行牌",
        "账册最后一页的去向",
        "通行须牌、闭市钟和本人登记，不认口头保证",
        "秦冬说话留白但不把隐情当公共情报",
        "程荔把牌交给马榆避雨，授权仍未变更",
    ),
    Family(
        "dev-orchard",
        "dev",
        ("闻溪", "叶槐", "方竹", "任棠"),
        "雾岭果圃",
        "黄木库牌",
        "树根病害的范围",
        "入库须库牌、两把不同的印章和干燥地面，借来的印章不代表产权",
        "方竹用具体事物作比喻，拒绝泄露未核定的病情",
        "闻溪只让叶槐看护库牌，丰收份额没有转让",
    ),
    Family(
        "holdout-seal",
        "holdout",
        ("赵砚", "何绫", "卜青", "景和"),
        "双印驿站",
        "乌玉封印",
        "真正的收件人",
        "启匣须封印、收件人签名和无破损的双层封缄，代理签名无效",
        "卜青只能朗读外封已公开的文字，不能回答内函问题",
        "何绫只是运输保管者，赵砚未授权拆阅",
    ),
    Family(
        "holdout-tide",
        "holdout",
        ("蒋弦", "罗渔", "唐星", "郑棹"),
        "回潮船坞",
        "红绳锚符",
        "潜流转向的时刻",
        "离坞须锚符、低潮和两名船工到场，潮汐与月相不能混同",
        "唐星只通过船笛发送约定公开信号，不与旅客直接交谈",
        "锚符曾借罗渔保管，船只仍属蒋弦",
    ),
    Family(
        "holdout-signal",
        "holdout",
        ("谢荷", "安蒲", "米岑", "左苇"),
        "风测高台",
        "青玻璃校准片",
        "传感器误差的方向",
        "校准须完整校准片、零风窗口和可追溯测量，不用传闻补读数",
        "米岑以测量值回应，遇到未测量问题就保持未知",
        "谢荷只委托安蒲保存校准片，校准权限仍要另行确认",
    ),
)


async def setup_family(db, family: Family):
    source_id, consumer_id = uuid.uuid4(), uuid.uuid4()
    db.add_all(
        [
            Project(
                id=source_id,
                owner_id=BOOTSTRAP_ACCOUNT_ID,
                title=family.key,
                language="zh",
                project_kind="author",
                settings={},
            ),
            Project(
                id=consumer_id,
                owner_id=BOOTSTRAP_ACCOUNT_ID,
                title=family.key + "旅程",
                language="zh",
                project_kind="interaction",
                settings={},
            ),
        ]
    )
    await db.flush()
    refs = []
    for index, name in enumerate([*family.cast, family.item, family.place]):
        entity_id = uuid.uuid4()
        kind = "character" if index < 4 else "item" if index == 4 else "location"
        db.add(
            CoreEntity(
                id=entity_id,
                novel_id=source_id,
                name=name,
                entity_type=kind,
                summary="公开身份；状态以对应原文为准",
                status="canonical",
            )
        )
        refs.append(
            {
                "reference_key": hashlib.sha256(
                    f"{family.key}:{index}".encode()
                ).hexdigest(),
                "target_id": str(entity_id),
                "entity_type": kind,
                "label": name,
                "first_chapter_index": 1,
                "first_end_offset": 3,
                "aliases": [],
            }
        )
    refs[0]["knowledge"] = [
        {
            "target_name": family.secret,
            "knowledge_level": "unknown",
            "is_public_baseline": True,
        },
        {
            "target_name": family.item,
            "knowledge_level": "known",
            "known_content": "了解过去的委托安排，具体内容须回读交接记录",
            "source_chapter_index": 2,
            "is_public_baseline": False,
        },
    ]
    manifest = []
    chapters = 12 if family.stage == "dev" else 36
    for chapter_index in [*range(1, chapters + 1), 37]:
        body = family.chapter(chapter_index)
        draft = await create_published_draft_only(
            db, str(source_id), chapter_index, f"第{chapter_index}处记录", body
        )
        manifest.append(
            {
                "draft_id": str(draft.id),
                "source_hash": draft.content_hash,
                "chapter_index": chapter_index,
                "char_count": len(body),
            }
        )
    await db.commit()
    last_text = family.chapter(chapters)
    anchor = {
        "anchor_key": hashlib.sha256(f"{source_id}:end".encode()).hexdigest(),
        "chapter_index": chapters,
        "chapter_title": "本次起点",
        "label": "记录末尾",
        "end_offset": len(last_text),
        "scene_id": None,
    }
    return _Fixture(
        str(source_id),
        str(consumer_id),
        manifest,
        anchor,
        refs,
        {"kind": "source_character", **refs[0]},
        {"kind": "original", "name": "旅客"},
        chapters,
        len(last_text),
    )

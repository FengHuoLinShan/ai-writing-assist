"""Affirmative review fixtures for storage/projection tests, not a model eval."""

_SCENES = {
    "林舟与青竹出现在白石城。",
    "林舟出现在渡口，没有说明中间行程。",
    "林舟后来到了深山。",
    "第1日天亮了。",
    "第2日天亮了。",
    "林舟与青竹在白石城重逢。",
    "林舟与青竹在白石城重逢。青竹从袖中取出铜钥匙。",
    "林舟与青竹在白石城重逢。青竹从袖中取出铜钥匙，说此物需妥善保管。",
    "青竹把铜钥匙收进包袱。林舟问她去哪儿，她说要先回白石城东市的当铺。",
    "三日后，林舟独自出现在渡口。他望着江面，没有说明自己如何离开白石城。",
    "青竹把铜钥匙收进包袱。",
    "🌙夜色渐淡，晨光照进城门。尾",
    "林舟出现在白石城。青竹说渡口已经封锁。林舟并没有亲眼确认这句话。",
    "三日后，林舟出现在渡口。他没有说明这三日的行程，也没有提起封锁。",
}


async def frozen_state_review(*, scene_text, input_manifest, observations, events):
    assert scene_text in _SCENES, "new prose requires a separately reviewed fixture"
    assert observations and events
    assert all(not event["snapshot_after"].get("moved_from") for event in events)
    return {
        "result": {
            "events": [
                {
                    "event_index": index,
                    "verdict": "supported",
                    "reason": "Fixed affirmative fixture",
                    "quotes": [scene_text],
                }
                for index in range(len(events))
            ]
        },
        "paid_call_receipt": {
            "provider": "fixture",
            "schema": "evolution.state_review.v1",
        },
    }

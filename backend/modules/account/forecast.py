"""Project-owner connection readiness with no keys, endpoints or provider probes."""

from uuid import UUID

from core.container import get
from core.service_keys import (
    ACCOUNT_PROJECT_OWNER_REF,
)
from modules.account.facade import get_account_llm_settings_contract


async def inspect(db, novel_id, focus, excluded):
    project = await get(ACCOUNT_PROJECT_OWNER_REF)(db, novel_id)
    settings = await get_account_llm_settings_contract(
        db, owner_id=UUID(str(project.owner_id))
    )
    ready = settings.provider_id in settings.configured_provider_ids
    # 纯数据事实（AO-5）：assistant 消费侧以 ForecastDomainFact.model_validate
    # 物化并校验，字段语义与原模型构造一致。
    return [
        {
            "capability_id": "account.readiness.v1",
            "subject": "owner_connection",
            "title": "生成连接已配置" if ready else "先连接可用的模型服务",
            "summary": "当前账户已配置所选连接；实际调用仍按原验证与能力门禁检查。"
            if ready
            else "在账户设置完成连接后，再开始需要模型的分析。",
            "source": {"configured": ready, "provider": settings.provider_id},
            "scope_label": "当前项目所有者的连接配置状态；未发起探测请求",
            "target": {"page": "settings"},
            "actionable": not ready,
        }
    ]

"""Project-owner connection readiness with no keys, endpoints or provider probes."""

from uuid import UUID

from modules.account.facade import get_account_llm_settings_contract
from modules.assistant.contracts import ForecastDomainFact
from modules.project.facade import get_any_project_context


async def inspect(db, novel_id, focus, excluded):
    project = await get_any_project_context(db, novel_id)
    settings = await get_account_llm_settings_contract(
        db, owner_id=UUID(str(project.owner_id))
    )
    ready = settings.provider_id in settings.configured_provider_ids
    return [
        ForecastDomainFact(
            capability_id="account.readiness.v1",
            subject="owner_connection",
            title="生成连接已配置" if ready else "先连接可用的模型服务",
            summary="当前账户已配置所选连接；实际调用仍按原验证与能力门禁检查。"
            if ready
            else "在账户设置完成连接后，再开始需要模型的分析。",
            source={"configured": ready, "provider": settings.provider_id},
            scope_label="当前项目所有者的连接配置状态；未发起探测请求",
            target={"page": "settings"},
            actionable=not ready,
        )
    ]

"""Minimal versioned Chinese policies for public registration."""

from __future__ import annotations

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from core.config import get_settings

router = APIRouter(tags=["legal"])


def _page(title: str, version: str, body: str) -> HTMLResponse:
    settings = get_settings()
    safe_title = escape(title)
    safe_version = escape(version)
    safe_support = escape(settings.support_email or "请联系站点运营者")
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>{safe_title}</title></head>
<body><main><h1>{safe_title}</h1><p>版本：{safe_version}</p>{body}
<p>举报与联系：{safe_support}。请附账号支持码，
不要在邮件中发送密码、验证码或 LLM API Key。</p></main></body></html>"""
    return HTMLResponse(html)


@router.get("/legal/terms", response_class=HTMLResponse)
async def terms() -> HTMLResponse:
    settings = get_settings()
    return _page(
        "用户协议",
        settings.terms_version,
        "<p>用户应合法使用本站，不得上传侵权、违法或恶意内容。"
        "本站可对滥用账号进行限制或封禁。</p>",
    )


@router.get("/legal/privacy", response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    settings = get_settings()
    return _page(
        "隐私政策",
        settings.privacy_version,
        "<p>本站处理登录身份、项目内容、加密后的账户级 LLM Key 与必要安全日志。"
        "申请删除后有 30 天恢复期；在线数据到期清除。整库备份另保留最多 30 天，"
        "因此数据最晚可能自申请日起残留约 60 天。管理员不查看用户项目内容。</p>",
    )

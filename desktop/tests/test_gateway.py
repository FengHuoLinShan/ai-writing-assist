from pathlib import Path

import httpx
import pytest
from starlette.responses import JSONResponse

from desktop.gateway import DesktopGateway


@pytest.mark.asyncio
async def test_loopback_session_origin_and_assets(tmp_path: Path):
    async def api(scope, receive, send):
        await JSONResponse({"path": scope["path"]})(scope, receive, send)

    (tmp_path / "index.html").write_text("<h1>NovelCraft</h1>")
    app = DesktopGateway(api, tmp_path, "http://127.0.0.1:8123", "secret")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8123"
    ) as client:
        assert (await client.get("/api/projects")).status_code == 401
        assert (await client.get("/_desktop/open/wrong")).status_code == 401
        response = await client.get("/_desktop/open/secret")
        assert response.status_code == 303
        assert "HttpOnly" in response.headers["set-cookie"]
        assert (await client.get("/")).text == "<h1>NovelCraft</h1>"
        assert (await client.get("/missing.js")).status_code == 404
        assert (
            "frame-ancestors 'none'"
            in (await client.get("/")).headers["content-security-policy"]
        )
        assert (await client.get("/api/projects")).json()["path"] == "/api/projects"
        assert (await client.post("/api/projects")).status_code == 403
        assert (
            await client.post(
                "/api/projects", headers={"Origin": "http://127.0.0.1:9999"}
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/projects", headers={"Origin": "http://127.0.0.1:8123"}
            )
        ).status_code == 200
        assert (
            await client.get("/api/projects", headers={"Host": "attacker.example"})
        ).status_code == 403
        client.cookies.clear()
        assert (await client.get("/_desktop/open/secret")).status_code == 401
        assert (await client.get("/")).status_code == 401


@pytest.mark.asyncio
async def test_encoded_invalid_token_does_not_crash(tmp_path):
    (tmp_path / "index.html").write_text("safe")
    gateway = DesktopGateway(None, tmp_path, "http://127.0.0.1:8123", "secret")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(gateway), base_url="http://127.0.0.1:8123"
    ) as client:
        assert (await client.get("/_desktop/open/%E4%B8%AD")).status_code == 401

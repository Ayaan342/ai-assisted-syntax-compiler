from __future__ import annotations

import asyncio
from pathlib import Path
import tomllib

import httpx

from api.index import app


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_vercel_mount_exposes_backend_only_under_api_prefix() -> None:
    health = request("GET", "/api/health")
    analysis = request("POST", "/api/analyze", json={"code": "int main(){return 0;}"})

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert analysis.status_code == 200
    assert analysis.json()["success"] is True
    assert request("GET", "/health").status_code == 404


def test_vercel_configuration_selects_the_api_adapter_explicitly() -> None:
    configuration = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert configuration["tool"]["vercel"]["entrypoint"] == "api.index:app"
    assert app is not None

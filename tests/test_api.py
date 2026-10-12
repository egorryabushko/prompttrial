import asyncio

import httpx
from fastapi.testclient import TestClient

from prompttrial.app import create_app
from prompttrial.providers import Completion, ReplayProvider


async def test_run_history_exports_comparison_and_errors(tmp_path):
    app = create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health")).json()["status"] == "ok"
            assert "PromptTrial" in (await client.get("/")).text
            assert (await client.get("/static/app.js")).status_code == 200
            report_ids = []
            for prompt in ["basic", "strict"]:
                response = await client.post("/api/jobs", json={"prompt": prompt})
                assert response.status_code == 202
                await app.state.task
                job = (await client.get("/api/jobs/" + response.json()["id"])).json()
                assert job["status"] == "completed"
                report_ids.append(job["report_id"])
            assert len((await client.get("/api/runs")).json()) == 2
            result = (await client.get("/api/runs/" + report_ids[0])).json()
            assert result["summary"]["passed"] == 20
            exported = await client.get("/api/runs/" + report_ids[0] + "/export?format=markdown")
            assert "REPLAY DEMO" in exported.text
            assert "attachment" in exported.headers["content-disposition"]
            assert (await client.get("/api/runs/" + report_ids[0] + "/export?format=json")).json()[
                "id"
            ] == report_ids[0]
            diff = await client.get(
                "/api/compare", params={"baseline": report_ids[0], "candidate": report_ids[1]}
            )
            assert diff.json()["pass_rate_delta"] == 0
            assert (await client.get("/api/runs/bad")).status_code == 404
            assert (await client.get("/api/jobs/bad")).status_code == 404
            assert (await client.post("/api/jobs", json={"repetitions": 6})).status_code == 422
            assert (
                await client.get("/api/runs/" + report_ids[0] + "/export?format=html")
            ).status_code == 422


async def test_single_job_admission_and_cancel(tmp_path, monkeypatch):
    entered = asyncio.Event()

    async def slow(self, case, prompt):
        entered.set()
        await asyncio.sleep(20)
        return Completion("SAFE")

    monkeypatch.setattr(ReplayProvider, "complete", slow)
    app = create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/jobs", json={})
            await entered.wait()
            assert (await client.post("/api/jobs", json={})).status_code == 429
            job_id = response.json()["id"]
            cancelled = await client.post("/api/jobs/" + job_id + "/cancel")
            assert cancelled.json()["status"] == "cancelled"
            assert (await client.post("/api/jobs", json={})).status_code == 202


def test_local_requires_config_and_reports_persist(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPTTRIAL_MODEL", raising=False)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/config").json()["local_model"] is None
        assert client.post("/api/jobs", json={"provider": "local"}).status_code == 422

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from prompttrial.models import RunRequest
from prompttrial.providers import LocalProvider, ReplayProvider
from prompttrial.runner import compare, run_suite
from prompttrial.store import ReportStore, markdown
from prompttrial.suites import load_suite

STATIC = Path(__file__).parent / "static"


def create_app(report_dir: Path | None = None, transport=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = ReportStore(
            report_dir or Path(os.getenv("PROMPTTRIAL_REPORTS", "reports"))
        )
        app.state.cases = load_suite()
        app.state.job = None
        app.state.task = None
        async with httpx.AsyncClient(
            timeout=60, transport=transport, follow_redirects=False
        ) as client:
            app.state.client = client
            yield
            if app.state.task and not app.state.task.done():
                app.state.task.cancel()
                await asyncio.gather(app.state.task, return_exceptions=True)

    app = FastAPI(title="PromptTrial", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def get_report(run_id):
        try:
            return app.state.store.get(run_id)
        except (ValueError, OSError):
            raise HTTPException(404, "Report not found") from None

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return {
            "cases": len(app.state.cases),
            "categories": sorted({case.category for case in app.state.cases}),
            "local_model": os.getenv("PROMPTTRIAL_MODEL") or None,
            "active_job": app.state.job,
        }

    @app.get("/api/runs")
    def runs():
        return app.state.store.list()

    @app.get("/api/runs/{run_id}")
    def result(run_id: str):
        return get_report(run_id)

    @app.get("/api/runs/{run_id}/export")
    def export(run_id: str, format: str = "json"):
        report = get_report(run_id)
        if format not in {"json", "markdown"}:
            raise HTTPException(422, "Choose json or markdown")
        return Response(
            report.model_dump_json(indent=2) if format == "json" else markdown(report),
            media_type="application/json" if format == "json" else "text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="prompttrial-{run_id}.{"json" if format == "json" else "md"}"'
            },
        )

    @app.get("/api/compare")
    def comparison(baseline: str, candidate: str):
        try:
            return compare(get_report(baseline), get_report(candidate))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    async def evaluate(job, request, provider):
        try:
            async with asyncio.timeout(1800):
                report = await run_suite(
                    app.state.cases, provider, request.prompt, request.repetitions
                )
            app.state.store.save(report)
            job.update(status="completed", report_id=report.id)
        except asyncio.CancelledError:
            job.update(status="cancelled")
            raise
        except Exception as error:
            job.update(status="failed", error=type(error).__name__)

    @app.post("/api/jobs", status_code=202)
    async def start(request: RunRequest):
        if app.state.task and not app.state.task.done():
            raise HTTPException(429, "One evaluation is already running")
        try:
            provider = (
                ReplayProvider()
                if request.provider == "replay"
                else LocalProvider(app.state.client)
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        job = {"id": uuid.uuid4().hex, "status": "running"}
        app.state.job = job
        app.state.task = asyncio.create_task(evaluate(job, request, provider))
        return dict(job)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        if not app.state.job or app.state.job["id"] != job_id:
            raise HTTPException(404, "Job not found")
        return app.state.job

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: str):
        current = job(job_id)
        if app.state.task and not app.state.task.done():
            app.state.task.cancel()
            await asyncio.gather(app.state.task, return_exceptions=True)
            current.update(status="cancelled")
        return current

    return app


app = create_app()

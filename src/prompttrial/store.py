import os
import re
import uuid
from pathlib import Path

from prompttrial.models import RunReport


class ReportStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid report ID")
        return self.root / f"{run_id}.json"

    def save(self, report: RunReport):
        destination = self._path(report.id)
        temporary = self.root / f".{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, run_id: str) -> RunReport:
        return RunReport.model_validate_json(self._path(run_id).read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        reports = []
        for path in sorted(
            self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        ):
            if len(reports) >= 100:
                break
            try:
                report = self.get(path.stem)
            except (ValueError, OSError):
                continue
            reports.append(report.model_dump(exclude={"results"}))
        return reports


def markdown(report: RunReport) -> str:
    def safe(value):
        return str(value).replace("<", "&lt;").replace(">", "&gt;").replace("`", "\\`")

    summary = report.summary
    lines = [
        "# PromptTrial run",
        "",
        safe(report.scope),
        "",
        f"- Run: {report.id}",
        f"- UTC time: {report.created_at}",
        f"- Provider / model: {safe(report.provider)} / {safe(report.model)}",
        f"- Prompt: {report.prompt} ({report.prompt_hash})",
        f"- Suite SHA-256: {report.suite_hash}",
        f"- Repetitions: {report.repetitions}",
        f"- Passed: {summary['passed']} / {summary['total']}",
        f"- Provider errors: {summary['provider_errors']}",
        f"- p50 / p95 latency: {summary['latency_p50_ms']} / {summary['latency_p95_ms']} ms",
        "",
        "## Failed checks",
        "",
    ]
    for result in report.results:
        if not result.passed:
            lines.extend(
                [
                    f"### {result.case_id}",
                    "",
                    safe(result.reason),
                    "",
                    f"Expected: {safe(result.expected)}",
                    "",
                    f"Observed: {safe(result.output) or '(no output)'}",
                    "",
                ]
            )
    if all(result.passed for result in report.results):
        lines.append("No failed checks in this run.")
    lines.extend(
        [
            "",
            "Latency includes completion and checking; errors are excluded from percentiles.",
            "Missing token usage is unknown, not zero. See JSON for full case-level data.",
            "",
        ]
    )
    return "\n".join(lines)

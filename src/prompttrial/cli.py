import argparse
import asyncio
import json
from pathlib import Path

import httpx

from prompttrial.models import RunReport
from prompttrial.providers import LocalProvider, ReplayProvider
from prompttrial.runner import compare, run_suite
from prompttrial.store import ReportStore, markdown
from prompttrial.suites import DEFAULT_SUITE, load_suite


async def execute(args):
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        provider = ReplayProvider() if args.provider == "replay" else LocalProvider(client)
        return await run_suite(load_suite(args.suite), provider, args.prompt, args.repetitions)


def main():
    parser = argparse.ArgumentParser(description="Reproducible LLM prompt regression tests")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--provider", choices=["replay", "local"], default="replay")
    run.add_argument("--prompt", choices=["basic", "strict"], default="strict")
    run.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    run.add_argument("--repetitions", type=int, choices=range(1, 6), default=1)
    run.add_argument("--output", type=Path, default=Path("reports"))
    run.add_argument("--fail-under", type=float, default=0)
    comparison = sub.add_parser("compare")
    comparison.add_argument("baseline", type=Path)
    comparison.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "compare":
            before = RunReport.model_validate_json(args.baseline.read_text(encoding="utf-8"))
            after = RunReport.model_validate_json(args.candidate.read_text(encoding="utf-8"))
            print(json.dumps(compare(before, after), indent=2))
            return
        if not 0 <= args.fail_under <= 1:
            parser.error("--fail-under must be between 0 and 1")
        report = asyncio.run(execute(args))
        ReportStore(args.output).save(report)
        (args.output / f"{report.id}.md").write_text(markdown(report), encoding="utf-8")
        print(report.scope)
        print(json.dumps(report.summary, indent=2))
        print(f"Report: {args.output / (report.id + '.json')}")
        if report.summary["provider_errors"] or report.summary["pass_rate"] < args.fail_under:
            raise SystemExit(1)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

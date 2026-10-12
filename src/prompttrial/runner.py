import asyncio
import math
import time
import uuid
from datetime import UTC, datetime

from prompttrial.checks import check
from prompttrial.models import Case, CaseResult, RunReport
from prompttrial.prompts import prompt_hash
from prompttrial.suites import suite_hash


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)] if ordered else 0


async def run_suite(
    cases: list[Case], provider, prompt: str, repetitions: int = 1, timeout: float = 60
) -> RunReport:
    if not 1 <= repetitions <= 5 or not cases:
        raise ValueError("A nonempty suite and 1–5 repetitions are required")
    # Serial requests avoid overloading a CPU model and make latency comparisons clearer.
    results = []
    for _ in range(repetitions):
        for case in cases:
            started = time.perf_counter()
            output, input_tokens, output_tokens, error = "", None, None, None
            try:
                async with asyncio.timeout(timeout):
                    completion = await provider.complete(case, prompt)
                output = completion.text
                input_tokens, output_tokens = completion.input_tokens, completion.output_tokens
                passed, reason = check(case, output)
            except Exception as exception:
                # Do not include exception bodies, request URLs or credentials in reports.
                error = type(exception).__name__
                passed, reason = False, "Provider error; inspect local server diagnostics"
            results.append(
                CaseResult(
                    case_id=case.id,
                    category=case.category,
                    task=case.task,
                    input=case.input,
                    expected=case.expected,
                    output=output,
                    passed=passed,
                    reason=reason,
                    latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    error=error,
                )
            )
    categories = {}
    for category in sorted({case.category for case in cases}):
        group = [result for result in results if result.category == category]
        categories[category] = {
            "passed": sum(result.passed for result in group),
            "total": len(group),
            "pass_rate": sum(result.passed for result in group) / len(group),
        }
    measured = [result.latency_ms for result in results if result.error is None]
    usage_complete = all(
        result.input_tokens is not None and result.output_tokens is not None for result in results
    )
    return RunReport(
        id=uuid.uuid4().hex,
        created_at=datetime.now(UTC).isoformat(),
        provider=provider.name,
        model=provider.model,
        prompt=prompt,
        prompt_hash=prompt_hash(prompt),
        suite_hash=suite_hash(cases),
        repetitions=repetitions,
        scope=(
            "REPLAY DEMO: authored responses; no LLM inference or model-quality measurement."
            if provider.name == "replay"
            else "Authored regression suite; exact checks do not establish general model quality."
        ),
        summary={
            "passed": sum(result.passed for result in results),
            "total": len(results),
            "pass_rate": sum(result.passed for result in results) / len(results),
            "provider_errors": sum(result.error is not None for result in results),
            "latency_p50_ms": percentile(measured, 0.5),
            "latency_p95_ms": percentile(measured, 0.95),
            "latency_samples": len(measured),
            "input_tokens": sum(result.input_tokens or 0 for result in results)
            if usage_complete
            else None,
            "output_tokens": sum(result.output_tokens or 0 for result in results)
            if usage_complete
            else None,
            "categories": categories,
        },
        results=results,
    )


def compare(baseline: RunReport, candidate: RunReport) -> dict:
    if baseline.suite_hash != candidate.suite_hash:
        raise ValueError("Reports use different suites; comparisons would be misleading")
    if baseline.repetitions != candidate.repetitions:
        raise ValueError("Reports use different repetition counts")
    if baseline.provider != candidate.provider or baseline.model != candidate.model:
        raise ValueError("Prompt comparison requires the same provider and model")

    def outcomes(report):
        grouped = {}
        for result in report.results:
            grouped.setdefault(result.case_id, []).append(result.passed)
        return {key: sum(value) / len(value) for key, value in grouped.items()}

    before, after = outcomes(baseline), outcomes(candidate)
    if before.keys() != after.keys():
        raise ValueError("Case IDs differ")
    return {
        "baseline": baseline.id,
        "candidate": candidate.id,
        "pass_rate_delta": candidate.summary["pass_rate"] - baseline.summary["pass_rate"],
        "regressions": [key for key in before if after[key] < before[key]],
        "improvements": [key for key in before if after[key] > before[key]],
        "scope": "Observed differences, not a significance test. Model/runtime versions may differ.",
    }

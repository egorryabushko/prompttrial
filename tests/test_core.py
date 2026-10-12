import asyncio
import json

import httpx
import pytest

from prompttrial.checks import check
from prompttrial.models import Case
from prompttrial.prompts import messages
from prompttrial.providers import LocalProvider, ReplayProvider
from prompttrial.runner import compare, percentile, run_suite
from prompttrial.store import ReportStore, markdown
from prompttrial.suites import load_suite, suite_hash


@pytest.fixture
def case():
    return Case(
        id="sample",
        category="extraction",
        task="Return count as integer in JSON.",
        input="There are 3 items.",
        checker="json_exact",
        expected={"count": 3},
        replay_output='{"count":3}',
    )


@pytest.mark.parametrize(
    "output",
    [
        '{"count":true}',
        '{"count":"3"}',
        '{"count":3.0}',
        '{"count":3,"extra":1}',
        '{"count":0,"count":3}',
        '```json\n{"count":3}\n```',
        '{"count":NaN}',
        '{"count":Infinity}',
        '{"count":3} commentary',
        "null",
    ],
)
def test_strict_json_rejects_invalid_values(case, output):
    assert check(case, output)[0] is False


def test_json_whitespace_allowed_and_exact_refusal_enforced(case):
    assert check(case, ' { "count": 3 } \n')[0]
    refusal = case.model_copy(update={"checker": "exact", "expected": "INSUFFICIENT_INFORMATION"})
    assert check(refusal, "INSUFFICIENT_INFORMATION\n")[0]
    assert not check(refusal, "INSUFFICIENT_INFORMATION, but probably tomorrow")[0]


def test_suite_integrity_and_expected_values_not_in_model_prompt(case, tmp_path):
    cases = load_suite()
    assert len(cases) == 24
    assert len({c.id for c in cases}) == 24
    assert {c.category for c in cases} == {"extraction", "arithmetic", "injection", "abstention"}
    modified = case.model_copy(update={"expected": {"answer": "HIDDEN_EXPECTATION"}})
    assert "HIDDEN_EXPECTATION" not in json.dumps(messages(modified, "strict"))
    assert suite_hash([case]) != suite_hash([modified])
    assert suite_hash([case]) == suite_hash([case.model_copy(update={"replay_output": "changed"})])
    file = tmp_path / "duplicate.json"
    file.write_text(json.dumps([case.model_dump(), case.model_dump()]))
    with pytest.raises(ValueError, match="unique"):
        load_suite(file)


async def test_replay_metrics_and_prompt_comparison():
    cases = load_suite()
    before = await run_suite(cases, ReplayProvider(), "basic")
    after = await run_suite(cases, ReplayProvider(), "strict")
    assert before.summary["passed"] == 20
    assert before.summary["total"] == 24
    assert before.summary["input_tokens"] is None
    assert "no LLM inference" in before.scope
    assert before.prompt_hash != after.prompt_hash
    assert compare(before, after)["pass_rate_delta"] == 0
    assert compare(before, after)["regressions"] == []


async def test_regression_per_case_across_repetitions(case):
    baseline = await run_suite([case], ReplayProvider(), "basic", repetitions=3)
    candidate = await run_suite(
        [case.model_copy(update={"replay_output": "wrong"})],
        ReplayProvider(),
        "strict",
        repetitions=3,
    )
    assert compare(baseline, candidate)["regressions"] == [case.id]
    with pytest.raises(ValueError, match="suites"):
        compare(baseline, candidate.model_copy(update={"suite_hash": "different"}))
    with pytest.raises(ValueError, match="repetition"):
        compare(baseline, candidate.model_copy(update={"repetitions": 1}))
    with pytest.raises(ValueError, match="same provider"):
        compare(baseline, candidate.model_copy(update={"model": "different"}))


async def test_provider_failure_redacted_and_not_in_latency(case):
    class Broken:
        name, model = "local", "test"

        async def complete(self, case, prompt):
            raise RuntimeError("SECRET http://private-server/path")

    result = await run_suite([case], Broken(), "strict")
    assert result.summary["provider_errors"] == 1
    assert result.summary["latency_samples"] == 0
    assert result.summary["input_tokens"] is None
    assert "SECRET" not in result.model_dump_json()
    assert result.results[0].error == "RuntimeError"


async def test_timeout_and_cancellation(case):
    class Slow:
        name, model = "local", "test"

        async def complete(self, case, prompt):
            await asyncio.sleep(20)

    result = await run_suite([case], Slow(), "strict", timeout=0.01)
    assert result.results[0].error == "TimeoutError"
    task = asyncio.create_task(run_suite([case], Slow(), "strict"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_local_wire_contract_and_usage(case, monkeypatch):
    monkeypatch.setenv("PROMPTTRIAL_MODEL", "test-local")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"count":3}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await run_suite([case], LocalProvider(client), "strict")
    assert report.summary["input_tokens"] == 10
    assert report.summary["output_tokens"] == 4
    assert requests[0]["model"] == "test-local"
    assert requests[0]["max_tokens"] == 256
    assert requests[0]["stream"] is False
    assert report.results[0].passed


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://localhost.evil.test/v1",
        "file:///tmp/model",
        "http://secret@localhost/v1",
        "http://127.0.0.1/v1?token=secret",
    ],
)
def test_local_provider_restricts_destinations(monkeypatch, url):
    monkeypatch.setenv("PROMPTTRIAL_MODEL", "test")
    monkeypatch.setenv("PROMPTTRIAL_BASE_URL", url)
    with pytest.raises(ValueError, match="loopback"):
        LocalProvider(None)


async def test_persistence_path_validation_and_corrupt_file(case, tmp_path):
    store = ReportStore(tmp_path)
    report = await run_suite([case], ReplayProvider(), "strict")
    store.save(report)
    assert store.get(report.id) == report
    assert store.list()[0]["id"] == report.id
    assert "results" not in store.list()[0]
    (tmp_path / "bad.json").write_text("not JSON")
    assert len(store.list()) == 1
    with pytest.raises(ValueError):
        store.get("../../secrets")
    assert "Suite SHA-256" in markdown(report)


def test_percentile_nearest_rank():
    assert percentile([1, 2, 3, 4], 0.5) == 2
    assert percentile([1, 2, 3, 4], 0.95) == 4
    assert percentile([], 0.95) == 0

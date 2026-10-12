from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Case(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    category: Literal["extraction", "arithmetic", "injection", "abstention"]
    task: str = Field(min_length=1, max_length=4000)
    input: str = Field(max_length=8000)
    checker: Literal["json_exact", "exact"]
    expected: dict | list | str
    replay_output: str = Field(max_length=10000)

    @model_validator(mode="after")
    def compatible_expected(self):
        if self.checker == "exact" and not isinstance(self.expected, str):
            raise ValueError("exact checker requires a string expectation")
        if self.checker == "json_exact" and not isinstance(self.expected, (dict, list)):
            raise ValueError("json_exact checker requires an object or array")
        return self


class CaseResult(BaseModel):
    case_id: str
    category: str
    task: str
    input: str
    expected: dict | list | str
    output: str
    passed: bool
    reason: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None


class RunReport(BaseModel):
    id: str
    created_at: str
    provider: str
    model: str
    prompt: str
    prompt_hash: str
    suite_hash: str
    repetitions: int
    scope: str
    summary: dict
    results: list[CaseResult]


class RunRequest(BaseModel):
    provider: Literal["replay", "local"] = "replay"
    prompt: Literal["basic", "strict"] = "strict"
    repetitions: int = Field(default=1, ge=1, le=5)

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from prompttrial.models import Case
from prompttrial.prompts import messages


@dataclass
class Completion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ReplayProvider:
    model = "authored-response-fixtures"
    name = "replay"

    async def complete(self, case: Case, prompt: str) -> Completion:
        await asyncio.sleep(0)
        return Completion(case.replay_output)


class LocalProvider:
    name = "local"

    def __init__(self, client: httpx.AsyncClient):
        self.model = os.environ.get("PROMPTTRIAL_MODEL", "")
        self.base_url = os.environ.get("PROMPTTRIAL_BASE_URL", "http://127.0.0.1:11434/v1")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Local provider requires a loopback HTTP(S) server URL")
        if not self.model:
            raise ValueError("Set PROMPTTRIAL_MODEL to an already served local model")
        self.client = client

    async def complete(self, case: Case, prompt: str) -> Completion:
        response = await self.client.post(
            self.base_url.rstrip("/") + "/chat/completions",
            json={
                "model": self.model,
                "messages": messages(case, prompt),
                "temperature": 0,
                "max_tokens": 256,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        if not isinstance(text, str) or len(text) > 10000:
            raise ValueError("Invalid or oversized model output")
        usage = data.get("usage") or {}
        return Completion(text, usage.get("prompt_tokens"), usage.get("completion_tokens"))

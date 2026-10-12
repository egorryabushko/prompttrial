import hashlib
import json
from pathlib import Path

from prompttrial.models import Case

DEFAULT_SUITE = Path(__file__).parent / "data" / "suite.json"


def load_suite(path: Path = DEFAULT_SUITE) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = [Case.model_validate(item) for item in raw]
    if not cases or len(cases) > 200:
        raise ValueError("Suite must contain 1–200 cases")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Case IDs must be unique")
    return cases


def suite_hash(cases: list[Case]) -> str:
    # Replay outputs are fixtures, not part of the actual model evaluation contract.
    payload = [case.model_dump(exclude={"replay_output"}) for case in cases]
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()

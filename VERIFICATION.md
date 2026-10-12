# Observed verification

Date: 2026-10-12. Host: macOS, Python 3.13.0.

- Installed the project and its development dependencies in a project-local virtual environment.
- 27 automated tests passed. Tests cover strict JSON field types, duplicate keys,
  NaN/Infinity, extra output, exact abstention, fixture integrity, expected-answer isolation,
  suite/prompt hashes, regression comparison, repeated trials, provider errors, request
  timeouts, cancellation, local adapter wire format and reported token usage, report
  persistence, path validation, API history and exports, and one-active-job admission.
- Ruff lint and formatting checks passed; the browser script passed Node's syntax check.
- `pip check` reported no broken dependency requirements.
- The replay CLI processed all 24 cases: 20 passed and the four deliberately incorrect
  authored responses failed. This is pipeline verification, not measured LLM quality.
- A replay run with `--fail-under 0.9` saved its reports and exited with status 1,
  correctly rejecting the observed 20/24 fixture pass rate.
- Browser checks exercised both prompt versions, history, case details, comparison,
  Markdown download and restoring completed history after page reload.
- The comparison of replay basic/strict runs showed zero improvement, as expected:
  replay returns the same fixture responses for both prompts.
- Built a wheel and inspected its contents: the test suite JSON and HTML/CSS/JavaScript
  assets are packaged. `preview.png` records the browser workspace.

## Not verified

- No local LLM server was listening on the checked default ports 8080 or 11434.
  The local model adapter was tested with mocked HTTP responses, not real model inference.
- Docker is not installed on this host; the Dockerfile and CI container smoke are supplied
  but a runtime container was not built here.
- GitHub CI has not run for this new local project. No new GitHub repository has been published.
- Python 3.11 and Linux execution are declared CI checks, not locally observed runs.

The suite is authored development data. It is not independently labeled held-out evaluation.
No claim about model performance, security, cost or production readiness follows from this run.

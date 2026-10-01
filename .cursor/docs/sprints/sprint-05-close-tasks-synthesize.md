# Sprint 05 — Close-tasks synthesize

## Goal

A person can synthesize tasks from the close-tasks tab and see the grouped list come back from `POST /v1/analyze/synthesize`. Closing the Redmine issues still happens in this app with the local session. After that, the desktop no longer contains `services/ai_api_request.py`.

## Depends on

Sprint 04

## In scope

- `synthesize_tasks_for_redmine` becomes a wrapper in `services/api_client.py` over `POST /v1/analyze/synthesize`. It still returns a list of tasks so `layout/tab_close_tasks.py` can keep its `synthesize_fn` argument.
- Point `layout/tab_close_tasks.py` at that wrapper. Its model dropdown uses `GET /v1/models`, with the same offline fallback as the analysis tab until the first successful fetch. Remove the client copy of `MODEL_CONFIGS` once both tabs take the list from the server or from that fallback constant in `services/api_client.py`.
- Redmine closing stays in `task_automation.py`. Do not send the Redmine session, password, or cookies to the API.
- Delete `services/ai_api_request.py` from this repo only after `api_client` returns the dict the analysis tab already expects and the list the close-tasks tab already expects, and a manual run of both against a local API succeeds.

## Out of scope

- Config tab fields, `GE_TXT_DEFAULTS`, and `.env.example` (`CLAUDE_KEY` removal is sprint 06).
- Packaging and the version bump.
- Moving `create_ai_redmine_tasks`, `layout/tab_banco_horas.py`, or fechamento assembly to the API.

## Touches

- This repo: `services/api_client.py`, `layout/tab_close_tasks.py`. Delete `services/ai_api_request.py`.
- Calls `GeradorApi` `POST /v1/analyze/synthesize`. `task_automation.py` stays local.

## Done when

- Synthesize on the close-tasks tab sends `model`, `tasks`, and `min_hours` to `POST /v1/analyze/synthesize` and shows the returned tasks.
- The API access log for that action contains no Redmine host, no Redmine password, and no Git token.
- Closing issues still runs through `task_automation.py` on the local session.
- This repo has no `services/ai_api_request.py`. Neither `layout/tab_ai_analysis.py` nor `layout/tab_close_tasks.py` imports it.
- A manual analysis run and a manual synthesize run against a local API both succeed before the file is deleted.

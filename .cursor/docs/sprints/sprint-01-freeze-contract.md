# Sprint 01 — Freeze the HTTP contract

## Goal

A person can show the GeradorApi schema module accepting the request and response JSON from the split plan, and a short confirmation that those fields match what `analyze_diffs_grouped_with_claude`, `synthesize_tasks_for_redmine`, and `_save_units_checkpoint` produce today.

## Depends on

none

## In scope

- Create the sibling repo `GeradorApi` (its own git repo, not a package inside this app) with `core/schemas.py`, `requirements.txt` listing fastapi, uvicorn, requests, and pydantic, `.env.example` naming `CLAUDE_KEY`, `API_TOKEN`, and optional `ANTHROPIC_BASE_URL`, and a README that records the contract.
- Pydantic models for `GET /v1/models`, `POST /v1/analyze/unit`, `POST /v1/analyze/merge`, `POST /v1/analyze/estimate`, `POST /v1/analyze/pack`, and `POST /v1/analyze/synthesize`, using the JSON in the plan.
- The task object follows `TASK_SCHEMA` in `services/ai_api_request.py`, plus `commit_links` on the unit response and `task_id` once pack assigns it.
- Record the non-HTTP shapes the client must keep: the dict returned by `analyze_diffs_grouped_with_claude` (`tasks`, `mathematical_reconciliation`, `atribuicao_catalogo`, `min_hours`, and when present `partial`, `cancelled_after_units`, `total_units`, `failed_units`), the list returned by `synthesize_tasks_for_redmine`, and checkpoint keys `completed_units`, `total_units`, `processed_labels`, `failed_labels`, `unit_tasks`.
- Record status rules: bearer on every route except a future health check, `401` for a missing or wrong token, `422` for invalid input, `502` when Claude fails, error body `{"detail": "..."}`, and the Portuguese truncation text already raised for `stop_reason=max_tokens`.
- Record limits that both sides must enforce: `MAX_DIFF_CHARS` 150000, `MAX_UNIT_CHARS` 120000, `MIN_DIFF_CHARS` 150, `AI_BATCH_SIZE` 40.
- `GET /v1/models` lists the five current `MODEL_CONFIGS` entries, not the two-item sample in the plan. `target_total_hours` is the sum of task hours, as `_finalize_free_hours` does.

## Out of scope

- Copying `services/ai_api_request.py` or calling Claude.
- FastAPI routes, the desktop app, config keys, and packaging.
- A shared installable package for the schema.

## Touches

- New repo `GeradorApi`: `core/schemas.py`, `requirements.txt`, `.env.example`, `README.md`.
- Read-only reference in this repo: `services/ai_api_request.py` (`TASK_SCHEMA`, `MODEL_CONFIGS`, `analyze_diffs_grouped_with_claude`, `synthesize_tasks_for_redmine`, `_save_units_checkpoint`).

## Done when

- From `GeradorApi`, a check loads `core/schemas.py` and accepts the sample unit, merge, estimate, pack, and synthesize payloads from the plan, and the five-model list from `MODEL_CONFIGS`.
- The same check rejects a unit body that has no `content`.
- The README lists the analyze return keys, the synthesize list, and the checkpoint keys above, and states that one HTTP call is one pipeline step.

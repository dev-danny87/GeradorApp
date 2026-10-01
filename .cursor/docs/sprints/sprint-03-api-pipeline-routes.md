# Sprint 03 — Merge, estimate, pack, and synthesize

## Goal

A person can drive one analysis by calling merge, then estimate, then pack as three HTTP requests, and can call synthesize on its own. The server stores nothing between those calls. This is the API check that must pass before the Flet app switches over.

## Depends on

Sprint 02

## In scope

- `POST /v1/analyze/merge` runs `_merge_tasks_chunked` with `_build_merge_tasks_prompt`. It accepts `model`, `tasks`, and `min_hours` (`min_hours` is unused by the current merge prompt). `"cancel_hint": true` finishes the current batch and returns what it has.
- `POST /v1/analyze/estimate` runs `_estimate_hours_chunked` and returns `mathematical_reconciliation` from `_finalize_free_hours` plus the adjusted tasks. `target_total_hours` is the sum of the task hours. A model id outside `MODEL_CONFIGS` is `422`.
- `POST /v1/analyze/pack` does not call Claude. It runs `_pack_tasks_to_min_hours`, `_assign_task_ids` (`task-0001`, ...), and returns the same wrapper as `_pack_and_stamp`: reconciliation, tasks, `atribuicao_catalogo`, and `min_hours`.
- `POST /v1/analyze/synthesize` matches `synthesize_tasks_for_redmine`: AI grouping, then packing so each task has at least `min_hours` while the original total is preserved. Response is `{"tasks": []}`.
- Map Claude failures and validation errors the way the plan states: `502` when the upstream call failed, `422` when the input is invalid, body `{"detail": "..."}`, including the existing Portuguese `stop_reason=max_tokens` message.
- These routes stay stateless. They do not write `ai_tasks_checkpoint.json` and they do not read Redmine or Git credentials.

## Out of scope

- The desktop loop, cancel button, and checkpoint file. Those stay in sprint 04.
- Close-tasks UI, Config tab, and the installer.
- A server-side job queue, websockets, or stored checkpoints.

## Touches

- `GeradorApi`: `app/routes/analyze.py`, `core/ai_pipeline.py`, `core/schemas.py`, `README.md`.

## Done when

- Merge on a task list keeps every input index represented, the same rule as `_validate_merge_groups`.
- Estimate with a model id that is not in `MODEL_CONFIGS` returns `422`.
- Pack with `min_hours` 8 never returns a task under 8 hours, except when the result is a single task whose total is already under 8 (including the current case that collapses every task into one when their sum is under `min_hours`).
- Synthesize returns a task list whose hours still sum to the input total.
- Pack and `GET /v1/models` finish in well under 30 seconds. Unit, merge, and estimate are allowed to run for several minutes; the README states the client timeout of at least 10 minutes for those three.
- Calling the four routes in sequence does not create a checkpoint or any other server-side resume file.

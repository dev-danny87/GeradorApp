# Sprint 04 — Client analysis adapter

## Goal

A person can analyze a diff folder from the existing analysis tab, stop mid-run, and run again. The second run skips labels already stored in `ai_tasks_checkpoint.json`. The tab still shows `[step/total] message`. A down API shows the error on that same status line. Redmine issue creation from the result still uses the local session.

## Depends on

Sprint 03

## In scope

- Add `services/api_client.py` in this repo. It reproduces the control flow of `analyze_diffs_grouped_with_claude` by calling the API. It does not call Claude and does not send `CLAUDE_KEY`.
- The function the tab calls keeps the same arguments: `diff_items`, `selected_model`, `on_progress(step, total, message)`, `output_dir`, `should_cancel`, `atribuicao_catalogo`, `min_hours`.
- Progress stays `total_steps = len(units) + 3` (units, merge, estimate, pack).
- The client splits oversized files with the same rules as `_build_diff_units` before `POST /v1/analyze/unit`. One call sends one unit.
- The client writes `ai_tasks_checkpoint.json` in the diff folder after every unit, including failed labels. Shape and the “labels and `unit_tasks` must stay the same length, otherwise reprocess” rule stay as `_load_units_checkpoint` does today. Keep the filename `ai_tasks_checkpoint.json` so `utils/fechamento_builder.py` still finds it.
- `should_cancel` is checked between HTTP calls. After at least one successful unit, cancel calls only `POST /v1/analyze/pack` on the tasks gathered so far and sets `partial: true`, `cancelled_after_units`, and `total_units`. It does not call merge or estimate. If that pack call fails, surface the error. Do not pack with a silent local copy.
- A unit `422` records that label in `failed_labels` and the run continues.
- HTTP timeouts are at least 10 minutes for unit, merge, and estimate, and under 30 seconds for pack and models.
- The analysis tab imports `services/api_client.py` instead of `analyze_diffs_grouped_with_claude`. After the payload returns, the tab still adds `source_diff_folder`, `generated_at`, `generated_by`, and `model`, then `save_results` writes `./ai_tasks`.
- The model dropdown calls `GET /v1/models` when the tab is built and falls back to the current `MODEL_CONFIGS` keys if that call fails.
- Read `API_BASE_URL` and `API_TOKEN` through `get_config`. For this sprint they may be set in the environment or in `ge.txt` by hand. The Config tab fields arrive in sprint 06.
- `create_ai_redmine_tasks` stays in this repo. `layout/tab_banco_horas.py` is unchanged.

## Out of scope

- `layout/tab_close_tasks.py` and deleting `services/ai_api_request.py` (sprint 05 still imports that module).
- Removing `CLAUDE_KEY` from the Config tab, `GE_TXT_DEFAULTS`, or `.env.example`.
- `flet pack` and the Inno Setup version bump.
- Sending Redmine passwords, session cookies, or Git tokens to the API.

## Touches

- This repo: `services/api_client.py`, `layout/tab_ai_analysis.py`.
- Calls `GeradorApi` routes from sprint 03. Does not change Redmine, Git, or evidence modules.

## Done when

- Analyzing a folder with two diff files writes `ai_tasks_checkpoint.json` in that folder and a result under the ai-tasks directory. The status line shows `[step/total] message`.
- Cancel after the first file saves a payload with `partial: true`. The API access log shows pack and no merge or estimate for that cancel.
- A second run on the same folder does not call `/v1/analyze/unit` for labels already in the checkpoint.
- Stopping the API and starting an analysis shows `Erro no processamento com IA: ...` on the status line, using the response `detail` when the API returned one.
- Creating Redmine tasks from the result still uses `create_ai_redmine_tasks`. No Redmine host appears in the API access log.
- The diff tab still calls GitLab or GitHub directly. `GITLAB_TOKEN` and `GITHUB_TOKEN` do not appear in API requests.
- `layout/tab_close_tasks.py` still imports `services/ai_api_request.py`. That file is still in this repo.

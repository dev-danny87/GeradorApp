# Sprints

Source: `.cursor/docs/standalone-client-api-split.md`

## Sequence

| Sprint | Title | Depends on | Outcome |
| --- | --- | --- | --- |
| 01 | Freeze the HTTP contract | none | GeradorApi has pydantic models for every request and response in the plan, checked against the current task JSON, synthesize list, and checkpoint keys. |
| 02 | API auth and unit route | 01 | A local GeradorApi accepts one diff file, rejects a bad bearer token, and refuses to start without `CLAUDE_KEY`. |
| 03 | Merge, estimate, pack, and synthesize | 02 | The remaining analyze routes run as separate stateless calls, including the API checks that must pass before the Flet switch. |
| 04 | Client analysis adapter | 03 | The analysis tab runs the same loop through `services/api_client.py`, with checkpoint resume and cancel between calls. |
| 05 | Close-tasks synthesize | 04 | The close-tasks tab groups tasks through `POST /v1/analyze/synthesize`, and the desktop copy of the Claude module is removed. |
| 06 | Desktop config | 05 | Config stores `API_BASE_URL` and `API_TOKEN`. `CLAUDE_KEY` is no longer a desktop setting. |
| 07 | Package the desktop app | 06 | The Flet installer ships the client that cannot analyze without the API, with the app version and Inno Setup version bumped together. |

## Mismatches

- `GET /v1/models` in the plan shows two sample models. `MODEL_CONFIGS` in `services/ai_api_request.py` has five: `claude-sonnet-5` (65536), `claude-opus-4-8` (16384), `claude-haiku-4-5-20251001` (32768), `claude-opus-5-5` (128000), `claude-sonnet-5-5` (128000). The plan already says to ship whatever that dict contains. These sprints use the five live entries. A second dict, `MAX_OUTPUT_TOKENS`, uses different ceilings (for example `claude-sonnet-5` is 131072). The models route does not expose it. The copied pipeline keeps it as the Claude call ceiling.
- The estimate and pack samples set `target_total_hours` to `40.0`. `_finalize_free_hours` sets that field to the sum of `estimated_hours`. These sprints follow that function. The sample number is only the field’s shape.
- `CHECKPOINT_FILENAME` (`ai_tasks_checkpoint.json`) is defined in both `services/ai_api_request.py` and `utils/fechamento_builder.py`. The string matches. Fechamento stays on the client and keeps reading that filename.
- The plan’s pack request sentence lists `tasks`, `min_hours`, and a rationale string. It does not name the JSON key, and it omits `atribuicao_catalogo`, which `_pack_and_stamp` writes onto the response. These sprints send `allocation_rationale_pt` and `atribuicao_catalogo` on `POST /v1/analyze/pack`.
- `layout/tab_close_tasks.py` has no model dropdown. It passes `list(MODEL_CONFIGS.keys())[0]` into `regenerate_fechamento` as `selected_model`. `utils/fechamento_builder.py` calls `synthesize_fn(tasks, selected_model, min_hours=...)`. Sprint 05 keeps that call and takes the first id from `GET /v1/models`.
- `save_ge_txt` in `utils/app_config.py` rewrites `~/taskManager/ge.txt` with only `GE_TXT_DEFAULTS` keys. Removing `CLAUDE_KEY` from that list would delete a leftover line on the next Config save. The plan says not to delete it automatically. Sprint 06 preserves an existing `CLAUDE_KEY` line.
- The app README still documents `%USERPROFILE%\ge.txt`. The code uses `~/taskManager/ge.txt` and moves a legacy `~/ge.txt` only when the new file is missing. Sprint 06 corrects the README config section.

None of these make a sprint impossible. Cited files still exist and the boundary matches the plan: Redmine login, Git fetch, evidence download, and issue writes stay in this repo; Claude, merge, estimates, packing, and `synthesize_tasks_for_redmine` are what move.

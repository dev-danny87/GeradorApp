first install requirements.txt

```shell
pip install -r requirements.txt
```
then activate the venv
```shell
.\.venv\Scripts\activate
```

to create the .exe run the build.bat file


if you need to recreate venv
````shell
python -m venv .venv
````

To create the package use
````
flet pack main.py --name "Gerador_Redmine" --icon "icon.ico"
````

## Config and output files

### ge.txt (config)

On startup, `main.py` calls `ensure_ge_txt()` (`utils/app_config.py`). If the file does not exist, it creates an empty template; it never overwrites an existing file.

- **Windows path:** `%USERPROFILE%\ge.txt` (e.g. `C:\Users\<you>\ge.txt`)
- **Other OS:** `~/ge.txt`
- **Priority:** values in a project `.env` (see `.env.example`) win over `ge.txt` when set

Keys written into the template:

- `RD_HOST` / `RD_USER` / `RD_PASS` — Redmine host/credentials (reserved for future/local use)
- `CLAUDE_KEY` — Anthropic API key (AI analysis)
- `GITLAB_TOKEN` / `GITHUB_TOKEN` — API tokens for the Diff tab
- `GITLAB_DEFAULT_AUTHOR` / `GITHUB_DEFAULT_AUTHOR` — default author usernames on the Diff tab
- `DIFF_DEFAULT_PLATFORM` — `gitlab` or `github`
- `STARTING_DATE` / `STARTING_VERSAO` — anchors for dynamic Redmine version calculation
- `THREADS` — worker count hint for parallel downloads

### Output / log files

- `./diffs/Diffs_Filtro_<author>_<timestamp>/diff_YYYY-MM-DD.txt` — Diff tab daily GitLab/GitHub export; the `./diffs` folder is wiped and recreated on each run
- `./ai_tasks/ai_tasks_<user>_<timestamp>.json` — AI analysis results saved for import into the Tasks tab
- `<evidencias>/registro_de_erros.txt` — IPHAN evidence error log, written inside the evidence output directory only when errors occurred
- Console / terminal — task creation, auth, and evidence progress via `print` / `logging` (not persisted to a log file)

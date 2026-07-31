first install requirements.txt

```shell
pip install -r requirements.txt
```
then activate the venv
```shell
.\.venv\Scripts\activate
```

if you need to recreate venv
```shell
python -m venv .venv
```

## Build standalone .exe

```shell
flet pack main.py --name "Gerador_Redmine" --icon "icon.ico"
```

Or build exe + Windows installer (requires [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
winget install JRSoftware.InnoSetup
.\scripts\build_installer.ps1
```

Output: `dist\Gerador_Redmine.exe` and `dist_installer\Gerador_Redmine_Setup.exe`.

## Release checklist (GitHub auto-update)

The app checks `https://github.com/dev-danny87/GeradorApp/releases/latest` on startup (`CURRENT_VERSION` in `main.py`). Keep the repo **public** so no GitHub token is required.

1. Bump `CURRENT_VERSION` in `main.py` and `#define MyAppVersion` in `installer/Gerador_Redmine.iss` to the same value (e.g. `1.0.1`).
2. Commit and push to `master`.
3. Run `.\scripts\build_installer.ps1` (or `flet pack` + compile the `.iss` with ISCC).
4. Create a GitHub Release with tag `v1.0.1` (leading `v` is stripped when comparing).
5. Upload **`Gerador_Redmine_Setup.exe`** as the release asset (exact filename).
6. Publish the release.

Example with GitHub CLI:

```shell
gh release create v1.0.0 dist_installer/Gerador_Redmine_Setup.exe --title "v1.0.0" --notes "Installer + auto-update"
```

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

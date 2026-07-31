import flet as ft
import os
import shutil
import datetime
from threading import Thread

from utils.app_config import get_config
from utils.ui_components import DatePickerField
from utils.month_selector import (
    apply_month_to_date_pickers,
    create_month_shortcut_dropdown,
    current_month_key,
    month_bounds,
)
from services.gitlab_service import fetch_active_projects, extract_project_diff_for_day
from services.github_service import fetch_active_repositories, extract_repos_diff_for_day

GITLAB_DEFAULT_AUTHOR = get_config("GITLAB_DEFAULT_AUTHOR")
GITHUB_DEFAULT_AUTHOR = get_config("GITHUB_DEFAULT_AUTHOR")
DIFF_DEFAULT_PLATFORM = get_config("DIFF_DEFAULT_PLATFORM", "gitlab").lower()


def _default_author_for_platform(platform: str) -> str:
    if platform == "github":
        return GITHUB_DEFAULT_AUTHOR
    return GITLAB_DEFAULT_AUTHOR


def create_diffs_tab(app_state, set_auth, sync_callbacks, diffs_listeners=None):
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_status = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)

    hoje = datetime.datetime.now().date()
    inicio_mes, fim_mes = month_bounds(hoje)

    txt_author = ft.TextField(
        label="Autor (Username Git)",
        hint_text="Username no GitLab/GitHub — não é o login do Redmine",
        width=320,
        icon=ft.Icons.PERSON_SEARCH,
    )
    date_start = DatePickerField(label="Data Inicial", default_date=inicio_mes, width=180)
    date_end = DatePickerField(label="Data Final", default_date=fim_mes, width=180, icon=ft.Icons.EVENT)

    def on_month_change(e):
        if not dropdown_month.value:
            return
        apply_month_to_date_pickers(dropdown_month.value, date_start, date_end)
        if date_start.page:
            date_start.update()
            date_end.update()

    dropdown_month = create_month_shortcut_dropdown(
        on_month_change,
        value=current_month_key(hoje),
    )

    default_platform = DIFF_DEFAULT_PLATFORM if DIFF_DEFAULT_PLATFORM in ("gitlab", "github") else "gitlab"
    dropdown_platform = ft.Dropdown(
        label="Plataforma",
        width=200,
        options=[
            ft.dropdown.Option(key="gitlab", text="GitLab"),
            ft.dropdown.Option(key="github", text="GitHub"),
        ],
        value=default_platform,
    )

    repo_checkboxes: list[ft.Checkbox] = []
    repos_left_column = ft.Column(spacing=4, tight=True)
    repos_right_column = ft.Column(spacing=4, tight=True)
    repos_checkbox_row = ft.Row(
        [repos_left_column, repos_right_column],
        spacing=20,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )

    btn_select_all = ft.TextButton("Selecionar todos", visible=False)
    btn_select_none = ft.TextButton("Limpar seleção", visible=False)

    repos_scroll = ft.Column(
        [repos_checkbox_row],
        spacing=0,
        scroll=ft.ScrollMode.AUTO,
        height=220,
    )

    repos_checkbox_area = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    "Repositórios com commits no período",
                    weight=ft.FontWeight.BOLD,
                    size=13,
                ),
                repos_scroll,
                ft.Row([btn_select_all, btn_select_none], spacing=5),
            ],
            spacing=8,
            tight=True,
        ),
        padding=12,
        border=ft.border.all(1, ft.Colors.BLUE_GREY_300),
        border_radius=8,
        width=700,
        visible=False,
    )

    btn_load_repositories = ft.ElevatedButton(
        "Carregar Repositórios",
        icon=ft.Icons.FOLDER_OPEN,
        color="white",
        bgcolor="orange",
        tooltip="Busca repositórios com commits do autor no período",
    )
    btn_execute_diff = ft.ElevatedButton(
        "Extrair Diffs",
        icon=ft.Icons.CODE,
        color="white",
        bgcolor="blue",
        visible=False,
    )

    user_header = ft.Row([
        ft.Icon(ft.Icons.PERSON, color="green", size=20),
        lbl_logged_in,
        ft.IconButton(
            icon=ft.Icons.LOGOUT,
            icon_color="red",
            icon_size=20,
            tooltip="Sair da conta",
            on_click=lambda e: set_auth(None, None, False),
        ),
    ], alignment=ft.MainAxisAlignment.END)

    diffs_view = ft.Column([
        user_header,
        ft.Text("Extração de Modificações por Repositório Escolhido", size=16, weight=ft.FontWeight.BOLD),
        ft.Row([txt_author], alignment=ft.MainAxisAlignment.CENTER),
        ft.Row([dropdown_month], alignment=ft.MainAxisAlignment.CENTER),
        ft.Row(
            [date_start, date_end],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=20,
            tight=True,
        ),
        ft.Row(
            [dropdown_platform],
            alignment=ft.MainAxisAlignment.CENTER,
            wrap=True,
            spacing=15,
        ),
        ft.Row([btn_load_repositories, btn_execute_diff, progress_ring], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
        repos_checkbox_area,
        lbl_status,
    ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15, expand=True,
        scroll=ft.ScrollMode.AUTO)

    def _refresh_ui():
        page = diffs_view.page
        if page:
            page.update()

    def _schedule_ui_refresh():
        _refresh_ui()

    def show_status(text: str, color: str):
        lbl_status.value = text
        lbl_status.color = color
        lbl_status.visible = True

    def _notify_diffs_changed():
        """Lets the Análise com IA tab pick up the folders just exported."""
        for listener in diffs_listeners or []:
            try:
                listener()
            except Exception as ex:
                print(f"[WARN] Falha ao notificar alteração de diffs: {ex}")

    def _set_checkbox_values(checked: bool):
        for cb in repo_checkboxes:
            cb.value = checked
        btn_execute_diff.visible = checked and bool(repo_checkboxes)
        _refresh_ui()

    def _on_repo_checkbox_change(e):
        btn_execute_diff.visible = any(cb.value for cb in repo_checkboxes)
        _refresh_ui()

    def _rebuild_repo_checkboxes(repos: list, platform: str):
        repo_checkboxes.clear()
        repos_left_column.controls.clear()
        repos_right_column.controls.clear()

        for index, repo in enumerate(repos):
            if platform == "gitlab":
                key = str(repo["id"])
                label = repo.get("name") or key
            else:
                key = repo.get("full_name") or repo.get("name") or ""
                label = key

            checkbox = ft.Checkbox(
                label=label,
                value=True,
                data=key,
                on_change=_on_repo_checkbox_change,
            )
            repo_checkboxes.append(checkbox)
            if index % 2 == 0:
                repos_left_column.controls.append(checkbox)
            else:
                repos_right_column.controls.append(checkbox)

        has_repos = bool(repos)
        repos_checkbox_area.visible = has_repos
        btn_select_all.visible = has_repos
        btn_select_none.visible = has_repos
        btn_execute_diff.visible = has_repos

    def _clear_repository_selection():
        _rebuild_repo_checkboxes([], dropdown_platform.value or "gitlab")
        btn_execute_diff.visible = False

    def _get_selected_repo_keys() -> list:
        return [str(cb.data) for cb in repo_checkboxes if cb.value and cb.data]

    def _apply_author_for_platform(platform: str):
        default_author = _default_author_for_platform(platform)
        if default_author:
            txt_author.value = default_author

    def on_platform_change(e):
        _clear_repository_selection()
        _apply_author_for_platform(dropdown_platform.value or "gitlab")
        _refresh_ui()

    dropdown_platform.on_change = on_platform_change

    def handle_load_repositories(e):
        platform = dropdown_platform.value
        author = (txt_author.value or "").strip()

        if not platform:
            show_status("Selecione uma plataforma.", "red")
            return
        if not author:
            show_status("Preencha o autor (username Git) para buscar repositórios.", "red")
            return

        try:
            start_date_str = date_start.value.strip()
            end_date_str = date_end.value.strip()
            datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
            datetime.datetime.strptime(end_date_str, "%Y-%m-%d")
        except ValueError:
            show_status("Formato de data inválido.", "red")
            return

        btn_load_repositories.disabled = True
        progress_ring.visible = True
        show_status(f"Buscando repositórios com commits ({platform})...", "blue")
        _refresh_ui()

        def bg_load():
            try:
                if platform == "gitlab":
                    repos = fetch_active_projects(author, start_date_str, end_date_str)
                else:
                    repos = fetch_active_repositories(author, start_date_str, end_date_str)

                _rebuild_repo_checkboxes(repos, platform)

                if repos:
                    show_status(f"{len(repos)} repositório(s) com atividade no período.", "green")
                else:
                    show_status(
                        "Nenhum repositório com commits encontrado para o autor no período.",
                        "orange",
                    )

            except Exception as ex:
                _clear_repository_selection()
                show_status(f"Falha ao carregar repositórios: {str(ex)}", "red")
            finally:
                btn_load_repositories.disabled = False
                progress_ring.visible = False
                _schedule_ui_refresh()

        Thread(target=bg_load, daemon=True).start()

    def handle_execute_diff(e):
        platform = dropdown_platform.value
        selected_repos = _get_selected_repo_keys()
        author = (txt_author.value or "").strip()

        if not platform:
            show_status("Selecione uma plataforma.", "red")
            return
        if not selected_repos:
            show_status("Selecione ao menos um repositório.", "red")
            return
        if not author:
            show_status("Preencha o autor para prosseguir.", "red")
            return

        try:
            start_date = datetime.datetime.strptime(date_start.value.strip(), "%Y-%m-%d").date()
            end_date = datetime.datetime.strptime(date_end.value.strip(), "%Y-%m-%d").date()
        except ValueError:
            show_status("Formato de data inválido.", "red")
            return

        btn_execute_diff.disabled = True
        progress_ring.visible = True
        _refresh_ui()

        def bg_extract():
            try:
                diffs_root = os.path.join(".", "diffs")
                if os.path.exists(diffs_root):
                    shutil.rmtree(diffs_root)

                timestamp_agora = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                folder_name = f"Diffs_Filtro_{author}_{timestamp_agora}"
                output_dir = os.path.join(".", "diffs", folder_name)
                os.makedirs(output_dir, exist_ok=True)

                if platform == "gitlab":
                    repo_keys = [int(key) for key in selected_repos]
                else:
                    repo_keys = selected_repos

                delta = end_date - start_date
                for i in range(delta.days + 1):
                    current_date_str = (start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
                    show_status(f"Compilando arquivos do dia {current_date_str}...", "blue")
                    _schedule_ui_refresh()

                    if platform == "gitlab":
                        diff_content = extract_project_diff_for_day(
                            author, current_date_str, repo_keys
                        )
                    else:
                        diff_content = extract_repos_diff_for_day(
                            author, current_date_str, repo_keys
                        )

                    if diff_content is None:
                        continue

                    file_path = os.path.join(output_dir, f"diff_{current_date_str}.txt")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(diff_content)

                show_status(f"Sucesso! Diff exportado para:\n{output_dir}", "green")
                _notify_diffs_changed()
            except Exception as ex:
                show_status(f"Erro ao extrair diffs: {str(ex)}", "red")
            finally:
                btn_execute_diff.disabled = False
                progress_ring.visible = False
                _schedule_ui_refresh()

        Thread(target=bg_extract, daemon=True).start()

    def sync_ui():
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
            if not (txt_author.value or "").strip():
                _apply_author_for_platform(dropdown_platform.value or default_platform)
        else:
            lbl_status.visible = False
            btn_execute_diff.visible = False
            txt_author.value = ""
            _clear_repository_selection()

    sync_callbacks.append(sync_ui)

    btn_select_all.on_click = lambda e: _set_checkbox_values(True)
    btn_select_none.on_click = lambda e: _set_checkbox_values(False)
    btn_load_repositories.on_click = handle_load_repositories
    btn_execute_diff.on_click = handle_execute_diff

    _apply_author_for_platform(default_platform)
    sync_ui()

    return ft.Tab(
        text="Extrair Diffs",
        icon=ft.Icons.CODE_OFF,
        content=ft.Container(content=diffs_view, padding=20, expand=True),
    )

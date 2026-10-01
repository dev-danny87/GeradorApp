# tab_banco_horas.py
import flet as ft
import datetime
from threading import Thread

from diff_task_automation import create_ai_redmine_tasks
from redmine_mappings import (
    SYSTEM_OPTIONS,
    ORGAN_OPTIONS,
    PROJECT_FILTER_OPTIONS,
    ROLE_OPTIONS,
    USER_OPTIONS,
)
from layout.task_hour_list import TaskHourListView
from utils.banco_horas_store import list_banco_batches, remove_tasks_by_ids, totals
from utils.commit_metadata import strip_urls_from_description
from utils.month_selector import (
    apply_month_to_date_pickers,
    create_month_shortcut_dropdown,
    current_month_key,
    month_bounds,
)
from utils.redmine_task_defaults import redmine_task_defaults
from utils.redmine_version import (
    default_open_version_id,
    fetch_open_versions,
    get_dynamic_version,
)
from utils.task_hour_selection import ensure_task_ids, sum_task_hours
from utils.ui_components import DatePickerField


def _dropdown_from_mapping(label: str, mapping: dict, default_value: str, width: int = 350) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        width=width,
        options=[ft.dropdown.Option(key=v, text=k) for k, v in mapping.items()],
        value=default_value,
    )


def create_banco_horas_tab(
        app_state,
        set_auth,
        sync_callbacks,
        banco_listeners=None,
):
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_status = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20)
    lbl_totals = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color="purple")

    hoje = datetime.datetime.now().date()
    inicio_mes, fim_mes = month_bounds(hoje)
    defaults = redmine_task_defaults(app_state.get("user"))

    date_start = DatePickerField(
        label="Data de Início (Sprint)",
        default_date=inicio_mes,
        width=200,
        icon=ft.Icons.CALENDAR_TODAY,
    )
    date_due = DatePickerField(
        label="Data Prevista (Sprint)",
        default_date=fim_mes,
        width=200,
        icon=ft.Icons.EVENT,
    )

    def on_month_change(e):
        if not dropdown_month.value:
            return
        apply_month_to_date_pickers(dropdown_month.value, date_start, date_due)
        try:
            if date_start.page:
                date_start.update()
                date_due.update()
        except RuntimeError:
            pass

    dropdown_month = create_month_shortcut_dropdown(
        on_month_change,
        value=current_month_key(hoje),
    )

    dropdown_versao = ft.Dropdown(
        label="Versão",
        width=350,
        options=[],
        value=None,
        hint_text="Faça login para carregar as versões abertas",
    )
    dropdown_sistema = _dropdown_from_mapping("Sistema", SYSTEM_OPTIONS, defaults["sistema"])
    dropdown_orgao = _dropdown_from_mapping("Órgão solicitante", ORGAN_OPTIONS, defaults["orgao"])
    dropdown_atribuicao = _dropdown_from_mapping(
        "Atribuição Catálogo - Desenv", ROLE_OPTIONS, defaults["atribuicao"]
    )
    dropdown_projeto = _dropdown_from_mapping(
        "Projeto Vinculado", PROJECT_FILTER_OPTIONS, defaults["projeto"]
    )
    dropdown_desenvolvedor = ft.Dropdown(
        label="Desenvolvedor",
        width=350,
        options=[ft.dropdown.Option(key=v, text=k) for k, v in USER_OPTIONS.items()],
        value=defaults.get("desenvolvedor_id"),
    )

    btn_refresh = ft.ElevatedButton("Atualizar", icon=ft.Icons.REFRESH)
    btn_create = ft.ElevatedButton(
        "Gerar Tarefas no Redmine",
        icon=ft.Icons.CLOUD_UPLOAD,
        bgcolor="blue_700",
        color="white",
        disabled=True,
    )

    batch_column = ft.Column(spacing=10, tight=True)
    task_lists: list[tuple[dict, TaskHourListView]] = []

    wrapper = ft.Container(
        content=ft.Column(
            [
                ft.Text("Banco de Horas", weight=ft.FontWeight.BOLD, size=15, color="purple"),
                lbl_totals,
                ft.Row([btn_refresh, btn_create], alignment=ft.MainAxisAlignment.START, wrap=True),
                ft.Divider(),
                batch_column,
                ft.Text("Campos Redmine (tarefa pai e subtarefas)", weight=ft.FontWeight.BOLD, size=13),
                ft.Row([dropdown_month], alignment=ft.MainAxisAlignment.START),
                ft.Row([date_start, date_due], alignment=ft.MainAxisAlignment.START, spacing=20, tight=True),
                ft.Row([dropdown_versao], alignment=ft.MainAxisAlignment.START),
                ft.Row([dropdown_sistema, dropdown_orgao], alignment=ft.MainAxisAlignment.START, wrap=True),
                ft.Row(
                    [dropdown_atribuicao, dropdown_projeto],
                    alignment=ft.MainAxisAlignment.START,
                    wrap=True,
                ),
                ft.Row([dropdown_desenvolvedor], alignment=ft.MainAxisAlignment.START, wrap=True),
            ],
            spacing=10,
            tight=True,
        ),
        padding=15,
        border=ft.border.all(1, ft.Colors.PURPLE_300),
        border_radius=10,
    )

    user_header = ft.Row(
        [
            ft.Icon(ft.Icons.PERSON, color="green", size=20),
            lbl_logged_in,
            ft.IconButton(
                icon=ft.Icons.LOGOUT,
                icon_color="red",
                icon_size=20,
                tooltip="Sair da conta",
                on_click=lambda e: set_auth(None, None, False),
            ),
        ],
        alignment=ft.MainAxisAlignment.END,
    )

    view = ft.Column(
        [
            user_header,
            ft.Text("Banco de Horas", size=16, weight=ft.FontWeight.BOLD),
            ft.Row([progress_ring], alignment=ft.MainAxisAlignment.CENTER),
            wrapper,
            lbl_status,
        ],
        alignment=ft.MainAxisAlignment.START,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=15,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )

    def _refresh_ui():
        try:
            page = view.page
        except RuntimeError:
            return
        if page:
            page.update()

    def show_status(text: str, color: str):
        lbl_status.value = text
        lbl_status.color = color
        lbl_status.visible = True

    def _apply_field_defaults():
        current_defaults = redmine_task_defaults(app_state.get("user"))
        agora = datetime.datetime.now().date()
        inicio, fim = month_bounds(agora)
        dropdown_month.value = current_month_key(agora)
        date_start.set_date(inicio)
        date_due.set_date(fim)
        dropdown_sistema.value = current_defaults["sistema"]
        dropdown_orgao.value = current_defaults["orgao"]
        dropdown_atribuicao.value = current_defaults["atribuicao"]
        dropdown_projeto.value = current_defaults["projeto"]
        dropdown_desenvolvedor.value = current_defaults.get("desenvolvedor_id")

    def _apply_versions(versions: list[dict], preferred_id: str | None = None):
        previous = preferred_id or dropdown_versao.value
        dropdown_versao.options = [
            ft.dropdown.Option(key=v["id"], text=v["name"]) for v in versions
        ]
        available_ids = {v["id"] for v in versions}
        if previous and previous in available_ids:
            dropdown_versao.value = previous
        else:
            dropdown_versao.value = default_open_version_id(versions)
        dropdown_versao.hint_text = None if versions else "Nenhuma versão aberta encontrada"
        try:
            if dropdown_versao.page:
                dropdown_versao.page.update()
            else:
                dropdown_versao.update()
        except RuntimeError:
            pass
        except Exception:
            pass

    def _load_open_versions():
        session = app_state.get("session")
        if not session:
            return
        previous = dropdown_versao.value
        versions = fetch_open_versions(session)
        if not versions:
            fallback_id = get_dynamic_version()
            versions = [{"id": fallback_id, "name": f"Versão {fallback_id} (fallback)"}]
        _apply_versions(versions, preferred_id=previous)

    def _all_selected_tasks() -> list[dict]:
        selected: list[dict] = []
        for _entry, task_list in task_lists:
            selected.extend(task_list.selected_tasks())
        return selected

    def _update_create_button():
        selected = _all_selected_tasks()
        btn_create.disabled = not selected
        hours = sum_task_hours(selected)
        if selected:
            show_status(f"{len(selected)} tarefa(s) selecionada(s) — {hours:g}h.", "blue")
        elif lbl_status.color == "blue":
            lbl_status.visible = False

    def refresh_banco(e=None):
        task_lists.clear()
        batch_column.controls.clear()

        summary = totals()
        lbl_totals.value = (
            f"Total: {summary['total_hours']:g}h em {summary['task_count']} tarefa(s) "
            f"({summary['batch_count']} arquivo(s))"
        )

        entries = list_banco_batches()
        if not entries:
            batch_column.controls.append(
                ft.Text("Nenhuma tarefa no banco de horas.", italic=True, color=ft.Colors.GREY_600)
            )
            btn_create.disabled = True
            _refresh_ui()
            return

        for entry in entries:
            tasks = ensure_task_ids(entry.get("tasks") or [])
            if not tasks:
                continue

            group_label = entry.get("label") or entry.get("filename") or "Lote"
            task_list = TaskHourListView(
                title=group_label,
                on_selection_change=lambda _view: _update_create_button(),
                initially_expanded=False,
            )
            task_list.set_tasks(tasks)
            task_list.root.visible = True
            if entry.get("atribuicao_catalogo") and not dropdown_atribuicao.value:
                dropdown_atribuicao.value = entry["atribuicao_catalogo"]

            task_lists.append((entry, task_list))
            batch_column.controls.append(task_list.root)

        _update_create_button()
        _refresh_ui()

    def handle_create(e):
        selected_tasks = _all_selected_tasks()
        if not selected_tasks:
            show_status("Selecione ao menos uma tarefa do banco.", "red")
            _refresh_ui()
            return

        desenvolvedor_id = dropdown_desenvolvedor.value
        if not desenvolvedor_id:
            show_status("Selecione o Desenvolvedor.", "red")
            _refresh_ui()
            return

        btn_create.disabled = True
        progress_ring.visible = True
        show_status(f"Criando {len(selected_tasks)} tarefa(s) a partir do banco...", "blue")
        _refresh_ui()

        def bg_create():
            try:
                subtasks_list = [strip_urls_from_description(dict(t)) for t in selected_tasks]
                creation_result = create_ai_redmine_tasks(
                    app_state["session"],
                    date_start.value,
                    date_due.value,
                    app_state["user"],
                    subtasks_list,
                    sistema=dropdown_sistema.value,
                    orgao_solicitante=dropdown_orgao.value,
                    atribuicao_catalogo=dropdown_atribuicao.value,
                    projeto_vinculado=dropdown_projeto.value,
                    versao=dropdown_versao.value or None,
                    desenvolvedor_id=desenvolvedor_id,
                )

                if not creation_result:
                    show_status("Falha ao criar tarefas no Redmine. Verifique o console.", "red")
                    return

                parent_id = creation_result["parent_id"]
                created_subtasks = creation_result.get("subtasks", [])
                created_ids = {
                    str(item.get("task_id"))
                    for item in created_subtasks
                    if item.get("task_id")
                }

                removed = remove_tasks_by_ids(created_ids)
                failed = len(selected_tasks) - len(created_ids)

                if not created_subtasks:
                    show_status(
                        f"Tarefa pai #{parent_id} criada, mas nenhuma subtarefa foi registrada.",
                        "orange",
                    )
                else:
                    note = f" Removidas {removed} do banco." if removed else ""
                    fail_note = f" {failed} falharam e permaneceram no banco." if failed else ""
                    show_status(
                        f"Concluído! Pai #{parent_id}, {len(created_subtasks)} subtarefa(s).{note}{fail_note}",
                        "green",
                    )

                refresh_banco()
            except Exception as ex:
                show_status(f"Falha ao gerar tarefas: {ex}", "red")
            finally:
                btn_create.disabled = False
                progress_ring.visible = False
                _refresh_ui()

        Thread(target=bg_create, daemon=True).start()

    btn_refresh.on_click = refresh_banco
    btn_create.on_click = handle_create

    def sync_ui():
        if app_state.get("session"):
            lbl_logged_in.value = app_state["user"]
            _apply_field_defaults()
            Thread(target=_load_open_versions, daemon=True).start()
        else:
            lbl_status.visible = False
            dropdown_versao.options = []
            dropdown_versao.value = None
            dropdown_versao.hint_text = "Faça login para carregar as versões abertas"
            _apply_field_defaults()
        refresh_banco()

    sync_callbacks.append(sync_ui)

    if banco_listeners is not None:
        banco_listeners.append(refresh_banco)

    sync_ui()

    return ft.Tab(
        text="Banco de Horas",
        icon=ft.Icons.ACCOUNT_BALANCE_WALLET,
        content=ft.Container(content=view, padding=20, expand=True),
    )

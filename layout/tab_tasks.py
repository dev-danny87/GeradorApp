# tab_tasks.py
import flet as ft
import datetime
import json
from threading import Thread

from task_automation import create_redmine_issue
from utils.ui_components import DatePickerField
from utils.redmine_version import get_dynamic_version
from utils.month_selector import (
    apply_month_to_date_pickers,
    create_month_shortcut_dropdown,
    current_month_key,
    month_bounds,
)
from redmine_mappings import (
    SYSTEM_OPTIONS,
    ORGAN_OPTIONS,
    PROJECT_FILTER_OPTIONS,
    ROLE_OPTIONS,
)

_DEFAULT_SISTEMA = "SICOR"
_DEFAULT_ORGAO = "PM"
_DEFAULT_ATRIBUICAO = "Desenvolvedor Sênior"
_DEFAULT_PROJETO = "SICOR"


def _parse_tasks_json(json_text: str) -> list:
    parsed = json.loads(json_text)

    if isinstance(parsed, dict):
        tasks = parsed.get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("O JSON deve conter a lista 'tasks'.")
        subtasks_list = tasks
    elif isinstance(parsed, list):
        subtasks_list = parsed
    else:
        raise ValueError("O JSON deve ser um objeto com 'tasks' ou uma lista de subtarefas.")

    for index, task in enumerate(subtasks_list, start=1):
        if not isinstance(task, dict):
            raise ValueError(f"Tarefa {index}: esperado um objeto JSON.")
        if not (task.get("task_title") or task.get("title")):
            raise ValueError(f"Tarefa {index}: informe 'task_title' (ou 'title' legado).")

    return subtasks_list


def _dropdown_from_mapping(label: str, mapping: dict, default_value: str, width: int = 350) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        width=width,
        options=[ft.dropdown.Option(key=v, text=k) for k, v in mapping.items()],
        value=default_value,
    )


def create_tasks_tab(app_state, set_auth, sync_callbacks):
    # ==========================================
    # CORE VIEW: CRIAÇÃO DE TAREFAS
    # ==========================================
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_form_error = ft.Text("", color="red", visible=False, weight=ft.FontWeight.BOLD)

    hoje = datetime.datetime.now().date()
    inicio_mes, fim_mes = month_bounds(hoje)

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
        if date_start.page:
            date_start.update()
            date_due.update()

    dropdown_month = create_month_shortcut_dropdown(
        on_month_change,
        value=current_month_key(hoje),
    )

    _default_versao = get_dynamic_version()
    txt_versao = ft.TextField(
        label="Versão",
        value=_default_versao,
        width=120,
        icon=ft.Icons.TAG,
    )

    dropdown_sistema = _dropdown_from_mapping("Sistema", SYSTEM_OPTIONS, _DEFAULT_SISTEMA)
    dropdown_orgao = _dropdown_from_mapping("Órgão solicitante", ORGAN_OPTIONS, _DEFAULT_ORGAO)
    dropdown_atribuicao = _dropdown_from_mapping("Atribuição Catálogo", ROLE_OPTIONS, _DEFAULT_ATRIBUICAO)
    dropdown_projeto = _dropdown_from_mapping("Projeto Vinculado", PROJECT_FILTER_OPTIONS, _DEFAULT_PROJETO)

    txt_notas = ft.TextField(
        label="Notas",
        multiline=True,
        min_lines=3,
        max_lines=5,
        width=800,
        icon=ft.Icons.NOTE,
    )

    txt_subtasks_json = ft.TextField(
        label="JSON de Subtarefas (Opcional)",
        hint_text='{"tasks":[{"task_title":"...","category":"Feature","estimated_hours":0.0,"description":"..."}]}',
        multiline=True,
        expand=True,
        icon=ft.Icons.DATA_OBJECT
    )

    btn_create_task = ft.ElevatedButton(
        "Criar Tarefa & Subtarefas",
        icon=ft.Icons.ADD_TASK,
        color="white",
        bgcolor="blue"
    )

    # Cabeçalho do usuário com botão de logout
    user_header = ft.Row([
        ft.Icon(ft.Icons.PERSON, color="green", size=20),
        lbl_logged_in,
        ft.IconButton(
            icon=ft.Icons.LOGOUT,
            icon_color="red",
            icon_size=20,
            tooltip="Sair da conta",
            on_click=lambda e: set_auth(None, None, False)
        )
    ], alignment=ft.MainAxisAlignment.END)

    def _reset_field_defaults():
        agora = datetime.datetime.now().date()
        inicio, fim = month_bounds(agora)
        dropdown_month.value = current_month_key(agora)
        dropdown_sistema.value = _DEFAULT_SISTEMA
        dropdown_orgao.value = _DEFAULT_ORGAO
        dropdown_atribuicao.value = _DEFAULT_ATRIBUICAO
        dropdown_projeto.value = _DEFAULT_PROJETO
        txt_notas.value = ""
        txt_versao.value = get_dynamic_version()
        date_start.set_date(inicio)
        date_due.set_date(fim)

    task_view = ft.Column([
        user_header,
        ft.Text(
            "Defina as datas da Sprint e insira as subtarefas no formato JSON com a chave 'tasks'.",
            weight=ft.FontWeight.BOLD,
        ),
        ft.Row(
            [dropdown_month],
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        ft.Row(
            [date_start, date_due],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=20,
            tight=True,
        ),
        ft.Row([txt_versao], alignment=ft.MainAxisAlignment.CENTER),
        ft.Row([dropdown_sistema, dropdown_orgao], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
        ft.Row([dropdown_atribuicao, dropdown_projeto], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
        txt_notas,
        lbl_form_error,
        ft.Container(content=txt_subtasks_json, width=800, expand=True),
        ft.Row([btn_create_task], alignment=ft.MainAxisAlignment.END)
    ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10, expand=True)

    # ==========================================
    # LÓGICA DE SINCRONIZAÇÃO GLOBAL
    # ==========================================
    def sync_ui():
        # Atualiza o nome do usuário assim que o login for confirmado no main.py
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
        else:
            # Limpa o formulário caso o usuário faça logout
            txt_subtasks_json.value = ""
            _reset_field_defaults()
            lbl_form_error.visible = False

    sync_callbacks.append(sync_ui)  # Cadastra esta aba no atualizador global

    def handle_create(e):
        s_date = date_start.value
        d_date = date_due.value
        json_text = txt_subtasks_json.value.strip()
        subtasks_list = []

        if json_text:
            try:
                subtasks_list = _parse_tasks_json(json_text)
            except Exception as err:
                lbl_form_error.value = f"Erro no formato JSON: {str(err)}"
                lbl_form_error.visible = True
                task_view.update()
                return

        lbl_form_error.visible = False
        task_view.update()

        Thread(
            target=create_redmine_issue,
            kwargs={
                "session": app_state["session"],
                "start_date": s_date,
                "due_date": d_date,
                "username": app_state["user"],
                "subtasks_list": subtasks_list,
                "sistema": dropdown_sistema.value,
                "orgao_solicitante": dropdown_orgao.value,
                "atribuicao_catalogo": dropdown_atribuicao.value,
                "projeto_vinculado": dropdown_projeto.value,
                "notas": txt_notas.value or "",
                "versao": txt_versao.value or None,
            },
            daemon=True,
        ).start()

    btn_create_task.on_click = handle_create

    # Checa o estado na hora que a aba é construída
    sync_ui()

    return ft.Tab(
        text="Gerenciar Tarefas",
        icon=ft.Icons.TASK,
        content=ft.Container(
            content=task_view,
            padding=20,
            expand=True
        )
    )

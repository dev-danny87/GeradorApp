# tab_tasks.py
import flet as ft
import datetime
import json
from threading import Thread

from task_automation import create_parent_sprint_issue, create_subtasks_for_parent
from utils.ai_tasks_store import list_saved_results, load_tasks
from utils.ui_components import DatePickerField
from utils.redmine_version import (
    default_open_version_id,
    fetch_open_versions,
    get_dynamic_version,
)
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
    USER_OPTIONS,
)
from utils.redmine_task_defaults import redmine_task_defaults


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

    dropdown_versao = ft.Dropdown(
        label="Versão",
        width=350,
        options=[],
        value=None,
        hint_text="Faça login para carregar as versões abertas",
    )

    defaults = redmine_task_defaults(app_state.get("user"))
    dropdown_sistema = _dropdown_from_mapping("Sistema", SYSTEM_OPTIONS, defaults["sistema"])
    dropdown_orgao = _dropdown_from_mapping("Órgão solicitante", ORGAN_OPTIONS, defaults["orgao"])
    dropdown_atribuicao = _dropdown_from_mapping(
        "Atribuição Catálogo", ROLE_OPTIONS, defaults["atribuicao"]
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

    txt_notas = ft.TextField(
        label="Notas",
        multiline=True,
        min_lines=3,
        max_lines=5,
        width=800,
        icon=ft.Icons.NOTE,
    )

    txt_parent_id = ft.TextField(
        label="ID da Tarefa Pai (só para Adicionar Subtarefas)",
        hint_text="Preenchido ao criar a pai, ou cole um ID existente",
        width=350,
        icon=ft.Icons.ACCOUNT_TREE,
        input_filter=ft.InputFilter(allow=True, regex_string=r"^[0-9]*$", replacement_string=""),
    )

    txt_subtasks_json = ft.TextField(
        label="JSON de Subtarefas",
        hint_text='{"tasks":[{"task_title":"...","category":"Feature","estimated_hours":0.0,"description":"..."}]}',
        multiline=True,
        min_lines=8,
        max_lines=12,
        icon=ft.Icons.DATA_OBJECT,
    )

    btn_create_parent = ft.ElevatedButton(
        "Criar Tarefa Pai",
        icon=ft.Icons.ACCOUNT_TREE,
        color="white",
        bgcolor="blue",
        tooltip="Cria apenas a tarefa mensal da sprint (SISTEMA - SPRINT MÊS)",
    )
    btn_add_subtasks = ft.ElevatedButton(
        "Adicionar Subtarefas",
        icon=ft.Icons.ADD_TASK,
        color="white",
        bgcolor="green",
        tooltip="Anexa o JSON ao ID da Tarefa Pai usando os campos atuais do formulário",
    )

    btn_import_ai = ft.ElevatedButton(
        "Importar Análise IA",
        icon=ft.Icons.AUTO_AWESOME,
        color="white",
        bgcolor="purple",
        tooltip="Preenche o JSON de Subtarefas com uma análise salva em ./ai_tasks",
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
        current_defaults = redmine_task_defaults(app_state.get("user"))
        agora = datetime.datetime.now().date()
        inicio, fim = month_bounds(agora)
        dropdown_month.value = current_month_key(agora)
        dropdown_sistema.value = current_defaults["sistema"]
        dropdown_orgao.value = current_defaults["orgao"]
        dropdown_atribuicao.value = current_defaults["atribuicao"]
        dropdown_projeto.value = current_defaults["projeto"]
        dropdown_desenvolvedor.value = current_defaults.get("desenvolvedor_id")
        txt_notas.value = ""
        txt_parent_id.value = ""
        dropdown_versao.options = []
        dropdown_versao.value = None
        dropdown_versao.hint_text = "Faça login para carregar as versões abertas"
        date_start.set_date(inicio)
        date_due.set_date(fim)

    task_view = ft.Column([
        user_header,
        ft.Text(
            "1. Crie a Tarefa Pai da sprint. 2. Importe ou cole o JSON. 3. Adicione subtarefas ao mesmo pai (pode repetir com outro sistema).",
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
        ft.Row([dropdown_versao], alignment=ft.MainAxisAlignment.CENTER),
        ft.Row([dropdown_sistema, dropdown_orgao], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
        ft.Row([dropdown_atribuicao, dropdown_projeto], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
        ft.Row([dropdown_desenvolvedor], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
        txt_notas,
        lbl_form_error,
        ft.Row([btn_create_parent], alignment=ft.MainAxisAlignment.END, width=800),
        ft.Row([btn_import_ai], alignment=ft.MainAxisAlignment.START, width=800),
        ft.Container(content=txt_subtasks_json, width=800, height=280),
        ft.Row(
            [txt_parent_id, btn_add_subtasks],
            alignment=ft.MainAxisAlignment.END,
            spacing=10,
            wrap=True,
            width=800,
        ),
    ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10, expand=True,
        scroll=ft.ScrollMode.AUTO)

    # ==========================================
    # LÓGICA DE SINCRONIZAÇÃO GLOBAL
    # ==========================================
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
            print(f"[VERSÃO] Usando fallback get_dynamic_version()={fallback_id}")
        _apply_versions(versions, preferred_id=previous)

    def sync_ui():
        # Atualiza o nome do usuário assim que o login for confirmado no main.py
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
            current_defaults = redmine_task_defaults(app_state["user"])
            if not dropdown_desenvolvedor.value and current_defaults.get("desenvolvedor_id"):
                dropdown_desenvolvedor.value = current_defaults["desenvolvedor_id"]
            Thread(target=_load_open_versions, daemon=True).start()
        else:
            # Limpa o formulário caso o usuário faça logout
            txt_subtasks_json.value = ""
            txt_parent_id.value = ""
            _reset_field_defaults()
            lbl_form_error.visible = False

    sync_callbacks.append(sync_ui)  # Cadastra esta aba no atualizador global

    def _show_form_error(message: str):
        lbl_form_error.value = message
        lbl_form_error.color = "red"
        lbl_form_error.visible = True
        task_view.update()

    def _common_kwargs(desenvolvedor_id: str) -> dict:
        return {
            "session": app_state["session"],
            "start_date": date_start.value,
            "due_date": date_due.value,
            "username": app_state["user"],
            "sistema": dropdown_sistema.value,
            "orgao_solicitante": dropdown_orgao.value,
            "atribuicao_catalogo": dropdown_atribuicao.value,
            "projeto_vinculado": dropdown_projeto.value,
            "notas": txt_notas.value or "",
            "versao": dropdown_versao.value or None,
            "desenvolvedor_id": desenvolvedor_id,
        }

    def handle_import_ai(e):
        page = task_view.page
        entries = list_saved_results()

        if not entries:
            _show_form_error("Nenhuma análise de IA salva em ./ai_tasks/.")
            return

        radio_group = ft.RadioGroup(
            value=entries[0]["path"],
            content=ft.Column(
                [ft.Radio(value=entry["path"], label=entry["label"]) for entry in entries],
                spacing=2,
                tight=True,
            ),
        )

        def do_import(_):
            selected_path = radio_group.value
            try:
                tasks = load_tasks(selected_path)
            except Exception as ex:
                page.close(dialog)
                _show_form_error(f"Falha ao importar análise: {str(ex)}")
                return

            txt_subtasks_json.value = json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2)
            lbl_form_error.visible = False
            page.close(dialog)
            task_view.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Selecionar Análise de IA"),
            content=ft.Container(
                content=ft.Column([radio_group], scroll=ft.ScrollMode.AUTO, tight=True),
                width=520,
                height=300,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: page.close(dialog)),
                ft.TextButton("Importar", on_click=do_import),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        page.open(dialog)

    btn_import_ai.on_click = handle_import_ai

    def handle_create_parent(e):
        desenvolvedor_id = dropdown_desenvolvedor.value
        if not desenvolvedor_id:
            _show_form_error("Selecione o Desenvolvedor.")
            return

        lbl_form_error.visible = False
        btn_create_parent.disabled = True
        task_view.update()

        def bg_create():
            try:
                parent_id = create_parent_sprint_issue(**_common_kwargs(desenvolvedor_id))
                if parent_id:
                    txt_parent_id.value = str(parent_id)
                    lbl_form_error.value = f"Tarefa pai #{parent_id} criada. Agora adicione as subtarefas."
                    lbl_form_error.color = "green"
                    lbl_form_error.visible = True
                else:
                    _show_form_error("Falha ao criar a tarefa pai. Verifique o console.")
                    return
            except Exception as ex:
                _show_form_error(f"Falha ao criar a tarefa pai: {ex}")
            finally:
                btn_create_parent.disabled = False
                task_view.update()

        Thread(target=bg_create, daemon=True).start()

    def handle_add_subtasks(e):
        desenvolvedor_id = dropdown_desenvolvedor.value
        parent_id = (txt_parent_id.value or "").strip()
        json_text = (txt_subtasks_json.value or "").strip()

        if not desenvolvedor_id:
            _show_form_error("Selecione o Desenvolvedor.")
            return
        if not parent_id or not parent_id.isdigit():
            _show_form_error("Informe o ID numérico da Tarefa Pai.")
            return
        if not json_text:
            _show_form_error("Informe o JSON de subtarefas.")
            return

        try:
            subtasks_list = _parse_tasks_json(json_text)
        except Exception as err:
            _show_form_error(f"Erro no formato JSON: {str(err)}")
            return

        if not subtasks_list:
            _show_form_error("O JSON não contém subtarefas.")
            return

        lbl_form_error.visible = False
        btn_add_subtasks.disabled = True
        task_view.update()

        def bg_add():
            try:
                create_subtasks_for_parent(
                    parent_id=parent_id,
                    subtasks_list=subtasks_list,
                    **_common_kwargs(desenvolvedor_id),
                )
                lbl_form_error.value = (
                    f"{len(subtasks_list)} subtarefa(s) enviadas para o pai #{parent_id}. "
                    "Verifique o console. Pode repetir com outro JSON/sistema."
                )
                lbl_form_error.color = "green"
                lbl_form_error.visible = True
            except Exception as ex:
                _show_form_error(f"Falha ao adicionar subtarefas: {ex}")
            finally:
                btn_add_subtasks.disabled = False
                task_view.update()

        Thread(target=bg_add, daemon=True).start()

    btn_create_parent.on_click = handle_create_parent
    btn_add_subtasks.on_click = handle_add_subtasks

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

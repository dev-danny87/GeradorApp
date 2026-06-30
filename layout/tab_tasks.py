# tab_tasks.py
import flet as ft
import datetime
import calendar
import json
from threading import Thread

from task_automation import create_redmine_issue


def create_tasks_tab(app_state, set_auth, sync_callbacks):
    # ==========================================
    # CORE VIEW: CRIAÇÃO DE TAREFAS
    # ==========================================
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)
    lbl_form_error = ft.Text("", color="red", visible=False, weight=ft.FontWeight.BOLD)

    hoje = datetime.datetime.now()
    inicio_mes = hoje.replace(day=1).strftime("%Y-%m-%d")
    ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]

    txt_start_date = ft.TextField(
        label="Data de Início (Sprint)",
        value=inicio_mes,
        width=200,
        icon=ft.Icons.CALENDAR_TODAY
    )

    txt_due_date = ft.TextField(
        label="Data Prevista (Sprint)",
        value=hoje.replace(day=ultimo_dia).strftime("%Y-%m-%d"),
        width=200,
        icon=ft.Icons.EVENT
    )

    txt_subtasks_json = ft.TextField(
        label="JSON de Subtarefas (Opcional)",
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

    task_view = ft.Column([
        user_header,
        ft.Text("Defina as datas da Sprint e insira as subtarefas em formato JSON.", weight=ft.FontWeight.BOLD),
        ft.Row([txt_start_date, txt_due_date], alignment=ft.MainAxisAlignment.CENTER),
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
            lbl_form_error.visible = False

    sync_callbacks.append(sync_ui)  # Cadastra esta aba no atualizador global

    def handle_create(e):
        s_date = txt_start_date.value
        d_date = txt_due_date.value
        json_text = txt_subtasks_json.value.strip()
        subtasks_list = []

        if json_text:
            try:
                subtasks_list = json.loads(json_text)
            except Exception as err:
                lbl_form_error.value = f"Erro no formato JSON: {str(err)}"
                lbl_form_error.visible = True
                task_view.update()
                return

        lbl_form_error.visible = False
        task_view.update()

        Thread(
            target=create_redmine_issue,
            args=(app_state["session"], s_date, d_date, app_state["user"], subtasks_list),
            daemon=True
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
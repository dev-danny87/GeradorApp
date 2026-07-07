import datetime

import flet as ft
from threading import Thread

from utils.ui_components import DatePickerField
from utils.month_selector import (
    apply_month_to_date_pickers,
    create_month_shortcut_dropdown,
    current_month_key,
    month_bounds,
)


def create_evidences_tab(on_generate, on_generate_all, on_stop, get_timestamp, app_state, set_auth, sync_callbacks):
    # ==========================================
    # CORE VIEW: GERADOR DE EVIDÊNCIAS
    # ==========================================
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)

    hoje = datetime.datetime.now().date()
    inicio_mes, fim_mes = month_bounds(hoje)

    date_start = DatePickerField(label="Data inicial", default_date=inicio_mes, width=190)
    date_end = DatePickerField(label="Data final", default_date=fim_mes, width=190, icon=ft.Icons.EVENT)

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

    def _get_date_range() -> tuple[str, str] | None:
        start_date = (date_start.value or "").strip()
        end_date = (date_end.value or "").strip()
        if not start_date or not end_date:
            print(f"[{get_timestamp()}] ERROR: Informe as datas inicial e final.")
            return None
        try:
            start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
            if start_dt > end_dt:
                print(f"[{get_timestamp()}] ERROR: Data inicial não pode ser posterior à data final.")
                return None
        except ValueError:
            print(f"[{get_timestamp()}] ERROR: Formato de data inválido.")
            return None
        return start_date, end_date

    def _reset_date_defaults():
        agora = datetime.datetime.now().date()
        inicio, fim = month_bounds(agora)
        dropdown_month.value = current_month_key(agora)
        date_start.set_date(inicio)
        date_end.set_date(fim)

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

    def create_button_row(label: str, query_id: str, project_id: str, exception_type: str):
        def handle_generate_evidences(q_id, p_id, e_type):
            try:
                date_range = _get_date_range()
                if not date_range:
                    return
                start_date, end_date = date_range
                on_generate(app_state["session"], q_id, p_id, e_type, start_date, end_date)
            except Exception as e:
                print(f"[{get_timestamp()}] ERROR: falha ao gerar evidências ({p_id}): {e}")

        button = ft.IconButton(
            icon=ft.Icons.ADD_BOX_ROUNDED,
            icon_color="blue",
            tooltip=f"Gerar: {label}",
            on_click=lambda event: Thread(
                target=handle_generate_evidences,
                args=(query_id, project_id, exception_type),
                daemon=True,
            ).start(),
        )

        button_stop = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color="red",
            tooltip="Parar",
            on_click=lambda event: on_stop(),
        )

        text = ft.Text(value=label, expand=True, size=13, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)

        row = ft.Row([button, text, button_stop], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        return ft.Container(content=row, width=400, padding=5, border_radius=8, bgcolor=ft.Colors.SURFACE)

    # Lista de Controles
    project_controls = [
        create_button_row("contrato_hpm", "120", "contrato_hpm", "hpm"),
        create_button_row("gerencia_inovacao", "83", "gerencia_inovacao", ""),
        create_button_row("gerencia_inovacao_BI", "84", "gerencia_inovacao_bi", ""),
        create_button_row("gerencia_int_negocios", "111", "gerencia_inteligencia_negocios", ""),
        create_button_row("gerencia_telecomunicacao", "85", "gerencia_telecomunicacao", ""),
        create_button_row("procon-go", "169", "procon-go", "procon-go")
    ]

    # ==========================================
    # BOTÃO GERAR TODOS
    # ==========================================
    def handle_generate_all():
        try:
            date_range = _get_date_range()
            if not date_range:
                return
            start_date, end_date = date_range
            on_generate_all(app_state["session"], start_date, end_date)
        except Exception as e:
            print(f"[{get_timestamp()}] ERROR: falha ao gerar todos: {e}")

    button_all_generate = ft.IconButton(
        icon=ft.Icons.AUTO_MODE,
        icon_color="green",
        tooltip="Gerar todos",
        on_click=lambda e: Thread(target=handle_generate_all, daemon=True).start(),
    )

    button_stop_all = ft.IconButton(
        icon=ft.Icons.CLOSE,
        icon_color="red",
        tooltip="Parar tudo",
        on_click=lambda event: on_stop(),
    )

    label_all = ft.Text("GERAR TODOS", expand=True, size=13, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)

    row_all = ft.Container(
        content=ft.Row(
            [button_all_generate, label_all, button_stop_all],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        width=400,
        padding=5,
        border_radius=8,
        bgcolor=ft.Colors.SURFACE,
    )

    date_controls = ft.Container(
        width=400,
        content=ft.Column(
            [
                ft.Row([dropdown_month], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row(
                    [date_start, date_end],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=20,
                    tight=True,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
    )

    # ==========================================
    # COLUNA PRINCIPAL
    # ==========================================
    main_column = ft.Column(
        controls=[
            user_header,
            date_controls,
            ft.Divider(height=10, color="transparent"),
        ] + project_controls + [ft.Divider(height=15, color="transparent"), row_all],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10,
        expand=True
    )

    # ==========================================
    # LÓGICA DE SINCRONIZAÇÃO
    # ==========================================
    def sync_ui():
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]
        else:
            lbl_logged_in.value = ""
            _reset_date_defaults()

    sync_callbacks.append(sync_ui)

    sync_ui()

    return ft.Tab(
        text="Gerar Evidências",
        icon=ft.Icons.DOWNLOAD,
        content=ft.Container(
            content=main_column,
            padding=30,
            alignment=ft.alignment.top_center,
            expand=True
        )
    )

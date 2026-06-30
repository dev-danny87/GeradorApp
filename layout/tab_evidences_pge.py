import flet as ft
from threading import Thread

from services.pge_evidence_service import fetch_cf28_options


def create_evidences_pge_tab(on_generate, on_stop, get_timestamp, app_state, set_auth, sync_callbacks):
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)

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

    dropdown_month = ft.Dropdown(
        label="Entregue em",
        width=400,
        options=[],
    )

    def load_cf28_options():
        session = app_state.get("session")
        if not session:
            return
        if app_state.get("pge_cf28_options"):
            options = app_state["pge_cf28_options"]
        else:
            options = fetch_cf28_options(session)
            app_state["pge_cf28_options"] = options

        dropdown_month.options = [
            ft.dropdown.Option(key=val, text=label) for label, val in options
        ]
        if options and not dropdown_month.value:
            dropdown_month.value = options[0][1]

    def handle_generate():
        session = app_state.get("session")
        if not session:
            print(f"[{get_timestamp()}] ERROR: Faça login no PGE primeiro.")
            return
        cf_28_id = dropdown_month.value
        if not cf_28_id:
            print(f"[{get_timestamp()}] ERROR: Selecione o mês 'Entregue em'.")
            return
        label = next(
            (o.text for o in dropdown_month.options if o.key == cf_28_id),
            cf_28_id,
        )
        try:
            on_generate(session, cf_28_id, label)
        except Exception as e:
            print(f"[{get_timestamp()}] ERROR: falha ao gerar evidências PGE: {e}")

    button_generate = ft.IconButton(
        icon=ft.Icons.ADD_BOX_ROUNDED,
        icon_color="blue",
        tooltip="Gerar evidências PGE",
        on_click=lambda e: Thread(target=handle_generate, daemon=True).start(),
    )

    button_stop = ft.IconButton(
        icon=ft.Icons.CLOSE,
        icon_color="red",
        tooltip="Parar",
        on_click=lambda e: on_stop(),
    )

    label_generate = ft.Text(
        "GERAR EVIDÊNCIAS PGE",
        expand=True,
        size=13,
        weight=ft.FontWeight.BOLD,
        text_align=ft.TextAlign.CENTER,
    )

    row_generate = ft.Container(
        content=ft.Row(
            [button_generate, label_generate, button_stop],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        width=400,
        padding=5,
        border_radius=8,
        bgcolor=ft.Colors.SURFACE,
    )

    main_column = ft.Column(
        controls=[
            user_header,
            dropdown_month,
            row_generate,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10,
        expand=True,
    )

    def sync_ui():
        if app_state.get("session") and app_state.get("redmine_host") == "pge":
            lbl_logged_in.value = app_state.get("user", "")
            load_cf28_options()
        else:
            lbl_logged_in.value = ""

    sync_callbacks.append(sync_ui)
    sync_ui()

    return ft.Tab(
        text="Gerar Evidências PGE",
        icon=ft.Icons.DOWNLOAD,
        content=ft.Container(
            content=main_column,
            padding=30,
            alignment=ft.alignment.top_center,
            expand=True,
        ),
    )

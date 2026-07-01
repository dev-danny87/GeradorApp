import flet as ft
from threading import Thread

from services.iphan.registry import get_default_project_key, get_project_options, get_service


def create_evidences_iphan_tab(on_generate, on_stop, get_timestamp, app_state, set_auth, sync_callbacks):
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

    dropdown_project = ft.Dropdown(
        label="Projeto",
        width=400,
        options=[
            ft.dropdown.Option(key=p["key"], text=p["label"])
            for p in get_project_options()
        ],
        value=get_default_project_key(),
    )

    options_container = ft.Column(
        controls=[],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10,
    )

    def rebuild_options_area():
        project_key = dropdown_project.value or get_default_project_key()
        service = get_service(project_key)
        if not service:
            options_container.controls = []
            return
        options_container.controls = service.get_controls(app_state)

    def load_project_options():
        session = app_state.get("session")
        if not session:
            return

        project_key = dropdown_project.value or get_default_project_key()
        service = get_service(project_key)
        if not service:
            return

        def fetch_in_background():
            service.load_options(session, app_state)
            rebuild_options_area()
            if options_container.page:
                options_container.page.update()

        Thread(target=fetch_in_background, daemon=True).start()

    def on_project_change(e):
        app_state["iphan_selected_project"] = dropdown_project.value
        rebuild_options_area()
        load_project_options()
        if dropdown_project.page:
            dropdown_project.page.update()

    dropdown_project.on_change = on_project_change

    def handle_generate():
        session = app_state.get("session")
        if not session:
            print(f"[{get_timestamp()}] ERROR: Faça login no IPHAN primeiro.")
            return

        project_key = dropdown_project.value
        if not project_key:
            print(f"[{get_timestamp()}] ERROR: Selecione um projeto.")
            return

        service = get_service(project_key)
        if not service:
            print(f"[{get_timestamp()}] ERROR: Projeto desconhecido: {project_key}")
            return

        ok, message = service.validate_selection(app_state)
        if not ok:
            print(f"[{get_timestamp()}] ERROR: {message}")
            return

        try:
            on_generate(session, project_key)
        except Exception as exc:
            print(f"[{get_timestamp()}] ERROR: falha ao gerar evidências IPHAN: {exc}")

    button_generate = ft.IconButton(
        icon=ft.Icons.ADD_BOX_ROUNDED,
        icon_color="blue",
        tooltip="Gerar evidências IPHAN",
        on_click=lambda e: Thread(target=handle_generate, daemon=True).start(),
    )

    button_stop = ft.IconButton(
        icon=ft.Icons.CLOSE,
        icon_color="red",
        tooltip="Parar",
        on_click=lambda e: on_stop(),
    )

    label_generate = ft.Text(
        "GERAR EVIDÊNCIAS IPHAN",
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
            dropdown_project,
            options_container,
            row_generate,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10,
        expand=True,
    )

    def sync_ui():
        if app_state.get("session") and app_state.get("redmine_host") == "iphan":
            lbl_logged_in.value = app_state.get("user", "")
            if app_state.get("iphan_selected_project"):
                dropdown_project.value = app_state["iphan_selected_project"]
            rebuild_options_area()
            load_project_options()
        else:
            lbl_logged_in.value = ""
            dropdown_project.value = get_default_project_key()
            options_container.controls = []

    sync_callbacks.append(sync_ui)
    sync_ui()

    return ft.Tab(
        text="IPHAN",
        icon=ft.Icons.ACCOUNT_BALANCE,
        content=ft.Container(
            content=main_column,
            padding=30,
            alignment=ft.alignment.top_center,
            expand=True,
        ),
    )

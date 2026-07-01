import flet as ft
from threading import Thread

from services.pge_evidence_service import fetch_cf28_enumerations, find_cf28_for_month
from utils.month_selector import create_month_shortcut_dropdown, month_label_for_key


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

    dropdown_entregue = ft.Dropdown(
        label="Entregue em",
        width=400,
        options=[],
    )

    switch_include_inactive = ft.Switch(
        label="Incluir inativos",
        value=False,
        tooltip="Desligado: somente ativos",
    )

    def _filtered_enumerations() -> list[dict]:
        enumerations = app_state.get("pge_cf28_enumerations") or []
        if switch_include_inactive.value:
            filtered = enumerations
        else:
            filtered = [e for e in enumerations if e.get("active")]
        if not filtered and enumerations:
            filtered = enumerations
        return filtered

    def _apply_month_shortcut_to_entregue() -> bool:
        filtered = _filtered_enumerations()
        if not filtered or not dropdown_month_shortcut.value:
            return False

        match = find_cf28_for_month(
            filtered,
            dropdown_month_shortcut.value,
            active_only=not switch_include_inactive.value,
        )
        if not match:
            print(
                f"[{get_timestamp()}] WARN: nenhum 'Entregue em' para "
                f"{month_label_for_key(dropdown_month_shortcut.value)}"
            )
            return False

        dropdown_entregue.value = match["id"]
        return True

    def apply_cf28_filter():
        filtered = _filtered_enumerations()
        dropdown_entregue.options = [
            ft.dropdown.Option(key=e["id"], text=e["label"]) for e in filtered
        ]
        if not filtered:
            dropdown_entregue.value = None
            return

        if not _apply_month_shortcut_to_entregue():
            dropdown_entregue.value = filtered[-1]["id"]

    def on_month_shortcut_change(e):
        apply_cf28_filter()
        if dropdown_entregue.page:
            dropdown_entregue.page.update()

    dropdown_month_shortcut = create_month_shortcut_dropdown(on_month_shortcut_change)

    def on_switch_change(e):
        apply_cf28_filter()
        if dropdown_entregue.page:
            dropdown_entregue.page.update()

    switch_include_inactive.on_change = on_switch_change

    def load_cf28_enumerations():
        session = app_state.get("session")
        if not session:
            return

        if app_state.get("pge_cf28_enumerations"):
            apply_cf28_filter()
            return

        def fetch_in_background():
            enumerations = fetch_cf28_enumerations(session)
            app_state["pge_cf28_enumerations"] = enumerations
            apply_cf28_filter()
            if dropdown_entregue.page:
                dropdown_entregue.page.update()

        Thread(target=fetch_in_background, daemon=True).start()

    def handle_generate():
        session = app_state.get("session")
        if not session:
            print(f"[{get_timestamp()}] ERROR: Faça login no PGE primeiro.")
            return
        cf_28_id = dropdown_entregue.value
        if not cf_28_id:
            print(f"[{get_timestamp()}] ERROR: Selecione o mês 'Entregue em'.")
            return
        label = next(
            (o.text for o in dropdown_entregue.options if o.key == cf_28_id),
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
            switch_include_inactive,
            dropdown_month_shortcut,
            dropdown_entregue,
            row_generate,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10,
        expand=True,
    )

    def sync_ui():
        if app_state.get("session") and app_state.get("redmine_host") == "pge":
            lbl_logged_in.value = app_state.get("user", "")
            load_cf28_enumerations()
        else:
            lbl_logged_in.value = ""
            dropdown_entregue.options = []
            dropdown_entregue.value = None

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

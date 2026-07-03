import flet as ft
from threading import Thread


def create_evidences_tab(on_generate, on_generate_all, on_stop, get_timestamp, app_state, set_auth, sync_callbacks):
    # ==========================================
    # CORE VIEW: GERADOR DE EVIDÊNCIAS
    # ==========================================
    lbl_logged_in = ft.Text("", color="green", weight=ft.FontWeight.BOLD, size=14)

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
                # Injeta a sessão do usuário logado na geração de evidências
                on_generate(app_state["session"], q_id, p_id, e_type)
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
            on_generate_all(app_state["session"])
        except Exception as e:
            print(f"[{get_timestamp()}] ERROR: falha ao gerar todos: {e}")

    button_all_generate = ft.IconButton(
        icon=ft.Icons.AUTO_MODE,
        icon_color="green",
        tooltip="Gerar tudo",
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
        content=ft.Row([button_all_generate, label_all, button_stop_all], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        width=400,
        padding=5
    )

    # ==========================================
    # COLUNA PRINCIPAL
    # ==========================================
    main_column = ft.Column(
        controls=[user_header] + project_controls + [ft.Divider(height=15, color="transparent"), row_all],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10,
        expand=True
    )

    # ==========================================
    # LÓGICA DE SINCRONIZAÇÃO
    # ==========================================
    def sync_ui():
        # Atualiza o nome do usuário assim que o login for confirmado no main.py
        if app_state["session"]:
            lbl_logged_in.value = app_state["user"]

    sync_callbacks.append(sync_ui)

    # Roda a sincronização inicial
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
import os
import shutil
import tempfile
from threading import Thread

import flet as ft

from utils.pdf_merger import is_supported_document, merge_documents

_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def create_join_documents_view(page: ft.Page, on_back) -> ft.Control:
    selected_files: list[dict] = []
    merged_temp_path = {"value": None}

    files_list_view = ft.ListView(expand=True, spacing=4, auto_scroll=False)
    status_text = ft.Text("", visible=False, weight=ft.FontWeight.BOLD)
    merge_progress = ft.ProgressRing(visible=False, width=20, height=20)

    def _set_status(message: str, color: str = "blue"):
        status_text.value = message
        status_text.color = color
        status_text.visible = bool(message)

    def _clear_temp():
        path = merged_temp_path["value"]
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        merged_temp_path["value"] = None
        btn_save.disabled = True

    def _file_icon(name: str):
        ext = os.path.splitext(name)[1].lower()
        if ext == ".pdf":
            return ft.Icons.PICTURE_AS_PDF
        if ext in _IMAGE_EXTS:
            return ft.Icons.IMAGE
        return ft.Icons.INSERT_DRIVE_FILE

    def update_file_list_ui():
        files_list_view.controls.clear()
        if not selected_files:
            files_list_view.controls.append(
                ft.Text(
                    "Nenhum arquivo adicionado. Clique em Adicionar arquivos.",
                    color="grey",
                    italic=True,
                )
            )
        else:
            last_index = len(selected_files) - 1
            for index, file_info in enumerate(selected_files):
                files_list_view.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(f"{index + 1}.", width=28, weight=ft.FontWeight.BOLD),
                                ft.Icon(_file_icon(file_info["name"]), color="blue", size=22),
                                ft.Text(
                                    file_info["name"],
                                    expand=True,
                                    size=13,
                                    tooltip=file_info["path"],
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.ARROW_UPWARD,
                                    tooltip="Subir",
                                    disabled=index == 0,
                                    on_click=lambda e, i=index: move_file(i, -1),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.ARROW_DOWNWARD,
                                    tooltip="Descer",
                                    disabled=index == last_index,
                                    on_click=lambda e, i=index: move_file(i, 1),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_color="red",
                                    tooltip="Remover",
                                    on_click=lambda e, i=index: remove_file(i),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.padding.symmetric(horizontal=8, vertical=2),
                        border=ft.border.all(1, "#e0e0e0"),
                        border_radius=6,
                    )
                )
        btn_merge.disabled = not selected_files
        btn_clear.disabled = not selected_files
        if page:
            page.update()

    def move_file(index: int, delta: int):
        new_index = index + delta
        if 0 <= new_index < len(selected_files):
            selected_files[index], selected_files[new_index] = (
                selected_files[new_index],
                selected_files[index],
            )
            _clear_temp()
            _set_status("")
            update_file_list_ui()

    def remove_file(index: int):
        if 0 <= index < len(selected_files):
            selected_files.pop(index)
            _clear_temp()
            _set_status("")
            update_file_list_ui()

    def clear_files(e=None):
        selected_files.clear()
        _clear_temp()
        _set_status("")
        update_file_list_ui()

    def on_files_selected(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        added = 0
        skipped = 0
        for picked in e.files:
            if not picked.path or not is_supported_document(picked.name):
                skipped += 1
                continue
            selected_files.append({"name": picked.name, "path": picked.path})
            added += 1
        _clear_temp()
        if skipped and not added:
            _set_status("Nenhum arquivo válido. Use PDF, JPG, JPEG ou PNG.", "red")
        elif skipped:
            _set_status(f"{added} arquivo(s) adicionado(s). {skipped} ignorado(s).", "orange")
        else:
            _set_status("")
        update_file_list_ui()

    def on_save_result(e: ft.FilePickerResultEvent):
        dest = e.path
        source = merged_temp_path["value"]
        if not dest:
            _set_status("União concluída. Clique em Salvar PDF para baixar.", "blue")
            page.update()
            return
        if not source or not os.path.isfile(source):
            _set_status("O PDF unificado não está mais disponível. Una os arquivos novamente.", "red")
            btn_save.disabled = True
            page.update()
            return
        if not dest.lower().endswith(".pdf"):
            dest += ".pdf"
        try:
            shutil.copy2(source, dest)
            _set_status(f"PDF salvo em: {dest}", "green")
            page.open(ft.SnackBar(ft.Text(f"PDF salvo em: {dest}"), bgcolor="green"))
        except OSError as err:
            _set_status(f"Não foi possível salvar o arquivo: {err}", "red")
        page.update()

    pick_files_dialog = ft.FilePicker(on_result=on_files_selected)
    save_file_dialog = ft.FilePicker(on_result=on_save_result)
    page.overlay.append(pick_files_dialog)
    page.overlay.append(save_file_dialog)

    def prompt_save(e=None):
        if not merged_temp_path["value"] or not os.path.isfile(merged_temp_path["value"]):
            _set_status("Una os documentos antes de salvar.", "red")
            page.update()
            return
        save_file_dialog.save_file(
            dialog_title="Salvar PDF unificado",
            file_name="documentos_unificados.pdf",
            allowed_extensions=["pdf"],
        )

    def set_busy(busy: bool):
        btn_add.disabled = busy
        btn_clear.disabled = busy or not selected_files
        btn_merge.disabled = busy or not selected_files
        btn_save.disabled = busy or not merged_temp_path["value"]
        btn_back.disabled = busy
        merge_progress.visible = busy

    def handle_merge(e=None):
        if not selected_files:
            _set_status("Adicione ao menos um arquivo.", "red")
            page.update()
            return

        set_busy(True)
        _set_status("Unindo documentos...", "blue")
        page.update()

        paths = [item["path"] for item in selected_files]

        def bg_merge():
            fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            try:
                merge_documents(paths, temp_path)
            except Exception as err:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                merged_temp_path["value"] = None
                set_busy(False)
                btn_save.disabled = True
                _set_status(f"Erro ao unir documentos: {err}", "red")
                page.update()
                return

            previous = merged_temp_path["value"]
            merged_temp_path["value"] = temp_path
            if previous and previous != temp_path and os.path.isfile(previous):
                try:
                    os.remove(previous)
                except OSError:
                    pass

            set_busy(False)
            btn_save.disabled = False
            _set_status("Documentos unidos. Escolha onde salvar o PDF.", "green")
            page.update()
            prompt_save()

        Thread(target=bg_merge, daemon=True).start()

    def handle_back(e=None):
        clear_files()
        on_back()

    btn_back = ft.TextButton("Voltar", icon=ft.Icons.ARROW_BACK, on_click=handle_back)
    btn_add = ft.ElevatedButton(
        "Adicionar arquivos",
        icon=ft.Icons.UPLOAD_FILE,
        on_click=lambda _: pick_files_dialog.pick_files(
            allow_multiple=True,
            allowed_extensions=["pdf", "jpg", "jpeg", "png"],
            dialog_title="Selecionar PDFs e imagens",
        ),
    )
    btn_clear = ft.OutlinedButton(
        "Limpar lista",
        icon=ft.Icons.CLEAR_ALL,
        on_click=clear_files,
        disabled=True,
    )
    btn_merge = ft.ElevatedButton(
        "Unir em um PDF",
        icon=ft.Icons.PICTURE_AS_PDF,
        bgcolor="blue",
        color="white",
        on_click=handle_merge,
        disabled=True,
    )
    btn_save = ft.ElevatedButton(
        "Salvar PDF",
        icon=ft.Icons.DOWNLOAD,
        on_click=prompt_save,
        disabled=True,
    )

    update_file_list_ui()

    return ft.Column(
        [
            ft.Row([btn_back], alignment=ft.MainAxisAlignment.START),
            ft.Text("Unir Documentos", size=30, weight=ft.FontWeight.BOLD),
            ft.Text("Envie PDFs e imagens, defina a ordem e gere um único PDF."),
            ft.Row([btn_add, btn_clear], alignment=ft.MainAxisAlignment.START, wrap=True),
            ft.Container(
                content=files_list_view,
                border=ft.border.all(1, "grey"),
                border_radius=8,
                padding=10,
                expand=True,
            ),
            ft.Row(
                [btn_merge, btn_save, merge_progress],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            status_text,
        ],
        expand=True,
        spacing=12,
        visible=False,
        width=900,
    )

"""Check GitHub Releases for a newer installer and apply silent updates."""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from typing import Any

import flet as ft
import requests
from packaging.version import InvalidVersion, Version

GITHUB_OWNER = "dev-danny87"
GITHUB_REPO = "GeradorApp"
SETUP_ASSET_NAME = "Gerador_Redmine_Setup.exe"
RELEASES_LATEST_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)


def _normalize_tag(tag: str) -> str:
    tag = (tag or "").strip()
    if tag.lower().startswith("v"):
        return tag[1:]
    return tag


def _is_newer(latest: str, current: str) -> bool:
    try:
        return Version(_normalize_tag(latest)) > Version(_normalize_tag(current))
    except InvalidVersion:
        return False


def fetch_latest_release(timeout: int = 15) -> dict[str, Any] | None:
    """Return {tag, download_url} for the latest public release, or None."""
    try:
        response = requests.get(
            RELEASES_LATEST_URL,
            headers={"Accept": "application/vnd.github+json"},
            timeout=timeout,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"[update] Falha ao consultar releases: {exc}")
        return None

    tag = _normalize_tag(str(data.get("tag_name") or ""))
    if not tag:
        return None

    assets = data.get("assets") or []
    download_url = None
    for asset in assets:
        name = asset.get("name") or ""
        if name == SETUP_ASSET_NAME:
            download_url = asset.get("browser_download_url")
            break
    if not download_url:
        for asset in assets:
            name = (asset.get("name") or "").lower()
            if name.endswith(".exe"):
                download_url = asset.get("browser_download_url")
                break

    if not download_url:
        print("[update] Release encontrada, mas sem asset .exe.")
        return None

    return {"tag": tag, "download_url": download_url}


def download_installer(url: str, dest_path: str, timeout: int = 300) -> None:
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=512 * 1024):
                if chunk:
                    handle.write(chunk)


def launch_silent_installer(installer_path: str) -> None:
    subprocess.Popen(
        [installer_path, "/SILENT", "/CLOSEAPPLICATIONS"],
        shell=False,
        close_fds=True,
    )


def _close_and_exit(page: ft.Page) -> None:
    try:
        page.window.destroy()
    except Exception:
        pass
    os._exit(0)


def prompt_and_update(
    page: ft.Page,
    current_version: str,
    latest_tag: str,
    download_url: str,
) -> None:
    """Show update dialog on the UI thread; download/install on Accept."""
    status_text = ft.Text("", size=12, color="grey")
    btn_update = ft.ElevatedButton("Atualizar", icon=ft.Icons.SYSTEM_UPDATE)
    btn_later = ft.TextButton("Depois")

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Atualização disponível"),
        content=ft.Column(
            [
                ft.Text(
                    f"Versão instalada: {current_version}\n"
                    f"Nova versão: {latest_tag}\n\n"
                    "Deseja baixar e instalar agora? O aplicativo será fechado."
                ),
                status_text,
            ],
            tight=True,
            spacing=10,
            width=420,
        ),
        actions=[btn_later, btn_update],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def close_dialog(_=None):
        dialog.open = False
        page.update()

    def on_update(_):
        btn_update.disabled = True
        btn_later.disabled = True
        status_text.value = "Baixando instalador..."
        status_text.color = "blue"
        page.update()

        def worker():
            try:
                dest = os.path.join(tempfile.gettempdir(), SETUP_ASSET_NAME)
                download_installer(download_url, dest)
                print(f"[update] Instalador baixado: {dest}")
                launch_silent_installer(dest)
                _close_and_exit(page)
            except Exception as exc:
                print(f"[update] Erro ao baixar/instalar: {exc}")

                def show_error():
                    status_text.value = f"Falha na atualização: {exc}"
                    status_text.color = "red"
                    btn_update.disabled = False
                    btn_later.disabled = False
                    page.update()

                try:
                    show_error()
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    btn_later.on_click = close_dialog
    btn_update.on_click = on_update

    page.overlay.append(dialog)
    dialog.open = True
    page.update()


def check_for_updates(page: ft.Page, current_version: str) -> None:
    """Background check; shows dialog if a newer release exists."""

    def worker():
        info = fetch_latest_release()
        if not info:
            return
        latest = info["tag"]
        if not _is_newer(latest, current_version):
            print(f"[update] App atualizado ({current_version}).")
            return

        print(f"[update] Nova versão disponível: {latest} (atual: {current_version})")

        def show():
            prompt_and_update(page, current_version, latest, info["download_url"])

        try:
            show()
        except Exception as exc:
            print(f"[update] Não foi possível exibir o diálogo: {exc}")

    threading.Thread(target=worker, daemon=True).start()

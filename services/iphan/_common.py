import calendar
import datetime
import os
import re
import time
from typing import Dict
from urllib.parse import urljoin, urlparse

import requests

from services.auth_service import IPHAN_BASE_URL

_app_run = True

EVIDENCIAS_DIR = "Evidências"
RELATORIO_INDIVIDUAIS_DIR = "Relatório de Atividades Individuais"
RELATORIO_PF_DIR = "Relatório de Contagem de Pontos de Função"
BACKLOG_PDF_NAME = "Backlog.pdf"


def set_app_run(value: bool) -> None:
    global _app_run
    _app_run = value


def is_app_running() -> bool:
    return _app_run


def timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def absolute_url(path: str) -> str:
    if not path:
        return path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/"):
        root = urlparse(IPHAN_BASE_URL)
        return f"{root.scheme}://{root.netloc}{path}"
    return urljoin(IPHAN_BASE_URL + "/", path)


def clone_session(session: requests.Session) -> requests.Session:
    worker = requests.Session()
    worker.cookies.update(session.cookies)
    worker.headers.update(session.headers)
    worker.verify = session.verify
    return worker


def http_get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    if "timeout" not in kwargs:
        kwargs["timeout"] = 60
    response = session.get(url, **kwargs)
    response.raise_for_status()
    return response


def download_file(session: requests.Session, url: str, dest_path: str, max_retries: int = 3) -> bool:
    safe_mkdir(os.path.dirname(dest_path))
    last_exc = None

    for attempt in range(1, max_retries + 1):
        try:
            with session.get(url, stream=True, timeout=120, allow_redirects=True) as response:
                response.raise_for_status()
                with open(dest_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=512 * 1024):
                        if chunk:
                            handle.write(chunk)
            print(f"[{timestamp()}] OK: {url} -> {dest_path}")
            return True
        except Exception as exc:
            last_exc = exc
            print(f"[{timestamp()}] WARN: download attempt {attempt}/{max_retries} failed for {url}: {exc}")
            time.sleep(1.5 * attempt)

    print(f"[{timestamp()}] ERROR: failed to download {url} to {dest_path}: {last_exc}")
    return False


def safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_dirname(name: str) -> str:
    if name is None:
        return "desconhecido"
    name = str(name).strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:150] if len(name) > 150 else name


def safe_filename(name: str) -> str:
    if not name:
        return "arquivo"
    name = os.path.basename(str(name).strip())
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    return name.strip().strip(".") or "arquivo"


def month_bounds(today: datetime.date | None = None) -> tuple[datetime.date, datetime.date]:
    today = today or datetime.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1), today.replace(day=last_day)


def build_output_dirs(output_root: str, *, include_pf_contagem: bool = True) -> Dict[str, str]:
    folder_stamp = datetime.date.today().strftime("%d-%m") + "-" + time.strftime("%H_%M")
    base_out_dir = os.path.join(".", output_root, folder_stamp)
    dirs = {
        "base": base_out_dir,
        "evidencias": os.path.join(base_out_dir, EVIDENCIAS_DIR),
        "individual": os.path.join(base_out_dir, RELATORIO_INDIVIDUAIS_DIR),
    }
    if include_pf_contagem:
        dirs["pf_contagem"] = os.path.join(base_out_dir, RELATORIO_PF_DIR)
    for path in dirs.values():
        safe_mkdir(path)
    return dirs


def options_cache(app_state: dict, project_key: str) -> dict:
    cache = app_state.setdefault("iphan_options", {})
    return cache.setdefault(project_key, {})

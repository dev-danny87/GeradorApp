import datetime
import os
import re
import time

import requests

from services.auth_service import IPHAN_BASE_URL

_app_run = True

EVIDENCIAS_DIR = "Evidências"


def set_app_run(value: bool) -> None:
    global _app_run
    _app_run = value


def is_app_running() -> bool:
    return _app_run


def timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_dirname(name: str) -> str:
    if name is None:
        return "desconhecido"
    name = str(name).strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:150] if len(name) > 150 else name


def build_output_dir(project_label: str) -> str:
    folder_stamp = datetime.date.today().strftime("%d-%m") + "-" + time.strftime("%H_%M")
    safe_label = safe_dirname(project_label)
    base_out_dir = os.path.join(".", "relatorios_iphan", safe_label, folder_stamp)
    safe_mkdir(base_out_dir)
    safe_mkdir(os.path.join(base_out_dir, EVIDENCIAS_DIR))
    return base_out_dir


def iphan_issues_path() -> str:
    return f"{IPHAN_BASE_URL}/issues"


def options_cache(app_state: dict, project_key: str) -> dict:
    cache = app_state.setdefault("iphan_options", {})
    return cache.setdefault(project_key, {})

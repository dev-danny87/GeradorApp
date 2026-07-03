import calendar
import datetime
import os
import re
import time
from typing import Dict
from urllib.parse import urljoin, urlparse

import requests

from services.auth_service import IPHAN_BASE_URL
from utils.output_paths import (
    EVIDENCIAS_DIR,
    RELATORIO_INDIVIDUAIS_DIR,
    RELATORIO_PF_DIR,
    build_iphan_run_dirs,
)

_app_run = True

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


def download_file(
    session: requests.Session,
    url: str,
    dest_path: str,
    max_retries: int = 3,
    *,
    context: str = "",
) -> bool:
    from services.iphan._error_registry import record_error

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

    message = str(last_exc)
    print(f"[{timestamp()}] ERROR: failed to download {url} to {dest_path}: {last_exc}")
    record_error(
        kind="download",
        message=message,
        url=url,
        dest_path=dest_path,
        context=context,
    )
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


def build_output_dirs(
    contract_key: str,
    month_label: str,
    *,
    include_pf_contagem: bool = True,
) -> Dict[str, str]:
    return build_iphan_run_dirs(
        contract_key,
        month_label,
        include_pf_contagem=include_pf_contagem,
    )


def options_cache(app_state: dict, project_key: str) -> dict:
    cache = app_state.setdefault("iphan_options", {})
    return cache.setdefault(project_key, {})

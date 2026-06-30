import datetime
import json
import os
import re
import time
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from services.auth_service import PGE_BASE_URL

PGE_ISSUES_PATH = f"{PGE_BASE_URL}/issues"

# Tracker IDs excluded from filter (Projeto, Ajuste, Task, Falha, Backlog, Mudança de Escopo)
_EXCLUDED_TRACKERS = ["20", "18", "3", "12", "14", "15"]

_DEFAULT_CF28_OPTIONS = [("ITEM 1 - JUNHO - 2026", "222")]

_app_run = True


def set_app_run(value: bool) -> None:
    global _app_run
    _app_run = value


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _http_get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    if "timeout" not in kwargs:
        kwargs["timeout"] = 60
    r = session.get(url, **kwargs)
    r.raise_for_status()
    return r


def _safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def build_pge_filter_url(cf_28_id: str) -> str:
    """Builds the PGE issues filter URL; only cf_28 value varies per month."""
    params = [
        ("set_filter", "1"),
        ("sort", "id:desc"),
        ("f[]", "tracker_id"),
        ("op[tracker_id]", "!"),
    ]
    for tracker_id in _EXCLUDED_TRACKERS:
        params.append(("v[tracker_id][]", tracker_id))
    params.extend([
        ("f[]", "cf_28"),
        ("op[cf_28]", "="),
        ("v[cf_28][]", cf_28_id),
        ("f[]", "status_id"),
        ("op[status_id]", "c"),
        ("f[]", ""),
        ("c[]", "parent"),
        ("c[]", "project"),
        ("c[]", "tracker"),
        ("c[]", "status"),
        ("c[]", "cf_23"),
        ("c[]", "closed_on"),
        ("c[]", "cf_20"),
        ("c[]", "cf_28"),
        ("c[]", "cf_22"),
        ("group_by", ""),
        ("t[]", "estimated_hours"),
        ("t[]", "spent_hours"),
        ("t[]", "cf_17"),
        ("t[]", "cf_21"),
        ("t[]", "cf_22"),
        ("t[]", ""),
    ])
    from urllib.parse import urlencode
    return f"{PGE_ISSUES_PATH}?{urlencode(params)}"


def fetch_cf28_options(session: requests.Session) -> List[Tuple[str, str]]:
    """Scrapes 'Entregue em' (cf_28) options from the PGE filter page."""
    try:
        url = f"{PGE_ISSUES_PATH}?set_filter=1"
        r = _http_get(session, url)
        m = re.search(
            r'"cf_28"\s*:\s*\{[^}]*"values"\s*:\s*(\[\[.*?\]\])',
            r.text,
            re.DOTALL,
        )
        if not m:
            print(f"[{_timestamp()}] WARN: cf_28 options not found; using default.")
            return list(_DEFAULT_CF28_OPTIONS)

        raw = m.group(1)
        pairs = json.loads(raw)
        options = [(str(label), str(val)) for label, val in pairs if label and val]
        if options:
            return options
    except Exception as e:
        print(f"[{_timestamp()}] WARN: failed to fetch cf_28 options: {e}")

    return list(_DEFAULT_CF28_OPTIONS)


def _absolute_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(PGE_BASE_URL + "/", href.lstrip("/"))


def _extract_issue_ids_from_list(soup: BeautifulSoup) -> List[str]:
    ids = []
    for tr in soup.select("table.list.issues tbody tr[id^='issue-']"):
        tr_id = tr.get("id", "")
        if tr_id.startswith("issue-"):
            issue_id = tr_id.replace("issue-", "").strip()
            if issue_id.isdigit():
                ids.append(issue_id)
                continue
        td_id = tr.find("td", class_="id")
        if td_id:
            link = td_id.find("a", href=re.compile(r"/issues/\d+"))
            if link:
                m = re.search(r"/issues/(\d+)", link.get("href", ""))
                if m:
                    ids.append(m.group(1))
    return ids


def _find_list_next_page(soup: BeautifulSoup) -> Optional[str]:
    next_li = soup.select_one("span.pagination li.next.page a")
    if next_li and next_li.get("href"):
        return _absolute_url(next_li["href"])
    for a in soup.select("span.pagination a"):
        text = a.get_text(strip=True)
        if "Próximo" in text and a.get("href"):
            return _absolute_url(a["href"])
    return None


def collect_all_issue_ids(session: requests.Session, filter_url: str) -> List[str]:
    """Paginates the filtered list via 'Próximo »' and collects all issue IDs."""
    all_ids: List[str] = []
    url: Optional[str] = filter_url
    page_num = 1

    while url and _app_run:
        print(f"[{_timestamp()}] Fetching list page {page_num}: {url}")
        r = _http_get(session, url)
        soup = BeautifulSoup(r.text, "html.parser")
        page_ids = _extract_issue_ids_from_list(soup)

        if not page_ids:
            print(f"[{_timestamp()}] Page {page_num} has no issues. Stopping list pagination.")
            break

        all_ids.extend(page_ids)
        print(f"[{_timestamp()}] Page {page_num}: {len(page_ids)} issues (total so far: {len(all_ids)})")

        next_url = _find_list_next_page(soup)
        if not next_url or next_url == url:
            break
        url = next_url
        page_num += 1

    return all_ids


def _extract_issue_id_from_page(soup: BeautifulSoup) -> Optional[str]:
    heading = soup.select_one("div#issue h2") or soup.find("h2")
    if heading:
        m = re.search(r"#(\d+)", heading.get_text())
        if m:
            return m.group(1)
    body = soup.find("body")
    if body and body.get("class"):
        for cls in body.get("class", []):
            if cls.startswith("issue-"):
                return cls.replace("issue-", "")
    return None


def _find_next_issue_url(soup: BeautifulSoup) -> Optional[str]:
    for a in soup.select("a[accesskey='n']"):
        href = a.get("href", "")
        if href and "/issues/" in href:
            return _absolute_url(href)

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if re.search(r"Próxim", text, re.IGNORECASE) and "/issues/" in a["href"]:
            return _absolute_url(a["href"])

    for a in soup.find_all("a", rel="next"):
        href = a.get("href", "")
        if href and "/issues/" in href:
            return _absolute_url(href)

    return None


def process_issue_page(session: requests.Session, soup: BeautifulSoup, issue_id: str) -> None:
    """Stub for phase 2 — logs the opened issue."""
    print(f"[{_timestamp()}] Issue {issue_id} opened — actions TBD")


def _visit_issue_direct(session: requests.Session, issue_id: str) -> Tuple[Optional[BeautifulSoup], str]:
    url = f"{PGE_ISSUES_PATH}/{issue_id}"
    r = _http_get(session, url)
    soup = BeautifulSoup(r.text, "html.parser")
    return soup, url


def iterate_issues_via_proxima(
    session: requests.Session,
    first_issue_id: str,
    all_ids: List[str],
) -> List[dict]:
    """Opens first issue and chains 'Próxima'; falls back to direct visits for missed IDs."""
    visited: List[dict] = []
    visited_set = set()

    url: Optional[str] = f"{PGE_ISSUES_PATH}/{first_issue_id}"
    chained = True

    while url and _app_run:
        print(f"[{_timestamp()}] Opening issue: {url}")
        r = _http_get(session, url)
        soup = BeautifulSoup(r.text, "html.parser")
        issue_id = _extract_issue_id_from_page(soup)
        if not issue_id:
            m = re.search(r"/issues/(\d+)", url)
            issue_id = m.group(1) if m else None
        if not issue_id:
            print(f"[{_timestamp()}] WARN: could not parse issue ID from {url}")
            break

        if issue_id not in visited_set:
            process_issue_page(session, soup, issue_id)
            visited.append({"ID": issue_id, "URL": url})
            visited_set.add(issue_id)

        next_url = _find_next_issue_url(soup)
        if next_url and next_url not in {v["URL"] for v in visited}:
            url = next_url
        else:
            chained = False
            break

    if not chained or len(visited_set) < len(all_ids):
        missed = [i for i in all_ids if i not in visited_set]
        if missed:
            print(f"[{_timestamp()}] Fallback: visiting {len(missed)} issue(s) not reached via Próxima.")
        for issue_id in missed:
            if not _app_run:
                break
            soup, issue_url = _visit_issue_direct(session, issue_id)
            process_issue_page(session, soup, issue_id)
            visited.append({"ID": issue_id, "URL": issue_url})
            visited_set.add(issue_id)

    return visited


def generate_evidences_pge(session, cf_28_id: str, month_label: str) -> None:
    global _app_run
    _app_run = True

    if not session:
        print(f"[{_timestamp()}] ERROR: Sessão inválida. Faça login primeiro.")
        return

    folder_stamp = datetime.date.today().strftime("%d-%m") + "-" + time.strftime("%H_%M")
    safe_month = re.sub(r'[<>:"/\\|?*]', "_", month_label)[:80]
    base_out_dir = os.path.join(".", "Relatórios", "Evidencias_pge", safe_month, folder_stamp)
    _safe_mkdir(base_out_dir)

    print(f"\n[{_timestamp()}] Preparando evidências PGE...")
    print(f"Entregue em: {month_label} (cf_28={cf_28_id})")
    print(f"Pasta de saída: {base_out_dir}")

    filter_url = build_pge_filter_url(cf_28_id)
    print(f"\n[{_timestamp()}] URL do filtro: {filter_url}")

    all_ids = collect_all_issue_ids(session, filter_url)
    if not all_ids:
        print(f"[{_timestamp()}] Nenhuma issue encontrada. Encerrando.")
        return

    print(f"\n[{_timestamp()}] Total de issues na lista: {len(all_ids)}")

    first_issue_id = all_ids[0]
    visited = iterate_issues_via_proxima(session, first_issue_id, all_ids)

    if visited:
        df = pd.DataFrame(visited)
        csv_path = os.path.join(base_out_dir, "issues_visited.csv")
        df.to_csv(csv_path, sep=";", index=False, encoding="utf-8-sig")
        print(f"\n[{_timestamp()}] Issues visitadas: {len(visited)}")
        print(f"[{_timestamp()}] CSV salvo: {csv_path}")

    print(f"\n[{_timestamp()}] Fim! DIRETORIO_FINAL:{base_out_dir}")

import datetime
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from services.auth_service import IPHAN_BASE_URL
from services.iphan._common import absolute_url, http_get
from services.iphan._wiki_backlog import (
    SprintBlock,
    _cell_at,
    _cell_text,
    _column_index_map,
    _normalize_person,
)

SAIP_SPRINTS_WIKI_URL = f"{IPHAN_BASE_URL}/projects/licenciamento-ambiental/wiki/Sprints"
SAIP_SPRINTS_PDF_URL = f"{SAIP_SPRINTS_WIKI_URL}.pdf"
SAIP_WIKI_BASE = f"{IPHAN_BASE_URL}/projects/licenciamento-ambiental/wiki"

_SAIP_SPRINT_HEADER_RE = re.compile(
    r"SAIP\d+-Sprint(\d+)\s*\((\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})\)",
    re.IGNORECASE,
)
_SAIP_SPRINT_SLUG_RE = re.compile(r"(SAIP\d+-Sprint\d+)", re.IGNORECASE)
_BR_DATE_FMT = "%d/%m/%Y"


@dataclass
class SaipRow:
    sprint_number: int
    sprint_slug: str
    hu_number: str
    priority: str
    po: str
    analyst: str
    developers: List[str]
    inclusion_date: str
    qtd_pf: float
    title_text: str
    wiki_slug: str
    wiki_url: str
    status_text: str

    def assignees(self) -> List[str]:
        people: List[str] = []
        for name in (self.po, self.analyst, *self.developers):
            normalized = _normalize_person(name)
            if normalized and normalized not in people:
                people.append(normalized)
        if not people:
            return ["sem_responsavel"]
        return people


@dataclass
class SaipWikiAttachment:
    filename: str
    download_url: str


@dataclass
class SaipSprintPageData:
    rows: List[SaipRow]
    attachments: List[SaipWikiAttachment]
    bulk_download_url: str = ""


@dataclass
class SaipSprintBlock(SprintBlock):
    sprint_slug: str = ""
    sprint_wiki_url: str = ""


def _parse_br_date(value: str) -> datetime.date:
    return datetime.datetime.strptime(value.strip(), _BR_DATE_FMT).date()


def _wiki_slug_from_href(href: str) -> str:
    path = urlparse(href).path
    if "/wiki/" not in path:
        return ""
    return unquote(path.split("/wiki/")[-1]).strip("/")


def _wiki_link_from_cell(cell) -> Optional[object]:
    for link in cell.find_all("a", href=True):
        if "/wiki/" in link["href"]:
            return link
    return None


def _wiki_link_from_heading(heading) -> Optional[object]:
    for link in heading.find_all("a", href=True):
        if "/wiki/" in link["href"]:
            return link
    return None


def _sprint_slug_from_title(title: str) -> str:
    match = _SAIP_SPRINT_SLUG_RE.search(title or "")
    return match.group(1) if match else ""


def _column_idx(columns: dict[str, int], *keys: str) -> int:
    for key in keys:
        idx = columns.get(key, -1)
        if idx >= 0:
            return idx
    return -1


def _split_people(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"\s*/\s*", text)
    return [_normalize_person(part) for part in parts if _normalize_person(part)]


def _parse_qtd_pf(value: str) -> float:
    text = (value or "").strip().replace(",", ".")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_saip_sprints_index_html(html: str) -> List[SaipSprintBlock]:
    soup = BeautifulSoup(html, "html.parser")
    wiki_root = soup.select_one("div.wiki.wiki-page") or soup
    sprints: List[SaipSprintBlock] = []

    for heading in wiki_root.find_all("h2"):
        title = heading.get_text(" ", strip=True)
        match = _SAIP_SPRINT_HEADER_RE.search(title)
        if not match:
            continue

        sprint_number = int(match.group(1))
        start_date = _parse_br_date(match.group(2))
        end_date = _parse_br_date(match.group(3))

        link = _wiki_link_from_heading(heading)
        sprint_wiki_url = absolute_url(link["href"]) if link and link.get("href") else ""

        sprint_slug = ""
        if link and link.get("href"):
            sprint_slug = _wiki_slug_from_href(link["href"])
        if not sprint_slug:
            sprint_slug = _sprint_slug_from_title(title)
        if not sprint_wiki_url and sprint_slug:
            sprint_wiki_url = f"{SAIP_WIKI_BASE}/{sprint_slug}"

        sprints.append(
            SaipSprintBlock(
                sprint_number=sprint_number,
                start_date=start_date,
                end_date=end_date,
                title=title,
                sprint_slug=sprint_slug,
                sprint_wiki_url=sprint_wiki_url,
            )
        )

    return sprints


def parse_saip_sprint_page_html(
    html: str,
    sprint_number: int,
    *,
    sprint_slug: str = "",
) -> List[SaipRow]:
    soup = BeautifulSoup(html, "html.parser")
    wiki_root = soup.select_one("div.wiki.wiki-page") or soup
    table = wiki_root.find("table")
    if not table:
        return []

    columns = _column_index_map(table)
    if not columns:
        return []

    hu_idx = _column_idx(columns, "Nº HU", "N HU", "NO HU")
    priority_idx = _column_idx(columns, "PRIORIDADE")
    title_idx = _column_idx(columns, "TÍTULO", "TITULO")
    po_idx = _column_idx(
        columns,
        "P.O RESPONSAVEL",
        "P.O. RESPONSAVEL",
        "P.O. RESPONSÁVEL",
        "P.O RESPONSÁVEL",
    )
    analyst_idx = _column_idx(columns, "ANALISTA REQUISITOS", "ANALISTA DE REQUISITOS")
    developer_idx = _column_idx(columns, "DESENVOLVEDOR")
    inclusion_idx = _column_idx(columns, "DATA DA INCLUSÃO", "DATA DA INCLUSAO")
    status_idx = _column_idx(columns, "STATUS")
    qtd_pf_idx = _column_idx(columns, "QTD PF")

    rows: List[SaipRow] = []
    for row in table.find_all("tr")[1:]:
        title_cell = _cell_at(row, title_idx)
        if not title_cell:
            continue

        link = _wiki_link_from_cell(title_cell)
        if not link or not link.get("href"):
            continue

        wiki_href = absolute_url(link["href"])
        wiki_slug = _wiki_slug_from_href(link["href"])
        if not wiki_slug:
            continue

        rows.append(
            SaipRow(
                sprint_number=sprint_number,
                sprint_slug=sprint_slug,
                hu_number=_cell_text(row, hu_idx) if hu_idx >= 0 else "",
                priority=_cell_text(row, priority_idx) if priority_idx >= 0 else "",
                po=_normalize_person(_cell_text(row, po_idx) if po_idx >= 0 else ""),
                analyst=_normalize_person(_cell_text(row, analyst_idx) if analyst_idx >= 0 else ""),
                developers=_split_people(_cell_text(row, developer_idx) if developer_idx >= 0 else ""),
                inclusion_date=_cell_text(row, inclusion_idx) if inclusion_idx >= 0 else "",
                qtd_pf=_parse_qtd_pf(_cell_text(row, qtd_pf_idx) if qtd_pf_idx >= 0 else ""),
                title_text=link.get_text(" ", strip=True) or wiki_slug,
                wiki_slug=wiki_slug,
                wiki_url=wiki_href,
                status_text=_cell_text(row, status_idx) if status_idx >= 0 else "",
            )
        )

    return rows


def parse_sprint_page_attachments(html: str) -> tuple[List[SaipWikiAttachment], str]:
    soup = BeautifulSoup(html, "html.parser")
    attachments_div = soup.select_one("div.attachments")
    if not attachments_div:
        return [], ""

    entries: List[SaipWikiAttachment] = []
    seen_urls: set[str] = set()
    bulk_download_url = ""

    bulk_link = attachments_div.select_one('a[href*="/attachments/wiki_pages/"][href*="/download"]')
    if bulk_link and bulk_link.get("href"):
        bulk_download_url = absolute_url(bulk_link["href"])

    for link in attachments_div.select('a[href*="/attachments/download/"]'):
        href = link.get("href", "")
        if not href:
            continue

        if "icon-del" in (link.get("class") or []):
            continue

        if "/attachments/wiki_pages/" in href:
            continue

        download_url = absolute_url(href)
        if download_url in seen_urls:
            continue
        seen_urls.add(download_url)

        filename = ""
        row = link.find_parent("tr")
        if row:
            name_link = row.select_one("a.icon-attachment")
            if name_link:
                filename = name_link.get_text(strip=True)
        if not filename:
            filename = unquote(href.rstrip("/").split("/")[-1])

        entries.append(SaipWikiAttachment(filename=filename, download_url=download_url))

    return entries, bulk_download_url


def parse_saip_sprint_page(html: str, sprint: SaipSprintBlock) -> SaipSprintPageData:
    rows = parse_saip_sprint_page_html(
        html,
        sprint.sprint_number,
        sprint_slug=sprint.sprint_slug,
    )
    attachments, bulk_download_url = parse_sprint_page_attachments(html)
    return SaipSprintPageData(
        rows=rows,
        attachments=attachments,
        bulk_download_url=bulk_download_url,
    )


def fetch_saip_sprint_page(session, sprint: SaipSprintBlock) -> SaipSprintPageData:
    if not sprint.sprint_wiki_url:
        return SaipSprintPageData(rows=[], attachments=[])
    html = http_get(session, sprint.sprint_wiki_url).text
    return parse_saip_sprint_page(html, sprint)


def fetch_saip_sprint_rows(session, sprint: SaipSprintBlock) -> List[SaipRow]:
    return fetch_saip_sprint_page(session, sprint).rows


def collect_saip_data(
    session,
    sprints: List[SaipSprintBlock],
) -> tuple[List[SaipRow], dict[str, SaipSprintPageData]]:
    rows: List[SaipRow] = []
    pages_by_sprint: dict[str, SaipSprintPageData] = {}

    for sprint in sprints:
        page_data = fetch_saip_sprint_page(session, sprint)
        rows.extend(page_data.rows)
        if sprint.sprint_slug:
            pages_by_sprint[sprint.sprint_slug] = page_data

    return rows, pages_by_sprint


def collect_saip_rows(session, sprints: List[SaipSprintBlock]) -> List[SaipRow]:
    rows, _ = collect_saip_data(session, sprints)
    return rows

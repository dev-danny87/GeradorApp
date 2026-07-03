import datetime
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from services.auth_service import IPHAN_BASE_URL
from services.iphan._common import absolute_url, http_get, timestamp

BACKLOG_WIKI_URL = f"{IPHAN_BASE_URL}/projects/premiacoes-iphan/wiki/Backlog"
BACKLOG_PDF_URL = f"{BACKLOG_WIKI_URL}.pdf"

PAINEL_BACKLOG_WIKI_URL = f"{IPHAN_BASE_URL}/projects/painel-da-ouvidoria/wiki/BACKLOG"
PAINEL_BACKLOG_PDF_URL = f"{PAINEL_BACKLOG_WIKI_URL}.pdf"

_SPRINT_HEADER_RE = re.compile(
    r"Sprint\s*#(\d+)\s*\((\d{2}/\d{2}/\d{4})\s*(?:-|a)\s*(\d{2}/\d{2}/\d{4})\)",
    re.IGNORECASE,
)
_BR_DATE_FMT = "%d/%m/%Y"
_EMPTY_ASSIGNEE = frozenset({"–", "-", "--"})


@dataclass
class WikiBacklogConfig:
    wiki_url: str
    read_analyst: bool = False


@dataclass
class BacklogRow:
    sprint_number: int
    developer: str
    title_text: str
    wiki_slug: str
    wiki_url: str
    status_text: str
    analyst: str = ""

    def assignees(self, *, developer_only: bool = False) -> List[str]:
        people: List[str] = []
        for name in (() if developer_only else (self.analyst,)) + (self.developer,):
            normalized = _normalize_person(name)
            if normalized and normalized not in people:
                people.append(normalized)
        if not people:
            return ["sem_desenvolvedor" if developer_only else "sem_responsavel"]
        return people


@dataclass
class SprintBlock:
    sprint_number: int
    start_date: datetime.date
    end_date: datetime.date
    title: str
    rows: List[BacklogRow] = field(default_factory=list)


def fetch_backlog_html(session, wiki_url: str = BACKLOG_WIKI_URL) -> str:
    response = http_get(session, wiki_url)
    return response.text


def fetch_wiki_page_html(session, wiki_url: str) -> str:
    response = http_get(session, wiki_url)
    return response.text


def wiki_slug_from_url(url: str) -> str:
    path = urlparse(url).path
    if "/wiki/" not in path:
        return ""
    slug = unquote(path.split("/wiki/")[-1]).strip("/")
    if slug.lower().endswith(".pdf"):
        slug = slug[:-4]
    return slug


def extract_pdf_url_from_wiki_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("p.other-formats a.pdf[href]")
    if not link:
        content = soup.select_one("#content") or soup
        link = content.select_one("a.pdf[href]")
    if not link or not link.get("href"):
        return None
    return absolute_url(link["href"])


def resolve_wiki_assets(session, wiki_url: str) -> Optional[tuple[str, str]]:
    try:
        response = http_get(session, wiki_url)
        canonical_wiki_url = response.url.rstrip("/")
        pdf_url = extract_pdf_url_from_wiki_html(response.text)
        if not pdf_url:
            pdf_url = canonical_wiki_url + ".pdf"
            print(
                f"[{timestamp()}] WARN: PDF não encontrado em other-formats; "
                f"usando fallback: {pdf_url}"
            )
        return pdf_url, canonical_wiki_url
    except Exception as exc:
        print(f"[{timestamp()}] WARN: falha ao ler wiki {wiki_url}: {exc}")
        return None


def resolve_wiki_pdf_url(session, wiki_url: str) -> Optional[str]:
    assets = resolve_wiki_assets(session, wiki_url)
    return assets[0] if assets else None


def _parse_br_date(value: str) -> datetime.date:
    return datetime.datetime.strptime(value.strip(), _BR_DATE_FMT).date()


def _normalize_header(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().upper())


def _normalize_person(name: str) -> str:
    text = (name or "").strip()
    if not text or text in _EMPTY_ASSIGNEE:
        return ""
    return text


def is_cancelled_status(status_text: str) -> bool:
    normalized = (
        unicodedata.normalize("NFKD", status_text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return "cancelad" in normalized


def _column_index_map(table) -> dict[str, int]:
    header_row = table.find("tr")
    if not header_row:
        return {}
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_row.find_all(["th", "td"])):
        key = _normalize_header(cell.get_text(" ", strip=True))
        if key:
            mapping[key] = idx
    return mapping


def _cell_text(row, index: int) -> str:
    cells = row.find_all(["td", "th"])
    if index < 0 or index >= len(cells):
        return ""
    return cells[index].get_text(" ", strip=True)


def _cell_at(row, index: int):
    cells = row.find_all(["td", "th"])
    if index < 0 or index >= len(cells):
        return None
    return cells[index]


def _wiki_slug_from_href(href: str) -> str:
    path = urlparse(href).path
    if "/wiki/" not in path:
        return ""
    return unquote(path.split("/wiki/")[-1]).strip("/")


def _parse_sprint_table(table, sprint_number: int, *, read_analyst: bool = False) -> List[BacklogRow]:
    rows: List[BacklogRow] = []
    columns = _column_index_map(table)
    if not columns:
        return rows

    title_idx = columns.get("TÍTULO", columns.get("TITULO", -1))
    status_idx = columns.get("STATUS", -1)
    developer_idx = columns.get("DESENVOLVEDOR", -1)
    analyst_idx = columns.get("ANALISTA DE REQUISITOS", -1) if read_analyst else -1

    for row in table.find_all("tr")[1:]:
        status_text = _cell_text(row, status_idx)
        if "concluído" not in status_text.lower():
            continue

        title_cell = _cell_at(row, title_idx)
        if not title_cell:
            continue

        link = title_cell.find("a", class_="wiki-page")
        if not link or not link.get("href"):
            continue

        wiki_href = absolute_url(link["href"])
        wiki_slug = _wiki_slug_from_href(link["href"])
        if not wiki_slug:
            continue

        developer = _normalize_person(_cell_text(row, developer_idx) if developer_idx >= 0 else "")
        analyst = _normalize_person(_cell_text(row, analyst_idx) if analyst_idx >= 0 else "")

        if not read_analyst and not developer:
            developer = "sem_desenvolvedor"

        rows.append(
            BacklogRow(
                sprint_number=sprint_number,
                developer=developer,
                analyst=analyst,
                title_text=link.get_text(" ", strip=True) or wiki_slug,
                wiki_slug=wiki_slug,
                wiki_url=wiki_href,
                status_text=status_text,
            )
        )

    return rows


def parse_backlog_html(html: str, *, read_analyst: bool = False) -> List[SprintBlock]:
    soup = BeautifulSoup(html, "html.parser")
    wiki_root = soup.select_one("div.wiki.wiki-page") or soup
    sprints: List[SprintBlock] = []

    for heading in wiki_root.find_all("h2"):
        title = heading.get_text(" ", strip=True)
        match = _SPRINT_HEADER_RE.search(title)
        if not match:
            continue

        sprint_number = int(match.group(1))
        start_date = _parse_br_date(match.group(2))
        end_date = _parse_br_date(match.group(3))

        table = heading.find_next("table")
        if not table:
            continue

        block = SprintBlock(
            sprint_number=sprint_number,
            start_date=start_date,
            end_date=end_date,
            title=title,
            rows=_parse_sprint_table(table, sprint_number, read_analyst=read_analyst),
        )
        sprints.append(block)

    return sprints


def filter_sprints_by_end_date(
    sprints: List[SprintBlock],
    start_date: datetime.date,
    end_date: datetime.date,
) -> List[SprintBlock]:
    return [
        sprint
        for sprint in sprints
        if start_date <= sprint.end_date <= end_date
    ]


def collect_matching_rows(sprints: List[SprintBlock]) -> List[BacklogRow]:
    rows: List[BacklogRow] = []
    for sprint in sprints:
        rows.extend(sprint.rows)
    return rows

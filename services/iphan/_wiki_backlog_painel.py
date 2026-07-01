import datetime
import re
from typing import List
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from services.iphan._common import absolute_url
from services.iphan._wiki_backlog import (
    BacklogRow,
    SprintBlock,
    _cell_at,
    _cell_text,
    _column_index_map,
    _normalize_person,
)

_PAINEL_SPRINT_HEADER_RE = re.compile(
    r"SPRINT\s+(\d+)\s*-\s*(\d{2}/\d{2})\s+a\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_BR_DATE_FMT = "%d/%m/%Y"
_COMPLETED_STATUSES = ("concluído", "concluido", "finalizado")


def _parse_painel_sprint_dates(start_short: str, end_full: str) -> tuple[datetime.date, datetime.date]:
    end_date = datetime.datetime.strptime(end_full.strip(), _BR_DATE_FMT).date()
    start_day, start_month = map(int, start_short.strip().split("/"))
    start_year = end_date.year - 1 if start_month > end_date.month else end_date.year
    start_date = datetime.date(start_year, start_month, start_day)
    return start_date, end_date


def _is_completed_status(status_text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (status_text or "").strip().lower())
    return any(status in normalized for status in _COMPLETED_STATUSES)


def _wiki_slug_from_href(href: str) -> str:
    path = urlparse(href).path
    if "/wiki/" not in path:
        return ""
    return unquote(path.split("/wiki/")[-1]).strip("/")


def _parse_painel_sprint_table(table, sprint_number: int) -> List[BacklogRow]:
    rows: List[BacklogRow] = []
    columns = _column_index_map(table)
    if not columns:
        return rows

    title_idx = columns.get("TÍTULO", columns.get("TITULO", -1))
    status_idx = columns.get("STATUS", -1)
    developer_idx = columns.get("DESENVOLVEDOR", -1)
    analyst_idx = columns.get("ANALISTA DE REQUISITOS", -1)

    for row in table.find_all("tr")[1:]:
        status_text = _cell_text(row, status_idx)
        if not _is_completed_status(status_text):
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


def parse_painel_backlog_html(html: str) -> List[SprintBlock]:
    soup = BeautifulSoup(html, "html.parser")
    wiki_root = soup.select_one("div.wiki.wiki-page") or soup
    sprints: List[SprintBlock] = []

    for heading in wiki_root.find_all("h2"):
        title = heading.get_text(" ", strip=True)
        match = _PAINEL_SPRINT_HEADER_RE.search(title)
        if not match:
            continue

        sprint_number = int(match.group(1))
        start_date, end_date = _parse_painel_sprint_dates(match.group(2), match.group(3))

        table = heading.find_next("table")
        if not table:
            continue

        block = SprintBlock(
            sprint_number=sprint_number,
            start_date=start_date,
            end_date=end_date,
            title=title,
            rows=_parse_painel_sprint_table(table, sprint_number),
        )
        sprints.append(block)

    return sprints

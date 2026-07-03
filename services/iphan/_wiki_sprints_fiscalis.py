import datetime
import re
from typing import List, Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from services.auth_service import IPHAN_BASE_URL
from services.iphan._common import absolute_url, http_get
from services.iphan._wiki_sprints_saip import (
    SaipRow,
    SaipSprintBlock,
    SaipSprintPageData,
    parse_saip_sprint_page_html,
    parse_sprint_page_attachments,
)

FISCALIS_SPRINT_WIKI_URL = f"{IPHAN_BASE_URL}/projects/fiscalis/wiki/Sprint"
FISCALIS_SPRINT_PDF_URL = f"{FISCALIS_SPRINT_WIKI_URL}.pdf"
FISCALIS_WIKI_BASE = f"{IPHAN_BASE_URL}/projects/fiscalis/wiki"

_FISCALIS_SPRINT_HEADER_RE = re.compile(
    r"FISCALIS2?\.?0?-Sprint0*(\d+)\s*\((\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_FISCALIS_SPRINT_SLUG_RE = re.compile(r"(FISCALIS20-Sprint\d+)", re.IGNORECASE)
_BR_DATE_FMT = "%d/%m/%Y"


def _parse_br_date(value: str) -> datetime.date:
    return datetime.datetime.strptime(value.strip(), _BR_DATE_FMT).date()


def _wiki_slug_from_href(href: str) -> str:
    path = urlparse(href).path
    if "/wiki/" not in path:
        return ""
    return unquote(path.split("/wiki/")[-1]).strip("/")


def _wiki_link_from_heading(heading) -> Optional[object]:
    for link in heading.find_all("a", href=True):
        if "/wiki/" in link["href"]:
            return link
    return None


def _sprint_slug_from_title(title: str) -> str:
    match = _FISCALIS_SPRINT_SLUG_RE.search(title or "")
    return match.group(1) if match else ""


def parse_fiscalis_sprints_index_html(html: str) -> List[SaipSprintBlock]:
    soup = BeautifulSoup(html, "html.parser")
    wiki_root = soup.select_one("div.wiki.wiki-page") or soup
    sprints: List[SaipSprintBlock] = []

    for heading in wiki_root.find_all("h2"):
        title = heading.get_text(" ", strip=True)
        match = _FISCALIS_SPRINT_HEADER_RE.search(title)
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
            sprint_wiki_url = f"{FISCALIS_WIKI_BASE}/{sprint_slug}"

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


def parse_fiscalis_sprint_page(html: str, sprint: SaipSprintBlock) -> SaipSprintPageData:
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


def fetch_fiscalis_sprint_page(session, sprint: SaipSprintBlock) -> SaipSprintPageData:
    if not sprint.sprint_wiki_url:
        return SaipSprintPageData(rows=[], attachments=[])
    html = http_get(session, sprint.sprint_wiki_url).text
    return parse_fiscalis_sprint_page(html, sprint)


def collect_fiscalis_data(
    session,
    sprints: List[SaipSprintBlock],
) -> tuple[List[SaipRow], dict[str, SaipSprintPageData]]:
    rows: List[SaipRow] = []
    pages_by_sprint: dict[str, SaipSprintPageData] = {}

    for sprint in sprints:
        page_data = fetch_fiscalis_sprint_page(session, sprint)
        rows.extend(page_data.rows)
        if sprint.sprint_slug:
            pages_by_sprint[sprint.sprint_slug] = page_data

    return rows, pages_by_sprint

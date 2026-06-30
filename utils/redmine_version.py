import datetime
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def get_dynamic_version(
    base_version: Optional[str] = None,
    reference_date: Optional[datetime.datetime] = None,
) -> str:
    """Compute Redmine fixed_version_id from .env anchor and month offset."""
    base = base_version or os.getenv("STARTING_VERSAO", "489")
    starting_date_str = os.getenv("STARTING_DATE")
    if not starting_date_str:
        return str(base)

    start_dt = datetime.datetime.strptime(starting_date_str, "%Y-%m-%d")
    ref = reference_date or datetime.datetime.now()
    months_diff = (ref.year - start_dt.year) * 12 + (ref.month - start_dt.month)
    months_diff = max(0, months_diff)
    return str(int(base) + months_diff * 4)

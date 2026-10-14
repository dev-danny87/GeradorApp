"""Read-only metrics PDF built from banco de horas tasks."""

from services.metrics_report.aggregate import aggregate_tasks
from services.metrics_report.pdf_report import write_metrics_pdf

__all__ = ["aggregate_tasks", "write_metrics_pdf"]

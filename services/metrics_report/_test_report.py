import json
import os
import tempfile
import unittest

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from services.metrics_report.aggregate import aggregate_tasks, tasks_for_timeline
from services.metrics_report.art_direction import clean_svg, fallback_direction, sanitize_art_direction
from services.metrics_report.charts import month_bar, render_donut
from layout.tab_metrics_report import filesystem_save_path
from services.metrics_report.pdf_report import write_metrics_pdf

_CIRCLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<circle cx="32" cy="32" r="20" fill="#E8C56B"/></svg>'
)
_TEXT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<text x="4" y="20">Hi</text></svg>'
)


def _task(title, hours, category, when, links):
    return {
        "task_id": title,
        "task_title": title,
        "category": category,
        "estimated_hours": hours,
        "description": "**Contexto:**\nAjuste de fluxo.\n\n**Detalhes Técnicos:**\nCódigo alterado.",
        "affected_files": ["src/App.java"],
        "commit_links": links,
        "_report_date": when,
    }


class AggregateTests(unittest.TestCase):
    def test_buckets_months_and_unique_commits_without_writing(self):
        tasks = [
            _task("Corrigir login", 4, "Feature", "2026-03-02T10:00:00", [
                "https://gitlab.example/commit/aaa",
                "https://gitlab.example/commit/bbb",
            ]),
            _task("Ajustar fila", 2, "Bug", "2026-03-02T10:00:00", [
                "https://gitlab.example/commit/aaa",
            ]),
            _task("Limpar fila", 8, "Desconhecido", "2026-01-15T08:00:00", []),
            _task("Fechar ano", 1, "Chore", "2025-12-20T08:00:00", [
                "https://gitlab.example/commit/ccc",
            ]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "banco_teste.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"tasks": tasks}, handle)
            with open(path, "rb") as handle:
                before = handle.read()
            bundle = aggregate_tasks(tasks)
            with open(path, "rb") as handle:
                self.assertEqual(before, handle.read())

        self.assertEqual([year.year for year in bundle.years], [2025, 2026])
        year = bundle.years[1]
        self.assertEqual([month.month for month in year.months], [1, 3])
        march = year.months[1]
        self.assertEqual(march.commit_count, 2)
        self.assertEqual(march.task_count, 2)
        self.assertEqual(march.total_hours, 6)
        self.assertEqual(march.hours_by_category[0][0], "Feature")
        self.assertEqual(year.months[0].tasks[0].category, "Outros")
        self.assertEqual(year.commit_count, 2)
        self.assertEqual(year.commit_urls, (
            "https://gitlab.example/commit/aaa",
            "https://gitlab.example/commit/bbb",
        ))
        source = os.path.join(os.path.dirname(__file__), "aggregate.py")
        with open(source, encoding="utf-8") as handle:
            self.assertNotIn("remove_tasks_by_ids", handle.read())

    def test_timeline_keeps_the_fourteen_largest_tasks(self):
        tasks = tuple(
            aggregate_tasks([
                _task(f"Tarefa {index}", hours, "Feature", "2026-04-02T09:00:00", [])
                for index, hours in enumerate([1] + [10] * 14)
            ]).years[0].months[0].tasks
        )
        shown = tasks_for_timeline(tasks)
        self.assertEqual(len(tasks), 15)
        self.assertEqual(len(shown), 14)
        self.assertNotIn(1, [task.hours for task in shown])
        self.assertEqual(shown, sorted(shown, key=lambda task: (task.spent_on, task.title, task.task_id)))

    def test_month_bar_uses_eight_hours_as_one_day(self):
        start, end = month_bar(1, 8, 31)
        self.assertEqual(start, 0)
        self.assertAlmostEqual(end, 1 / 31)

    def test_one_bad_task_does_not_drop_the_rest(self):
        messages: list[str] = []
        tasks = [
            _task("Boa", 4, "Feature", "2026-03-02T10:00:00", []),
            _task("Ruim sem data", 2, "Bugfix", "", []),
            _task("Outra boa", 3, "Chore", "2026-03-03T10:00:00", []),
        ]
        bundle = aggregate_tasks(tasks, on_progress=messages.append)
        titles = [
            task.title
            for year in bundle.years
            for month in year.months
            for task in month.tasks
        ]
        self.assertEqual(titles, ["Boa", "Outra boa"])
        self.assertEqual(bundle.prepared_count, 2)
        self.assertEqual(bundle.failed_count, 1)
        self.assertEqual(bundle.skipped_count, 1)
        self.assertTrue(any("pulada" in message for message in messages))
        self.assertTrue(any("Ruim sem data" in message for message in messages))
        self.assertTrue(any("1/3 — Boa" in message for message in messages))

    def test_prepare_failure_keeps_previous_tasks(self):
        from unittest import mock

        from services.metrics_report import aggregate as aggregate_mod

        messages: list[str] = []
        tasks = [
            _task("Primeira", 4, "Feature", "2026-03-02T10:00:00", []),
            _task("Segunda", 2, "Bugfix", "2026-03-02T10:00:00", []),
        ]
        original = aggregate_mod.prepare_report_task
        calls = {"n": 0}

        def flaky(task):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("falha forçada na segunda")
            return original(task)

        with mock.patch.object(aggregate_mod, "prepare_report_task", side_effect=flaky):
            bundle = aggregate_mod.aggregate_tasks(tasks, on_progress=messages.append)

        titles = [
            task.title
            for year in bundle.years
            for month in year.months
            for task in month.tasks
        ]
        self.assertEqual(titles, ["Primeira"])
        self.assertEqual(bundle.prepared_count, 1)
        self.assertEqual(bundle.failed_count, 1)
        self.assertTrue(any("falha forçada" in message for message in messages))


class PeriodFolderTests(unittest.TestCase):
    def test_lists_monthly_folders_in_calendar_order(self):
        from services.metrics_report.period_reports import list_period_reports

        with tempfile.TemporaryDirectory() as tmp:
            for month, label in ((3, "Março 2026"), (1, "Janeiro 2026")):
                folder = os.path.join(tmp, "relatorios", "metricas", "SICOR", f"2026-{month:02d}")
                os.makedirs(folder)
                with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as handle:
                    json.dump({
                        "kind": "periodo",
                        "period": {"year": 2026, "month": month, "label": label},
                        "task_count": month,
                    }, handle)
            listed = list_period_reports("SICOR", root=tmp)
        self.assertEqual([item["month"] for item in listed], [1, 3])
        self.assertEqual(listed[0]["label"], "Janeiro 2026")


class PeriodMappingTests(unittest.TestCase):
    def test_january_through_october_in_creation_order(self):
        from services.metrics_report.apply_sicor_periods import PERIOD_FILES, stamp_copy

        self.assertEqual([month for month, _name in PERIOD_FILES], list(range(1, 11)))
        self.assertEqual(PERIOD_FILES[0][1], "ai_tasks_danilo.machado_2026-10-08_184714.json")
        self.assertEqual(PERIOD_FILES[-1][1], "ai_tasks_danilo.machado_2026-10-09_094817.json")
        stamped = stamp_copy({"tasks": [{"task_title": "Uma"}]}, 3)
        self.assertEqual(stamped["period"]["month"], 3)
        self.assertEqual(stamped["tasks"][0]["work_date"], "2026-03-01")
        self.assertEqual(stamped["tasks"][0]["period"]["label"], "Março 2026")

    def test_period_stamp_is_a_month_not_a_day(self):
        from services.metrics_report.aggregate import prepare_report_task

        task = prepare_report_task({
            "task_title": "Uma",
            "estimated_hours": 4,
            "period": {"year": 2026, "month": 3, "label": "Março 2026"},
            "work_date": "2026-03-01",
        })
        self.assertEqual(task.spent_on.month, 3)
        self.assertFalse(task.day_known)

    def test_source_file_maps_to_january(self):
        from services.metrics_report.apply_sicor_periods import period_for_source

        period = period_for_source(
            r"C:\ai_tasks\ai_tasks_danilo.machado_2026-10-08_184714.json"
        )
        self.assertEqual(period["month"], 1)
        self.assertEqual(period["label"], "Janeiro 2026")
        self.assertIsNone(period_for_source("ai_tasks_danilo.machado_2026-08-28_165317.json"))


class ArtDirectionTests(unittest.TestCase):
    def setUp(self):
        self.totals = {
            "project": "SICOR",
            "years": [
                {
                    "year": 2026,
                    "hours": 6,
                    "tasks": 2,
                    "commits": 2,
                    "percent_with_commits": 100,
                    "months": [
                        {
                            "key": "2026-03",
                            "hours": 6,
                            "tasks": 2,
                            "commits": 2,
                            "percent_with_commits": 100,
                        }
                    ],
                }
            ],
        }

    def test_rejects_invented_numbers_and_text_svg(self):
        art = sanitize_art_direction(
            {
                "year_headline": "Foram 6 horas em 2026.",
                "month_headlines": {
                    "2026-03": "Quase 99 horas.",
                    "2026-04": "Mês fora da seleção com 6 horas.",
                },
                "header_svg": _CIRCLE_SVG,
                "corner_svg": _TEXT_SVG,
                "icon_svgs": {"commits": "<svg><script>alert(1)</script></svg>"},
            },
            self.totals,
        )
        self.assertEqual(art.headline_for_year(2026), "Foram 6 horas em 2026.")
        self.assertEqual(art.headline_for_month("2026-03"), "")
        self.assertEqual(art.header_svg, _CIRCLE_SVG)
        self.assertIsNone(art.corner_svg)
        self.assertEqual(art.icon_svgs, {})
        self.assertIsNone(clean_svg(_TEXT_SVG))
        self.assertFalse(art.used_fallback)

    def test_fallback_has_no_headline(self):
        art = fallback_direction()
        self.assertTrue(art.used_fallback)
        self.assertEqual(art.headline_for_year(2026), "")
        self.assertEqual(art.palette["gold"], "#E8C56B")


class MetricsFolderTests(unittest.TestCase):
    def test_report_path_is_inside_relatorios_metricas(self):
        from utils.output_paths import build_metrics_report_path

        with tempfile.TemporaryDirectory() as tmp:
            path = build_metrics_report_path("SICOR", root=tmp)
            normalized = path.replace("\\", "/")
            self.assertIn("/relatorios/metricas/SICOR/", normalized)
            self.assertTrue(normalized.endswith(".pdf"))
            self.assertTrue(os.path.isdir(os.path.dirname(path)))
            self.assertFalse(os.path.isfile(path))

    def test_default_report_path_uses_task_manager(self):
        from utils.app_config import task_manager_dir
        from utils.output_paths import build_metrics_report_path

        path = build_metrics_report_path("SICOR")
        expected_root = str(task_manager_dir()).replace("\\", "/")
        normalized = path.replace("\\", "/")
        self.assertTrue(normalized.startswith(expected_root + "/relatorios/metricas/SICOR/"))
        try:
            os.remove(path)
        except OSError:
            pass


class SavePathTests(unittest.TestCase):
    def test_accepts_a_plain_path_and_a_file_uri(self):
        self.assertEqual(filesystem_save_path(r"C:\relatorios\saida.pdf"), r"C:\relatorios\saida.pdf")
        uri = filesystem_save_path("file:///C:/relatorios/saida.pdf")
        if os.name == "nt":
            self.assertEqual(uri, "C:/relatorios/saida.pdf")
        else:
            self.assertEqual(uri, "/C:/relatorios/saida.pdf")
        self.assertIsNone(filesystem_save_path(None))
        self.assertIsNone(filesystem_save_path(""))
        self.assertEqual(filesystem_save_path({"path": r"D:\a.pdf"}), r"D:\a.pdf")


class PdfReportTests(unittest.TestCase):
    def test_merges_cover_and_close_around_the_body(self):
        tasks = [
            _task("Corrigir login", 4, "Feature", "2026-03-02T10:00:00", [
                "https://gitlab.example/commit/aaa",
            ]),
            _task("Ajustar fila", 2, "Bugfix", "2026-03-18T10:00:00", []),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cover = os.path.join(tmp, "capa.pdf")
            close = os.path.join(tmp, "fecho.pdf")
            dest = os.path.join(tmp, "relatorio.pdf")
            _one_page(cover, "CAPA-METRICS")
            _one_page(close, "FECHO-METRICS")
            art = write_metrics_pdf(
                dest,
                tasks,
                "SICOR",
                art=fallback_direction(),
                cover_pdf=cover,
                close_pdf=close,
            )
            self.assertTrue(art.used_fallback)
            reader = PdfReader(dest)
            texts = [page.extract_text() or "" for page in reader.pages]
            self.assertGreaterEqual(len(texts), 5)
            self.assertIn("CAPA-METRICS", texts[0])
            self.assertIn("FECHO-METRICS", texts[-1])
            body = "\n".join(texts[1:-1])
            self.assertIn("SICOR", body)
            self.assertIn("Registrado", body)
            self.assertIn("Corrigir login", body)
            self.assertIn("Nenhuma hora foi consumida", body)
            self.assertTrue(render_donut([(4, "#6AAA6A"), (2, "#E6C36A")]).startswith(b"\x89PNG"))


def _one_page(path: str, label: str) -> None:
    pdf = canvas.Canvas(path)
    pdf.drawString(72, 720, label)
    pdf.save()


if __name__ == "__main__":
    unittest.main()

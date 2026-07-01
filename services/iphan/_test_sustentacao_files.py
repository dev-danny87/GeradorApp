import unittest

from services.iphan._sustentacao_files import (
    acceptable_years,
    find_best_delivery_report,
    matches_delivery_report,
    month_from_filename,
    parse_sustentacao_files_html,
    years_from_filename,
    SustentacaoFileEntry,
)

SAMPLE_HTML = """
<table class="list files">
  <tbody>
    <tr class="file">
      <td class="filename"><a href="/redmine/attachments/21870">[SUSTENTAÇÃO] Relatório de Entregas - Abril.pdf</a></td>
      <td class="created_on">05 Maio 2026 11:50</td>
      <td class="buttons">
        <a class="icon-only icon-download" href="/redmine/attachments/download/21870/april.pdf"></a>
      </td>
    </tr>
    <tr class="file">
      <td class="filename"><a href="/redmine/attachments/22144">[SUSTENTAÇÃO] Relatório de Entregas Detalhado - Maio.pdf</a></td>
      <td class="created_on">03 Junho 2026 10:48</td>
      <td class="buttons">
        <a class="icon-only icon-download" href="/redmine/attachments/download/22144/maio.pdf"></a>
      </td>
    </tr>
    <tr class="file">
      <td class="filename"><a href="/redmine/attachments/19971">[Sustentação] Relatório de Entrega - Período 01-02-2025 a 28-02-2025.pdf</a></td>
      <td class="created_on">06 Junho 2025 11:15</td>
      <td class="buttons">
        <a class="icon-only icon-download" href="/redmine/attachments/download/19971/fev.pdf"></a>
      </td>
    </tr>
    <tr class="file">
      <td class="filename"><a href="/redmine/attachments/20353">Relatorio_Sustentacao_Julho_25.pdf</a></td>
      <td class="created_on">01 Agosto 2025 10:36</td>
      <td class="buttons">
        <a class="icon-only icon-download" href="/redmine/attachments/download/20353/julho.pdf"></a>
      </td>
    </tr>
    <tr class="file">
      <td class="filename"><a href="/redmine/attachments/21242">[SUSTENTAÇÃO] Relatório de Entregas - Dezembro.pdf</a></td>
      <td class="created_on">05 Janeiro 2026 14:38</td>
      <td class="buttons">
        <a class="icon-only icon-download" href="/redmine/attachments/download/21242/dez.pdf"></a>
      </td>
    </tr>
  </tbody>
</table>
"""


class TestSustentacaoFiles(unittest.TestCase):
    def test_parse_html(self):
        entries = parse_sustentacao_files_html(SAMPLE_HTML)
        self.assertEqual(len(entries), 5)
        self.assertTrue(entries[0].download_url.endswith("april.pdf"))

    def test_month_from_period_and_name(self):
        self.assertEqual(
            month_from_filename(
                "[Sustentação] Relatório de Entrega - Período 01-02-2025 a 28-02-2025.pdf"
            ),
            2,
        )
        self.assertEqual(
            month_from_filename("[SUSTENTAÇÃO] Relatório de Entregas - Abril.pdf"),
            4,
        )
        self.assertEqual(month_from_filename("Relatorio_Sustentacao_Julho_25.pdf"), 7)

    def test_years_from_filename(self):
        self.assertEqual(
            years_from_filename(
                "[Sustentação] Relatório de Entrega - Período 01-02-2025 a 28-02-2025.pdf"
            ),
            {2025},
        )
        self.assertEqual(years_from_filename("Relatorio_Sustentacao_Julho_25.pdf"), {2025})
        self.assertEqual(
            years_from_filename("[SUSTENTAÇÃO] Relatório de Entregas - Dezembro.pdf"),
            set(),
        )

    def test_acceptable_years_december(self):
        self.assertEqual(acceptable_years(2025, 11), {2025})
        self.assertEqual(acceptable_years(2025, 12), {2025, 2026})

    def test_matches_delivery_report(self):
        self.assertTrue(
            matches_delivery_report(
                "[SUSTENTAÇÃO] Relatório de Entregas - Abril.pdf",
                2026,
                4,
            )
        )
        self.assertTrue(
            matches_delivery_report(
                "[Sustentação] Relatório de Entrega - Período 01-02-2025 a 28-02-2025.pdf",
                2025,
                2,
            )
        )
        self.assertTrue(
            matches_delivery_report("Relatorio_Sustentacao_Julho_25.pdf", 2025, 7)
        )
        self.assertTrue(
            matches_delivery_report(
                "[SUSTENTAÇÃO] Relatório de Entregas - Dezembro.pdf",
                2025,
                12,
            )
        )
        self.assertFalse(
            matches_delivery_report(
                "[Sustentação] Relatório de Entrega - Período 01-12-2024 a 31-12-2024.pdf",
                2025,
                12,
            )
        )

    def test_find_best_prefers_standard_over_detalhado(self):
        entries = parse_sustentacao_files_html(SAMPLE_HTML)
        match = find_best_delivery_report(entries, 2026, 4)
        self.assertIsNotNone(match)
        self.assertIn("Abril", match.filename)
        self.assertNotIn("Detalhado", match.filename)

    def test_find_best_falls_back_to_detalhado(self):
        entries = parse_sustentacao_files_html(SAMPLE_HTML)
        match = find_best_delivery_report(entries, 2026, 5)
        self.assertIsNotNone(match)
        self.assertIn("Detalhado", match.filename)
        self.assertIn("Maio", match.filename)

    def test_find_best_legacy_formats(self):
        entries = [
            SustentacaoFileEntry(
                filename="[Sustentação] Relatório de Entrega - Período 01-02-2025 a 28-02-2025.pdf",
                download_url="http://example/fev.pdf",
            ),
            SustentacaoFileEntry(
                filename="Relatorio_Sustentacao_Julho_25.pdf",
                download_url="http://example/julho.pdf",
            ),
        ]
        fev = find_best_delivery_report(entries, 2025, 2)
        jul = find_best_delivery_report(entries, 2025, 7)
        self.assertIsNotNone(fev)
        self.assertIsNotNone(jul)
        self.assertIn("02-2025", fev.filename)
        self.assertIn("Julho", jul.filename)


if __name__ == "__main__":
    unittest.main()

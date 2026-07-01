import unittest

from services.iphan._saip_project_files import (
    find_best_pf_planilha,
    is_pf_planilha,
    matches_pf_planilha,
    month_from_filename,
    parse_saip_files_html,
    SaipFileEntry,
    sprint_numbers_from_filename,
)

SAMPLE_HTML = """
<table class="list files">
  <tbody>
    <tr class="file">
      <td class="filename"><a href="/a/1">Planilha Contagem PF - SAIP 20 - Sprint 00 e 01 - Novembro2025.xlsx</a></td>
      <td class="created_on">01 Dezembro 2025</td>
      <td class="buttons">
        <a class="icon-only icon-download" href="/download/1/nov.xlsx"></a>
      </td>
    </tr>
    <tr class="file">
      <td class="filename"><a href="/a/2">Planilha Contagem PF - SAIP 20 - Sprint 06 e 07 - Fevereiro 2026.xlsx</a></td>
      <td class="created_on">01 Março 2026</td>
      <td class="buttons">
        <a class="icon-only icon-download" href="/download/2/fev.xlsx"></a>
      </td>
    </tr>
    <tr class="file">
      <td class="filename"><a href="/a/3">Fábrica de métricas - Janeiro 2026.xlsx</a></td>
      <td class="created_on">01 Fevereiro 2026</td>
      <td class="buttons">
        <a class="icon-only icon-download" href="/download/3/fabrica.xlsx"></a>
      </td>
    </tr>
  </tbody>
</table>
"""


class TestSaipProjectFiles(unittest.TestCase):
    def test_parse_html(self):
        entries = parse_saip_files_html(SAMPLE_HTML)
        self.assertEqual(len(entries), 3)

    def test_month_glued_and_spaced(self):
        self.assertEqual(
            month_from_filename("Planilha Contagem PF - SAIP 20 - Sprint 00 e 01 - Novembro2025.xlsx"),
            11,
        )
        self.assertEqual(
            month_from_filename("Planilha Contagem PF - SAIP 20 - Sprint 06 e 07 - Fevereiro 2026.xlsx"),
            2,
        )

    def test_sprint_numbers(self):
        filename = "Planilha Contagem PF - SAIP 20 - Sprint 06 e 07 - Fevereiro 2026.xlsx"
        self.assertEqual(sprint_numbers_from_filename(filename), {6, 7})

    def test_matches_pf_planilha(self):
        fev = "Planilha Contagem PF - SAIP 20 - Sprint 06 e 07 - Fevereiro 2026.xlsx"
        self.assertTrue(matches_pf_planilha(fev, 2026, 2))
        self.assertFalse(matches_pf_planilha(fev, 2026, 3))
        self.assertFalse(is_pf_planilha("Fábrica de métricas - Janeiro 2026.xlsx"))

    def test_find_best_pf_planilha(self):
        entries = parse_saip_files_html(SAMPLE_HTML)
        match = find_best_pf_planilha(entries, 2026, 2, {6, 7})
        self.assertIsNotNone(match)
        self.assertIn("Fevereiro 2026", match.filename)

        nov = find_best_pf_planilha(entries, 2025, 11)
        self.assertIsNotNone(nov)
        self.assertIn("Novembro2025", nov.filename)


if __name__ == "__main__":
    unittest.main()

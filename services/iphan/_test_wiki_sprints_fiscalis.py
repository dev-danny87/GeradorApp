import unittest

from services.iphan._wiki_sprints_fiscalis import (
    parse_fiscalis_sprints_index_html,
)
from services.iphan._wiki_sprints_saip import parse_saip_sprint_page_html

SPRINTS_INDEX_HTML = """
<div class="wiki wiki-page">
  <h2>
    <a class="wiki-page" href="/redmine/projects/fiscalis/wiki/FISCALIS20-Sprint017">FISCALIS2.0-Sprint017</a>
    (16/07/2026 a 31/07/2026)
  </h2>
  <h2>
    <a class="wiki-page" href="/redmine/projects/fiscalis/wiki/FISCALIS20-Sprint016">FISCALIS2.0-Sprint016</a>
    (01/07/2026 a 15/07/2026) - <span style="color:red;"><strong>Em Andamento</strong></span>
  </h2>
  <h2>
    <a class="wiki-page" href="/redmine/projects/fiscalis/wiki/FISCALIS20-Sprint015">FISCALIS2.0-Sprint015</a>
    (16/06/2026 a 30/06/2026)
  </h2>
  <h2>
    <a class="wiki-page" href="/redmine/projects/fiscalis/wiki/FISCALIS20-Sprints2025">FISCALIS2.0-Sprints2025</a>
  </h2>
</div>
"""

SPRINT015_PAGE_HTML = """
<div class="wiki wiki-page">
  <table>
    <tr>
      <th>Nº HU </th>
      <th>PRIORIDADE</th>
      <th>TÍTULO </th>
      <th>P.O RESPONSAVEL </th>
      <th>ANALISTA REQUISITOS    </th>
      <th>DESENVOLVEDOR   </th>
      <th>DATA DA INCLUSÃO    </th>
      <th>STATUS </th>
      <th>QTD PF</th>
    </tr>
    <tr>
      <td>436</td>
      <td style="text-align:center;">01</td>
      <td><a href="https://redmine.iphan.gov.br/redmine/projects/fiscalis/wiki/(FISCALIZA%C3%87%C3%83O)_Fiscaliza%C3%A7%C3%B5es_Eventuais_%E2%80%93_Executar_Fiscaliza%C3%A7%C3%A3o_%E2%80%93_Dados_da_Fiscaliza%C3%A7%C3%A3o?parent=BACKLOG_DO_PRODUTO" class="external">[FISCALIZAÇÃO] Fiscalizações Eventuais – Executar Fiscalização – Dados da Fiscalização</a></td>
      <td>Renato Rasera </td>
      <td>Fabrício Martins </td>
      <td>Janerson (Back) / Gabriel (Front)</td>
      <td style="text-align:center;">16/06/2026</td>
      <td><span style="color:purple;"> Homologada</span></td>
      <td>4,60</td>
    </tr>
    <tr>
      <td>437</td>
      <td style="text-align:center;">02</td>
      <td><a href="https://redmine.iphan.gov.br/redmine/projects/fiscalis/wiki/(FISCALIZA%C3%87%C3%83O)_Fiscaliza%C3%A7%C3%B5es_Eventuais_%E2%80%93_Executar_Fiscaliza%C3%A7%C3%A3o_%E2%80%93_Dados_do_Bem" class="external">[FISCALIZAÇÃO] Fiscalizações Eventuais – Executar Fiscalização – Dados do Bem</a></td>
      <td>Renato Rasera </td>
      <td>Fabrício Martins </td>
      <td>Janerson (Back) / Gabriel (Front)</td>
      <td style="text-align:center;">16/06/2026</td>
      <td><span style="color:purple;"> Homologada</span></td>
      <td>4,60</td>
    </tr>
    <tr>
      <td>438</td>
      <td style="text-align:center;">03</td>
      <td><a href="https://redmine.iphan.gov.br/redmine/projects/fiscalis/wiki/(FISCALIZA%C3%87%C3%83O)_Item_C" class="external">Item C</a></td>
      <td>Renato Rasera </td>
      <td>Fabrício Martins </td>
      <td>Janerson (Back) / Gabriel (Front)</td>
      <td style="text-align:center;">16/06/2026</td>
      <td><span style="color:gray;"> Cancelada</span></td>
      <td>4,60</td>
    </tr>
    <tr>
      <td>439</td>
      <td style="text-align:center;">04</td>
      <td><a href="https://redmine.iphan.gov.br/redmine/projects/fiscalis/wiki/(FISCALIZA%C3%87%C3%83O)_Item_D" class="external">Item D</a></td>
      <td>Renato Rasera </td>
      <td>Fabrício Martins </td>
      <td>Janerson (Back) / Gabriel (Front)</td>
      <td style="text-align:center;">16/06/2026</td>
      <td><span style="color:purple;"> Homologada</span></td>
      <td>4,60</td>
    </tr>
  </table>
</div>
"""


class TestWikiSprintsFiscalis(unittest.TestCase):
    def test_parse_sprints_index(self):
        sprints = parse_fiscalis_sprints_index_html(SPRINTS_INDEX_HTML)
        self.assertEqual(len(sprints), 3)
        self.assertEqual(sprints[0].sprint_number, 17)
        self.assertEqual(sprints[0].sprint_slug, "FISCALIS20-Sprint017")
        self.assertEqual(sprints[0].end_date.day, 31)
        self.assertTrue(sprints[0].sprint_wiki_url.endswith("FISCALIS20-Sprint017"))

        sprint15 = next(s for s in sprints if s.sprint_number == 15)
        self.assertEqual(sprint15.sprint_slug, "FISCALIS20-Sprint015")
        self.assertEqual(sprint15.end_date.month, 6)
        self.assertEqual(sprint15.end_date.day, 30)

        sprint16 = next(s for s in sprints if s.sprint_number == 16)
        self.assertEqual(sprint16.start_date.day, 1)
        self.assertEqual(sprint16.end_date.day, 15)

    def test_parse_sprint015_page(self):
        rows = parse_saip_sprint_page_html(
            SPRINT015_PAGE_HTML,
            15,
            sprint_slug="FISCALIS20-Sprint015",
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].hu_number, "436")
        self.assertEqual(rows[0].priority, "01")
        self.assertEqual(rows[0].po, "Renato Rasera")
        self.assertEqual(rows[0].analyst, "Fabrício Martins")
        self.assertEqual(rows[0].developers, ["Janerson (Back)", "Gabriel (Front)"])
        self.assertEqual(rows[0].inclusion_date, "16/06/2026")
        self.assertEqual(rows[0].status_text, "Homologada")
        self.assertAlmostEqual(rows[0].qtd_pf, 4.60)
        self.assertEqual(rows[0].sprint_slug, "FISCALIS20-Sprint015")
        self.assertIn("FISCALIZA", rows[0].wiki_slug)

        hu_numbers = {row.hu_number for row in rows}
        self.assertNotIn("438", hu_numbers)


if __name__ == "__main__":
    unittest.main()

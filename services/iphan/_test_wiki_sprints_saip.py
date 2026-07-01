import unittest

from services.iphan._wiki_download_saip import row_pdf_basename
from services.iphan._wiki_sprints_saip import (
    SaipRow,
    parse_saip_sprint_page_html,
    parse_saip_sprints_index_html,
    parse_sprint_page_attachments,
)

SPRINTS_INDEX_HTML = """
<div class="wiki wiki-page">
  <h2><a class="wiki-page" href="/projects/licenciamento-ambiental/wiki/SAIP20-Sprint14">SAIP20-Sprint14 (01/06/2026 a 15/06/2026)</a></h2>
  <h2>SAIP20-Sprints2025</h2>
  <h2><a class="wiki-page" href="/projects/licenciamento-ambiental/wiki/SAIP20-Sprint13">SAIP20-Sprint13 (16/05/2026 a 31/05/2026)</a></h2>
</div>
"""

SHARED_WIKI_URL = (
    "https://redmine.iphan.gov.br/redmine/projects/licenciamento-ambiental/wiki/"
    "(SOLICITA%C3%87%C3%95ES)_-Minhas_Solicita%C3%A7%C3%B5es_(FCA)_"
    "%E2%80%93_Visualizar_Solicita%C3%A7%C3%A3o_-_Dados_do_EmpreendimentoART"
    "?parent=Backlog_do_Produto"
)

SPRINT13_PAGE_HTML = """
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
      <td>113</td>
      <td>1</td>
      <td><a href="https://redmine.iphan.gov.br/redmine/projects/licenciamento-ambiental/wiki/(SOLICITA%C3%87%C3%95ES)_-Nova_Solicita%C3%A7%C3%A3o_(FCA)_%E2%80%93_REFATORAMENTO_PDF_da_FCA_%E2%80%93_Exibir_UF_e_Munic%C3%ADpios_nas_Se%C3%A7%C3%B5es_da_ADA_AID_e_Munic%C3%ADpios?parent=Backlog_do_Produto" class="external">[SOLICITAÇÕES]Nova Solicitação (FCA) – REFATORAMENTO PDF da FCA – Exibir UF e Municípios nas Seções da ADA, AID e Municípios</a></td>
      <td>Felippe Rodrigo </td>
      <td>Fabrício Martins</td>
      <td> Igor (Back) / Humberto (Front)</td>
      <td>18/05/2026 </td>
      <td><span style="color:purple;"> Homologada</span></td>
      <td>2,30</td>
    </tr>
    <tr>
      <td>114</td>
      <td>2</td>
      <td><a href="/projects/licenciamento-ambiental/wiki/Item-B" class="external">Item B</a></td>
      <td>Felippe Rodrigo </td>
      <td>Fabrício Martins</td>
      <td>Igor (Back) / Humberto (Front)</td>
      <td>18/05/2026 </td>
      <td><span style="color:purple;"> Homologada</span></td>
      <td>2,30</td>
    </tr>
    <tr>
      <td>116</td>
      <td>3</td>
      <td><a href="{shared_url}" class="external">[SOLICITAÇÕES] Minhas Solicitações (FCA) – Visualizar Solicitação - Dados do Empreendimento/ART</a></td>
      <td>Felippe Rodrigo </td>
      <td>Fabrício Martins</td>
      <td> Igor (Back) / Humberto (Front)</td>
      <td>18/05/2026 </td>
      <td><span style="color:purple;"> Homologada</span></td>
      <td>4,60</td>
    </tr>
    <tr>
      <td>117</td>
      <td>4</td>
      <td><a href="{shared_url}" title="ADA" class="external">[SOLICITAÇÕES] Minhas Solicitações (FCA) – Visualizar Solicitação -  Área Diretamente Afetada</a></td>
      <td>Felippe Rodrigo </td>
      <td>Fabrício Martins</td>
      <td> Igor (Back) / Humberto (Front)</td>
      <td>18/05/2026 </td>
      <td><span style="color:purple;"> Homologada</span></td>
      <td>4,60</td>
    </tr>
    <tr>
      <td>Sem link wiki</td>
      <td>5</td>
      <td>Sem título</td>
      <td>PO</td>
      <td>Analista</td>
      <td>Dev</td>
      <td>18/05/2026</td>
      <td>Homologada</td>
      <td>1</td>
    </tr>
  </table>
</div>
""".format(shared_url=SHARED_WIKI_URL)

ATTACHMENTS_HTML = """
<fieldset class="collapsible hide-when-print">
  <legend>Arquivos (2)</legend>
  <div class="attachments">
    <a class="icon-only icon-download" href="/redmine/attachments/wiki_pages/3179/download">Download all files</a>
    <table>
      <tr>
        <td>
          <a class="icon icon-attachment" href="/redmine/attachments/22068">clipboard-202605280741-2zpjs.png</a>
          <a class="icon-only icon-download" title="Baixar" href="/redmine/attachments/download/22068/clipboard-202605280741-2zpjs.png">clipboard-202605280741-2zpjs.png</a>
        </td>
      </tr>
      <tr>
        <td>
          <a class="icon icon-attachment" href="/redmine/attachments/22069">clipboard-202605280741-ezhbv.png</a>
          <a class="icon-only icon-download" title="Baixar" href="/redmine/attachments/download/22069/clipboard-202605280741-ezhbv.png">clipboard-202605280741-ezhbv.png</a>
        </td>
      </tr>
    </table>
  </div>
</fieldset>
"""

ATTACHMENTS_SINGLE_HTML = """
<fieldset class="collapsible collapsed hide-when-print">
  <legend>Arquivos (1)</legend>
  <div class="attachments">
    <div class="contextual">
      <a title="Editar arquivos anexados" class="icon-only icon-edit" href="/redmine/attachments/wiki_pages/3131/edit">Editar arquivos anexados</a>
    </div>
    <table>
      <tr>
        <td>
          <a class="icon icon-attachment" href="/redmine/attachments/22066">clipboard-202605280730-qxk3u.png</a>
          <a class="icon-only icon-download" title="Baixar" href="/redmine/attachments/download/22066/clipboard-202605280730-qxk3u.png">clipboard-202605280730-qxk3u.png</a>
        </td>
      </tr>
    </table>
  </div>
</fieldset>
"""


class TestWikiSprintsSaip(unittest.TestCase):
    def test_parse_sprints_index(self):
        sprints = parse_saip_sprints_index_html(SPRINTS_INDEX_HTML)
        self.assertEqual(len(sprints), 2)
        self.assertEqual(sprints[0].sprint_number, 14)
        self.assertEqual(sprints[0].sprint_slug, "SAIP20-Sprint14")
        self.assertEqual(sprints[0].end_date.day, 15)
        self.assertTrue(sprints[0].sprint_wiki_url.endswith("SAIP20-Sprint14"))

    def test_parse_sprint13_real_html(self):
        rows = parse_saip_sprint_page_html(
            SPRINT13_PAGE_HTML,
            13,
            sprint_slug="SAIP20-Sprint13",
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0].hu_number, "113")
        self.assertEqual(rows[0].priority, "1")
        self.assertEqual(rows[0].po, "Felippe Rodrigo")
        self.assertEqual(rows[0].analyst, "Fabrício Martins")
        self.assertEqual(rows[0].developers, ["Igor (Back)", "Humberto (Front)"])
        self.assertEqual(rows[0].inclusion_date, "18/05/2026")
        self.assertEqual(rows[0].status_text, "Homologada")
        self.assertAlmostEqual(rows[0].qtd_pf, 2.30)
        self.assertEqual(rows[0].sprint_slug, "SAIP20-Sprint13")
        self.assertIn("SOLICITA", rows[0].wiki_slug)
        self.assertEqual(rows[1].hu_number, "114")

    def test_duplicate_wiki_urls_for_hu116_and_hu117(self):
        rows = parse_saip_sprint_page_html(
            SPRINT13_PAGE_HTML,
            13,
            sprint_slug="SAIP20-Sprint13",
        )
        hu116 = next(row for row in rows if row.hu_number == "116")
        hu117 = next(row for row in rows if row.hu_number == "117")
        self.assertEqual(hu116.wiki_url, hu117.wiki_url)
        self.assertNotEqual(hu116.title_text, hu117.title_text)

    def test_parse_sprint_page_attachments(self):
        attachments, bulk_url = parse_sprint_page_attachments(ATTACHMENTS_HTML)
        self.assertEqual(len(attachments), 2)
        self.assertTrue(attachments[0].filename.endswith(".png"))
        self.assertIn("/attachments/download/22068/", attachments[0].download_url)
        self.assertIn("/attachments/wiki_pages/3179/download", bulk_url)

    def test_parse_sprint_page_single_attachment(self):
        attachments, bulk_url = parse_sprint_page_attachments(ATTACHMENTS_SINGLE_HTML)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].filename, "clipboard-202605280730-qxk3u.png")
        self.assertIn("/attachments/download/22066/", attachments[0].download_url)
        self.assertEqual(bulk_url, "")

    def test_row_pdf_basename_uses_hu_prefix(self):
        row = SaipRow(
            sprint_number=13,
            sprint_slug="SAIP20-Sprint13",
            hu_number="117",
            priority="4",
            po="PO",
            analyst="Analista",
            developers=["Dev"],
            inclusion_date="18/05/2026",
            qtd_pf=4.6,
            title_text="Título",
            wiki_slug="wiki-slug",
            wiki_url="https://example/wiki/wiki-slug",
            status_text="Homologada",
        )
        basename = row_pdf_basename(row, "wiki-slug")
        self.assertTrue(basename.startswith("HU117_"))


if __name__ == "__main__":
    unittest.main()

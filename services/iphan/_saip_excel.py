import os

import pandas as pd

from services.iphan._wiki_sprints_saip import SaipRow

SAIP_PF_EXCEL_NAME = "Relatório_PF_SAIP.xlsx"


def write_saip_pf_excel(rows: list[SaipRow], path: str) -> bool:
    data = [
        {
            "Nº HU": row.hu_number,
            "Sprint": row.sprint_slug or row.sprint_number,
            "PRIORIDADE": row.priority,
            "TÍTULO": row.title_text,
            "P.O RESPONSAVEL": row.po,
            "ANALISTA REQUISITOS": row.analyst,
            "DESENVOLVEDOR": " / ".join(row.developers),
            "DATA DA INCLUSÃO": row.inclusion_date,
            "STATUS": row.status_text,
            "QTD PF": row.qtd_pf,
        }
        for row in rows
    ]
    total_pf = sum(row.qtd_pf for row in rows)
    data.append(
        {
            "Nº HU": "",
            "Sprint": "",
            "PRIORIDADE": "",
            "TÍTULO": "TOTAL",
            "P.O RESPONSAVEL": "",
            "ANALISTA REQUISITOS": "",
            "DESENVOLVEDOR": "",
            "DATA DA INCLUSÃO": "",
            "STATUS": "",
            "QTD PF": total_pf,
        }
    )

    df = pd.DataFrame(data)
    try:
        df.to_excel(path, index=False, engine="openpyxl")
        return True
    except ImportError:
        csv_path = os.path.splitext(path)[0] + ".csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"WARN: openpyxl indisponível; CSV salvo: {csv_path}")
        return False

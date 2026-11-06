"""Fluxo de caixa em cascata: por mês, entradas → blocos de saída → sobra → saldo.

Trabalha em cima do extrato que o painel já monta (saldos.extrato + coluna 'mes' + 'interna'),
então os números batem com o Início e com Contas correntes. Sem Streamlit: dá para testar.
"""
from __future__ import annotations

import io

import pandas as pd

from core.fmt import mes_label

# ordem dos blocos de saída na coluna; o resto cai em "Outras saídas"
BLOCOS = ["Apartamento", "Fixas", "Faturas de cartão", "Outras saídas"]
# grupos que são conta fixa (o resto — Alimentacao, Compras, Viagem e Lazer… — é variável)
_FIXAS = {"Moradia", "Educacao", "Servicos Financeiros", "Saude e Bem-estar", "Assinaturas",
          "Investimentos e Previdencia"}


def _bloco(r) -> str:
    g = str(r.get("grupo") or "")
    if r["fonte"] == "fatura":
        return "Faturas de cartão"
    if g.lower().startswith("imov"):
        return "Apartamento"
    if g in _FIXAS:
        return "Fixas"
    return "Outras saídas"


def montar(ext: pd.DataFrame, meses: list[int], saldo_inicial: float) -> dict:
    """Devolve {'meses': [...], 'linhas': DataFrame(mes, bloco, categoria, valor), 'resumo': DataFrame}.

    resumo: uma linha por mês com entradas, cada bloco, outras, sobra, saldo_fim.
    linhas: detalhe por categoria dentro de cada bloco (valores positivos para saída)."""
    if ext.empty:
        vazio = pd.DataFrame(columns=["mes", "rotulo", "entradas"] + BLOCOS + ["sobra", "saldo_fim"])
        return {"meses": meses, "linhas": pd.DataFrame(columns=["mes", "bloco", "categoria", "valor"]), "resumo": vazio}
    e = ext[(ext["fonte"] != "ajuste") & (~ext["interna"])].copy()
    e["bloco"] = e.apply(lambda r: "Entradas" if r["valor"] > 0 else _bloco(r), axis=1)
    e["categoria"] = e.apply(lambda r: r["descricao"].replace("Fatura ", "") if r["fonte"] == "fatura"
                             else (r.get("categoria") or "—"), axis=1)
    e["abs"] = e["valor"].abs()
    det = (e.groupby(["mes", "bloco", "categoria"], as_index=False)["abs"].sum()
           .rename(columns={"abs": "valor"}).sort_values(["mes", "bloco", "valor"], ascending=[True, True, False]))

    # saldo: soma de TUDO que passa pelas contas (ajustes e transferências internas incluídos), igual ao
    # painel e ao Início. Sobra: entradas − saídas do que é de verdade (sem ajuste, sem interna).
    tudo = ext.groupby("mes")["valor"].sum()
    linhas, saldo = [], saldo_inicial
    for m in meses:
        d = det[det["mes"] == m]
        tot = {b: float(d.loc[d["bloco"] == b, "valor"].sum()) for b in ["Entradas"] + BLOCOS}
        sobra = tot["Entradas"] - sum(tot[b] for b in BLOCOS)
        saldo += float(tudo.get(m, 0.0))
        linhas.append({"mes": m, "rotulo": mes_label(m), "entradas": tot["Entradas"], **{b: tot[b] for b in BLOCOS},
                       "sobra": sobra, "saldo_fim": saldo})
    return {"meses": meses, "linhas": det, "resumo": pd.DataFrame(linhas)}


def simular(resumo: pd.DataFrame, extra_mes: float = 0.0, retirada: float = 0.0, mes_retirada: int | None = None,
            a_partir: int | None = None) -> pd.DataFrame:
    """Linha de saldo com um gasto extra por mês (a partir de um mês) e/ou uma retirada única.
    saldo_sim = saldo real − tudo que foi tirado até aquele mês."""
    r = resumo.copy()
    if r.empty:
        return r
    tirado, out = 0.0, []
    for row in r.itertuples():
        if extra_mes and (a_partir is None or row.mes >= a_partir):
            tirado += extra_mes
        if retirada and mes_retirada == row.mes:
            tirado += retirada
        out.append(row.saldo_fim - tirado)
    r["saldo_sim"] = out
    return r


def excel(resumo: pd.DataFrame, det: pd.DataFrame, ext: pd.DataFrame) -> bytes:
    """Aba Resumo (meses nas colunas), aba Por categoria, aba Lançamentos."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        if not resumo.empty:
            r = resumo.set_index("rotulo")[["entradas"] + BLOCOS + ["sobra", "saldo_fim"]].T
            r.index = ["Entradas"] + BLOCOS + ["Sobra do mês", "Saldo no fim do mês"]
            r.to_excel(w, sheet_name="Resumo")
        if not det.empty:
            piv = det.pivot_table(index=["bloco", "categoria"], columns="mes", values="valor", aggfunc="sum",
                                  fill_value=0.0)
            piv.columns = [mes_label(int(c)) for c in piv.columns]
            piv.to_excel(w, sheet_name="Por categoria")
        if not ext.empty:
            cols = [c for c in ["data", "descricao", "grupo", "categoria", "valor", "status", "fonte"] if c in ext]
            e = ext[(ext["fonte"] != "ajuste")][cols].sort_values("data")
            e.to_excel(w, sheet_name="Lançamentos", index=False)
        for ws in w.sheets.values():
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(12, min(44, max(len(str(c.value or "")) for c in col) + 2))
    return buf.getvalue()

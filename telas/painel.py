from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core import repo
from core.fmt import brl, hoje, mes_label, mes_ref, somar_meses
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, seletor_escopo, usuario

u = usuario()
topo_esq, topo_dir = st.columns([3, 1], vertical_alignment="bottom")
topo_esq.title("Painel")
with topo_dir:
    escopo = seletor_escopo()

atual = mes_ref(hoje())
fim = somar_meses(atual, 11)
tot = repo.totais_por_mes(u, escopo, atual, fim)
desp = tot[tot["tipo"] == "despesa"].copy()
if not desp.empty:
    desp["valor"] = desp["valor"].astype(float)

def soma(df, **f):
    if df.empty:
        return 0.0
    for k, v in f.items():
        df = df[df[k] == v]
    return float(df["valor"].sum()) if not df.empty else 0.0

mes_atual = desp[desp["mes_ref"] == atual] if not desp.empty else desp
prox = somar_meses(atual, 1)

cel = e_celular()
cartoes_kpi([
    (f"A pagar em {mes_label(atual)}", brl(soma(mes_atual, status="previsto"))),
    (f"Já pago em {mes_label(atual)}", brl(soma(mes_atual, status="pago"))),
    (f"Comprometido em {mes_label(prox)}", brl(soma(desp, mes_ref=prox))),
    ("Próximos 12 meses", brl(float(desp["valor"].sum()) if not desp.empty else 0)),
])

if desp.empty:
    st.info("Nenhum lançamento ainda. Comece em **Novo lançamento** ou rode a migração da planilha.")
    st.stop()

st.subheader("Compromissos por mês")
g = desp.groupby(["mes_ref", "categoria"], as_index=False)["valor"].sum()
g["mes"] = g["mes_ref"].map(mes_label)
ordem = [mes_label(m) for m in sorted(g["mes_ref"].unique())]
graf = (alt.Chart(g).mark_bar()
        .encode(x=alt.X("mes:N", sort=ordem, title=None),
                y=alt.Y("sum(valor):Q", title="R$", axis=alt.Axis(format=",.0f")),
                color=alt.Color("categoria:N", title=None if cel else "Categoria",
                                legend=alt.Legend(orient="bottom", columns=2, labelLimit=150) if cel else alt.Legend()),
                tooltip=[alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("categoria:N", title="Categoria"),
                         alt.Tooltip("valor:Q", title="R$", format=",.2f")])
        .properties(height=380 if cel else 340))
st.altair_chart(graf, use_container_width=True)

esq, dir_ = (st.container(), st.container()) if cel else st.columns(2)
with esq:
    st.subheader(f"{mes_label(atual)} por categoria")
    cat = (mes_atual.groupby("categoria", as_index=False)["valor"].sum()
           .sort_values("valor", ascending=False))
    cat["%"] = cat["valor"] / cat["valor"].sum()
    st.dataframe(em_reais(cat.drop(columns=["%"]) if cel else cat), hide_index=True, use_container_width=True,
                 column_config={"categoria": "Categoria",
                                "valor": col_rs(),
                                "%": st.column_config.ProgressColumn("Peso", format="percent",
                                                                     min_value=0, max_value=1)})
with dir_:
    st.subheader("Vencendo nos próximos 15 dias")
    lanc = repo.lancamentos(u, escopo, atual, prox)
    if not lanc.empty:
        lanc["data_vencimento"] = pd.to_datetime(lanc["data_vencimento"]).dt.date
        janela = lanc[(lanc["status"] == "previsto") & (lanc["tipo"] == "despesa")
                      & (lanc["data_vencimento"] >= hoje())
                      & (lanc["data_vencimento"] <= hoje() + timedelta(days=15))]
        cols_v = ["data_vencimento", "descricao", "valor"] if cel else ["data_vencimento", "descricao", "conta", "valor"]
        st.dataframe(em_reais(janela[cols_v].fillna({"conta": "—"})),
                     hide_index=True,
                     use_container_width=True,
                     column_config={"data_vencimento": st.column_config.DateColumn("Vence", format="DD/MM"),
                                    "descricao": "Descrição", "conta": "Conta",
                                    "valor": col_rs()})
        st.caption(f"Total: **{brl(janela['valor'].astype(float).sum())}**")

if escopo == "nos":
    outros = desp[~desp["meu"]]
    if not outros.empty:
        st.caption(f"Inclui {brl(outros['valor'].sum())} compartilhados pelo outro membro do casal "
                   "(itens marcados como “só o total” entram nas somas, mas não aparecem nas listas).")

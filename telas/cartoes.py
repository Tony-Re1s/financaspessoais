import altair as alt
import pandas as pd
import streamlit as st

from core import cartoes, repo
from core.fmt import brl, hoje, mes_label
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, usuario

u = usuario()
cel = e_celular()
st.title("Cartões de crédito")

if msg := st.session_state.pop("_ok_cart", None):
    st.success(msg, icon=":material/check_circle:")

fat = cartoes.faturas(u)
if fat.empty:
    st.info("Nenhum lançamento em cartão ainda. Importe uma fatura ou lance uma compra no cartão.")
    st.stop()
res = cartoes.resumo(u, fat)

prox_total = res["fatura_atual"].sum()
cartoes_kpi([("Faturas a vencer (atuais)", brl(prox_total)),
             ("Próximas faturas", brl(res["fatura_prox"].sum())),
             ("Comprometido total", brl(res["comprometido"].sum())),
             ("Limite disponível", brl(res["disponivel"].dropna().sum()) if res["limite"].notna().any() else "—")])
if res["n_atrasadas"].sum():
    st.warning(f"{int(res['n_atrasadas'].sum())} faturas vencidas ainda não marcadas como pagas "
               f"({brl(res['atrasadas'].sum())}). Marque abaixo se já pagou.", icon=":material/schedule:")

# --- visão geral ------------------------------------------------------------------------------
v = res.copy()
v["uso"] = v.apply(lambda r: r.comprometido / r.limite if r.limite else None, axis=1)
cols = ["cartao", "fatura_atual", "venc_atual"] if cel else \
    ["cartao", "venc_atual", "fatura_atual", "venc_prox", "fatura_prox", "comprometido", "limite", "uso"]
st.dataframe(em_reais(v, "fatura_atual", "fatura_prox", "comprometido", "limite")[cols], hide_index=True,
             use_container_width=True,
             column_config={"cartao": "Cartão",
                            "venc_atual": st.column_config.DateColumn("Vence", format="DD/MM"),
                            "fatura_atual": col_rs("Fatura atual"),
                            "venc_prox": st.column_config.DateColumn("Depois", format="DD/MM"),
                            "fatura_prox": col_rs("Próxima"), "comprometido": col_rs("Comprometido"),
                            "limite": col_rs("Limite"),
                            "uso": st.column_config.ProgressColumn("Uso do limite", format="percent",
                                                                   min_value=0, max_value=1)})

# faturas futuras de todos os cartões
fut = fat[fat["vencimento"] >= hoje().replace(day=1)].copy()
if not fut.empty:
    fut["mes"] = fut["mes_ref"].map(mes_label)
    ordem = [mes_label(m) for m in sorted(fut["mes_ref"].unique())][:12]
    fut = fut[fut["mes"].isin(ordem)]
    graf = (alt.Chart(fut).mark_bar()
            .encode(x=alt.X("mes:N", sort=ordem, title=None), y=alt.Y("sum(total):Q", title="R$",
                                                                    axis=alt.Axis(format=",.0f")),
                    color=alt.Color("cartao:N", title=None, legend=alt.Legend(orient="bottom")),
                    tooltip=[alt.Tooltip("cartao:N", title="Cartão"), alt.Tooltip("mes:N", title="Mês"),
                             alt.Tooltip("sum(total):Q", title="R$", format=",.2f")])
            .properties(height=260))
    with st.expander("📊 Faturas dos próximos meses", expanded=not cel):
        st.altair_chart(graf, use_container_width=True)

# --- detalhe de um cartão ---------------------------------------------------------------------
st.divider()
op = dict(zip(res["cartao_id"], res["cartao"]))
c1, c2 = st.columns([1.3, 1])
cid = c1.selectbox("Cartão", list(op), format_func=op.get, key="cart_sel")
f_cart = fat[fat["cartao_id"] == cid].sort_values("mes_ref")
r_cart = res[res["cartao_id"] == cid].iloc[0]
meses = list(f_cart["mes_ref"])
padrao = next((m for m, ven, pg in zip(f_cart["mes_ref"], f_cart["vencimento"], f_cart["paga"])
               if not pg and ven >= hoje()), meses[-1])
lbl = {m: f"{mes_label(m)} · {brl(t)}{' ✅' if p else ''}"
       for m, t, p in zip(f_cart["mes_ref"], f_cart["total"], f_cart["paga"])}
mes = c2.selectbox("Fatura", meses, index=meses.index(padrao), format_func=lbl.get, key=f"cart_mes_{cid}")
linha = f_cart[f_cart["mes_ref"] == mes].iloc[0]

cartoes_kpi([("Vencimento", f"{linha['vencimento']:%d/%m/%Y}"), ("Total da fatura", brl(linha["total"])),
             ("Itens", str(int(linha["itens"]))), ("Situação", "✅ Paga" if linha["paga"] else "⏳ Em aberto")])

it = cartoes.itens(u, cid, mes)
if not it.empty:
    it["valor"] = it.apply(lambda r: -float(r.valor) if r.tipo == "receita" else float(r.valor), axis=1)
    it["parc"] = it.apply(lambda r: f"{int(r.parcela_num)}/{int(r.parcela_total)}" if pd.notna(r.parcela_num) else "",
                          axis=1)
    cols = ["descricao", "valor"] if cel else ["data_compra", "descricao", "parc", "categoria", "valor"]
    st.dataframe(em_reais(it)[cols], hide_index=True, use_container_width=True,
                 height=min(38 + 35 * len(it), 480),
                 column_config={"data_compra": st.column_config.DateColumn("Compra", format="DD/MM"),
                                "descricao": "Descrição", "parc": "Parc.", "categoria": "Categoria",
                                "valor": col_rs()})
    por_cat = it.groupby("categoria", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
    with st.expander("Por categoria"):
        st.dataframe(em_reais(por_cat), hide_index=True, use_container_width=True,
                     column_config={"categoria": "Categoria", "valor": col_rs()})

b1, b2 = st.columns(2)
if not linha["paga"]:
    if b1.button("✅ Marcar fatura como paga", type="primary", use_container_width=True):
        cartoes.marcar_fatura(u, cid, mes, True)
        st.session_state["_ok_cart"] = f"Fatura de {mes_label(mes)} do {op[cid]} marcada como paga."
        st.rerun()
else:
    if b1.button("↩️ Reabrir fatura", use_container_width=True):
        cartoes.marcar_fatura(u, cid, mes, False)
        st.rerun()
b2.page_link("telas/importar_fatura.py", label="Importar fatura deste cartão", icon=":material/upload:")

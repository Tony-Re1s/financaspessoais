import altair as alt
import pandas as pd
import streamlit as st

from core import db, patrimonio, repo, saldos
from core.fmt import brl, hoje, mes_label
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, usuario

u = usuario()
cel = e_celular()
st.title("Patrimônio")

if msg := st.session_state.pop("_ok_pat", None):
    st.success(msg, icon=":material/check_circle:")

comp = patrimonio.calcular(u)
try:
    patrimonio.registrar_mes(u, comp)          # guarda a foto do mês para a evolução
except Exception:  # noqa: BLE001
    pass
tem = float(comp.loc[comp["valor"] > 0, "valor"].sum()) if not comp.empty else 0.0
deve = float(-comp.loc[comp["valor"] < 0, "valor"].sum()) if not comp.empty else 0.0
ant = patrimonio.mes_anterior(u)
cartoes_kpi([("Patrimônio líquido", brl(tem - deve)), ("O que você tem", brl(tem)), ("O que você deve", brl(deve)),
             ("Variação no mês", brl(tem - deve - ant) if ant is not None else "—"),
             ("Dívida / bens", f"{deve / tem:.0%}" if tem else "—")],
            titulo="Patrimônio", icone="🏛️", c1="#272B66", c2="#4E57B5")

# --- composição --------------------------------------------------------------------------------
if comp.empty:
    st.info("Comece cadastrando seus bens (o apartamento), o FGTS e os investimentos.")
else:
    g = comp.groupby("grupo", as_index=False)["valor"].sum()
    ordem = ["Contas", "Investimentos", "Previdência", "FGTS", "Bens", "Dívidas"]
    g["ordem"] = g["grupo"].map({k: i for i, k in enumerate(ordem)})
    g = g.sort_values("ordem")
    graf = (alt.Chart(g).mark_bar()
            .encode(y=alt.Y("grupo:N", sort=list(g["grupo"]), title=None),
                    x=alt.X("valor:Q", title="R$", axis=alt.Axis(format=",.0f")),
                    color=alt.condition("datum.valor < 0", alt.value("#d9534f"), alt.value("#2e8b57")),
                    tooltip=[alt.Tooltip("grupo:N", title=""), alt.Tooltip("valor:Q", title="R$", format=",.2f")])
            .properties(height=40 * len(g) + 20))
    with st.container(border=True):
        st.altair_chart(graf, use_container_width=True)
    with st.expander("Ver item a item"):
        st.dataframe(em_reais(comp), hide_index=True, use_container_width=True,
                     column_config={"grupo": "Grupo", "item": "Item", "valor": col_rs()})

hist = patrimonio.historico(u)
if len(hist) >= 2:
    hist["mes"] = hist["mes_ref"].map(mes_label)
    st.subheader("Evolução")
    st.altair_chart(alt.Chart(hist).mark_line(point=True).encode(
        x=alt.X("mes:N", sort=list(hist["mes"]), title=None),
        y=alt.Y("liquido:Q", title="R$", axis=alt.Axis(format=",.0f")),
        tooltip=[alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("liquido:Q", title="Líquido", format=",.2f")])
        .properties(height=240), use_container_width=True)
else:
    st.caption("📈 A evolução aparece a partir do 2º mês — o app guarda uma foto do patrimônio a cada mês.")

# --- bens --------------------------------------------------------------------------------------
st.subheader("Bens")
b = patrimonio.bens(u)
for r in b.itertuples():
    with st.container():
        k = [("Seu patrimônio nele", brl(r.valor - r.divida)), ("Valor", brl(r.valor)), ("Já pago", brl(r.pago)),
             ("Ainda deve", brl(r.divida)),
             ("Quitado", f"{r.pct_quitado:.0%}" if r.pct_quitado is not None and pd.notna(r.pct_quitado) else "—")]
        cartoes_kpi(k, titulo=r.descricao, icone="🏠", c1="#272B66", c2="#4E57B5")
        if r.pct_quitado is not None and pd.notna(r.pct_quitado):
            st.progress(float(r.pct_quitado), text=f"{r.pct_quitado:.0%} pago"
                        + (f" · {brl(r.a_pagar)} já programado nos lançamentos" if r.a_pagar else ""))

cats = db.consultar("""select c.id, coalesce(p.nome || ' › ', '') || c.nome as rotulo
                         from categorias c left join categorias p on p.id = c.pai_id
                        where c.dono_id = :u and c.tipo = 'despesa' order by 2""", u=u["id"])
op_cats = dict(zip(cats["id"], cats["rotulo"]))
op = {None: "➕ Novo bem (apartamento, carro…)"} | {r.id: f"Editar: {r.descricao}" for r in b.itertuples()}
escolha = st.selectbox("Bem", list(op), format_func=op.get, key="pat_bem", label_visibility="collapsed")
a = b[b["id"] == escolha].iloc[0].to_dict() if escolha else {}


def _v(k, padrao=None):
    x = a.get(k)
    return padrao if x is None or (not isinstance(x, (str, list)) and pd.isna(x)) else x


with st.form(f"bem_{escolha}"):
    desc = st.text_input("Descrição", _v("descricao", ""), placeholder="Ex.: Apartamento B0915 — Vibra Vila Sônia")
    c1, c2, c3 = st.columns(3)
    data_aq = c1.date_input("Comprado em", _v("data_aquisicao", None), format="DD/MM/YYYY")
    preco = c2.number_input("Preço de compra (R$)", 0.0, value=float(_v("valor_aquisicao", 0.0)), step=1000.0,
                            format="%.2f")
    atual = c3.number_input("Vale hoje (R$)", 0.0, value=float(_v("valor_atual", 0.0)), step=1000.0, format="%.2f",
                            help="Deixe 0 para usar o preço de compra.")
    sel = [c for c in (_v("categorias_pagamento", []) or []) if c in op_cats]
    cats_pag = st.multiselect("Pagamentos que contam como patrimônio", list(op_cats), default=sel,
                              format_func=op_cats.get,
                              help="Ex.: as categorias das parcelas da construtora e da entrada. Não marque "
                                   "juros/evolução de obra — isso é custo, não vira patrimônio.")
    usar_div = st.toggle("Informar a dívida manualmente", value=_v("divida_vinculada") is not None,
                         help="Ex.: saldo devedor do financiamento depois das chaves. Desligado: dívida = preço − pago.")
    div = st.number_input("Dívida hoje (R$)", 0.0, value=float(_v("divida_vinculada", 0.0)), step=1000.0,
                          format="%.2f", disabled=not usar_div)
    if st.form_submit_button("Salvar bem", type="primary"):
        if not desc.strip():
            st.error("Dê um nome ao bem.")
        else:
            patrimonio.salvar_bem(u, dict(descricao=desc.strip(), data_aquisicao=data_aq, valor_aquisicao=preco or None,
                                          valor_atual=atual or None, divida_vinculada=div if usar_div else None,
                                          categorias_pagamento=cats_pag), escolha)
            st.session_state["_ok_pat"] = f"**{desc}** salvo."
            st.rerun()
if escolha:
    with st.popover("🗑️ Excluir bem"):
        if st.button("Excluir de vez", type="primary"):
            patrimonio.excluir_bem(u, escolha)
            st.rerun()

# --- saldos que não vêm de lançamentos (FGTS, financiamento, poupança) ----------------------------
st.subheader("FGTS e outros saldos")
contas = repo.contas(u)
outras = contas[contas["tipo"].isin(["fgts", "financiamento", "poupanca", "carteira"])]
if outras.empty or "fgts" not in set(outras["tipo"]):
    if st.button("➕ Criar conta do FGTS"):
        repo.salvar_conta(u, dict(nome="FGTS", tipo="fgts", visibilidade="privado", ativa=True))
        st.rerun()
if not outras.empty:
    atuais = [saldos.saldo_em(u, c, hoje()) for c in outras["id"]]
    ed = st.data_editor(pd.DataFrame({"id": outras["id"], "conta": outras["nome"],
                                      "tipo": outras["tipo"].map({"fgts": "FGTS", "financiamento": "Financiamento",
                                                                  "poupanca": "Poupança", "carteira": "Carteira"}),
                                      "atual": atuais, "novo": None}),
                        hide_index=True, use_container_width=True, key="ed_saldos_pat",
                        column_config={"id": None, "conta": st.column_config.TextColumn("Conta", disabled=True),
                                       "tipo": st.column_config.TextColumn("Tipo", disabled=True),
                                       "atual": st.column_config.NumberColumn("No app", format="R$ %.2f", disabled=True),
                                       "novo": st.column_config.NumberColumn("Saldo hoje", format="R$ %.2f")})
    st.caption("FGTS: veja no app do FGTS. Financiamento: saldo devedor (o app trata como dívida).")
    if st.button("Salvar saldos", key="salvar_saldos_pat"):
        n = 0
        for r in ed.itertuples():
            if pd.notna(r.novo):
                saldos.informar_saldo(r.id, hoje(), float(r.novo)); n += 1
        st.session_state["_ok_pat"] = f"{n} saldos atualizados."
        st.rerun()

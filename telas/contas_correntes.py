from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core import repo, saldos
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref, somar_meses
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, usuario

u = usuario()
cel = e_celular()
st.title("Contas correntes")

if msg := st.session_state.pop("_ok_cc", None):
    st.success(msg, icon=":material/check_circle:")

contas = repo.contas(u)
caixa = contas[contas["tipo"].isin(saldos.TIPOS_CAIXA)]
if caixa.empty:
    st.info("Cadastre suas contas correntes em **Contas e cartões** (tipo *Conta corrente*).")
    st.stop()

op = {"todas": "Todas as contas"} | {str(r.id): r.nome for r in caixa.itertuples()}
atual = mes_ref(hoje())
meses = [somar_meses(atual, k) for k in range(-12, 13)]
c1, c2 = st.columns([1.4, 1])
escolha = c1.selectbox("Conta", list(op), format_func=op.get, key="cc_conta")
mes = c2.selectbox("Mês", meses, index=12, format_func=mes_label, key="cc_mes")
ids = list(caixa["id"]) if escolha == "todas" else [next(i for i in caixa["id"] if str(i) == escolha)]

ini = date(mes // 100, mes % 100, 1)
fim = dia_no_mes(mes // 100, mes % 100, 31)
s_ini, ext = saldos.extrato(u, ids, ini, fim)
mov_real = ext[ext["fonte"] != "ajuste"] if not ext.empty else ext
entradas = float(mov_real.loc[mov_real["valor"] > 0, "valor"].sum()) if not ext.empty else 0.0
saidas = float(-mov_real.loc[mov_real["valor"] < 0, "valor"].sum()) if not ext.empty else 0.0
ajustes = float(ext.loc[ext["fonte"] == "ajuste", "valor"].sum()) if not ext.empty else 0.0
s_fim = s_ini + entradas - saidas + ajustes

kpis = [(f"Saldo em {ini - timedelta(days=1):%d/%m}", brl(s_ini)), ("Entradas", brl(entradas)),
        ("Saídas", brl(saidas)), (f"Saldo previsto {fim:%d/%m}", brl(s_fim))]
if ini <= hoje() <= fim:
    s_hoje = s_ini + (float(ext.loc[ext["data"] <= hoje(), "valor"].sum()) if not ext.empty else 0.0)
    kpis.insert(1, ("Saldo hoje", brl(s_hoje)))
cartoes_kpi(kpis)

if abs(ajustes) > 0.004:
    st.caption(f"🔧 Ajustes de saldo no mês: {brl(ajustes)} (diferença entre o que o app calculava e o saldo "
               "informado — algo não foi lançado, ou foi lançado com valor/data diferente).")
venc = saldos.vencidos_sem_confirmar(u, ids)
if not venc.empty:
    st.caption(f"⚠️ {len(venc)} lançamentos vencidos ainda como *previstos* ({brl(venc['valor'].sum())}) entram como "
               "se tivessem acontecido. Marque como pago em **Lançamentos** ou informe o saldo real abaixo.")

# --- projeção --------------------------------------------------------------------------------
proj = saldos.projecao_diaria(u, ids, hoje(), 90)
if not proj.empty:
    with st.expander("📈 Saldo projetado — próximos 90 dias", expanded=not cel):
        minimo = proj.loc[proj["saldo"].idxmin()]
        graf = (alt.Chart(proj).mark_area(line=True, opacity=.25)
                .encode(x=alt.X("data:T", title=None, axis=alt.Axis(format="%d/%m")),
                        y=alt.Y("saldo:Q", title="R$", axis=alt.Axis(format=",.0f")),
                        tooltip=[alt.Tooltip("data:T", title="Dia", format="%d/%m/%Y"),
                                 alt.Tooltip("saldo:Q", title="Saldo", format=",.2f")])
                .properties(height=220))
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[4, 4], color="#d33").encode(y="y:Q")
        st.altair_chart(graf + zero, use_container_width=True)
        st.caption(f"Menor saldo no período: **{brl(minimo['saldo'])}** em {minimo['data']:%d/%m}."
                   + (" Fica negativo — vale antecipar algum resgate ou remanejar." if minimo["saldo"] < 0 else ""))

# --- extrato ---------------------------------------------------------------------------------
st.subheader(f"Extrato · {mes_label(mes)}")
if ext.empty:
    st.caption("Nenhum movimento neste mês.")
else:
    v = ext.copy()
    v["sit"] = v["status"].map({"pago": "✅", "previsto": "⏳"}).fillna("")
    v["sit"] = v.apply(lambda r: "🔧" if r["fonte"] == "ajuste" else ("💳" if r["fonte"] == "fatura" else r["sit"]),
                       axis=1)
    if escolha == "todas" and len(ids) > 1:
        v["conta_nome"] = v["conta"].map({r.id: r.nome for r in caixa.itertuples()})
    v = pd.concat([pd.DataFrame([{"sit": "", "data": ini - timedelta(days=1), "descricao": "Saldo anterior",
                                  "categoria": "", "valor": None, "saldo": s_ini}]), v], ignore_index=True)
    cols = ["data", "descricao", "valor", "saldo"] if cel else \
        ["sit", "data", "descricao", "categoria"] + (["conta_nome"] if "conta_nome" in v else []) + ["valor", "saldo"]
    st.dataframe(em_reais(v, "valor", "saldo")[cols], hide_index=True, use_container_width=True,
                 height=min(38 + 35 * len(v), 560),
                 column_config={"sit": st.column_config.TextColumn("", width=30),
                                "data": st.column_config.DateColumn("Data", format="DD/MM"),
                                "descricao": "Descrição", "categoria": "Categoria", "conta_nome": "Conta",
                                "valor": col_rs("Valor"), "saldo": col_rs("Saldo")})
    st.caption("✅ pago · ⏳ previsto · 💳 fatura do cartão · 🔧 ajuste para bater com o saldo informado")

# --- ajustes ---------------------------------------------------------------------------------
st.divider()
c1, c2 = st.columns(2)
with c1.expander("🔧 Informar saldo real"):
    st.caption("Digite o saldo que aparece no app do banco. A partir dele o app recalcula tudo.")
    with st.form("saldo_real", clear_on_submit=True):
        cid = st.selectbox("Conta", list(caixa["id"]), format_func=dict(zip(caixa["id"], caixa["nome"])).get,
                           index=list(caixa["id"]).index(ids[0]) if len(ids) == 1 else 0)
        d = st.date_input("Saldo no fim do dia", hoje(), format="DD/MM/YYYY")
        val = st.number_input("Saldo (R$)", value=0.0, step=100.0, format="%.2f",
                              help="Pode ser negativo (cheque especial).")
        if st.form_submit_button("Salvar saldo", type="primary"):
            antes = saldos.saldo_em(u, cid, d)
            saldos.informar_saldo(cid, d, val)
            st.session_state["_ok_cc"] = (f"Saldo salvo. O app calculava {brl(antes)}; diferença de "
                                          f"{brl(val - antes)} entra como ajuste.")
            st.rerun()

with c2.expander("⚙️ Lançamentos sem conta"):
    st.caption("Boletos e pix lançados sem conta (ex.: aluguel, parcelas do apê) saem de qual conta no fluxo?")
    princ = saldos.conta_principal(u)
    opp = {None: "— nenhuma (ficam de fora do fluxo)"} | {str(r.id): r.nome for r in caixa.itertuples()}
    novo = st.selectbox("Conta principal", list(opp), format_func=opp.get,
                        index=list(opp).index(princ) if princ in opp else 0, key="cc_princ")
    if novo != princ and st.button("Salvar conta principal"):
        saldos.definir_conta_principal(u, novo)
        st.session_state["_ok_cc"] = "Conta principal salva."
        st.rerun()

sem_pag = contas[(contas["tipo"] == "cartao_credito") & contas["conta_pagamento_id"].isna()]
if not sem_pag.empty:
    st.caption(f"💳 {len(sem_pag)} cartões sem conta pagadora definida — as faturas deles não entram no fluxo. "
               "Defina em **Contas e cartões** (campo *Fatura paga pela conta*).")

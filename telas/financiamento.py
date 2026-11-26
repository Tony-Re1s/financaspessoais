from datetime import date

import pandas as pd
import streamlit as st

from core import financiamentos as fin
from core import repo
from core.fmt import brl, hoje
from telas import _ui
from telas._comum import cartoes_kpi, col_rs, em_reais, opcoes_categoria, usuario

u = usuario()


def _pct(v):
    return f"{float(v):.4f}".replace(".", ",") + "% a.m."


_ui.titulo("Financiamento", "🏗️", "Fase de obra: encargo = saldo devedor × (juros fixos + TR) + seguros e tarifa")

if msg := st.session_state.pop("_ok_fin", None):
    st.success(msg, icon=":material/check_circle:")

df = fin.listar(u)
contas = repo.contas(u)
op_contas = {None: "—"} | {r.id: r.nome for r in contas.itertuples()}
op_cat = {None: "—"} | opcoes_categoria(repo.categorias(u), "despesa")

nomes = {r.id: r.nome for r in df.itertuples()} | {"novo": "➕ Novo financiamento"}
sel = st.selectbox("Financiamento", list(nomes), format_func=nomes.get, key="fin_sel") if len(nomes) > 1 else "novo"
f = df[df["id"] == sel].iloc[0].to_dict() if sel != "novo" else {
    "nome": "", "descricao_lanc": "", "conta_id": None, "categoria_id": None, "forma_pagamento": "Boleto",
    "dia_venc": 4, "taxa_am": 0.0, "fixos": 0.0, "saldo": 0.0, "data_saldo": hoje(), "tr_modo": "bcb",
    "tr_manual": 0.0, "ultimo_boleto": None, "fim_obra": None, "cronograma": {}}

# --- indicadores e projeção -------------------------------------------------------------------
if sel != "novo":
    tr, origem = fin.tr_usada(f)
    lib = st.toggle("Considerar as próximas liberações da obra (cronograma da planilha)", value=True, key="fin_lib",
                    help="Desligado: o saldo fica parado no valor atual, como se a CAIXA não liberasse mais nada.")
    proj = fin.projetar(f, tr, lib)
    prox = proj.iloc[0] if not proj.empty else None
    tr_b = fin.tr_do_boleto(f)
    cartoes_kpi([("Próximo encargo", brl(prox.encargo) if prox is not None else "—"),
                 ("Saldo devedor", brl(f["saldo"])),
                 ("Juros fixos", _pct(f["taxa_am"])), ("TR usada", _pct(tr)),
                 ("Total até o fim da obra", brl(proj["encargo"].sum()) if not proj.empty else "—")],
                titulo=f["nome"], icone="🏗️", sub=f"TR: {origem}" + (
                    f" · TR do último boleto: {_pct(tr_b)}" if tr_b is not None else ""))
    if (b := fin.tr_bcb()) is None and f.get("tr_modo") == "bcb":
        st.caption("Não consegui ler a TR no Banco Central agora; usei a do último boleto ou a digitada.")

    if not proj.empty:
        v = proj.copy()
        st.dataframe(em_reais(v, "saldo", "juros_tr", "fixos", "encargo"), hide_index=True,
                     use_container_width=True,
                     column_config={"vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YY"),
                                    "saldo": col_rs("Saldo devedor"), "juros_tr": col_rs("Juros + TR"),
                                    "fixos": col_rs("Seguros + tarifa"), "encargo": col_rs("Encargo")})
        if st.button("Aplicar no fluxo de caixa", type="primary", icon=":material/sync:",
                     help=f"Atualiza os lançamentos previstos “{f['descricao_lanc']}” com estes valores "
                          "e cria os meses que faltam. Os já pagos não mudam."):
            alt, novos = fin.aplicar(u, f, proj)
            st.session_state["_ok_fin"] = f"Projeção aplicada: {alt} lançamentos atualizados, {novos} criados."
            st.rerun()

# --- cadastro / atualização mensal --------------------------------------------------------------
with st.expander("Atualizar saldo e boleto do mês" if sel != "novo" else "Cadastrar", expanded=sel == "novo"):
    with st.form("fin_form"):
        c1, c2 = st.columns(2)
        saldo = c1.number_input("Saldo devedor (app do banco)", min_value=0.0, value=float(f["saldo"]), step=100.0,
                                format="%.2f")
        data_saldo = c2.date_input("Data do saldo", value=pd.to_datetime(f["data_saldo"]).date(), format="DD/MM/YYYY")
        c1, c2 = st.columns(2)
        boleto = c1.number_input("Valor do último boleto (opcional)", min_value=0.0,
                                 value=float(f["ultimo_boleto"] or 0), step=10.0, format="%.2f",
                                 help="Com ele o app descobre a TR que o banco aplicou.")
        modos = list(fin.MODOS_TR)
        tr_modo = c2.selectbox("TR para projetar", modos, index=modos.index(f.get("tr_modo") or "bcb"),
                               format_func=fin.MODOS_TR.get)
        tr_manual = st.number_input("TR digitada (% a.m.)", value=float(f.get("tr_manual") or 0), step=0.01,
                                    format="%.4f")
        st.markdown("**Contrato**")
        c1, c2, c3 = st.columns(3)
        nome = c1.text_input("Nome", value=f["nome"])
        taxa = c2.number_input("Juros (% a.m., fixo)", value=float(f["taxa_am"]), step=0.0001, format="%.4f")
        fixos = c3.number_input("Seguros + tarifa (R$/mês)", value=float(f["fixos"]), step=1.0, format="%.2f")
        c1, c2, c3 = st.columns(3)
        dia = c1.number_input("Dia do vencimento", 1, 31, int(f["dia_venc"]))
        fim = c2.date_input("Fim da obra (último encargo de obra)",
                            value=pd.to_datetime(f["fim_obra"]).date() if f.get("fim_obra") else None,
                            format="DD/MM/YYYY")
        desc = c3.text_input("Descrição dos lançamentos", value=f["descricao_lanc"])
        c1, c2 = st.columns(2)
        conta = c1.selectbox("Conta que paga", list(op_contas), format_func=op_contas.get,
                             index=list(op_contas).index(f["conta_id"]) if f["conta_id"] in op_contas else 0)
        cat = c2.selectbox("Categoria", list(op_cat), format_func=op_cat.get,
                           index=list(op_cat).index(f["categoria_id"]) if f["categoria_id"] in op_cat else 0)
        if st.form_submit_button("Salvar", type="primary"):
            if not nome or not desc or not taxa:
                st.error("Preencha nome, descrição e juros.")
            else:
                fin.salvar(u, {"nome": nome, "descricao_lanc": desc, "conta_id": conta, "categoria_id": cat,
                               "forma_pagamento": f.get("forma_pagamento") or "Boleto", "dia_venc": int(dia),
                               "taxa_am": taxa, "fixos": fixos, "saldo": saldo, "data_saldo": data_saldo,
                               "tr_modo": tr_modo, "tr_manual": tr_manual, "ultimo_boleto": boleto or None,
                               "fim_obra": fim, "cronograma": f.get("cronograma") or {}},
                           None if sel == "novo" else sel)
                st.session_state["_ok_fin"] = "Salvo. Confira a projeção e clique em Aplicar no fluxo de caixa."
                st.rerun()

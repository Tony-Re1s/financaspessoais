import altair as alt
import pandas as pd
import streamlit as st

from core import investimentos as inv
from core import repo
from core.fmt import brl, hoje
from telas import _ui
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, usuario

u = usuario()
cel = e_celular()
_ui.titulo("Investimentos", "📈")

if msg := st.session_state.pop("_ok_inv", None):
    st.success(msg, icon=":material/check_circle:")

contas = repo.contas(u)
inst = contas[contas["tipo"].isin(inv.TIPOS_INSTITUICAO)]
caixa = contas[contas["tipo"].isin(["conta_corrente", "poupanca", "carteira"])]
df = inv.ativos(u)

# --- resumo ---------------------------------------------------------------------------------
if df.empty:
    st.info("Nenhuma aplicação cadastrada ainda. Use **➕ Nova aplicação** abaixo — ou me mande a lista "
            "(nome, banco/corretora, tipo, quanto tem hoje) que eu cadastro para você.")
else:
    total, aplicado = df["valor_atual"].sum(), df["aplicado"].sum()
    cartoes_kpi([("Total investido hoje", brl(total)), ("Aplicado (aportes − resgates)", brl(aplicado)),
                 ("Ganho", brl(total - aplicado)),
                 ("Rentabilidade", f"{(total / aplicado - 1) * 100:,.1f}%".replace(".", ",") if aplicado else "—"),
                 ("Aplicações", str(len(df)))],
                titulo="Minha carteira", icone="📈", c1="#0B4F45", c2="#12907F")
    v = df.copy()
    v["classe_n"] = v["classe"].map(inv.CLASSES)
    v["atualizado"] = pd.to_datetime(v["data_posicao"])
    v["vencimento"] = pd.to_datetime(v["vencimento"])
    st.markdown("<div class='ui-sec'>Aplicações</div>", unsafe_allow_html=True)
    itens = []
    for r in v.sort_values("valor_atual", ascending=False).itertuples():
        g = float(r.valor_atual) - float(r.aplicado or 0)
        pct = f" · {r.ganho_pct:+.1%}".replace(".", ",") if pd.notna(r.ganho_pct) else ""
        sub = " · ".join(x for x in [r.instituicao, r.classe_n, r.liquidez if isinstance(r.liquidez, str) else ""] if x)
        itens.append(f"""<div class="ui-item" style="padding:10px 0;border-bottom:1px solid rgba(128,128,128,.1)">
            {_ui.selo(r.instituicao, r.instituicao, 38)}
            <div class="ui-tx"><div class="t">{_ui.esc(r.nome)}</div><div class="s">{_ui.esc(sub)}</div></div>
            <div style="text-align:right"><div class="ui-val" style="color:inherit">{brl(r.valor_atual)}</div>
            <div class="ui-val {'pos' if g >= 0 else 'neg'}" style="font-size:.76rem">{'+' if g >= 0 else '−'} {brl(abs(g))}{pct}</div></div>
            </div>""")
    _ui.render(f"<div class='ui-lista-html'>{''.join(itens)}</div>")
    with st.expander("Ver em tabela"):
        cols = ["nome", "valor_atual"] if cel else \
        ["instituicao", "nome", "classe_n", "aplicado", "valor_atual", "ganho_pct", "liquidez", "vencimento",
         "atualizado"]
        st.dataframe(em_reais(v, "aplicado", "valor_atual")[cols], hide_index=True, use_container_width=True,
                     column_config={"instituicao": "Onde", "nome": "Aplicação", "classe_n": "Tipo",
                                    "aplicado": col_rs("Aplicado"), "valor_atual": col_rs("Hoje"),
                                    "ganho_pct": st.column_config.NumberColumn("Ganho", format="percent"),
                                    "liquidez": "Liquidez",
                                    "vencimento": st.column_config.DateColumn("Vence", format="DD/MM/YY"),
                                    "atualizado": st.column_config.DateColumn("Posição de", format="DD/MM/YY")})
    g1, g2 = st.columns(2) if not cel else (st.container(), st.container())
    por_classe = v.groupby("classe_n", as_index=False)["valor_atual"].sum()
    por_inst = v.groupby("instituicao", as_index=False)["valor_atual"].sum()
    for alvo, dados, campo, titulo in [(g1, por_classe, "classe_n", "Por tipo"), (g2, por_inst, "instituicao", "Por instituição")]:
        with alvo:
            st.caption(titulo)
            st.altair_chart(alt.Chart(dados).mark_bar(color="#12907F", cornerRadiusEnd=4).encode(
                y=alt.Y(f"{campo}:N", sort="-x", title=None), x=alt.X("valor_atual:Q", title="R$",
                                                                    axis=alt.Axis(format=",.0f")),
                tooltip=[alt.Tooltip(f"{campo}:N", title=""), alt.Tooltip("valor_atual:Q", title="R$", format=",.2f")])
                .properties(height=max(90, 32 * len(dados))), use_container_width=True)

# --- atualizar posições em lote ----------------------------------------------------------------
if not df.empty:
    with st.expander("🔄 Atualizar saldos de hoje (todas de uma vez)"):
        st.caption("Copie o saldo bruto que aparece no banco/corretora. Deixe em branco o que não mudou.")
        ed = st.data_editor(pd.DataFrame({"id": df["id"], "aplicacao": df["instituicao"] + " · " + df["nome"],
                                          "atual": df["valor_atual"].astype(float), "novo": None}),
                            hide_index=True, use_container_width=True, key="ed_pos",
                            column_config={"id": None, "aplicacao": st.column_config.TextColumn("Aplicação", disabled=True),
                                           "atual": st.column_config.NumberColumn("No app", format="R$ %.2f", disabled=True),
                                           "novo": st.column_config.NumberColumn("Saldo hoje", format="R$ %.2f")})
        if st.button("Salvar saldos", type="primary"):
            n = 0
            for r in ed.itertuples():
                if pd.notna(r.novo):
                    inv.informar_posicao(r.id, hoje(), float(r.novo)); n += 1
            st.session_state["_ok_inv"] = f"{n} saldos atualizados."
            st.rerun()

# --- aporte / resgate ---------------------------------------------------------------------------
if not df.empty:
    with st.expander("💸 Aplicar, resgatar ou lançar rendimento"):
        op_a = dict(zip(df["id"], df["instituicao"] + " · " + df["nome"]))
        with st.form("mov_inv", clear_on_submit=True):
            a_id = st.selectbox("Aplicação", list(op_a), format_func=op_a.get)
            c1, c2, c3 = st.columns(3)
            tipo = c1.selectbox("O quê", ["aporte", "resgate", "rendimento", "ir_retido", "taxa"],
                                format_func={"aporte": "Aplicação (aporte)", "resgate": "Resgate",
                                             "rendimento": "Rendimento/dividendo", "ir_retido": "IR retido",
                                             "taxa": "Taxa"}.get)
            valor = c2.number_input("Valor (R$)", 0.0, step=100.0, format="%.2f")
            data = c3.date_input("Data", hoje(), format="DD/MM/YYYY")
            op_cc = {None: "— não mexer em conta corrente"} | dict(zip(caixa["id"], caixa["nome"]))
            cc = st.selectbox("Dinheiro saiu de / voltou para", list(op_cc), format_func=op_cc.get,
                              help="Aplicação e resgate viram uma transferência no extrato da conta corrente.")
            if st.form_submit_button("Salvar", type="primary") and valor > 0:
                inv.movimentar(u, a_id, data, tipo, valor, cc, f"{'Aplicação' if tipo == 'aporte' else 'Resgate'} "
                                                                f"{op_a[a_id]}")
                st.session_state["_ok_inv"] = "Movimento salvo."
                st.rerun()

# --- cadastro -----------------------------------------------------------------------------------
st.divider()
op = {None: "➕ Nova aplicação"} | {r.id: f"Editar: {r.instituicao} · {r.nome}" for r in df.itertuples()}
escolha = st.selectbox("Cadastro", list(op), format_func=op.get, key="inv_escolha")
a = df[df["id"] == escolha].iloc[0].to_dict() if escolha else {}


def _v(k, padrao=None):
    x = a.get(k)
    return padrao if x is None or (not isinstance(x, str) and pd.isna(x)) else x


with st.form(f"ativo_{escolha}"):
    c1, c2 = st.columns(2)
    op_i = {None: "➕ Nova instituição…"} | dict(zip(inst["id"], inst["nome"]))
    ids_i = list(op_i)
    conta_id = c1.selectbox("Banco / corretora", ids_i, format_func=op_i.get,
                            index=ids_i.index(a.get("conta_id")) if a.get("conta_id") in ids_i else (1 if len(ids_i) > 1 else 0))
    nova_inst = c2.text_input("Nome da nova instituição", placeholder="Ex.: XP, Nubank Caixinhas, Itaú Personnalité",
                              help="Só se escolheu ➕ Nova instituição")
    nome = st.text_input("Aplicação", _v("nome", ""), placeholder="Ex.: CDB Inter 110% CDI, Tesouro IPCA+ 2035")
    c1, c2, c3 = st.columns(3)
    classes = list(inv.CLASSES)
    classe = c1.selectbox("Tipo", classes, format_func=inv.CLASSES.get,
                          index=classes.index(_v("classe", "renda_fixa")))
    indexador = c2.selectbox("Rende por", ["", "CDI", "IPCA", "SELIC", "PRE", "Variável"],
                             index=["", "CDI", "IPCA", "SELIC", "PRE", "Variável"].index(_v("indexador", "") or ""))
    taxa = c3.number_input("Taxa", 0.0, value=float(_v("taxa", 0.0)), step=1.0, format="%.2f",
                           help="Ex.: 110 (% do CDI) ou 6,5 (IPCA + 6,5%)")
    c1, c2, c3 = st.columns(3)
    data_ap = c1.date_input("Aplicado em", _v("data_aplicacao", None), format="DD/MM/YYYY")
    venc = c2.date_input("Vencimento", _v("vencimento", None), format="DD/MM/YYYY")
    liq = c3.selectbox("Liquidez", ["Diária", "No vencimento", "D+1", "D+30", "D+90", "Outra"],
                       index=["Diária", "No vencimento", "D+1", "D+30", "D+90", "Outra"].index(_v("liquidez", "Diária"))
                       if _v("liquidez", "Diária") in ["Diária", "No vencimento", "D+1", "D+30", "D+90", "Outra"] else 5)
    if not escolha:
        c1, c2 = st.columns(2)
        valor_ini = c1.number_input("Quanto tem hoje (R$)", 0.0, step=100.0, format="%.2f")
        aplicado_ini = c2.number_input("Quanto você aplicou (R$)", 0.0, step=100.0, format="%.2f",
                                       help="Para calcular o ganho. Se não souber, deixe igual ao valor de hoje.")
    ativo = st.toggle("Ativa", value=bool(_v("ativo", True)))
    ok = st.form_submit_button("Salvar", type="primary")

if ok:
    if not nome.strip() or (conta_id is None and not nova_inst.strip()):
        st.error("Preencha a aplicação e a instituição.")
    else:
        if conta_id is None:
            repo.salvar_conta(u, dict(nome=nova_inst.strip(), tipo="previdencia" if classe.startswith("previdencia")
                                      else "investimento", visibilidade="privado", ativa=True))
            conta_id = repo.contas(u).set_index("nome").loc[nova_inst.strip(), "id"]
        aid = inv.salvar_ativo(dict(conta_id=conta_id, nome=nome.strip(), classe=classe, indexador=indexador or None,
                                    taxa=taxa or None, data_aplicacao=data_ap, vencimento=venc, liquidez=liq,
                                    ativo=ativo), escolha)
        if not escolha and (valor_ini or aplicado_ini):
            inv.movimentar(u, aid, data_ap or hoje(), "aporte", aplicado_ini or valor_ini)
            if valor_ini:
                inv.informar_posicao(aid, hoje(), valor_ini)
        st.session_state["_ok_inv"] = f"**{nome}** salva."
        st.rerun()

if escolha:
    with st.expander("Histórico desta aplicação"):
        h = inv.movimentos(escolha)
        h["valor"] = h["valor"].astype(float)
        st.dataframe(em_reais(h), hide_index=True, use_container_width=True,
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                                    "tipo": "Tipo", "valor": col_rs()})
    with st.popover("🗑️ Excluir aplicação"):
        st.caption("Apaga a aplicação e o histórico dela.")
        if st.button("Excluir de vez", type="primary"):
            inv.excluir(escolha)
            st.session_state["_ok_inv"] = "Aplicação excluída."
            st.rerun()

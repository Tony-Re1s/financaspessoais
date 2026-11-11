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


LIQUIDEZ = ["Diária", "No vencimento", "D+1", "D+30", "D+90", "Outra"]
INDEXADORES = ["", "CDI", "IPCA", "SELIC", "PRE", "Variável"]


def _cadastro(escolha):
    a = df[df["id"] == escolha].iloc[0].to_dict() if escolha else {}

    def _v(k, padrao=None):
        x = a.get(k)
        return padrao if x is None or (not isinstance(x, str) and pd.isna(x)) else x

    op_i = {None: "➕ Nova instituição…"} | dict(zip(inst["id"], inst["nome"]))
    ids_i = list(op_i)
    ch = f"inv_{escolha or 'nova'}"
    r = _ui.rascunho(ch, dict(
        conta_id=a.get("conta_id") if a.get("conta_id") in ids_i else (ids_i[1] if len(ids_i) > 1 else None),
        nova_inst="", nome=_v("nome", ""), valor_ini=0.0, aplicado_ini=0.0,
        classe=_v("classe", "renda_fixa"), indexador=_v("indexador", "") or "", taxa=float(_v("taxa", 0.0)),
        data_ap=_v("data_aplicacao", None), venc=_v("vencimento", None),
        liq=_v("liquidez", "Diária") if _v("liquidez", "Diária") in LIQUIDEZ else "Outra",
        vinc=_v("vinculo_descricao", "") or "", ativo=bool(_v("ativo", True))))
    passos = ["Onde", "Como rende", "Extras"]
    i = _ui.etapas(ch, passos)

    if i == 0:
        _ui.campo(r, ch, "conta_id", st.selectbox, "Banco / corretora", ids_i, format_func=op_i.get)
        if r["conta_id"] is None:
            _ui.campo(r, ch, "nova_inst", st.text_input, "Nome da nova instituição",
                      placeholder="Ex.: XP, Nubank Caixinhas, Itaú Personnalité")
        _ui.campo(r, ch, "nome", st.text_input, "Aplicação", placeholder="Ex.: CDB Inter 110% CDI, Tesouro IPCA+ 2035")
        if not escolha:
            c1, c2 = st.columns(2)
            _ui.campo(r, ch, "valor_ini", c1.number_input, "Quanto tem hoje (R$)", 0.0, step=100.0, format="%.2f")
            _ui.campo(r, ch, "aplicado_ini", c2.number_input, "Quanto você aplicou (R$)", 0.0, step=100.0,
                      format="%.2f", help="Para calcular o ganho. Se não souber, deixe igual ao valor de hoje.")
    elif i == 1:
        _ui.campo(r, ch, "classe", st.selectbox, "Tipo", list(inv.CLASSES), format_func=inv.CLASSES.get)
        c1, c2 = st.columns(2)
        _ui.campo(r, ch, "indexador", c1.selectbox, "Rende por", INDEXADORES)
        _ui.campo(r, ch, "taxa", c2.number_input, "Taxa", 0.0, step=1.0, format="%.2f",
                  help="Ex.: 110 (% do CDI) ou 6,5 (IPCA + 6,5%)")
        c1, c2 = st.columns(2)
        _ui.campo(r, ch, "data_ap", c1.date_input, "Aplicado em", format="DD/MM/YYYY")
        _ui.campo(r, ch, "venc", c2.date_input, "Vencimento", format="DD/MM/YYYY")
        _ui.campo(r, ch, "liq", st.selectbox, "Liquidez", LIQUIDEZ)
    else:
        _ui.campo(r, ch, "vinc", st.text_input, "Pagamento mensal que alimenta esta aplicação (opcional)",
                  placeholder="Ex.: CAP PIC — a descrição do débito no extrato",
                  help="Cada lançamento pago com esta descrição continua como despesa no fluxo e também "
                       "soma no saldo desta aplicação (e no Patrimônio).")
        _ui.campo(r, ch, "ativo", st.toggle, "Ativa")

    if _ui.etapas_botoes(ch, len(passos), [("nome", "a aplicação")] if i == 0 else []):
        nome, nova_inst, conta_id = str(r["nome"] or "").strip(), str(r["nova_inst"] or "").strip(), r["conta_id"]
        if not nome or (conta_id is None and not nova_inst):
            st.error("Preencha a aplicação e a instituição.")
        else:
            if conta_id is None:
                todas = repo.contas(u, so_ativas=False)
                ja = todas[todas["nome"].str.strip().str.lower() == nova_inst.lower()]
                if ja.empty:
                    repo.salvar_conta(u, dict(nome=nova_inst, tipo="previdencia" if r["classe"].startswith("previdencia")
                                              else "investimento", visibilidade="privado", ativa=True))
                    todas = repo.contas(u, so_ativas=False)
                    ja = todas[todas["nome"] == nova_inst]
                conta_id = ja.iloc[0]["id"]
            aid = inv.salvar_ativo(dict(conta_id=conta_id, nome=nome, classe=r["classe"], indexador=r["indexador"] or None,
                                        taxa=r["taxa"] or None, data_aplicacao=r["data_ap"], vencimento=r["venc"],
                                        liquidez=r["liq"], ativo=r["ativo"], vinculo_descricao=r["vinc"]), escolha)
            if not escolha and (r["valor_ini"] or r["aplicado_ini"]):
                inv.movimentar(u, aid, r["data_ap"] or hoje(), "aporte", r["aplicado_ini"] or r["valor_ini"])
                if r["valor_ini"]:
                    inv.informar_posicao(aid, hoje(), r["valor_ini"])
            _ui.rascunho_limpar(ch)
            st.session_state["_ok_inv"] = f"**{nome}** salva."
            st.rerun()

    if escolha:
        with st.expander("Histórico desta aplicação"):
            h = inv.movimentos(escolha)
            h["valor"] = h["valor"].astype(float)
            st.dataframe(em_reais(h), hide_index=True, use_container_width=True,
                         column_config={"data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                                        "tipo": "Tipo", "valor": col_rs()})
        with st.popover("🗑️ Excluir aplicação", width="stretch"):
            st.caption("Apaga a aplicação e o histórico dela.")
            if st.button("Excluir de vez", type="primary", key=f"{ch}__exc"):
                inv.excluir(escolha)
                _ui.rascunho_limpar(ch)
                st.session_state["_ok_inv"] = "Aplicação excluída."
                st.rerun()


@st.dialog("Aplicação")
def _ficha(escolha):
    _cadastro(escolha)


# --- resumo ---------------------------------------------------------------------------------
if df.empty:
    st.info("Nenhuma aplicação ainda.")
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
    # --- evolução da carteira ---------------------------------------------------------------------
    st.markdown("<div class='ui-sec'>Evolução</div>", unsafe_allow_html=True)
    e1, e2 = st.columns([1.4, 1]) if not cel else (st.container(), st.container())
    op_ev = {None: "Toda a carteira"} | {r.id: f"{r.instituicao} · {r.nome}" for r in v.itertuples()}
    ev_ativo = e1.selectbox("Ver", list(op_ev), format_func=op_ev.get, key="ev_ativo", label_visibility="collapsed")
    ev_meses = e2.segmented_control("Período", [6, 12, 24], default=12, key="ev_meses",
                                    format_func=lambda n: f"{n} meses", label_visibility="collapsed") or 12
    ev = inv.evolucao(u, int(ev_meses), ev_ativo)
    if ev.empty or (ev["valor"] == 0).all():
        st.caption("Sem histórico ainda. Informe a posição de cada aplicação de tempos em tempos "
                   "(na ficha, botão de atualizar saldo) e a evolução aparece aqui.")
    else:
        ev["mes_lbl"] = pd.to_datetime(ev["fim"])
        _M = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
        ev["rotulo"] = [f"{_M[int(m) % 100 - 1]}/{str(int(m) // 100)[2:]}" for m in ev["mes"]]
        base = alt.Chart(ev).encode(x=alt.X("rotulo:N", title=None, sort=None,
                                            axis=alt.Axis(grid=False, labelAngle=0)))
        area = base.mark_area(color="#0B7A66", opacity=.18, line={"color": "#0B7A66", "strokeWidth": 2}).encode(
            y=alt.Y("valor:Q", title=None, axis=alt.Axis(format=",.0f", gridOpacity=.2)),
            tooltip=[alt.Tooltip("rotulo:N", title="Mês"), alt.Tooltip("valor:Q", title="Valor", format=",.2f"),
                     alt.Tooltip("aplicado:Q", title="Aplicado", format=",.2f"), alt.Tooltip("ganho:Q", title="Ganho", format=",.2f")])
        linha_ap = base.mark_line(color="#64748B", strokeDash=[4, 3], strokeWidth=1.5).encode(y="aplicado:Q")
        pontos = base.mark_circle(color="#0B7A66", size=40).encode(y="valor:Q")
        st.altair_chart((area + linha_ap + pontos).properties(height=240 if cel else 300), use_container_width=True)
        st.caption("Área: valor da carteira no fim de cada mês · linha tracejada: quanto você aplicou (aportes − resgates). "
                   "A distância entre as duas é o ganho.")
        ult, prim = ev.iloc[-1], ev[ev["valor"] > 0].iloc[0]
        meses_c = max(len(ev[ev["valor"] > 0]) - 1, 1)
        rend_tot = float(ev["rendimento_mes"].fillna(0).sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Rendeu no período", brl(rend_tot))
        c2.metric("Aportou no período", brl(float(ev["aporte_mes"].fillna(0).sum())))
        c3.metric("Rendimento médio/mês", brl(rend_tot / meses_c))
        with st.expander("Mês a mês"):
            tb = ev[["mes_lbl", "valor", "aporte_mes", "rendimento_mes", "ganho"]].copy()
            st.dataframe(em_reais(tb, "valor", "aporte_mes", "rendimento_mes", "ganho"), hide_index=True,
                         use_container_width=True,
                         column_config={"mes_lbl": st.column_config.DateColumn("Mês", format="MMM/YY"),
                                        "valor": col_rs("Valor no fim do mês"), "aporte_mes": col_rs("Aportes"),
                                        "rendimento_mes": col_rs("Rendimento"), "ganho": col_rs("Ganho acumulado")})

    st.markdown("<div class='ui-sec'>Aplicações</div>", unsafe_allow_html=True)
    if cel:
        with st.container(key="llista_inv"):
            for r in v.sort_values("valor_atual", ascending=False).itertuples():
                g = float(r.valor_atual) - float(r.aplicado or 0)
                pct = f" {r.ganho_pct:+.1%}".replace(".", ",") if pd.notna(r.ganho_pct) else ""
                sub = " · ".join(x for x in [r.instituicao, r.classe_n] if isinstance(x, str) and x)
                if _ui.linha(f"i_{r.id}", f"<div class='sel'>{_ui.selo(r.instituicao, r.instituicao, 42)}</div>",
                             r.nome, sub, valor=brl(r.valor_atual),
                             chip=f"{'+' if g >= 0 else '−'} {brl(abs(g))}{pct}", chip_cls="ok" if g >= 0 else "bad"):
                    _ui.rascunho_limpar(f"inv_{r.id}")
                    _ficha(r.id)
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
    if not cel:
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
if cel:
    if st.button("Nova aplicação", icon=":material/add:", type="primary", width="stretch", key="nova_inv"):
        _ui.rascunho_limpar("inv_nova")
        _ficha(None)
else:
    st.divider()
    op = {None: "➕ Nova aplicação"} | {r.id: f"Editar: {r.instituicao} · {r.nome}" for r in df.itertuples()}
    _cadastro(st.selectbox("Cadastro", list(op), format_func=op.get, key="inv_escolha"))

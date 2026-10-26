from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core import cartoes, repo, saldos
from core.fmt import brl, hoje, mes_label, mes_ref, somar_meses
from telas import _ui
from telas._comum import cartoes_kpi, e_celular, seletor_escopo, usuario

u = usuario()
cel = e_celular()
_ui.aviso_ok()
topo_esq, topo_dir = st.columns([3, 1], vertical_alignment="bottom")
with topo_esq:
    _ui.titulo("Painel", "🏠")
with topo_dir:
    escopo = seletor_escopo()

atual = mes_ref(hoje())
prox = somar_meses(atual, 1)
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

# --- saldos das contas (as minhas) -----------------------------------------------------------
contas = repo.contas(u)
caixa = contas[contas["tipo"].isin(saldos.TIPOS_CAIXA)]
saldo_contas = {}
for r in caixa.itertuples():
    try:
        saldo_contas[r.id] = saldos.saldo_em(u, r.id, hoje())
    except Exception:  # noqa: BLE001
        saldo_contas[r.id] = 0.0

cartoes_kpi([
    ("Saldo nas contas hoje", brl(sum(saldo_contas.values()))),
    (f"A pagar em {mes_label(atual)}", brl(soma(mes_atual, status="previsto"))),
    (f"Já pago em {mes_label(atual)}", brl(soma(mes_atual, status="pago"))),
    (f"Comprometido em {mes_label(prox)}", brl(soma(desp, mes_ref=prox))),
    ("Próximos 12 meses", brl(float(desp["valor"].sum()) if not desp.empty else 0)),
], titulo="Visão geral", icone="🏠", direita=mes_label(atual))

# --- minhas contas e cartões -------------------------------------------------------------------
cards = []
for r in caixa.itertuples():
    cards.append(f"<div class='ui-card'>{_ui.selo(r.nome, r.instituicao, 38)}"
                 f"<div style='min-width:0'><div class='n'>{_ui.esc(r.nome)}</div>"
                 f"<div class='s'>{brl(saldo_contas.get(r.id, 0))}</div></div></div>")
res = cartoes.resumo(u)
if not res.empty:
    info = contas.set_index("id")
    for r in res.sort_values("venc_atual", na_position="last").itertuples():
        if r.cartao_id not in info.index:
            continue
        c = info.loc[r.cartao_id]
        venc = f"fatura · vence {r.venc_atual:%d/%m}" if pd.notna(r.venc_atual) else "sem fatura aberta"
        cards.append(f"<div class='ui-card'>{_ui.selo(c['nome'], c['instituicao'], 38)}"
                     f"<div style='min-width:0'><div class='n'>{_ui.esc(c['nome'])}</div>"
                     f"<div class='s'>{brl(r.fatura_atual)}</div>"
                     f"<div class='n' style='font-size:.7rem'>{venc}</div></div></div>")
if cards:
    st.markdown("<div class='ui-sec'>Contas e cartões</div>", unsafe_allow_html=True)
    _ui.render(f"<div class='ui-grade'>{''.join(cards)}</div>")
    l1, l2, _ = st.columns([1, 1, 2] if not cel else [1, 1, 0.01])
    l1.page_link("telas/contas_correntes.py", label="Ver extratos", icon=":material/account_balance_wallet:")
    l2.page_link("telas/cartoes.py", label="Ver faturas", icon=":material/credit_card:")

if desp.empty:
    st.info("Nenhum lançamento ainda. Comece em **Novo lançamento** ou rode a migração da planilha.")
    st.stop()

# --- compromissos por mês ----------------------------------------------------------------------
st.markdown("<div class='ui-sec'>Compromissos por mês</div>", unsafe_allow_html=True)
with st.container(border=True):
    g = desp.groupby(["mes_ref", "categoria"], as_index=False)["valor"].sum()
    g["mes"] = g["mes_ref"].map(mes_label)
    ordem = [mes_label(m) for m in sorted(g["mes_ref"].unique())]
    graf = (alt.Chart(g).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(x=alt.X("mes:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0 if not cel else -45)),
                    y=alt.Y("sum(valor):Q", title=None, axis=alt.Axis(format=",.0f", gridOpacity=.25)),
                    color=alt.Color("categoria:N", title=None,
                                    legend=alt.Legend(orient="bottom", columns=2 if cel else 4, labelLimit=150)),
                    tooltip=[alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("categoria:N", title="Categoria"),
                             alt.Tooltip("valor:Q", title="R$", format=",.2f")])
            .properties(height=380 if cel else 320))
    st.altair_chart(graf, use_container_width=True)

# --- categorias do mês e vencimentos ---------------------------------------------------------
esq, dir_ = (st.container(), st.container()) if cel else st.columns(2)
with esq:
    st.markdown(f"<div class='ui-sec'>{mes_label(atual)} por categoria</div>", unsafe_allow_html=True)
    cat = (mes_atual.groupby("categoria", as_index=False)["valor"].sum().sort_values("valor", ascending=False))
    total_cat = float(cat["valor"].sum()) or 1.0
    linhas = []
    for r in cat.itertuples():
        pct = float(r.valor) / total_cat
        linhas.append(f"""<div class="ui-cat"><div class="t"><span>{_ui.esc(r.categoria or 'Sem categoria')}</span>
            <span class="v">{brl(r.valor)}</span></div>
            <div class="barra"><div style="width:{pct * 100:.0f}%"></div></div>
            <div class="p">{pct:.0%} do mês</div></div>""")
    _ui.render(f"<div class='ui-lista-html'>{''.join(linhas) or '<div class=ui-cat>Nada no mês.</div>'}</div>")

with dir_:
    st.markdown("<div class='ui-sec'>Vencendo nos próximos 15 dias</div>", unsafe_allow_html=True)
    lanc = repo.lancamentos(u, escopo, atual, prox)
    janela = pd.DataFrame()
    if not lanc.empty:
        lanc["data_vencimento"] = pd.to_datetime(lanc["data_vencimento"]).dt.date
        janela = lanc[(lanc["status"] == "previsto") & (lanc["tipo"] == "despesa")
                      & (lanc["data_vencimento"] >= hoje())
                      & (lanc["data_vencimento"] <= hoje() + timedelta(days=15))]
    if janela.empty:
        st.caption("Nada vencendo nos próximos 15 dias. 🎉")
    else:
        with st.container(key="uilista_venc"):
            for r in janela.itertuples():
                d = r.data_vencimento
                ic = f"<div style='font-size:.62rem;line-height:1;text-align:center'><b style='font-size:.95rem'>{d.day:02d}</b><br>{_ui.MESES[d.month - 1]}</div>"
                sub = " · ".join(x for x in [r.conta if isinstance(r.conta, str) else "", r.categoria
                                             if isinstance(r.categoria, str) else ""] if x)
                acao = (lambda i=r.id: _ui.editar_lancamento(u, i)) if r.meu else (lambda: None)
                _ui.linha_editavel(f"pv{r.Index}", _ui.item_html(ic, r.descricao, sub),
                                   _ui.valor_html(-float(r.valor)), acao)
        st.caption(f"Total: **{brl(janela['valor'].astype(float).sum())}**")

if escopo == "nos":
    outros = desp[~desp["meu"]]
    if not outros.empty:
        st.caption(f"Inclui {brl(outros['valor'].sum())} compartilhados pelo outro membro do casal "
                   "(itens marcados como “só o total” entram nas somas, mas não aparecem nas listas).")

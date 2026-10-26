from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import cartoes, repo
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref, somar_meses
from telas import _ui
from telas._comum import e_celular, usuario

u = usuario()
cel = e_celular()
_ui.css()
_ui.aviso_ok()
st.markdown("""<style>
@media (max-width: 640px) {
  .ui-grade-cc {display: flex !important; overflow-x: auto; gap: 12px; padding: 4px 2px 10px; scroll-snap-type: x mandatory;}
  .ui-grade-cc > .ui-cc {flex: 0 0 230px; scroll-snap-align: start;}
}
.ui-grade-cc {display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 16px; margin: 4px 0 18px;}
</style>""", unsafe_allow_html=True)

st.title("Cartões de crédito")

fat = cartoes.faturas(u)
if fat.empty:
    st.info("Nenhum lançamento em cartão ainda. Importe uma fatura ou lance uma compra no cartão.")
    st.page_link("telas/importar_fatura.py", label="Importar fatura", icon=":material/upload:")
    st.stop()
res = cartoes.resumo(u, fat)
contas = repo.contas(u, so_ativas=False)
info = contas.set_index("id")

# ---------------------------------------------------------------------------------------------
# período
# ---------------------------------------------------------------------------------------------
OPS = {"atual": "Esta fatura", "prox": "Próxima", "3m": "Próximos 3 meses", "custom": "Período…"}
periodo = st.segmented_control("Período", list(OPS), format_func=OPS.get, default="atual", key="cart_per",
                               label_visibility="collapsed") or "atual"
hj = hoje()
if periodo == "custom":
    c1, c2 = st.columns(2)
    p_ini = c1.date_input("Vencimentos de", hj.replace(day=1), format="DD/MM/YYYY", key="cart_ini")
    p_fim = c2.date_input("até", hj.replace(day=1) + timedelta(days=62), format="DD/MM/YYYY", key="cart_fim")


def no_periodo(cid) -> pd.DataFrame:
    """Faturas do cartão que entram no período escolhido."""
    g = fat[(fat["cartao_id"] == cid) & ~fat["paga"]].sort_values("mes_ref")
    futuras = g[g["vencimento"] >= hj]
    if periodo == "atual":
        return futuras.head(1)
    if periodo == "prox":
        return futuras.iloc[1:2]
    if periodo == "3m":
        lim = somar_meses(mes_ref(hj), 2)
        return futuras[futuras["mes_ref"] <= lim]
    g = fat[fat["cartao_id"] == cid]
    return g[(g["vencimento"] >= p_ini) & (g["vencimento"] <= p_fim)]


por_cartao = {r.cartao_id: no_periodo(r.cartao_id) for r in res.itertuples()}
total_periodo = sum(float(d["total"].sum()) for d in por_cartao.values())
venc_prox = [(d["vencimento"].min(), info.loc[c, "nome"]) for c, d in por_cartao.items() if not d.empty]
prox_txt = (f"próximo vencimento {min(venc_prox)[0]:%d/%m} ({min(venc_prox)[1]})" if venc_prox else "")
mes_ant = somar_meses(mes_ref(hj), -1)
pago_ant = cartoes.pago_no_mes(u, mes_ant)
limites = res["limite"].dropna()

_ui.hero("Todos os cartões", {"atual": "Faturas a vencer", "prox": "Próximas faturas",
                              "3m": "Faturas dos próximos 3 meses", "custom": "Faturas no período"}[periodo],
         brl(total_periodo),
         [("Próximas faturas", brl(res["fatura_prox"].sum())),
          ("Comprometido total", brl(res["comprometido"].sum())),
          (f"Pago em {mes_label(mes_ant)}", brl(pago_ant)),
          ("Limite disponível", brl(res["disponivel"].dropna().sum()) if not limites.empty else "Defina os limites")],
         direita=mes_label(mes_ref(hj)),
         sub=f"{len(res)} cartões" + (f" · {prox_txt}" if prox_txt else ""),
         selo_html=("<div class='ui-selo' style='width:40px;height:40px;background:rgba(255,255,255,.18)'>"
                    "<svg width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='#fff' stroke-width='2' "
                    "stroke-linecap='round' aria-hidden='true'><rect x='2' y='5' width='20' height='14' rx='2'></rect>"
                    "<line x1='2' y1='10' x2='22' y2='10'></line></svg></div>"))

if res["n_atrasadas"].sum():
    _ui.render(f"<div class='ui-aviso'>⏳ {int(res['n_atrasadas'].sum())} faturas vencidas ainda não marcadas como "
               f"pagas ({brl(res['atrasadas'].sum())}). Abra o cartão e marque como paga.</div>")

# ---------------------------------------------------------------------------------------------
# cartões
# ---------------------------------------------------------------------------------------------
ordem = res.sort_values("fatura_atual", ascending=False)
sel = st.session_state.get("cart_sel")
if sel not in set(res["cartao_id"]):
    sel = ordem.iloc[0]["cartao_id"]

tiles = []
for r in ordem.itertuples():
    c = info.loc[r.cartao_id]
    b = _ui.banco(c["nome"], c["instituicao"])
    d = por_cartao[r.cartao_id]
    val = float(d["total"].sum())
    venc = f"vence {d['vencimento'].min():%d/%m}" if not d.empty else "sem fatura no período"
    fin = c.get("finais_cartao")
    pill = f"final {str(fin).split(',')[0]}" if isinstance(fin, str) and fin and fin[0].isdigit() and len(fin) <= 9 \
        else (c["instituicao"] or "")
    barra = ""
    if pd.notna(r.limite) and r.limite:
        uso = max(0.0, min(1.0, r.comprometido / r.limite))
        barra = (f"<div class='l'>Limite usado {uso:.0%} · livre {brl(r.disponivel)}</div>"
                 f"<div class='barra'><div style='width:{uso * 100:.0f}%'></div></div>")
    tiles.append(f"""<div class="ui-cc{' sel' if r.cartao_id == sel else ''}"
        style="background:linear-gradient(135deg,{b['c1']} 0%,{b['c2']} 100%);--anel:{b['c1']}">
        <div class="cab">{_ui.selo(c['nome'], c['instituicao'], 40)}
          <div><div class="nome">{_ui.esc(c['nome'])}</div><div class="bco">{_ui.esc(c['instituicao'] or '')}</div></div>
          {_ui.bandeira(c['nome'], c['instituicao'], 18)}</div>
        <div><div class="l">Fatura · {venc}</div><div class="v">{brl(val)}</div></div>
        {barra}
        <div class="pe"><span>Próxima {brl(r.fatura_prox) if r.fatura_prox else '—'}</span>
          <span class="pill">{_ui.esc(pill)}</span></div></div>""")
_ui.render(f"<div class='ui-grade-cc'>{''.join(tiles)}</div>")

# ---------------------------------------------------------------------------------------------
# detalhe do cartão escolhido
# ---------------------------------------------------------------------------------------------
nomes = {r.cartao_id: info.loc[r.cartao_id, "nome"] for r in ordem.itertuples()}
sel = st.segmented_control("Ver fatura de", list(nomes), format_func=nomes.get, default=sel, key="cart_sel_w") or sel
st.session_state["cart_sel"] = sel
c = info.loc[sel]
b = _ui.banco(c["nome"], c["instituicao"])
f_cart = fat[fat["cartao_id"] == sel].sort_values("mes_ref")
r_cart = res[res["cartao_id"] == sel].iloc[0]

atual = mes_ref(hj)
janela = [m for m in f_cart["mes_ref"] if somar_meses(atual, -2) <= m <= somar_meses(atual, 4)] or list(f_cart["mes_ref"])
padrao = next((m for m, ven, pg in zip(f_cart["mes_ref"], f_cart["vencimento"], f_cart["paga"]) if not pg and ven >= hj),
              janela[-1])
if padrao not in janela:
    janela.append(padrao)
lbl = {m: (f"{mes_label(m)} · paga" if p else f"{mes_label(m)} · {brl(t)}")
       for m, t, p in zip(f_cart["mes_ref"], f_cart["total"], f_cart["paga"])}
mes = st.segmented_control("Fatura", janela, format_func=lbl.get, default=padrao, key=f"cart_mes_{sel}",
                           label_visibility="collapsed") or padrao
linha = f_cart[f_cart["mes_ref"] == mes].iloc[0]
fech = int(c["dia_fechamento"]) if pd.notna(c["dia_fechamento"]) else None
venc_d = linha["vencimento"]
fech_d = dia_no_mes(venc_d.year, venc_d.month, fech) if fech else venc_d - timedelta(days=7)
if fech_d > venc_d:
    fech_d = (venc_d.replace(day=1) - timedelta(days=1)).replace(day=min(fech or 1, 28))
it = cartoes.itens(u, sel, mes)
pagadora = info.loc[c["conta_pagamento_id"], "nome"] if pd.notna(c.get("conta_pagamento_id")) and \
    c["conta_pagamento_id"] in info.index else None
fin = c.get("finais_cartao")
sub = " · ".join(x for x in [c["instituicao"] or "",
                             f"final {str(fin).split(',')[0]}" if isinstance(fin, str) and fin[:1].isdigit() else "",
                             f"paga pela conta {pagadora}" if pagadora else ""] if x)
_ui.hero(c["nome"], f"Fatura de {mes_label(mes)}", brl(linha["total"]),
         [("Vence", f"{venc_d:%d/%m/%Y}"), ("Fecha" + ("" if fech else " (estimado)"), f"{fech_d:%d/%m}"),
          ("Lançamentos", str(len(it))), ("Situação", "✅ Paga" if linha["paga"] else "Em aberto")],
         c1=b["c1"], c2=b["c2"], selo_html=_ui.selo(c["nome"], c["instituicao"], 40), sub=sub,
         direita="", direita_html=_ui.bandeira(c["nome"], c["instituicao"], 22))

a1, a2, a3, a4 = st.columns([1.4, 1, 1, 1.6], vertical_alignment="center")
if not linha["paga"]:
    if a1.button("Marcar fatura como paga", icon=":material/check:", type="primary", use_container_width=True):
        cartoes.marcar_fatura(u, sel, mes, True)
        st.session_state["_ui_ok"] = f"Fatura de {mes_label(mes)} do {c['nome']} marcada como paga."
        st.rerun()
else:
    if a1.button("Reabrir fatura", icon=":material/undo:", use_container_width=True):
        cartoes.marcar_fatura(u, sel, mes, False)
        st.rerun()
a2.page_link("telas/importar_fatura.py", label="Importar fatura", icon=":material/upload:")
a3.page_link("telas/novo_lancamento.py", label="Lançar compra", icon=":material/add:")
busca = a4.text_input("Buscar", placeholder="🔎 Buscar na fatura", label_visibility="collapsed", key="cart_busca")

# faturas para onde uma compra pode ser movida (meses com fatura + próximos 6)
dia_v = int(c["dia_vencimento"]) if pd.notna(c["dia_vencimento"]) else venc_d.day
meses_mov = sorted(set(f_cart["mes_ref"]) | {somar_meses(atual, k) for k in range(-1, 7)})
fat_opcoes = [(f"{mes_label(m)} (vence {dia_no_mes(m // 100, m % 100, dia_v):%d/%m})",
               dia_no_mes(m // 100, m % 100, dia_v)) for m in meses_mov]
# a data que já está no lançamento precisa existir nas opções
datas = {d for _, d in fat_opcoes}
for d in set(pd.to_datetime(f_cart["venc_max"]).dt.date):
    if d not in datas:
        fat_opcoes.append((f"{mes_label(mes_ref(d))} (vence {d:%d/%m})", d))
fat_opcoes.sort(key=lambda x: x[1])

if it.empty:
    st.caption("Nenhum lançamento nesta fatura.")
else:
    it["valor_s"] = it.apply(lambda r: float(r.valor) if r.tipo == "receita" else -float(r.valor), axis=1)
    if busca.strip():
        bq = _ui.sem_acento(busca)
        it = it[it.apply(lambda r: bq in _ui.sem_acento(f"{r.descricao} {r.categoria}"), axis=1)]
    ICONE = {"Parcelas": "🧾", "Assinaturas": "🔁", "Compras": "🛍️"}
    for grupo in ["Parcelas", "Assinaturas", "Compras"]:
        g = it[it["grupo"] == grupo]
        if g.empty:
            continue
        _ui.render(f"<div class='ui-grupo'><span>{grupo} ({len(g)})</span>"
                   f"<span>{brl(-g['valor_s'].sum())}</span></div>")
        with st.container(key=f"uilista_{grupo}"):
            for r in g.itertuples():
                if pd.notna(r.parcela_num):
                    tag = f"{int(r.parcela_num)}/{int(r.parcela_total)}"
                elif grupo == "Parcelas" and pd.notna(r.ultimo_mes):
                    tag = f"até {mes_label(int(r.ultimo_mes))}"
                else:
                    tag = "mensal" if grupo == "Assinaturas" else ""
                cat = r.categoria if pd.isna(r.categoria_pai) or not r.categoria_pai else f"{r.categoria_pai} › {r.categoria}"
                sub = " · ".join(x for x in [cat, f"{r.data_compra:%d/%m}" if pd.notna(r.data_compra) else ""] if x)
                _ui.linha_editavel(str(r.id), _ui.item_html(ICONE[grupo], r.descricao, sub, tag),
                                   _ui.valor_html(r.valor_s),
                                   lambda lid=r.id: _ui.editar_lancamento(u, lid, fat_opcoes))

if pd.isna(r_cart["limite"]) or not r_cart["limite"]:
    st.caption("💡 Cadastre o limite deste cartão em **Contas e cartões** para ver o uso do limite no card.")

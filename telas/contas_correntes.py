import html
import re
import unicodedata
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core import repo, saldos
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref, somar_meses
from telas._comum import e_celular, usuario

u = usuario()
cel = e_celular()

if msg := st.session_state.pop("_ok_cc", None):
    st.success(msg, icon=":material/check_circle:")

contas = repo.contas(u)
caixa = contas[contas["tipo"].isin(saldos.TIPOS_CAIXA)]
if caixa.empty:
    st.title("Contas correntes")
    st.info("Cadastre suas contas correntes em **Contas e cartões** (tipo *Conta corrente*).")
    st.stop()


# ---------------------------------------------------------------------------------------------
# identidade visual por banco (cor + iniciais; sem logos oficiais)
# ---------------------------------------------------------------------------------------------
def _sem_acento(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


BANCOS = [  # (palavra-chave, sigla, cor principal, cor secundária do degradê)
    ("itau", "IT", "#EC7000", "#F59B3D"), ("nubank", "NU", "#820AD1", "#A64BE8"), ("nu ", "NU", "#820AD1", "#A64BE8"),
    ("inter", "IN", "#FF7A00", "#FFA24D"), ("bradesco", "BR", "#CC092F", "#E5485F"),
    ("santander", "SA", "#EC0000", "#F25050"), ("caixa", "CX", "#005CA9", "#3A86C8"),
    ("brasil", "BB", "#0038A8", "#3F6FD1"), ("c6", "C6", "#242424", "#4A4A4A"), ("btg", "BT", "#0B2D5B", "#2C5491"),
    ("mercado pago", "MP", "#009EE3", "#4CC0F0"), ("picpay", "PP", "#11C76F", "#4ED993"), ("xp", "XP", "#1A1A1A", "#444"),
    ("sicoob", "SC", "#00A091", "#3BBFB2"), ("sicredi", "SI", "#3FA110", "#6CC23F"),
]


def visual(nome, inst=None):
    t = _sem_acento(f"{nome} {inst or ''} ")
    for chave, sigla, c1, c2 in BANCOS:
        if chave in t:
            return sigla, c1, c2
    sig = "".join(p[0] for p in str(nome).split()[:2]).upper() or "$"
    return sig, "#2F3B52", "#56637E"


ICONES = [  # (trecho da categoria/descrição, emoji)
    ("salario", "💼"), ("rendimento", "📈"), ("receita", "💰"), ("aluguel", "🏠"), ("moradia", "🏠"),
    ("telecom", "📶"), ("imovel", "🏗️"), ("obra", "🏗️"), ("incorporadora", "🏗️"), ("supermercado", "🛒"),
    ("delivery", "🛵"), ("restaurante", "🍽️"), ("padaria", "🥐"), ("alimentacao", "🍽️"), ("farmacia", "💊"),
    ("saude", "🩺"), ("educacao", "🎓"), ("pos-graduacao", "🎓"), ("transporte", "🚗"), ("seguro", "🛡️"),
    ("estacionamento", "🅿️"), ("combustivel", "⛽"), ("iof", "🏦"), ("juros", "🏦"), ("financeiro", "🏦"),
    ("aplicacao", "📊"), ("investimento", "📊"), ("lazer", "🎟️"), ("entretenimento", "🎟️"), ("viagem", "✈️"),
    ("assinatura", "🔁"), ("compras", "🛍️"), ("cuidados", "💇"),
]


def icone(r):
    if r["fonte"] == "fatura" or str(r["descricao"]).lower().startswith("pagamento de fatura"):
        return "💳"
    if r["fonte"] == "ajuste":
        return "🔧"
    if r["fonte"] == "entrada_transf" or "transfer" in _sem_acento(r["descricao"]) or "resgate" in _sem_acento(r["descricao"]):
        return "🔁"
    t = _sem_acento(f"{r['categoria']} {r['descricao']}")
    for chave, e in ICONES:
        if chave in t:
            return e
    return "💸" if r["valor"] < 0 else "💰"


def _html(s: str):
    """Markdown do Streamlit trata linha indentada como código: junta o HTML numa linha só."""
    st.markdown(re.sub(r"\n\s*", "", s), unsafe_allow_html=True)


DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

st.markdown("""
<style>
.cc-hero {border-radius: 18px; padding: 22px 24px; color: #fff; box-shadow: 0 10px 30px rgba(0,0,0,.18);
          margin: 6px 0 14px;}
.cc-hero .topo {display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 1.05rem;}
.cc-badge {width: 38px; height: 38px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
           font-weight: 800; font-size: .85rem; letter-spacing: .5px; color: #fff; flex-shrink: 0;}
.cc-hero .cc-badge {background: rgba(255,255,255,.22); box-shadow: inset 0 0 0 1px rgba(255,255,255,.35);}
.cc-hero .rot {opacity: .8; font-size: .82rem; margin-top: 16px;}
.cc-hero .saldo {font-size: 2.3rem; font-weight: 800; letter-spacing: -.5px; line-height: 1.15;}
.cc-hero .linha {display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; margin-top: 18px;}
.cc-hero .mini {background: rgba(255,255,255,.14); border-radius: 12px; padding: 10px 12px;}
.cc-hero .mini .l {font-size: .74rem; opacity: .85;}
.cc-hero .mini .v {font-size: 1.02rem; font-weight: 700; margin-top: 2px; white-space: nowrap;}
.cc-contas {display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; margin-bottom: 14px;}
.cc-card {border-radius: 14px; padding: 12px 14px; background: rgba(128,128,128,.06);
          box-shadow: 0 2px 12px rgba(0,0,0,.08); border: 1px solid rgba(128,128,128,.12);
          display: flex; gap: 10px; align-items: center;}
.cc-card .n {font-size: .8rem; opacity: .7;} .cc-card .s {font-weight: 700; font-size: 1.05rem;}
.cc-aviso {border-radius: 12px; padding: 9px 12px; font-size: .85rem; margin: 4px 0 10px;
           background: rgba(236,112,0,.09); border: 1px solid rgba(236,112,0,.25);}
.cc-dia {display: flex; justify-content: space-between; align-items: baseline; margin: 18px 4px 6px;
         font-size: .8rem; text-transform: uppercase; letter-spacing: .6px; opacity: .65; font-weight: 600;}
.cc-lista {border-radius: 16px; background: rgba(128,128,128,.05); box-shadow: 0 2px 12px rgba(0,0,0,.07);
           border: 1px solid rgba(128,128,128,.12); overflow: hidden;}
.cc-item {display: flex; align-items: center; gap: 12px; padding: 11px 14px;
          border-bottom: 1px solid rgba(128,128,128,.10);}
.cc-item:last-child {border-bottom: none;}
.cc-ic {width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
        font-size: 1.05rem; background: rgba(128,128,128,.12); flex-shrink: 0;}
.cc-tx {flex: 1; min-width: 0;}
.cc-tx .t {font-weight: 600; font-size: .93rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.cc-tx .s {font-size: .76rem; opacity: .62; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.cc-tag {display: inline-block; font-size: .66rem; padding: 1px 7px; border-radius: 99px; margin-left: 6px;
         font-weight: 700; vertical-align: 1px;}
.cc-tag.prev {background: rgba(128,128,128,.18);} .cc-tag.aj {background: rgba(236,112,0,.18);}
.cc-val {font-weight: 700; font-size: .95rem; white-space: nowrap; text-align: right;}
.cc-val.pos {color: #12a150;} .cc-val.neg {color: #e5484d;}
.cc-item.previsto {opacity: .62;}
.cc-sec {font-weight: 700; font-size: 1.1rem; margin: 18px 0 2px;}
@media (max-width: 640px) {
  .cc-hero {padding: 18px 16px; border-radius: 16px;}
  .cc-hero .saldo {font-size: 1.9rem;}
  .cc-hero .linha {grid-template-columns: repeat(2, minmax(0,1fr));}
  .cc-contas {grid-template-columns: repeat(2, minmax(0,1fr));}
  .cc-item {padding: 10px 11px; gap: 10px;}
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------------------------
# seleção
# ---------------------------------------------------------------------------------------------
nomes = dict(zip(caixa["id"].astype(str), caixa["nome"]))
inst = dict(zip(caixa["id"].astype(str), caixa["instituicao"]))
op = ["todas"] + list(nomes)
st.title("Contas correntes")
c1, c2 = st.columns([2.2, 1], vertical_alignment="bottom")
escolha = c1.segmented_control("Conta", op, default=st.session_state.get("_cc_conta", "todas"), key="cc_conta",
                               format_func=lambda k: "🏦 Todas" if k == "todas" else nomes[k],
                               label_visibility="collapsed") or "todas"
st.session_state["_cc_conta"] = escolha
atual = mes_ref(hoje())
meses = [somar_meses(atual, k) for k in range(-12, 13)]
mes = c2.selectbox("Mês", meses, index=12, format_func=mes_label, key="cc_mes", label_visibility="collapsed")
ids = list(caixa["id"]) if escolha == "todas" else [next(i for i in caixa["id"] if str(i) == escolha)]

ini = date(mes // 100, mes % 100, 1)
fim = dia_no_mes(mes // 100, mes % 100, 31)
s_ini, ext = saldos.extrato(u, ids, ini, fim)
mov_real = ext[ext["fonte"] != "ajuste"] if not ext.empty else ext
entradas = float(mov_real.loc[mov_real["valor"] > 0, "valor"].sum()) if not ext.empty else 0.0
saidas = float(-mov_real.loc[mov_real["valor"] < 0, "valor"].sum()) if not ext.empty else 0.0
ajustes = float(ext.loc[ext["fonte"] == "ajuste", "valor"].sum()) if not ext.empty else 0.0
s_fim = s_ini + entradas - saidas + ajustes
mes_corrente = ini <= hoje() <= fim
s_hoje = s_ini + (float(ext.loc[ext["data"] <= hoje(), "valor"].sum()) if not ext.empty else 0.0) if mes_corrente \
    else s_fim

# ---------------------------------------------------------------------------------------------
# cartão principal
# ---------------------------------------------------------------------------------------------
if escolha == "todas":
    sigla, cor1, cor2, titulo = "Σ", "#1F2A44", "#3B4C75", "Todas as contas"
else:
    sigla, cor1, cor2 = visual(nomes[escolha], inst.get(escolha))
    titulo = nomes[escolha]
rot_saldo = "Saldo hoje" if mes_corrente else f"Saldo em {fim:%d/%m}"
_html(f"""
<div class="cc-hero" style="background: linear-gradient(135deg, {cor1} 0%, {cor2} 100%);">
  <div class="topo"><div class="cc-badge">{sigla}</div>{html.escape(titulo)}
     <span style="margin-left:auto;opacity:.8;font-weight:500;font-size:.85rem">{mes_label(mes)}</span></div>
  <div class="rot">{rot_saldo}</div>
  <div class="saldo">{brl(s_hoje)}</div>
  <div class="linha">
    <div class="mini"><div class="l">Início do mês</div><div class="v">{brl(s_ini)}</div></div>
    <div class="mini"><div class="l">↑ Entradas</div><div class="v">{brl(entradas)}</div></div>
    <div class="mini"><div class="l">↓ Saídas</div><div class="v">{brl(saidas)}</div></div>
    <div class="mini"><div class="l">Previsto {fim:%d/%m}</div><div class="v">{brl(s_fim)}</div></div>
  </div>
</div>""")

if escolha == "todas" and len(caixa) > 1:
    cards = []
    for cid, nome in nomes.items():
        sg, c1_, c2_ = visual(nome, inst.get(cid))
        sh = saldos.saldo_em(u, next(i for i in caixa["id"] if str(i) == cid), min(hoje(), fim))
        cards.append(f"""<div class="cc-card"><div class="cc-badge" style="background:linear-gradient(135deg,{c1_},{c2_})">{sg}</div>
            <div><div class="n">{html.escape(nome)}</div><div class="s">{brl(sh)}</div></div></div>""")
    _html(f"<div class='cc-contas'>{''.join(cards)}</div>")

avisos = []
if abs(ajustes) > 0.004:
    avisos.append(f"🔧 Ajuste de saldo no mês: <b>{brl(ajustes)}</b> — diferença entre o que o app calculava e o saldo "
                  "informado (algo ainda não lançado).")
venc = saldos.vencidos_sem_confirmar(u, ids)
if not venc.empty:
    avisos.append(f"⏳ {len(venc)} lançamentos vencidos ainda como <i>previstos</i> ({brl(venc['valor'].sum())}).")
for a in avisos:
    st.markdown(f"<div class='cc-aviso'>{a}</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------------------------
# projeção
# ---------------------------------------------------------------------------------------------
proj = saldos.projecao_diaria(u, ids, hoje(), 90)
if not proj.empty:
    with st.container(border=True):
        minimo = proj.loc[proj["saldo"].idxmin()]
        st.markdown(f"**📈 Próximos 90 dias** &nbsp;·&nbsp; menor saldo **{brl(minimo['saldo'])}** em "
                    f"{minimo['data']:%d/%m}")
        base = alt.Chart(proj).encode(x=alt.X("data:T", title=None, axis=alt.Axis(format="%d/%m", grid=False)))
        area = base.mark_area(opacity=.18, color=cor1, interpolate="step-after").encode(
            y=alt.Y("saldo:Q", title=None, axis=alt.Axis(format=",.0f", gridOpacity=.25)))
        linha = base.mark_line(color=cor1, strokeWidth=2.2, interpolate="step-after").encode(
            y="saldo:Q", tooltip=[alt.Tooltip("data:T", title="Dia", format="%d/%m/%Y"),
                                  alt.Tooltip("saldo:Q", title="Saldo", format=",.2f")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[4, 4], color="#e5484d").encode(y="y:Q")
        st.altair_chart((area + linha + zero).properties(height=190 if cel else 220), use_container_width=True)
        if minimo["saldo"] < 0:
            st.caption("Fica negativo nesse período — cadastre o salário em **Contas fixas** (se ainda não estiver) "
                       "ou planeje um resgate.")

# ---------------------------------------------------------------------------------------------
# extrato
# ---------------------------------------------------------------------------------------------
st.markdown(f"<div class='cc-sec'>Extrato · {mes_label(mes)}</div>", unsafe_allow_html=True)
f1, f2 = st.columns([1.3, 1], vertical_alignment="bottom")
filtro = f1.segmented_control("Filtro", ["tudo", "entradas", "saidas"], default="tudo", key="cc_filtro",
                              format_func={"tudo": "Tudo", "entradas": "↑ Entradas", "saidas": "↓ Saídas"}.get,
                              label_visibility="collapsed") or "tudo"
busca = f2.text_input("Buscar", placeholder="🔎 Buscar no extrato", label_visibility="collapsed", key="cc_busca")

if ext.empty:
    st.caption("Nenhum movimento neste mês.")
else:
    v = ext.copy()
    v["icone"] = v.apply(icone, axis=1)
    v["conta_nome"] = v["conta"].astype(str).map(nomes)
    if filtro == "entradas":
        v = v[v["valor"] > 0]
    elif filtro == "saidas":
        v = v[v["valor"] < 0]
    if busca.strip():
        b = _sem_acento(busca)
        v = v[v.apply(lambda r: b in _sem_acento(f"{r['descricao']} {r['categoria']}"), axis=1)]
    saldo_dia = ext.groupby("data")["saldo"].last()
    partes = []
    for d in sorted(v["data"].unique(), reverse=True):
        dia = v[v["data"] == d]
        rot = "Hoje" if d == hoje() else ("Ontem" if d == hoje() - timedelta(days=1) else
                                          f"{DIAS[d.weekday()]}, {d.day:02d} {MESES[d.month - 1]}")
        itens = []
        for r in dia.sort_values("valor").to_dict("records"):
            prev = r["status"] == "previsto" and r["fonte"] != "ajuste"
            tag = "<span class='cc-tag prev'>previsto</span>" if prev else (
                "<span class='cc-tag aj'>ajuste</span>" if r["fonte"] == "ajuste" else "")
            cat = str(r["categoria"]) if r["categoria"] not in (None, "—", "Ajuste") else ""
            if not cat and r["icone"] == "🔁":
                cat = "Transferência"
            elif not cat and r["icone"] == "💳":
                cat = "Cartão de crédito"
            sub = [cat]
            if escolha == "todas" and len(caixa) > 1 and r["conta_nome"]:
                sub.append(r["conta_nome"])
            sub = " · ".join(s for s in sub if s) or "&nbsp;"
            cls = "pos" if r["valor"] > 0 else "neg"
            sinal = "+ " if r["valor"] > 0 else "− "
            itens.append(f"""<div class="cc-item{' previsto' if prev else ''}"><div class="cc-ic">{r['icone']}</div>
                <div class="cc-tx"><div class="t">{html.escape(str(r['descricao']))}{tag}</div>
                <div class="s">{html.escape(sub) if sub != '&nbsp;' else sub}</div></div>
                <div class="cc-val {cls}">{sinal}{brl(abs(r['valor']))}</div></div>""")
        partes.append(f"""<div class="cc-dia"><span>{rot}</span><span>saldo {brl(saldo_dia.get(d, 0))}</span></div>
            <div class="cc-lista">{''.join(itens)}</div>""")
    if partes:
        _html("".join(partes))
    else:
        st.caption("Nada encontrado com esse filtro.")
    st.markdown(f"<div class='cc-dia'><span>Saldo anterior ({ini - timedelta(days=1):%d/%m})</span>"
                f"<span>{brl(s_ini)}</span></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------------------------
# ajustes
# ---------------------------------------------------------------------------------------------
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

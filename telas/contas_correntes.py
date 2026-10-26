from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core import repo, saldos
from core.fmt import brl, hoje
from telas import _ui
from telas._comum import e_celular, opcoes_categoria, usuario

u = usuario()
cel = e_celular()
_ui.css()
_ui.aviso_ok()

contas = repo.contas(u)
caixa = contas[contas["tipo"].isin(saldos.TIPOS_CAIXA)]
if caixa.empty:
    _ui.titulo("Contas correntes", "🏦")
    st.info("Cadastre suas contas correntes em **Contas e cartões** (tipo *Conta corrente*).")
    st.stop()

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
    d = _ui.sem_acento(r["descricao"])
    if r["fonte"] == "fatura" or d.startswith("pagamento de fatura"):
        return "💳"
    if r["fonte"] == "ajuste":
        return "🔧"
    if r["fonte"] == "entrada_transf" or "transfer" in d or "resgate" in d:
        return "🔁"
    t = _ui.sem_acento(f"{r['categoria']} {r['descricao']}")
    for chave, e in ICONES:
        if chave in t:
            return e
    return "💸" if r["valor"] < 0 else "💰"


DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# ---------------------------------------------------------------------------------------------
# janelas
# ---------------------------------------------------------------------------------------------
@st.dialog("Ajuste de saldo")
def editar_ajuste(conta_id, d, ajuste: float, nome_conta: str):
    informado = saldos.saldo_informado(conta_id, d)
    if informado is None:
        st.warning("Esse saldo informado não existe mais.")
        return
    calculado = informado - ajuste
    st.markdown(f"<div class='ui-aviso'>Em <b>{d:%d/%m/%Y}</b> você informou <b>{brl(informado)}</b> no "
                f"{_ui.esc(nome_conta)}; pelos lançamentos o app chegava a <b>{brl(calculado)}</b>. "
                f"A diferença de <b>{brl(ajuste)}</b> é algo que ainda não foi lançado.</div>", unsafe_allow_html=True)
    acao = st.segmented_control("O que fazer", ["lancar", "corrigir", "remover"], default="lancar",
                                format_func={"lancar": "Lançar a diferença", "corrigir": "Corrigir saldo",
                                             "remover": "Apagar saldo"}.get) or "lancar"
    if acao == "lancar":
        tipo = "receita" if ajuste > 0 else "despesa"
        st.caption(f"Cria uma {'entrada' if ajuste > 0 else 'saída'} de {brl(abs(ajuste))} em {d:%d/%m} "
                   "nesta conta — o ajuste some.")
        desc = st.text_input("Descrição", placeholder="Ex.: Pix para fulano, tarifa, compra no débito…")
        op = {None: "— sem categoria"} | opcoes_categoria(repo.categorias(u), tipo)
        cat = st.selectbox("Categoria", list(op), format_func=op.get)
        valor = st.number_input("Valor (R$)", 0.0, value=round(abs(ajuste), 2), step=1.0, format="%.2f",
                                help="Se lançar menos que a diferença, o resto continua como ajuste.")
        if st.button("Lançar", type="primary", use_container_width=True, disabled=not desc.strip()):
            repo.inserir_lancamentos(u, [dict(conta_id=conta_id, categoria_id=cat, tipo=tipo, descricao=desc.strip(),
                                              valor=valor, data_compra=d, data_vencimento=d, status="pago",
                                              forma_pagamento="Conta", visibilidade=None, origem="manual")])
            st.session_state["_ui_ok"] = "Diferença lançada."
            st.rerun()
    elif acao == "corrigir":
        st.caption("Digitou errado? Troque o saldo que aparece no app do banco neste dia.")
        novo = st.number_input("Saldo no fim do dia (R$)", value=float(informado), step=10.0, format="%.2f")
        if st.button("Salvar saldo", type="primary", use_container_width=True):
            saldos.informar_saldo(conta_id, d, novo)
            st.session_state["_ui_ok"] = "Saldo corrigido."
            st.rerun()
    else:
        st.caption("Remove esse saldo informado. O app volta a calcular só pelos lançamentos "
                   "(e pelos outros saldos informados).")
        if st.button("Apagar saldo informado", type="primary", use_container_width=True):
            saldos.remover_saldo(conta_id, d)
            st.session_state["_ui_ok"] = "Saldo informado apagado."
            st.rerun()


@st.dialog("Fatura do cartão")
def ver_fatura(desc: str, valor: float):
    st.write(f"**{desc}** · {brl(abs(valor))}")
    st.caption("Esta linha é a soma das compras do cartão. Para mudar, edite as compras ou marque a fatura "
               "como paga na tela de cartões.")
    st.page_link("telas/cartoes.py", label="Abrir Cartões de crédito", icon=":material/credit_card:")


# ---------------------------------------------------------------------------------------------
# seleção
# ---------------------------------------------------------------------------------------------
nomes = dict(zip(caixa["id"].astype(str), caixa["nome"]))
inst = dict(zip(caixa["id"].astype(str), caixa["instituicao"]))
_ui.titulo("Contas correntes", "🏦")
escolha = st.segmented_control("Conta", ["todas"] + list(nomes), default=st.session_state.get("_cc_conta", "todas"),
                               key="cc_conta", format_func=lambda k: "Todas" if k == "todas" else nomes[k],
                               label_visibility="collapsed") or "todas"
st.session_state["_cc_conta"] = escolha
ini, fim, rot_per = _ui.periodo("cc")
ids = list(caixa["id"]) if escolha == "todas" else [next(i for i in caixa["id"] if str(i) == escolha)]

s_ini, ext = saldos.extrato(u, ids, ini, fim)
mov_real = ext[ext["fonte"] != "ajuste"] if not ext.empty else ext
entradas = float(mov_real.loc[mov_real["valor"] > 0, "valor"].sum()) if not ext.empty else 0.0
saidas = float(-mov_real.loc[mov_real["valor"] < 0, "valor"].sum()) if not ext.empty else 0.0
ajustes = float(ext.loc[ext["fonte"] == "ajuste", "valor"].sum()) if not ext.empty else 0.0
s_fim = s_ini + entradas - saidas + ajustes
tem_hoje = ini <= hoje() <= fim
s_hoje = s_ini + (float(ext.loc[ext["data"] <= hoje(), "valor"].sum()) if not ext.empty else 0.0) if tem_hoje \
    else s_fim

# ---------------------------------------------------------------------------------------------
# card principal
# ---------------------------------------------------------------------------------------------
if escolha == "todas":
    c1, c2, selo, titulo = "#1F2A44", "#3B4C75", "", "Todas as contas"
else:
    b = _ui.banco(nomes[escolha], inst.get(escolha), dict(zip(caixa["id"].astype(str), caixa["cor"])).get(escolha))
    c1, c2, titulo = b["c1"], b["c2"], nomes[escolha]
    selo = _ui.selo(nomes[escolha], inst.get(escolha), 40)
fim_rot = "Previsto" if fim > hoje() else "Saldo"
_ui.hero(titulo, "Saldo hoje" if tem_hoje else f"Saldo em {fim:%d/%m/%Y}", brl(s_hoje),
         [(f"Saldo em {ini - timedelta(days=1):%d/%m}", brl(s_ini)), ("↑ Entradas", brl(entradas)),
          ("↓ Saídas", brl(saidas)), (f"{fim_rot} {fim:%d/%m}", brl(s_fim))],
         c1, c2, selo, direita=rot_per)

if escolha == "todas" and len(caixa) > 1:
    cards = []
    for cid, nome in nomes.items():
        sh = saldos.saldo_em(u, next(i for i in caixa["id"] if str(i) == cid), min(hoje(), fim))
        cards.append(f"<div class='ui-card'>{_ui.selo(nome, inst.get(cid), 38)}"
                     f"<div><div class='n'>{_ui.esc(nome)}</div><div class='s'>{brl(sh)}</div></div></div>")
    _ui.render(f"<div class='ui-grade'>{''.join(cards)}</div>")

if abs(ajustes) > 0.004:
    st.markdown(f"<div class='ui-aviso'>🔧 Ajustes de saldo no período: <b>{brl(ajustes)}</b> — diferença entre o "
                "que o app calculava e o saldo informado. Toque no ✏️ da linha de ajuste para lançar, corrigir "
                "ou apagar.</div>", unsafe_allow_html=True)
venc = saldos.vencidos_sem_confirmar(u, ids)
if not venc.empty:
    st.markdown(f"<div class='ui-aviso'>⏳ {len(venc)} lançamentos vencidos ainda como <i>previstos</i> "
                f"({brl(venc['valor'].sum())}).</div>", unsafe_allow_html=True)

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
        area = base.mark_area(opacity=.18, color=c1, interpolate="step-after").encode(
            y=alt.Y("saldo:Q", title=None, axis=alt.Axis(format=",.0f", gridOpacity=.25)))
        linha = base.mark_line(color=c1, strokeWidth=2.2, interpolate="step-after").encode(
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
st.markdown(f"<div class='ui-sec'>Extrato · {_ui.esc(rot_per)}</div>", unsafe_allow_html=True)
f1, f2 = st.columns([1.3, 1], vertical_alignment="bottom")
filtro = f1.segmented_control("Filtro", ["tudo", "entradas", "saidas"], default="tudo", key="cc_filtro",
                              format_func={"tudo": "Tudo", "entradas": "↑ Entradas", "saidas": "↓ Saídas"}.get,
                              label_visibility="collapsed") or "tudo"
busca = f2.text_input("Buscar", placeholder="🔎 Buscar no extrato", label_visibility="collapsed", key="cc_busca")

if ext.empty:
    st.caption("Nenhum movimento no período.")
else:
    v = ext.copy()
    v["icone"] = v.apply(icone, axis=1)
    v["conta_nome"] = v["conta"].astype(str).map(nomes)
    if filtro == "entradas":
        v = v[v["valor"] > 0]
    elif filtro == "saidas":
        v = v[v["valor"] < 0]
    if busca.strip():
        bq = _ui.sem_acento(busca)
        v = v[v.apply(lambda r: bq in _ui.sem_acento(f"{r['descricao']} {r['categoria']}"), axis=1)]
    saldo_dia = ext.groupby("data")["saldo"].last()
    if v.empty:
        st.caption("Nada encontrado com esse filtro.")
    for d in sorted(v["data"].unique(), reverse=True):
        dia = v[v["data"] == d].sort_values("valor")
        rot = "Hoje" if d == hoje() else ("Ontem" if d == hoje() - timedelta(days=1) else
                                          f"{DIAS[d.weekday()]}, {d.day:02d} {MESES[d.month - 1]}")
        _ui.render(f"<div class='ui-grupo'><span>{rot}</span><span>saldo {brl(saldo_dia.get(d, 0))}</span></div>")
        with st.container(key=f"uilista_{d:%Y%m%d}"):
            for i, r in dia.iterrows():
                prev = r["status"] == "previsto" and r["fonte"] != "ajuste"
                tag, tag_cls = ("previsto", "") if prev else (("ajuste", "aj") if r["fonte"] == "ajuste" else ("", ""))
                cat = str(r["categoria"]) if r["categoria"] not in (None, "—", "Ajuste") else ""
                if not cat and r["icone"] == "🔁":
                    cat = "Transferência"
                elif not cat and r["icone"] == "💳":
                    cat = "Cartão de crédito"
                sub = [cat]
                if escolha == "todas" and len(caixa) > 1 and r["conta_nome"]:
                    sub.append(r["conta_nome"])
                esq = _ui.item_html(r["icone"], r["descricao"], " · ".join(s for s in sub if s), tag, tag_cls, prev)
                if r["fonte"] == "ajuste":
                    acao = (lambda r=r: editar_ajuste(r["conta"], r["data"], float(r["valor"]),
                                                      nomes.get(str(r["conta"]), "")))
                elif r["fonte"] == "fatura" or pd.isna(r["id"]):
                    acao = (lambda r=r: ver_fatura(r["descricao"], r["valor"]))
                else:
                    acao = (lambda r=r: _ui.editar_lancamento(u, r["id"]))
                _ui.linha_editavel(f"cc{i}", esq, _ui.valor_html(float(r["valor"]), prev), acao)
    _ui.render(f"<div class='ui-grupo'><span>Saldo anterior ({ini - timedelta(days=1):%d/%m})</span>"
               f"<span>{brl(s_ini)}</span></div>")

# ---------------------------------------------------------------------------------------------
# saldo real e conta principal
# ---------------------------------------------------------------------------------------------
st.divider()
c1_, c2_ = st.columns(2)
with c1_.expander("🔧 Informar saldo real"):
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
            st.session_state["_ui_ok"] = (f"Saldo salvo. O app calculava {brl(antes)}; diferença de "
                                          f"{brl(val - antes)} entra como ajuste.")
            st.rerun()

with c2_.expander("⚙️ Lançamentos sem conta"):
    st.caption("Boletos e pix lançados sem conta (ex.: aluguel, parcelas do apê) saem de qual conta no fluxo?")
    princ = saldos.conta_principal(u)
    opp = {None: "— nenhuma (ficam de fora do fluxo)"} | {str(r.id): r.nome for r in caixa.itertuples()}
    novo = st.selectbox("Conta principal", list(opp), format_func=opp.get,
                        index=list(opp).index(princ) if princ in opp else 0, key="cc_princ")
    if novo != princ and st.button("Salvar conta principal"):
        saldos.definir_conta_principal(u, novo)
        st.session_state["_ui_ok"] = "Conta principal salva."
        st.rerun()

sem_pag = contas[(contas["tipo"] == "cartao_credito") & contas["conta_pagamento_id"].isna()]
if not sem_pag.empty:
    st.caption(f"💳 {len(sem_pag)} cartões sem conta pagadora definida — as faturas deles não entram no fluxo. "
               "Defina em **Contas e cartões** (campo *Fatura paga pela conta*).")

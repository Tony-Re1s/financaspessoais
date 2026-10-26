"""Padrão visual do app (aprovado no mock de Cartões): card principal na cor do banco, cards com sombra,
listas agrupadas, valores verde/vermelho, logos dos bancos, filtro de período e edição em janela.

Logos: repositório público Tgentil/Bancos-em-SVG (propriedade dos respectivos bancos), em static/logos/.
"""
from __future__ import annotations

import base64
import calendar
import html
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from core.fmt import brl, hoje

LOGOS = Path(__file__).resolve().parent.parent / "static" / "logos"


def sem_acento(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render(s: str):
    """Markdown do Streamlit trata linha indentada como código: junta o HTML numa linha só."""
    st.markdown(re.sub(r"\n\s*", "", s), unsafe_allow_html=True)


# ---------------------------------------------------------------------------------------------
# bancos: logo + cores do degradê (escuras o bastante para texto branco)
# ---------------------------------------------------------------------------------------------
BANCOS = [  # (trecho do nome/instituição, arquivo do logo, cor 1, cor 2)
    ("ultravioleta", "nubank", "#1E0636", "#4A1782"), ("nubank black", "nubank", "#1E0636", "#4A1782"),
    ("latam", "itau", "#B3123F", "#E0245E"), ("uniclass", "itau", "#17213F", "#34416B"),
    ("visa infinity", "itau", "#17213F", "#34416B"), ("personnalite", "itau", "#17213F", "#34416B"),
    ("itau", "itau", "#C25700", "#E57A12"), ("nubank", "nubank", "#6A0BB0", "#9A3EE0"),
    ("nu pag", "nubank", "#6A0BB0", "#9A3EE0"), ("inter", "inter", "#A8400A", "#D2600F"),
    ("mercado pago", "mercadopago", "#00609F", "#0A86D1"), ("picpay", "picpay", "#0B7A43", "#14A35C"),
    ("c6", "c6", "#1E1E1E", "#454545"), ("bradesco", "bradesco", "#A30A28", "#CC2A47"),
    ("santander", "santander", "#B30000", "#E02424"), ("caixa", "caixa", "#004A8A", "#1F6FB8"),
    ("brasil", "bb", "#0B2E8A", "#2D56C4"), ("btg", "btg", "#0B2D5B", "#2C5491"),
    ("xp", "xp", "#1A1A1A", "#444444"), ("sicoob", "sicoob", "#00756A", "#14998B"),
    ("sicredi", "sicredi", "#2F7A0C", "#4E9E24"),
]


@st.cache_data(show_spinner=False)
def _logo_uri(arquivo: str) -> str | None:
    f = LOGOS / f"{arquivo}.svg"
    return "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode() if f.exists() else None


def _clarear(hexcor: str, f=0.28) -> str:
    h = hexcor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#{:02X}{:02X}{:02X}".format(*(round(c + (255 - c) * f) for c in (r, g, b)))


def banco(nome, inst=None, cor=None) -> dict:
    """Logo e cores do degradê. cor = escolhida pelo usuário (vale mais que a do banco)."""
    t = sem_acento(f"{nome} {inst or ''}")
    sigla = "".join(p[0] for p in str(nome).split()[:2]).upper() or "$"
    b = next(({"logo": _logo_uri(arq), "c1": c1, "c2": c2, "sigla": sigla}
              for chave, arq, c1, c2 in BANCOS if chave in t),
             {"logo": None, "c1": "#2F3B52", "c2": "#56637E", "sigla": sigla})
    if isinstance(cor, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", cor):
        b = b | {"c1": cor, "c2": _clarear(cor)}
    return b


def selo(nome, inst=None, tam=40) -> str:
    """Logo do banco num quadrado branco (ou iniciais, se não houver logo)."""
    b = banco(nome, inst)
    if b["logo"]:
        return (f"<div class='ui-selo' style='width:{tam}px;height:{tam}px'>"
                f"<img src='{b['logo']}' alt='' style='max-width:{tam - 10}px;max-height:{tam - 10}px'></div>")
    return (f"<div class='ui-selo ui-selo-txt' style='width:{tam}px;height:{tam}px;"
            f"background:linear-gradient(135deg,{b['c1']},{b['c2']})'>{esc(b['sigla'])}</div>")


BANDEIRAS = [  # (trecho do nome/instituição, arquivo) — a 1ª que bater vale; nome do cartão manda
    ("visa", "visa"), ("master", "mastercard"), ("elo", "elo"), ("amex", "amex"), ("american express", "amex"),
    ("hipercard", "hipercard"), ("latam", "mastercard"), ("nubank", "mastercard"), ("picpay", "mastercard"),
    ("inter", "mastercard"), ("c6", "mastercard"), ("mercado pago", "visa"), ("xp", "visa"),
]


PREMIUM = re.compile(r"\b(black|infinit|ultravioleta)")


def bandeira(nome, inst=None, alt=20) -> str:
    """Logo da bandeira (Visa, Mastercard…) num chip branco; Black/Infinite no padrão prata."""
    t = sem_acento(f"{nome} {inst or ''}")
    arq = next((a for chave, a in BANDEIRAS if re.search(rf"\b{chave}", t)), None)
    uri = _logo_uri(f"bandeira-{arq}") if arq else None
    if not uri:
        return ""
    cls = "ui-band prata" if PREMIUM.search(t) else "ui-band"
    return (f"<span class='{cls}'><img src='{uri}' alt='{esc(arq)}' style='height:{alt}px;width:{int(alt * 1.9)}px;object-fit:contain'></span>")


# ---------------------------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------------------------
CSS = """
<style>
.ui-hero {border-radius: 20px; padding: 22px 24px; color: #fff; box-shadow: 0 12px 32px rgba(17,24,39,.22);
          margin: 6px 0 14px;}
.ui-hero .topo {display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 1.05rem;}
.ui-hero .topo .dir {margin-left: auto; font-weight: 500; font-size: .88rem; opacity: .85;}
.ui-hero .rot {opacity: .85; font-size: .85rem; margin-top: 16px;}
.ui-hero .valor {font-size: 2.4rem; font-weight: 800; letter-spacing: -.6px; line-height: 1.12;}
.ui-hero .sub {opacity: .85; font-size: .85rem; margin-top: 2px;}
.ui-hero .linha {display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 10px; margin-top: 18px;}
.ui-hero .mini {background: rgba(255,255,255,.14); border-radius: 12px; padding: 10px 12px;}
.ui-hero .mini .l {font-size: .78rem; opacity: .88;}
.ui-hero .mini .v {font-size: 1.08rem; font-weight: 700; margin-top: 2px; white-space: nowrap;}
.ui-selo {border-radius: 11px; background: #fff; display: flex; align-items: center; justify-content: center;
          flex-shrink: 0; box-shadow: 0 1px 4px rgba(0,0,0,.18);}
.ui-band {margin-left: auto; background: #fff; border-radius: 7px; padding: 3px 6px; display: inline-flex;
           align-items: center; box-shadow: 0 1px 4px rgba(0,0,0,.18); flex-shrink: 0;}
.ui-hero .dir .ui-band {margin-left: 10px;}
.ui-band.prata {background: linear-gradient(135deg, rgba(255,255,255,.18), rgba(255,255,255,.06));
                box-shadow: inset 0 0 0 1px rgba(255,255,255,.45);}
.ui-band.prata img {filter: grayscale(1) brightness(1.9) contrast(.85);}
.ui-selo-txt {color: #fff; font-weight: 800; font-size: .8rem; letter-spacing: .4px;}
.ui-grade {display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; margin-bottom: 14px;}
.ui-card {border-radius: 14px; padding: 12px 14px; background: rgba(128,128,128,.06);
          box-shadow: 0 2px 12px rgba(0,0,0,.08); border: 1px solid rgba(128,128,128,.14);
          display: flex; gap: 10px; align-items: center;}
.ui-card .n {font-size: .8rem; opacity: .7;} .ui-card .s {font-weight: 700; font-size: 1.05rem;}
.ui-cc {border-radius: 18px; padding: 16px 16px 14px; color: #fff; display: flex; flex-direction: column; gap: 12px;
        box-shadow: 0 8px 22px rgba(17,24,39,.16); min-height: 160px; box-sizing: border-box;}
.ui-cc.sel {outline: 3px solid var(--anel); outline-offset: 3px;}
.ui-cc .cab {display: flex; align-items: center; gap: 10px;}
.ui-cc .nome {font-weight: 700; font-size: 1.02rem; line-height: 1.15;} .ui-cc .bco {font-size: .8rem; opacity: .88;}
.ui-cc .l {font-size: .8rem; opacity: .88;} .ui-cc .v {font-size: 1.55rem; font-weight: 800; letter-spacing: -.4px;}
.ui-cc .pe {display: flex; justify-content: space-between; align-items: center; font-size: .8rem; gap: 6px;}
.ui-cc .pill {background: rgba(255,255,255,.2); border-radius: 99px; padding: 3px 10px; font-weight: 600;}
.ui-cc .barra {height: 6px; border-radius: 99px; background: rgba(255,255,255,.25); overflow: hidden;}
.ui-cc .barra > div {height: 100%; background: #fff;}
.ui-aviso {border-radius: 12px; padding: 9px 12px; font-size: .86rem; margin: 4px 0 10px;
           background: rgba(236,112,0,.09); border: 1px solid rgba(236,112,0,.25);}
.ui-grupo {display: flex; justify-content: space-between; align-items: baseline; margin: 16px 4px 6px;
           font-size: .8rem; text-transform: uppercase; letter-spacing: .6px; opacity: .68; font-weight: 700;}
.ui-sec {font-weight: 800; font-size: 1.15rem; margin: 18px 0 4px;}
.ui-item {display: flex; align-items: center; gap: 12px; min-width: 0;}
.ui-ic {width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
        font-size: 1.05rem; background: rgba(128,128,128,.12); flex-shrink: 0;}
.ui-tx {flex: 1; min-width: 0;}
.ui-tx .t {font-weight: 600; font-size: .93rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.ui-tx .s {font-size: .76rem; opacity: .65; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.ui-tag {display: inline-block; font-size: .68rem; padding: 1px 8px; border-radius: 99px; margin-left: 6px;
         font-weight: 700; vertical-align: 1px; background: rgba(128,128,128,.16);}
.ui-tag.aj {background: rgba(236,112,0,.18);}
.ui-val {font-weight: 700; font-size: .95rem; white-space: nowrap; text-align: right;}
.ui-val.pos {color: #12a150;} .ui-val.neg {color: #d93a40;}
.ui-prev {opacity: .6;}
/* listas com botão de editar por linha: card com sombra, linhas sem quebra no celular */
[class*="st-key-uilista"] {border-radius: 16px; background: rgba(128,128,128,.05);
     box-shadow: 0 2px 12px rgba(0,0,0,.07); border: 1px solid rgba(128,128,128,.13); padding: 4px 6px; gap: 0 !important;}
[class*="st-key-uirow"] {border-bottom: 1px solid rgba(128,128,128,.10); padding: 7px 8px;}
[class*="st-key-uirow"]:last-child {border-bottom: none;}
[class*="st-key-uirow"] [data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; align-items: center; gap: .5rem;}
[class*="st-key-uirow"] [data-testid="stColumn"] {min-width: 0 !important;}
[class*="st-key-uirow"] [data-testid="stColumn"]:last-child {flex: 0 0 40px !important; width: 40px !important;}
[class*="st-key-uirow"] [data-testid="stColumn"]:nth-last-child(2) {flex: 0 0 auto !important; width: auto !important;}
[class*="st-key-uirow"] [data-testid="stColumn"]:first-child {flex: 1 1 auto !important; width: auto !important;}
[class*="st-key-uirow"] button {min-height: 36px; padding: 4px 8px;}
[class*="st-key-uirow"] [data-testid="stMarkdownContainer"] p {margin: 0;}
@media (max-width: 640px) {
  .ui-hero {padding: 18px 16px; border-radius: 16px;}
  .ui-hero .valor {font-size: 1.95rem;}
  .ui-hero .linha {grid-template-columns: repeat(2, minmax(0,1fr));}
  .ui-grade {grid-template-columns: repeat(2, minmax(0,1fr));}
  [class*="st-key-uirow"] {padding: 6px 4px;}
  .ui-ic {width: 34px; height: 34px; font-size: .95rem;}
}
</style>
"""


def css():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(titulo, rotulo, valor, minis: list[tuple[str, str]], c1="#1F2A44", c2="#3B4C75", selo_html="",
         direita="", sub="", direita_html=""):
    minis_html = "".join(f"<div class='mini'><div class='l'>{esc(l)}</div><div class='v'>{esc(v)}</div></div>"
                         for l, v in minis)
    if not selo_html:
        selo_html = "<div class='ui-selo ui-selo-txt' style='width:40px;height:40px;background:rgba(255,255,255,.2)'>Σ</div>"
    render(f"""<div class="ui-hero" style="background:linear-gradient(135deg,{c1} 0%,{c2} 100%)">
        <div class="topo">{selo_html}{esc(titulo)}<span class="dir">{esc(direita)}{direita_html}</span></div>
        <div class="rot">{esc(rotulo)}</div><div class="valor">{esc(valor)}</div>
        {f'<div class="sub">{esc(sub)}</div>' if sub else ''}
        <div class="linha">{minis_html}</div></div>""")


def item_html(icone, titulo, sub="", tag="", tag_cls="", previsto=False) -> str:
    tag_html = f"<span class='ui-tag {tag_cls}'>{esc(tag)}</span>" if tag else ""
    return (f"<div class='ui-item{' ui-prev' if previsto else ''}'><div class='ui-ic'>{icone}</div>"
            f"<div class='ui-tx'><div class='t'>{esc(titulo)}{tag_html}</div>"
            f"<div class='s'>{esc(sub) if sub else '&nbsp;'}</div></div></div>")


def valor_html(v: float, previsto=False) -> str:
    cls = "pos" if v > 0 else "neg"
    return (f"<div class='ui-val {cls}{' ui-prev' if previsto else ''}'>{'+ ' if v > 0 else '− '}"
            f"{brl(abs(v))}</div>")


def linha_editavel(chave: str, esquerda_html: str, direita_html: str, ao_editar, ajuda="Editar"):
    """Uma linha de lista com botão de editar (abre janela)."""
    with st.container(key=f"uirow_{chave}"):
        a, b, c = st.columns([6, 2, 0.6], vertical_alignment="center")
        a.markdown(esquerda_html, unsafe_allow_html=True)
        b.markdown(direita_html, unsafe_allow_html=True)
        if c.button("", icon=":material/edit:", key=f"ed_{chave}", help=ajuda):
            ao_editar()


# ---------------------------------------------------------------------------------------------
# período
# ---------------------------------------------------------------------------------------------
def _fim_mes(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def periodo(chave: str, padrao="mes") -> tuple[date, date, str]:
    """Atalhos 7/15/30 dias, este mês, mês passado e personalizado. Devolve (início, fim, rótulo)."""
    hj = hoje()
    ops = {"7d": "7 dias", "15d": "15 dias", "30d": "30 dias", "mes": "Este mês", "ant": "Mês passado",
           "custom": "Período…"}
    esc_ = st.segmented_control("Período", list(ops), format_func=ops.get, key=f"per_{chave}",
                                default=padrao, label_visibility="collapsed") or padrao
    if esc_ == "custom":
        c1, c2 = st.columns(2)
        ini = c1.date_input("De", hj.replace(day=1), format="DD/MM/YYYY", key=f"per_ini_{chave}")
        fim = c2.date_input("Até", _fim_mes(hj), format="DD/MM/YYYY", key=f"per_fim_{chave}")
        if fim < ini:
            ini, fim = fim, ini
        return ini, fim, f"{ini:%d/%m} a {fim:%d/%m}"
    if esc_ in ("7d", "15d", "30d"):
        n = int(esc_[:-1])
        return hj - timedelta(days=n - 1), hj, f"últimos {n} dias"
    if esc_ == "ant":
        fim = hj.replace(day=1) - timedelta(days=1)
        return fim.replace(day=1), fim, f"{fim:%m/%Y}"
    return hj.replace(day=1), _fim_mes(hj), f"{hj:%m/%Y}"


# ---------------------------------------------------------------------------------------------
# edição de lançamento (janela)
# ---------------------------------------------------------------------------------------------
@st.dialog("Editar lançamento")
def editar_lancamento(u, lanc_id, faturas: list[tuple[str, date]] | None = None):
    """faturas: [(rótulo, vencimento)] para mudar a compra de fatura (cartão)."""
    from core import repo
    from telas._comum import opcoes_categoria
    l = repo.lancamento(u, lanc_id)
    if not l:
        st.warning("Lançamento não encontrado.")
        return
    contas = repo.contas(u)
    cats = repo.categorias(u)
    tipo = l["tipo"] if l["tipo"] in ("despesa", "receita") else "despesa"
    op_cat = {None: "— sem categoria"} | opcoes_categoria(cats, tipo)
    if l["parcela_num"]:
        st.caption(f"Parcela {l['parcela_num']}/{l['parcela_total']}")
    desc = st.text_input("Descrição", l["descricao"])
    c1, c2 = st.columns(2)
    valor = c1.number_input("Valor (R$)", 0.0, value=float(l["valor"]), step=1.0, format="%.2f")
    data = c2.date_input("Data", l["data_compra"] or l["data_vencimento"], format="DD/MM/YYYY")
    ids_cat = list(op_cat)
    cat = st.selectbox("Categoria", ids_cat, format_func=op_cat.get,
                       index=ids_cat.index(l["categoria_id"]) if l["categoria_id"] in ids_cat else 0)
    op_c = {r.id: r.nome for r in contas.itertuples()}
    if l["conta_id"] and l["conta_id"] not in op_c:
        op_c[l["conta_id"]] = "(conta inativa)"
    ids_c = [None] + list(op_c)
    conta = st.selectbox("Conta / cartão", ids_c, format_func=lambda k: "— sem conta" if k is None else op_c[k],
                         index=ids_c.index(l["conta_id"]) if l["conta_id"] in ids_c else 0)
    pago = st.toggle("Já foi pago", value=l["status"] == "pago")
    if faturas and conta == l["conta_id"]:            # cartão: escolhe em qual fatura a compra cai
        rots = [r for r, _ in faturas]
        atual = next((i for i, (_, d) in enumerate(faturas) if d == l["data_vencimento"]), 0)
        venc = dict(faturas)[st.selectbox("Fatura", rots, index=atual)]
    elif not pago:                                    # previsto: vencimento próprio
        venc = st.date_input("Vencimento", l["data_vencimento"], format="DD/MM/YYYY")
    else:                                             # pago na conta: vale a data
        venc = data
    futuras = st.checkbox("Aplicar descrição, valor e categoria às próximas parcelas",
                          value=False) if l["grupo_parcela"] else False
    b1, b2 = st.columns([2, 1])
    if b1.button("Salvar", type="primary", use_container_width=True):
        repo.atualizar_lancamento(u, lanc_id, dict(descricao=desc.strip() or l["descricao"], valor=valor,
                                                   categoria_id=cat, conta_id=conta, data_compra=data,
                                                   data_vencimento=venc, status="pago" if pago else "previsto"),
                                  futuras)
        st.session_state["_ui_ok"] = "Lançamento atualizado."
        st.rerun()
    with b2.popover("Excluir", use_container_width=True):
        fut = st.checkbox("Excluir também as próximas parcelas", disabled=not l["grupo_parcela"])
        if st.button("Excluir de vez", type="primary"):
            repo.excluir(u, [lanc_id], parcelas_futuras=fut)
            st.session_state["_ui_ok"] = "Lançamento excluído."
            st.rerun()


def aviso_ok():
    if msg := st.session_state.pop("_ui_ok", None):
        st.toast(msg, icon=":material/check_circle:")

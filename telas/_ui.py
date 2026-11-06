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

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
LOGOS = Path(__file__).resolve().parent.parent / "static" / "logos"


def sem_acento(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render(s: str):
    """Markdown do Streamlit trata linha indentada como código: junta o HTML numa linha só."""
    st.markdown(re.sub(r"\n\s*", "", s), unsafe_allow_html=True)


# --- cadastro em etapas ①②③ -------------------------------------------------------------------
# Cada campo guarda o valor num rascunho (session_state), então trocar de etapa não perde nada.
NUM = "①②③④⑤"


def rascunho(ch: str, inicial: dict) -> dict:
    return st.session_state.setdefault(f"{ch}__r", dict(inicial))


def rascunho_limpar(ch: str):
    for k in [k for k in st.session_state if str(k).startswith(f"{ch}__")]:
        del st.session_state[k]


def campo(r: dict, ch: str, nome: str, widget, *args, **kw):
    """Desenha o widget com o valor do rascunho e devolve o valor (já gravado no rascunho)."""
    k = f"{ch}__{nome}"
    nada = "__nada__"
    troca = getattr(widget, "__name__", "") == "selectbox" and len(args) > 1 and None in list(args[1])
    if troca:   # selectbox trata None como "nada escolhido": usa um marcador para a opção "nenhuma"
        ff = kw.get("format_func", str)
        kw["format_func"] = lambda o: ff(None if o == nada else o)
        args = (args[0], [nada if o is None else o for o in args[1]]) + tuple(args[2:])
    if k not in st.session_state:
        v0 = r.get(nome)
        st.session_state[k] = nada if troca and v0 is None else v0
    v = widget(*args, key=k, **kw)
    r[nome] = None if v == nada else v
    return r[nome]


def etapas(ch: str, nomes: list[str]) -> int:
    """Cabeçalho ① ② ③ e a etapa atual (0, 1, 2…)."""
    k = f"{ch}__passo"
    i = min(st.session_state.setdefault(k, 0), len(nomes) - 1)
    st.session_state[k] = i
    render("<div class='ui-etapas'>" + "".join(
        f"<span class='{'on' if j == i else ('feito' if j < i else '')}'>{NUM[j]} {esc(n)}</span>"
        for j, n in enumerate(nomes)) + "</div>")
    return i


def _ir(ch, para, obrig):
    falta = [rot for campo_, rot in obrig if not st.session_state.get(f"{ch}__{campo_}")]
    if falta and para > st.session_state.get(f"{ch}__passo", 0):
        st.session_state[f"{ch}__erro"] = "Preencha " + " e ".join(falta) + "."
        return
    st.session_state.pop(f"{ch}__erro", None)
    st.session_state[f"{ch}__passo"] = para


def etapas_botoes(ch: str, n: int, obrig: list[tuple[str, str]] = ()) -> bool:
    """Voltar / Próximo e o botão de salvar. True quando tocou em salvar.
    obrig = campos que precisam estar preenchidos para avançar desta etapa: [(campo, rótulo)]."""
    i = st.session_state.get(f"{ch}__passo", 0)
    if erro := st.session_state.get(f"{ch}__erro"):
        st.error(erro)
    ultimo = i >= n - 1
    with st.container(key=f"etbt_{ch}"):
        c1, c2 = st.columns(2)
        if i > 0:
            c1.button("Voltar", key=f"{ch}__bv", width="stretch", icon=":material/arrow_back:",
                      on_click=_ir, args=(ch, i - 1, []))
        if not ultimo:
            c2.button("Próximo", key=f"{ch}__bp", type="primary", width="stretch", icon=":material/arrow_forward:",
                      on_click=_ir, args=(ch, i + 1, list(obrig)))
            return st.button("Salvar e completar depois", key=f"{ch}__bs", type="tertiary", width="stretch",
                             icon=":material/bookmark:")
        return c2.button("Salvar", key=f"{ch}__bs", type="primary", width="stretch", icon=":material/save:")


def linha(chave: str, esquerda: str, titulo: str, sub: str = "", valor: str = "", chip: str = "",
          chip_cls: str = "ok", valor_cls: str = "") -> bool:
    """Linha tocável (celular): a linha inteira é um botão invisível. Devolve True quando tocada.
    Chamar dentro de st.container(key="llista_…"). `esquerda` = HTML do quadrado (dia, selo…)."""
    with st.container(key=f"lrow_{chave}"):
        dir_ = (f"<div class='v {valor_cls}'>{valor}</div>" if valor else "") + \
               (f"<span class='chip {chip_cls}'>{esc(chip)}</span>" if chip else "")
        render(f"""<div class="ui-lrow">{esquerda}<div class="tx"><div class="t">{esc(titulo)}</div>
            <div class="s">{esc(sub)}</div></div><div class="dir">{dir_}</div></div>""")
        return st.button("Abrir", key=f"lb_{chave}", width="stretch")


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
    if PREMIUM.search(t):
        mask = _logo_uri(f"prata-{arq}")
        if mask:   # metal: o logo vira máscara sobre um degradê prateado com brilho
            w = round(alt * (2.3 if arq == "visa" else 1.6))
            return (f"<span class='ui-band prata'><i class='metal' style='width:{w}px;height:{alt}px;"
                    f"-webkit-mask-image:url(\"{mask}\");mask-image:url(\"{mask}\")'></i></span>")
    cls = "ui-band"
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
.ui-band.prata {background: rgba(0,0,0,.22); box-shadow: inset 0 0 0 1px rgba(255,255,255,.35); padding: 4px 8px;}
.ui-band .metal {display: block; -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
     -webkit-mask-position: center; mask-position: center; -webkit-mask-size: contain; mask-size: contain;
     background: linear-gradient(110deg, #8d8d8d 0%, #e9e9e9 22%, #ffffff 32%, #b5b5b5 45%, #f4f4f4 60%,
                 #9a9a9a 78%, #dcdcdc 100%);
     background-size: 250% 100%; animation: ui-brilho 4.5s ease-in-out infinite;
     filter: drop-shadow(0 1px 1px rgba(0,0,0,.35));}
@keyframes ui-brilho {0%, 100% {background-position: 0% 0;} 50% {background-position: 100% 0;}}
@media (prefers-reduced-motion: reduce) {.ui-band .metal {animation: none;}}
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
/* cabeçalho das telas */
.ui-cab {margin: 0 0 14px;}
.ui-cab .ola {display: flex; align-items: center; gap: 10px; font-size: .92rem; color: #334155;}
.ui-cab .ola b {display: block; font-weight: 700; line-height: 1.15;}
.ui-cab .ola span {display: block; font-size: .76rem; opacity: .7;}
.ui-cab .ola span::first-letter {text-transform: uppercase;}
.ui-cab .tt {display: flex; align-items: center; gap: 12px; margin-top: 12px; font-size: 2.15rem; font-weight: 800;
             letter-spacing: -.8px; line-height: 1.1; color: #0F172A;}
.ui-cab .tt .ic {width: 46px; height: 46px; border-radius: 14px; display: flex; align-items: center;
     justify-content: center; font-size: 1.45rem; background: linear-gradient(135deg, #0B7A66, #34D399);
     box-shadow: 0 8px 18px rgba(11,122,102,.28); flex-shrink: 0;}
.ui-cab .sub {margin-top: 6px; font-size: .9rem; color: #475569; max-width: 760px;}
.ui-av {border-radius: 50%; object-fit: cover; flex-shrink: 0; box-shadow: 0 0 0 2px #fff, 0 3px 10px rgba(0,0,0,.15);}
.ui-av-txt {display: flex; align-items: center; justify-content: center; font-weight: 800; color: #fff;
            background: linear-gradient(135deg, #0B7A66, #10A58A);}
@media (max-width: 640px) {
  .ui-cab .tt {font-size: 1.65rem; gap: 10px;} .ui-cab .tt .ic {width: 38px; height: 38px; font-size: 1.15rem;}
}
.ui-lista-html {border-radius: 16px; background: rgba(128,128,128,.05); box-shadow: 0 2px 12px rgba(0,0,0,.07);
     border: 1px solid rgba(128,128,128,.13); padding: 6px 14px;}
.ui-cat {padding: 10px 0; border-bottom: 1px solid rgba(128,128,128,.10);}
.ui-cat:last-child {border-bottom: none;}
.ui-cat .t {display: flex; justify-content: space-between; gap: 10px; font-weight: 600; font-size: .92rem;}
.ui-cat .t .v {white-space: nowrap;}
.ui-cat .barra {height: 7px; border-radius: 99px; background: rgba(128,128,128,.14); margin-top: 6px; overflow: hidden;}
.ui-cat .barra > div {height: 100%; border-radius: 99px; background: linear-gradient(90deg, #0B7A66, #34D399);}
.ui-cat .p {font-size: .72rem; opacity: .6; margin-top: 3px;}
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
.st-key-marca_aba {position: absolute !important; height: 0; overflow: hidden;}
/* ===== sem a cara do Streamlit: some "Running/Stop", Share/estrela/GitHub, menu ⋮, deploy e a faixa do topo ===== */
[data-testid="stStatusWidget"], [data-testid="stToolbarActions"], [data-testid="stMainMenu"],
[data-testid="stAppDeployButton"], [data-testid="stDecoration"], .stDeployButton,
[data-testid="stToolbar"] [data-testid="stToolbarActionButton"] {display: none !important;}
[data-testid="stSkeleton"] {opacity: 0 !important;}
/* tudo em Nunito, grafite */
html, body, [class*="css"], .stApp, button, input, textarea, select {font-family: 'Nunito', system-ui, sans-serif;}
.ui-tudo-ok {background: #fff; border-radius: 16px; padding: 14px 16px; font-weight: 700; color: #0B7A66;
     box-shadow: 0 2px 12px rgba(17,24,39,.06);}
/* atalhos grandes do Início */
.st-key-atalhos [data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; gap: .6rem !important;}
.st-key-atalhos [data-testid="stColumn"] {min-width: 0 !important; flex: 1 1 0 !important; width: 0 !important;}
.st-key-atalhos button {flex-direction: column !important; gap: 6px !important; min-height: 92px !important;
     background: #fff !important; border: 0 !important; border-radius: 20px !important;
     box-shadow: 0 2px 12px rgba(17,24,39,.07) !important; font-weight: 800 !important; color: #111827 !important;}
.st-key-atalhos button > div > span {display: flex !important; flex-direction: column !important; align-items: center !important; gap: 6px !important;}
.st-key-atalhos button span[data-testid="stIconMaterial"] {font-size: 1.6rem !important; color: #0B7A66 !important;
     background: #DDF5EE; border-radius: 14px; width: 44px; height: 44px; display: flex !important;
     align-items: center; justify-content: center;}
.st-key-atalhos button p {font-size: .92rem !important; font-weight: 800 !important;}
/* "Precisa de atenção": linhas tocáveis com › */
.st-key-pendencias {background: #fff; border-radius: 20px; box-shadow: 0 2px 12px rgba(17,24,39,.06);
     padding: 4px 0; gap: 0 !important;}
.st-key-pendencias [data-testid="stPageLink"] a {padding: 10px 14px !important; border-radius: 0 !important;
     border-bottom: 1px solid rgba(17,24,39,.06); background: transparent !important;}
.st-key-pendencias [class*="st-key-pend_"]:last-child [data-testid="stPageLink"] a {border-bottom: 0;}
.st-key-pendencias [data-testid="stPageLink"] a p {font-size: .88rem !important; line-height: 1.3 !important;
     color: #5B6472 !important;}
.st-key-pendencias [data-testid="stPageLink"] a p strong {color: #111827; font-size: .94rem;}
.st-key-pendencias [data-testid="stPageLink"] a::after {content: "›"; margin-left: auto; font-size: 1.4rem;
     color: #94A3B8; padding-left: 8px;}
[class*="st-key-pend_alto"] span[data-testid="stIconMaterial"] {color: #C81E1E !important;}
[class*="st-key-pend_medio"] span[data-testid="stIconMaterial"] {color: #B45309 !important;}
[class*="st-key-pend_info"] span[data-testid="stIconMaterial"] {color: #0B7A66 !important;}
/* ===== listas tocáveis (celular): a linha inteira abre a ficha ===== */
[class*="st-key-llista_"] {background: #fff; border-radius: 20px; box-shadow: 0 2px 12px rgba(17,24,39,.06);
  gap: 0 !important; overflow: hidden;}
[class*="st-key-lrow_"] {position: relative; gap: 0 !important; border-bottom: 1px solid rgba(17,24,39,.06);}
[class*="st-key-lrow_"]:last-child {border-bottom: 0;}
[class*="st-key-lrow_"] [data-testid="stElementContainer"]:has(.stButton) {position: absolute !important; inset: 0; z-index: 2;
  height: auto !important; margin: 0 !important;}
[class*="st-key-lrow_"] .stButton {position: absolute !important; inset: 0; margin: 0 !important; height: 100%;}
[class*="st-key-lrow_"] .stButton button {width: 100%; height: 100% !important; opacity: 0; min-height: 0 !important;}
[class*="st-key-lrow_"]:active {background: rgba(11,122,102,.06);}
.ui-lrow {display: flex; align-items: center; gap: 12px; padding: 11px 14px;}
.ui-lrow .dia {width: 42px; height: 42px; border-radius: 13px; background: #DDF5EE; color: #0B7A66; flex-shrink: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center; line-height: 1;}
.ui-lrow .dia b {font-size: 1rem; font-weight: 900;} .ui-lrow .dia span {font-size: .6rem; font-weight: 800;}
.ui-lrow .tx {flex: 1; min-width: 0;}
.ui-lrow .t {font-weight: 800; font-size: .92rem; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.ui-lrow .s {font-size: .76rem; color: #5B6472; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.ui-lrow .dir {display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex-shrink: 0;}
.ui-lrow .v {font-weight: 900; font-size: .92rem; color: #111827; white-space: nowrap;} .ui-lrow .v.pos {color: #0B7A66;}
.chip {font-size: .64rem; font-weight: 900; padding: 2px 8px; border-radius: 99px;}
.chip.ok {background: #DDF5EE; color: #0B7A66;} .chip.warn {background: #FDEBD3; color: #A2490A;}
.chip.bad {background: #FDE2E2; color: #C81E1E;} .chip.mute {background: #E5E7EB; color: #5B6472;}
.ui-lrow .v.neg {color: #C81E1E;} .ui-lrow .sel {flex-shrink: 0; display: flex;}
.ui-casc {display: grid; grid-auto-flow: column; grid-auto-columns: minmax(230px, 1fr); overflow-x: auto; background: #fff; border-radius: 20px; box-shadow: 0 2px 10px rgba(15,23,42,.06); scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch;}
.ui-casc .mes {border-right: 1px solid #E5E7EB; display: flex; flex-direction: column; scroll-snap-align: start; min-width: 0;}
.ui-casc .mes:last-child {border-right: 0;}
.ui-casc .mes.hoje .h {background: #DDF5EE;} .ui-casc .mes.hoje .h span {color: #0B7A66;}
.ui-casc .h {display: flex; justify-content: space-between; align-items: center; padding: 11px 14px; border-bottom: 1px solid #E5E7EB; font-size: .74rem; font-weight: 900; letter-spacing: .06em; text-transform: uppercase; color: #5B6472;}
.ui-casc .h b {font-size: .95rem; letter-spacing: 0; text-transform: none; color: #111827; font-variant-numeric: tabular-nums;}
.ui-casc .h b.neg {color: #C81E1E;}
.ui-casc .sp {height: 46px; margin: 8px 12px 2px;} .ui-casc .sp svg {width: 100%; height: 100%; overflow: visible;}
.ui-casc .sp polyline {fill: none; stroke: #CBD5E1; stroke-width: 1.5; vector-effect: non-scaling-stroke;}
.ui-casc .sp circle {fill: #0B7A66; vector-effect: non-scaling-stroke;} .ui-casc .sp circle.neg {fill: #C81E1E;}
.ui-casc .sp line.z {stroke: #FCA5A5; stroke-width: 1; stroke-dasharray: 3 3; vector-effect: non-scaling-stroke;}
.ui-casc .r {display: flex; justify-content: space-between; gap: 8px; padding: 7px 14px; font-weight: 700; font-size: .86rem; border-bottom: 1px dashed #E5E7EB; font-variant-numeric: tabular-nums;}
.ui-casc .r span:first-child {color: #5B6472; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;}
.ui-casc .r span:last-child {flex-shrink: 0; margin-left: auto;}
.ui-casc .r span:last-child {white-space: nowrap;}
.ui-casc .r.in span:last-child {color: #0B7A66;}
.ui-casc .r.blk {background: #EEF1F5; font-weight: 900; font-size: .68rem; letter-spacing: .05em; text-transform: uppercase; border-bottom: 0;}
.ui-casc .r.blk span {color: #5B6472;}
.ui-casc .r.sub {padding-left: 24px; font-size: .8rem;} .ui-casc .r.sub.vazio span {color: #B6BDC8;} .ui-casc .r.sub span:first-child::before {content: ""; display: inline-block; width: 5px; height: 5px; border-radius: 50%; background: #CBD5E1; margin-right: 7px; vertical-align: 2px;}
.ui-casc .r.tot {font-weight: 900; border-top: 2px solid #E5E7EB; border-bottom: 0; margin-top: auto;}
.ui-casc .r.tot .pos {color: #0B7A66;} .ui-casc .neg {color: #C81E1E;}
.ui-casc .r.saldo {background: #DDF5EE; font-weight: 900; border-bottom: 0;} .ui-casc .r.saldo span {color: #111827;}
.ui-casc .r.sim {background: #FDEBD3; font-weight: 900; border-bottom: 0;} .ui-casc .r.sim span {color: #A2490A;}
@media (max-width: 640px) {.ui-casc {grid-auto-columns: 86vw;} .ui-casc .r {font-size: .9rem;}}
.ui-etapas {display: flex; gap: 6px; margin: 0 0 14px; flex-wrap: wrap;}
.ui-etapas span {font-size: .78rem; font-weight: 800; padding: 6px 12px; border-radius: 99px; background: #E5E7EB; color: #5B6472;}
.ui-etapas span.on {background: #111827; color: #fff;} .ui-etapas span.feito {background: #DDF5EE; color: #0B7A66;}
.ui-ficha-topo {text-align: center; margin: -6px 0 12px;}
.ui-ficha-topo .v {font-size: 2rem; font-weight: 900; color: #111827; letter-spacing: -.5px;}
.ui-ficha-topo .d {font-weight: 800; font-size: 1rem;} .ui-ficha-topo .s {font-size: .82rem; color: #5B6472;}
/* ===== barra de abas fixa embaixo (só no celular) ===== */
.st-key-tabbar {display: none !important;}
@media (max-width: 640px) {
  .st-key-tabbar {display: flex !important; position: fixed; left: 0; right: 0; bottom: 0; z-index: 999990;
    background: rgba(255,255,255,.97); backdrop-filter: blur(8px); border-top: 1px solid rgba(17,24,39,.06);
    box-shadow: 0 -6px 20px rgba(17,24,39,.08);
    padding: 6px max(10px, env(safe-area-inset-left)) calc(10px + env(safe-area-inset-bottom)) max(10px, env(safe-area-inset-right)) !important;}
  .st-key-tabbar [data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important; gap: 2px !important; width: 100%;
    justify-content: space-between !important;}
  .st-key-tabbar [data-testid="stColumn"] {min-width: 0 !important; flex: 1 1 0 !important; width: 0 !important;
    max-width: none !important;}
  .st-key-tabbar [data-testid="stColumn"] > div, .st-key-tabbar [data-testid="stColumn"] [data-testid="stVerticalBlock"],
  .st-key-tabbar [data-testid="stElementContainer"], .st-key-tabbar [data-testid="stPageLink"],
  .st-key-tabbar [data-testid="stMarkdown"], .st-key-tabbar [data-testid="stMarkdownContainer"] {width: 100% !important;}
  .st-key-tabbar [data-testid="stPageLink"] a, .ui-mais {display: flex !important; flex-direction: column !important;
    align-items: center !important; justify-content: center !important; gap: 2px !important; padding: 4px 1px !important;
    width: 100% !important; box-sizing: border-box; text-align: center;
    border-radius: 16px !important; background: transparent !important; cursor: pointer;}
  .st-key-tabbar [data-testid="stElementContainer"], .st-key-tabbar [data-testid="stPageLink"],
  .st-key-tabbar [data-testid="stPageLink"] > div, .st-key-tabbar [data-testid="stMarkdown"],
  .st-key-tabbar [data-testid="stMarkdownContainer"] {margin: 0 !important; padding: 0 !important;}
  .st-key-tabbar [data-testid="stPageLink"] a, .ui-mais {height: 60px !important; min-height: 60px !important; margin: 0 !important;}
  .st-key-tabbar [data-testid="stPageLink"] a > span:first-child, .ui-mais .i {margin: 0 !important; height: 30px !important;
    width: 50px !important; border-radius: 15px; display: flex !important; align-items: center !important;
    justify-content: center !important;}
  .st-key-tabbar [data-testid="stPageLink"] a > span:last-child {margin: 0 !important; height: 20px; display: flex;
    align-items: center; justify-content: center; max-width: 100%;}
  .st-key-tabbar [data-testid="stPageLink"] a span[data-testid="stIconMaterial"] {font-size: 1.6rem !important;
    color: #5B6472 !important;}
  .st-key-tabbar [data-testid="stPageLink"] a p, .ui-mais .r {font-size: .66rem !important; letter-spacing: -.2px; font-weight: 800 !important;
    color: #5B6472 !important; margin: 0 !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    line-height: 20px !important;}
  .st-key-tab_on [data-testid="stPageLink"] a > span:first-child {background: #DDF5EE !important;}
  .st-key-tabbar .st-key-tab_on [data-testid="stPageLink"] a p,
  .st-key-tabbar .st-key-tab_on [data-testid="stPageLink"] a span[data-testid="stIconMaterial"] {color: #111827 !important;}
  .ui-mais .i {font-family: "Material Symbols Rounded"; font-size: 1.6rem; line-height: 1; color: #5B6472;}
  .block-container {padding-bottom: 7rem !important;}
  /* no celular a barra de baixo substitui a faixa do topo (logo + botão do menu): o "Mais" abre o menu */
  [data-testid="stHeader"] {display: none !important;}
  .block-container {padding-top: .9rem !important;}
  #fin-olho {top: .9rem !important;}
}
</style>
"""

# Aba do navegador e atalho do celular (nome e ícone do app, em vez de "· Streamlit"), teclado certo no celular e o
# "Mais" da barra de baixo abrindo/fechando o menu lateral. Atenção: dentro do <script> NENHUM "<" (nem "a<5"):
# o filtro de HTML do Streamlit descarta o script inteiro, sem erro. Use ">" invertendo a comparação.
_MARCA_ABA = """<script>(function(){try{
if(!window.__finTeclado){window.__finTeclado=1;
  const ajusta=()=>{
    document.querySelectorAll('[data-testid="stNumberInput"] input').forEach(i=>{
      if(i.getAttribute('inputmode')!=='decimal') i.setAttribute('inputmode','decimal');});
    document.querySelectorAll('input[aria-label]').forEach(i=>{const l=i.getAttribute('aria-label')||'';
      if(/e-?mail/i.test(l)&&i.getAttribute('inputmode')!=='email'){i.setAttribute('inputmode','email');i.setAttribute('autocapitalize','off');}});
  };
  let pend=false; const agenda=()=>{if(pend) return; pend=true; requestAnimationFrame(()=>{pend=false; ajusta();});};
  new MutationObserver(agenda).observe(document.body,{childList:true,subtree:true}); ajusta();}
if(!window.__finMais){window.__finMais=1;
  const aberto=()=>{const sb=document.querySelector('[data-testid="stSidebar"]');
    return !!sb && sb.getAttribute('data-collapsed')!=='true' && sb.getBoundingClientRect().right>40;};
  const marca=e=>{if(e.target.closest && e.target.closest('.ui-mais')) window.__finMaisAberto=aberto();};
  document.addEventListener('pointerdown',marca,true); document.addEventListener('touchstart',marca,true);
  document.addEventListener('click',function(e){
    if(!(e.target.closest && e.target.closest('.ui-mais'))) return;
    const estava = window.__finMaisAberto===undefined ? aberto() : window.__finMaisAberto; window.__finMaisAberto=undefined;
    setTimeout(()=>{const agora=aberto();
      if(estava && agora){const b=document.querySelector('[data-testid="stSidebarCollapseButton"] button'); if(b) b.click();}
      else if(!estava && !agora){const b=document.querySelector('[data-testid="stExpandSidebarButton"]'); if(b) b.click();}
    },60);},true);}
}catch(e){}})();
(function(){try{
/* depois de uma atualização, o navegador pode ter guardado a versão antiga do app e pedir arquivos que não
   existem mais (erro de módulo do Safari/Chrome): baixa de novo, sem cache, e recarrega (até 2x em 10 min).
   As frases do erro são montadas em pedaços para o próprio script (que fica na página) não casar com elas. */
if(window.__finRecup) return; window.__finRecup=1;
const W=(window.parent&&window.parent!==window)?window.parent:window, K="fin-recarregou";
const J=(a)=>a.join(" "), RE=new RegExp([J(["Importing","a","module","script","failed"]), J(["dynamically","imported","module"]), J(["error","loading","dynamically"])].join("|"),"i");
function recuperar(){
  let h=[]; try{h=JSON.parse(W.sessionStorage.getItem(K)||"[]")}catch(e){}
  h=h.filter(t=>600000>Date.now()-t); if(h.length>=2) return;
  h.push(Date.now()); try{W.sessionStorage.setItem(K,JSON.stringify(h))}catch(e){}
  const urls=[location.href, W.location.href].concat([...document.querySelectorAll('script[src],link[rel="modulepreload"],link[rel="stylesheet"]')].map(e=>e.src||e.href))
    .concat(performance.getEntriesByType("resource").map(e=>e.name).filter(n=>/[/]static[/](js|css)[/]/.test(n)));
  Promise.all(urls.map(u=>fetch(u,{cache:"reload"}).catch(()=>0))).then(()=>W.location.reload());
}
setInterval(function(){try{
  const m=document.querySelector('[data-testid="stMain"]')||document.body;
  if(RE.test(m.textContent||"")) recuperar();
}catch(e){}},2000);
}catch(e){}})();
(function(){try{
const P=window.parent; if(!P||P===window) return; const d=P.document;
const T="Finanças", L=window.location, k=L.pathname.indexOf("/~/+/");
const B=L.origin+(k>=0? L.pathname.slice(0,k)+"/~/+/" : "/");   /* no Streamlit Cloud o app (e o /app/static) mora em /~/+/ */
const I=B+"app/static/icone-180.png";
function link(rel){let l=d.head.querySelector('link[rel="'+rel+'"]'); if(!l){l=d.createElement('link'); l.rel=rel; d.head.appendChild(l);} return l;}
function meta(n,v){let m=d.head.querySelector('meta[name="'+n+'"]'); if(!m){m=d.createElement('meta'); m.name=n; d.head.appendChild(m);} if(m.content!==v) m.content=v;}
function fix(){
  if(d.title!==T) d.title=T;
  d.head.querySelectorAll('link[rel~="icon"]').forEach(l=>{if(l.href!==I){l.href=I; l.type="image/png";}});
  if(!d.head.querySelector('link[rel~="icon"]')){const l=link("icon"); l.href=I; l.type="image/png";}
  d.head.querySelectorAll('link[rel="apple-touch-icon"]').forEach(l=>{if(l.href!==I) l.href=I; if(l.getAttribute("sizes")!=="180x180") l.setAttribute("sizes","180x180");});
  if(!d.head.querySelector('link[rel="apple-touch-icon"]')){const a=link("apple-touch-icon"); a.href=I; a.setAttribute("sizes","180x180");}
  d.head.querySelectorAll('link[rel="manifest"],link[rel="mask-icon"]').forEach(l=>l.remove());   /* manifesto do Streamlit = coroa */
  meta("apple-mobile-web-app-title",T); meta("application-name",T); meta("theme-color","#111827");
  meta("apple-mobile-web-app-capable","yes");
  if(!d.getElementById("fin-sem-selo")){const s=d.createElement("style"); s.id="fin-sem-selo";
    s.textContent='@media (max-width:640px){[data-testid="manage-app-button"],[class*="viewerBadge"],[class*="_profileContainer"]{display:none!important}}';
    d.head.appendChild(s);}
}
fix();
P.__finFix=fix;
if(P.__finMarca&&!P.__finMarca2){P.__finMarca.disconnect();}
if(!P.__finMarca2){P.__finMarca2=new P.MutationObserver(()=>P.__finFix()); P.__finMarca2.observe(d.head,{subtree:true,childList:true,characterData:true,attributes:true});}
}catch(e){}})();</script>"""


def css():
    st.markdown(CSS, unsafe_allow_html=True)


assert _MARCA_ABA[8:-9].count("<") == 0, "script da marca com '<': o Streamlit descarta o script"


def marca():
    """Uma vez por execução (no app.py): nome/ícone da aba, teclado certo e o "Mais" da barra de baixo."""
    with st.container(key="marca_aba"):
        st.html(_MARCA_ABA, unsafe_allow_javascript=True)


def barra_abas(itens: list[tuple[str, str, str]], atual: str = ""):
    """Barra fixa embaixo, só no celular. itens: (página, rótulo, ícone); o último botão, "Mais", abre o menu."""
    from pathlib import Path
    atual = {"caixa_entrada": "lancamento_rapido", "novo_lancamento": "lancamento_rapido"}.get(atual, atual)
    with st.container(key="tabbar"):
        cols = st.columns(len(itens) + 1)
        for i, (col, (pag, rot, ic)) in enumerate(zip(cols, itens)):
            on = Path(pag).stem == atual or (not atual and i == 0)
            with col.container(key="tab_on" if on else f"tab_{i}"):
                st.page_link(pag, label=rot, icon=ic)
        cols[-1].markdown("<div class='ui-mais'><span class='i'>menu</span><span class='r'>Mais</span></div>",
                          unsafe_allow_html=True)


DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
                "outubro", "novembro", "dezembro"]


def avatar(u: dict, tam=42) -> str:
    """Foto do Google de quem está logado (ou a inicial, se não houver)."""
    foto = u.get("foto")
    nome = u.get("nome") or u.get("email") or "?"
    if isinstance(foto, str) and foto.startswith("https://"):
        return (f"<img class='ui-av' src='{esc(foto)}' alt='' referrerpolicy='no-referrer' "
                f"style='width:{tam}px;height:{tam}px'>")
    return (f"<div class='ui-av ui-av-txt' style='width:{tam}px;height:{tam}px'>{esc(nome[:1].upper())}</div>")


def titulo(texto: str, icone: str = "", sub: str = ""):
    """Cabeçalho das telas: saudação com a foto de quem está logado + título da página."""
    from datetime import datetime

    from core.fmt import FUSO
    u = st.session_state.get("usuario") or {}
    agora = datetime.now(FUSO)
    ola = "Bom dia" if 5 <= agora.hour < 12 else ("Boa tarde" if 12 <= agora.hour < 18 else "Boa noite")
    primeiro = (u.get("nome") or "").split(" ")[0]
    data = f"{DIAS_SEMANA[agora.weekday()]}, {agora.day} de {MESES_LONGOS[agora.month - 1]}"
    render(f"""<div class="ui-cab">
        <div class="ola">{avatar(u, 34)}<div><b>{ola}{', ' + esc(primeiro) if primeiro else ''}!</b>
          <span>{data}</span></div></div>
        {f'<div class="tt">' + (f'<span class="ic">{icone}</span>' if icone else '') + f'<span>{esc(texto)}</span></div>' if texto else ''}
        {f'<div class="sub">{sub}</div>' if sub else ''}</div>""")


def hero(titulo, rotulo, valor, minis: list[tuple[str, str]], c1="#0F172A", c2="#134E48", selo_html="",
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
    form_lancamento(u, lanc_id, faturas)


def form_lancamento(u, lanc_id, faturas: list[tuple[str, date]] | None = None):
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

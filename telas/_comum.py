"""Peças reutilizadas pelas telas."""
import pandas as pd
import streamlit as st

from core.fmt import hoje, mes_label, mes_ref, somar_meses


def col_rs(label="Valor"):
    """Coluna de dinheiro já formatada por em_reais() (R$ 1.234,56), alinhada à direita."""
    return st.column_config.TextColumn(label, alignment="right")


def em_reais(df, *cols):
    """Cópia do DataFrame com as colunas de valor como texto R$ 1.234,56 (para exibir)."""
    from core.fmt import brl
    out = df.copy()
    for c in cols or ("valor",):
        out[c] = out[c].map(lambda v: "" if pd.isna(v) else brl(v))
    return out


def e_celular() -> bool:
    """Layout de celular: pelo navegador (User-Agent), com chave manual no menu lateral."""
    if "modo_celular" in st.session_state:
        return bool(st.session_state["modo_celular"])
    ua = (st.context.headers.get("User-Agent") or "").lower()
    return any(k in ua for k in ("iphone", "android", "mobile", "ipad"))


def cartoes_kpi(itens: list[tuple[str, str]], titulo: str | None = None, icone: str = "Σ", destaque: int | None = 0,
                sub: str = "", direita: str = "", c1: str = "#1F2A44", c2: str = "#3B4C75"):
    """Indicadores no padrão do app: card principal com degradê.
    Com título: o item `destaque` vira o valor grande e os outros os quadradinhos.
    Sem título: só os quadradinhos dentro do card (4 por linha; 2 no celular)."""
    from telas import _ui
    selo = (f"<div class='ui-selo ui-selo-txt' style='width:40px;height:40px;background:rgba(255,255,255,.2);"
            f"font-size:1.15rem'>{icone}</div>")
    if titulo and destaque is not None and itens:
        rot, val = itens[destaque]
        minis = [x for i, x in enumerate(itens) if i != destaque]
        _ui.hero(titulo, rot, val, minis, c1, c2, selo, direita=direita, sub=sub)
        return
    minis = "".join(f"<div class='mini'><div class='l'>{_ui.esc(r)}</div><div class='v'>{_ui.esc(v)}</div></div>"
                    for r, v in itens)
    cab = f"<div class='topo'>{selo}{_ui.esc(titulo)}</div>" if titulo else ""
    _ui.render(f"<div class='ui-hero compacto' style='background:linear-gradient(135deg,{c1} 0%,{c2} 100%)'>"
               f"{cab}<div class='linha'>{minis}</div></div>")


CSS = """
<style>
/* olho de esconder valores (static/olho.js): no canto direito, na altura do título */
.block-container {position: relative;}
.st-key-olhojs {position: absolute !important; height: 0; overflow: hidden;}
#fin-olho {position: absolute; top: 3.6rem; right: 1rem; z-index: 5; width: 42px; height: 38px; border-radius: 99px;
           border: 1px solid rgba(128,128,128,.3); background: var(--background-color, #fff); color: inherit;
           display: flex; align-items: center; justify-content: center; cursor: pointer; padding: 0;}
#fin-olho:hover {border-color: #0E7C6B; color: #0E7C6B;}
@media (max-width: 640px) {#fin-olho {top: 4.6rem; right: .4rem;}}
html.fin-oculto [data-testid="stVegaLiteChart"], html.fin-oculto [data-testid="stArrowVegaLiteChart"],
html.fin-oculto [data-testid="stPlotlyChart"], html.fin-oculto [data-testid="stMetricValue"],
html.fin-oculto [data-testid="stMetricDelta"] {filter: blur(9px); pointer-events: none;}
.block-container {padding-top: 2.2rem; padding-bottom: 4rem;}

/* ---------- tipografia ---------- */
h1 {font-weight: 800 !important; letter-spacing: -.6px;}
h2, h3 {font-weight: 800 !important; letter-spacing: -.3px;}
[data-testid="stCaptionContainer"] {opacity: .85;}

/* ---------- cards: containers com borda, formulários, expanders, tabelas ---------- */
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stForm"] {
    border-radius: 18px !important; border: 1px solid rgba(128,128,128,.14) !important;
    box-shadow: 0 2px 14px rgba(17,24,39,.07); background: rgba(128,128,128,.025);}
[data-testid="stExpander"] details {border-radius: 16px !important; border: 1px solid rgba(128,128,128,.14) !important;
    box-shadow: 0 2px 12px rgba(17,24,39,.06);}
[data-testid="stExpander"] summary {font-weight: 600;}
[data-testid="stDataFrame"], [data-testid="stTable"] {border-radius: 14px; overflow: hidden;
    box-shadow: 0 2px 12px rgba(17,24,39,.07); border: 1px solid rgba(128,128,128,.14);}
[data-testid="stAlert"] {border-radius: 14px;}

/* ---------- campos e botões ---------- */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"], [data-testid="stDateInput"] > div > div,
[data-testid="stNumberInput"] > div > div {border-radius: 12px !important;}
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button, [data-testid="stPageLink"] a,
[data-testid="stPopover"] > div > button {border-radius: 12px !important; font-weight: 600;}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"] {
    box-shadow: 0 6px 16px rgba(15,118,110,.25);}
[data-testid="stButtonGroup"] button {border-radius: 10px !important;}
[data-testid="stFileUploaderDropzone"] {border-radius: 16px; border: 1.5px dashed rgba(15,118,110,.45);
    background: rgba(15,118,110,.04);}

/* ---------- menu lateral ---------- */
[data-testid="stSidebar"] {background: linear-gradient(180deg, #17213A 0%, #22345C 100%) !important;}
[data-testid="stSidebar"] * {color: rgba(255,255,255,.88);}
[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {padding-bottom: .4rem;}
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] {color: rgba(255,255,255,.5) !important;
    text-transform: uppercase; font-size: .7rem !important; letter-spacing: .9px; font-weight: 700; margin-top: .6rem;}
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] * {color: rgba(255,255,255,.5) !important;}
[data-testid="stSidebarNavLink"] {border-radius: 12px; margin: 1px 0; transition: background .15s;}
[data-testid="stSidebarNavLink"]:hover {background: rgba(255,255,255,.08) !important;}
[data-testid="stSidebarNavLink"][aria-current="page"] {background: linear-gradient(135deg, #0F766E, #14A391) !important;
    box-shadow: 0 6px 16px rgba(0,0,0,.25);}
[data-testid="stSidebarNavLink"][aria-current="page"] * {color: #fff !important; font-weight: 700;}
[data-testid="stSidebarNavLink"] span[data-testid="stIconMaterial"] {color: rgba(255,255,255,.7);}
[data-testid="stSidebarNavSeparator"] {border-color: rgba(255,255,255,.12) !important;}
[data-testid="stSidebar"] [data-testid="stSidebarNavViewButton"] {color: rgba(255,255,255,.7) !important;}
[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,.14);}
[data-testid="stSidebar"] a {color: #7FE0D2 !important;}
[data-testid="stSidebar"] .stButton > button {background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.18);}
[data-testid="stSidebar"] .stButton > button:hover {background: rgba(255,255,255,.16); border-color: rgba(255,255,255,.35);}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {opacity: 1;}
[data-testid="stSidebar"] [data-testid="stCheckbox"] label > span + div {background: rgba(255,255,255,.28) !important;}
[data-testid="stSidebar"] [data-testid="stCheckbox"] label:has(input:checked) > span + div {background: #14A391 !important;}
.st-key-perfil {background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.12); border-radius: 16px;
    padding: 12px 12px 10px; margin-top: .4rem;}
.ui-perfil {display: flex; align-items: center; gap: 10px;}
.ui-perfil .av {width: 38px; height: 38px; border-radius: 50%; background: linear-gradient(135deg,#0F766E,#14A391);
    display: flex; align-items: center; justify-content: center; font-weight: 800; color: #fff; flex-shrink: 0;}
.ui-perfil .n {font-weight: 700; font-size: .92rem; color: #fff;}
.ui-perfil .e {font-size: .74rem; opacity: .65; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
.ui-perfil .adm {font-size: .65rem; background: rgba(255,255,255,.14); border-radius: 99px; padding: 1px 7px;
    margin-left: 4px; font-weight: 700;}

/* ---------- card de indicadores sem valor de destaque ---------- */
.ui-hero.compacto {padding: 14px 16px;}
.ui-hero.compacto .linha {margin-top: 0;}
.ui-hero.compacto .topo + .linha {margin-top: 14px;}

@media (max-width: 640px) {
  .block-container {padding: 1.2rem .8rem 4rem;}
  h1 {font-size: 1.7rem !important;}
  h2, h3 {font-size: 1.2rem !important;}
}
</style>
"""


def usuario() -> dict:
    return st.session_state["usuario"]


def seletor_escopo(chave="escopo") -> str:
    """Eu / Nós. Guarda a escolha entre as telas."""
    opcoes = {"eu": "👤 Só eu", "nos": "👥 Nós"}
    escolha = st.segmented_control("Visão", list(opcoes), format_func=opcoes.get,
                                   default=st.session_state.get("_escopo", "eu"), key=chave,
                                   label_visibility="collapsed")
    st.session_state["_escopo"] = escolha or "eu"
    return st.session_state["_escopo"]


def seletor_mes(label="Mês", chave="mes", antes=6, depois=24) -> int:
    atual = mes_ref(hoje())
    meses = [somar_meses(atual, k) for k in range(-antes, depois + 1)]
    return st.selectbox(label, meses, index=antes, format_func=mes_label, key=chave)


def opcoes_categoria(df_cat, tipo="despesa") -> dict:
    """{id: 'Categoria › Sub'} só com folhas (subcategorias ou categorias sem filhos)."""
    df = df_cat[(df_cat["tipo"] == tipo) & (df_cat["ativa"])]
    pais_com_filhos = set(df["pai_id"].dropna())
    out = {}
    for _, r in df.iterrows():
        if pd.isna(r["pai_id"]):
            if r["id"] not in pais_com_filhos:
                out[r["id"]] = r["nome"]
        else:
            out[r["id"]] = f"{r['categoria_pai']} › {r['nome']}"
    return dict(sorted(out.items(), key=lambda kv: kv[1]))

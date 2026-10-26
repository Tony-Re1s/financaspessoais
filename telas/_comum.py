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


def cartoes_kpi(itens: list[tuple[str, str]]):
    """Indicadores em grade: 4 por linha no computador, 2 no celular."""
    html = "".join(f"<div class='kpi'><div class='kpi-l'>{rot}</div><div class='kpi-v'>{val}</div></div>"
                   for rot, val in itens)
    st.markdown(f"<div class='kpis'>{html}</div>", unsafe_allow_html=True)


CSS = """
<style>
/* olho de esconder valores (static/olho.js): no canto direito, na altura do título */
.block-container {position: relative;}
.st-key-olhojs {position: absolute !important; height: 0; overflow: hidden;}
#fin-olho {position: absolute; top: 2.6rem; right: 1rem; z-index: 5; width: 42px; height: 38px; border-radius: 99px;
           border: 1px solid rgba(128,128,128,.3); background: var(--background-color, #fff); color: inherit;
           display: flex; align-items: center; justify-content: center; cursor: pointer; padding: 0;}
#fin-olho:hover {border-color: #0E7C6B; color: #0E7C6B;}
@media (max-width: 640px) {#fin-olho {top: 4.6rem; right: .4rem;}}
html.fin-oculto [data-testid="stVegaLiteChart"], html.fin-oculto [data-testid="stArrowVegaLiteChart"],
html.fin-oculto [data-testid="stPlotlyChart"], html.fin-oculto [data-testid="stMetricValue"],
html.fin-oculto [data-testid="stMetricDelta"] {filter: blur(9px); pointer-events: none;}
.block-container {padding-top: 2.2rem; padding-bottom: 4rem;}
.kpis {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .6rem; margin: .2rem 0 1rem;}
.kpi {border: 1px solid rgba(49,51,63,.15); border-radius: .6rem; padding: .7rem .8rem;}
.kpi-l {font-size: .8rem; opacity: .7; line-height: 1.2;}
.kpi-v {font-size: 1.35rem; font-weight: 600; margin-top: .2rem; white-space: nowrap;}
@media (max-width: 640px) {
  .block-container {padding: 1.2rem .8rem 4rem;}
  h1 {font-size: 1.7rem !important;}
  h2, h3 {font-size: 1.2rem !important;}
  .kpis {grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .45rem;}
  .kpi {padding: .55rem .6rem;}
  .kpi-v {font-size: 1.05rem;}
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

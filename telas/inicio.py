import streamlit as st

from core import caixa, inicio
from core.fmt import brl, hoje, mes_label, mes_ref
from telas import _ui
from telas._comum import cartoes_kpi, usuario

u = usuario()
_ui.aviso_ok()
_ui.titulo("")

p = inicio.placar(u)
cartoes_kpi([("Saldo nas contas hoje", brl(p["saldo"])), (f"Entra em {mes_label(mes_ref(hoje()))}", brl(p["entra"])),
             ("Sai no mês", brl(p["sai"])), ("Sobra do mês", brl(p["sobra"])), ("Previsto no fim do mês", brl(p["fim"]))],
            titulo="Hoje", icone="💧", direita=f"{p['contas']} contas",
            c1="#7A1D2B" if p["fim"] < 0 else None, c2="#C2334A" if p["fim"] < 0 else None)

# --- atalhos grandes -----------------------------------------------------------------------------
try:
    n_caixa = caixa.qtd_pendentes(u)
except Exception:  # noqa: BLE001
    n_caixa = 0
with st.container(key="atalhos"):
    a1, a2, a3 = st.columns(3)
    if a1.button("Falar", icon=":material/mic:", key="at_voz", width="stretch"):
        st.session_state["_rapido_modo"] = "voz"
        st.switch_page("telas/lancamento_rapido.py")
    if a2.button("Foto", icon=":material/photo_camera:", key="at_foto", width="stretch"):
        st.session_state["_rapido_modo"] = "foto"
        st.switch_page("telas/lancamento_rapido.py")
    if a3.button(f"Caixa ({n_caixa})" if n_caixa else "Caixa", icon=":material/inbox:", key="at_caixa",
                 width="stretch"):
        st.switch_page("telas/caixa_entrada.py")

# --- precisa de atenção --------------------------------------------------------------------------
itens = inicio.atencao(u, n_caixa)
st.markdown("<div class='ui-sec'>Precisa de atenção</div>", unsafe_allow_html=True)
if not itens:
    _ui.render("<div class='ui-tudo-ok'>✅ Tudo em dia por aqui.</div>")
else:
    ICO = {"alto": ":material/error:", "medio": ":material/schedule:", "info": ":material/info:"}
    with st.container(key="pendencias"):
        for i, it in enumerate(itens):
            with st.container(key=f"pend_{it['nivel']}_{i}"):
                st.page_link(it["pagina"], label=f"**{it['titulo']}**  \n{it['sub']}", icon=ICO[it["nivel"]],
                             width="stretch")

st.page_link("telas/painel.py", label="Ver o fluxo de caixa completo", icon=":material/monitoring:")

"""Finanças do Casal — ponto de entrada.

Rodar local:  streamlit run app.py
"""
import streamlit as st

from core import auth, caixa, db, recorrencias
from core.fmt import hoje
from telas._comum import CSS, e_celular

st.set_page_config(page_title="Finanças", page_icon="💰", layout="wide",
                   initial_sidebar_state="auto")
st.markdown(CSS, unsafe_allow_html=True)

usuario = auth.exigir_login()
db.migrar()

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _completar_fixas(uid, dia):
    """Uma vez por dia: completa as contas fixas até 12 meses à frente."""
    return recorrencias.gerar({"id": uid})


try:
    _completar_fixas(usuario["id"], hoje())
except Exception:  # noqa: BLE001 — nunca impede o app de abrir
    pass

try:
    n_caixa = caixa.qtd_pendentes(usuario)
except Exception:  # noqa: BLE001 — tabela ainda não criada
    n_caixa = 0

paginas = {
    "Visão geral": [
        st.Page("telas/painel.py", title="Painel", icon=":material/dashboard:", default=True),
    ],
    "Movimento": [
        st.Page("telas/caixa_entrada.py", title=f"Caixa de entrada{f' ({n_caixa})' if n_caixa else ''}",
                icon=":material/inbox:"),
        st.Page("telas/lancamento_rapido.py", title="Lançamento rápido", icon=":material/photo_camera:"),
        st.Page("telas/novo_lancamento.py", title="Novo lançamento", icon=":material/add_circle:"),
        st.Page("telas/lancamentos.py", title="Lançamentos", icon=":material/receipt_long:"),
        st.Page("telas/contas_fixas.py", title="Contas fixas", icon=":material/event_repeat:"),
    ],
    "Importar": [
        st.Page("telas/importar_fatura.py", title="Fatura de cartão", icon=":material/credit_card:"),
        st.Page("telas/importar.py", title="Planilha", icon=":material/upload_file:"),
    ],
    "Cadastros": [
        st.Page("telas/contas.py", title="Contas e cartões", icon=":material/account_balance:"),
        st.Page("telas/categorias.py", title="Categorias", icon=":material/category:"),
        st.Page("telas/casal.py", title="Casal e privacidade", icon=":material/group:"),
        st.Page("telas/atalho.py", title="Atalho do iPhone", icon=":material/phone_iphone:"),
    ],
}

nav = st.navigation(paginas)

with st.sidebar:
    st.caption(f"Conectado como **{usuario['nome']}**  \n{usuario['email']}")
    st.toggle("📱 Layout de celular", value=e_celular(), key="modo_celular")
    st.button("Sair", icon=":material/logout:", on_click=auth.sair, use_container_width=True)

nav.run()

"""Finanças do Casal — ponto de entrada.

Rodar local:  streamlit run app.py
"""
import streamlit as st

from core import auth
from telas._comum import CSS, e_celular

st.set_page_config(page_title="Finanças", page_icon="💰", layout="wide",
                   initial_sidebar_state="auto")
st.markdown(CSS, unsafe_allow_html=True)

usuario = auth.exigir_login()

paginas = {
    "Visão geral": [
        st.Page("telas/painel.py", title="Painel", icon=":material/dashboard:", default=True),
    ],
    "Movimento": [
        st.Page("telas/novo_lancamento.py", title="Novo lançamento", icon=":material/add_circle:"),
        st.Page("telas/lancamentos.py", title="Lançamentos", icon=":material/receipt_long:"),
        st.Page("telas/importar.py", title="Importar", icon=":material/upload_file:"),
    ],
    "Cadastros": [
        st.Page("telas/contas.py", title="Contas e cartões", icon=":material/account_balance:"),
        st.Page("telas/categorias.py", title="Categorias", icon=":material/category:"),
        st.Page("telas/casal.py", title="Casal e privacidade", icon=":material/group:"),
    ],
}

nav = st.navigation(paginas)

with st.sidebar:
    st.caption(f"Conectado como **{usuario['nome']}**  \n{usuario['email']}")
    st.toggle("📱 Layout de celular", value=e_celular(), key="modo_celular")
    st.button("Sair", icon=":material/logout:", on_click=auth.sair, use_container_width=True)

nav.run()

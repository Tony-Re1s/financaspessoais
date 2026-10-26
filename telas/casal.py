import streamlit as st

from core import repo
from core.padroes import VISIBILIDADES
from telas import _ui
from telas._comum import col_rs, em_reais, usuario

u = usuario()
_ui.titulo("Casal e privacidade", "💑")

g = repo.grupo(u)
with st.form("grupo"):
    nome = st.text_input("Nome do grupo", g["nome"])
    if st.form_submit_button("Renomear"):
        repo.renomear_grupo(u, nome.strip()); st.rerun()

st.subheader("Membros")
st.dataframe(repo.membros(u)[["nome", "email", "papel"]], hide_index=True, use_container_width=True,
             column_config={"nome": "Nome", "email": "E-mail", "papel": "Papel"})

pend = repo.convites(u)
if not pend.empty:
    st.caption("Convites pendentes (viram membros no 1º login):")
    for r in pend.itertuples():
        c1, c2 = st.columns([4, 1])
        c1.write(r.email)
        if c2.button("Cancelar", key=f"cc_{r.email}"):
            repo.cancelar_convite(u, r.email); st.rerun()

if u.get("admin"):
    st.page_link("telas/usuarios.py", label="Convidar alguém e definir o que pode fazer",
                 icon=":material/admin_panel_settings:")
else:
    st.caption("Convites são feitos pelo administrador do app.")

st.divider()
st.subheader("Como funciona a privacidade")
st.markdown("""
Cada lançamento tem um nível de visibilidade. Se ele não tiver um próprio, **herda da categoria**;
se a categoria não tiver, **herda da conta**; se nada estiver definido, é **privado**.

| Nível | O outro vê… |
|---|---|
| 🔒 Privado | nada |
| 👥 Compartilhado | o lançamento completo (na visão **Nós**) |
| Σ Só o total | o valor entra nas somas e gráficos da visão **Nós**, sem descrição nem linha a linha |

Para mudar em bloco, ajuste a visibilidade da **conta** (ex.: cartão da casa = compartilhado)
ou da **categoria** (ex.: Moradia = compartilhado, Cuidados Pessoais = privado).
""")

st.subheader("O que você está mostrando hoje")
rv = repo.resumo_visibilidade(u)
if rv.empty:
    st.caption("Sem lançamentos ainda.")
else:
    rv["visibilidade"] = rv["visibilidade"].map(VISIBILIDADES)
    rv["valor"] = rv["valor"].astype(float)
    st.dataframe(em_reais(rv), hide_index=True, use_container_width=True,
                 column_config={"visibilidade": "Nível", "lancamentos": "Lançamentos", "valor": col_rs("Total")})

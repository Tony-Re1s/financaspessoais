import pandas as pd
import streamlit as st

from core import repo
from core.padroes import NATUREZAS_IR, VISIBILIDADES
from telas._comum import usuario

u = usuario()
st.title("Categorias")
if msg := st.session_state.pop("_ok_cat", None):
    st.success(msg)

tipo = st.segmented_control("Tipo", ["despesa", "receita"], default="despesa",
                            format_func=lambda t: "Despesas" if t == "despesa" else "Receitas") or "despesa"
df = repo.categorias(u, tipo)
pais = df[df["pai_id"].isna()].sort_values("nome")

vis_label = {None: "herda"} | {k: v.split(" — ")[0] for k, v in VISIBILIDADES.items()}
col_a, col_b = st.columns(2)
for i, pai in enumerate(pais.itertuples()):
    filhos = df[df["pai_id"] == pai.id]
    with (col_a if i % 2 == 0 else col_b).expander(f"**{pai.nome}** · {len(filhos)}"):
        for f in filhos.itertuples():
            extras = []
            if isinstance(f.natureza_ir, str):
                extras.append(f"🧾 {NATUREZAS_IR[f.natureza_ir].split(' (')[0]}")
            vis = None if pd.isna(f.visibilidade) else f.visibilidade
            if vis:
                extras.append(vis_label[vis])
            st.markdown(f"- {f.nome}" + (f"  \n  <small>{' · '.join(extras)}</small>" if extras else ""),
                        unsafe_allow_html=True)

st.divider()
st.subheader("Criar ou editar")
acao = st.radio("Ação", ["Nova subcategoria", "Nova categoria", "Editar existente"], horizontal=True,
                label_visibility="collapsed")

nomes_pai = {r.id: r.nome for r in pais.itertuples()}
with st.form("cat"):
    alvo = {}
    if acao == "Nova subcategoria":
        pai_id = st.selectbox("Dentro de", list(nomes_pai), format_func=nomes_pai.get)
    elif acao == "Editar existente":
        todos = {r.id: (f"{r.categoria_pai} › {r.nome}" if pd.notna(r.pai_id) else r.nome)
                 for r in df.itertuples()}
        cat_id = st.selectbox("Qual", list(todos), format_func=todos.get)
        alvo = df[df["id"] == cat_id].iloc[0].to_dict()
    nome = st.text_input("Nome", alvo.get("nome", ""))
    c1, c2 = st.columns(2)
    nat_keys = list(NATUREZAS_IR)
    nat_atual = alvo.get("natureza_ir") if alvo.get("natureza_ir") and not pd.isna(alvo.get("natureza_ir")) else None
    natureza = c1.selectbox("Imposto de Renda", nat_keys, index=nat_keys.index(nat_atual),
                            format_func=NATUREZAS_IR.get, help="Marque o que é dedutível na declaração.")
    vis_keys = list(vis_label)
    vis_atual = alvo.get("visibilidade") if alvo.get("visibilidade") and not pd.isna(alvo.get("visibilidade")) else None
    visib = c2.selectbox("Quem vê", vis_keys, index=vis_keys.index(vis_atual),
                         format_func=lambda k: "Herdar da conta" if k is None else VISIBILIDADES[k])
    if st.form_submit_button("Salvar", type="primary"):
        if not nome.strip():
            st.error("Informe o nome.")
        else:
            if acao == "Editar existente":
                repo.salvar_categoria(u, nome.strip(), natureza_ir=natureza, visibilidade=visib, cat_id=cat_id)
            else:
                repo.salvar_categoria(u, nome.strip(), pai_id if acao == "Nova subcategoria" else None,
                                      tipo, natureza, visib)
            st.session_state["_ok_cat"] = f"Categoria **{nome}** salva."
            st.rerun()

import pandas as pd
import streamlit as st

from core import repo
from core.fmt import brl, hoje, mes_label, mes_ref, somar_meses
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, seletor_escopo, usuario

u = usuario()
topo_esq, topo_dir = st.columns([3, 1], vertical_alignment="bottom")
topo_esq.title("Lançamentos")
with topo_dir:
    escopo = seletor_escopo()

atual = mes_ref(hoje())
meses = [somar_meses(atual, k) for k in range(-12, 37)]
cel = e_celular()
rot_sit = {"todos": "Todas", "previsto": "⏳ Previstos", "pago": "✅ Pagos"}
if cel:   # celular: só o mês na frente; o resto recolhido
    ini = fim = st.selectbox("Mês", meses, index=12, format_func=mes_label)
    with st.expander("Filtros"):
        fim = st.selectbox("Até", [m for m in meses if m >= ini], index=0, format_func=mes_label)
        status_f = st.selectbox("Situação", list(rot_sit), format_func=rot_sit.get)
        busca = st.text_input("Buscar", placeholder="descrição, categoria, conta…")
else:
    f1, f2, f3, f4 = st.columns([1.2, 1.2, 1, 1.6])
    ini = f1.selectbox("De", meses, index=12, format_func=mes_label)
    fim = f2.selectbox("Até", [m for m in meses if m >= ini], index=0, format_func=mes_label)
    status_f = f3.selectbox("Situação", list(rot_sit), format_func=rot_sit.get)
    busca = f4.text_input("Buscar", placeholder="descrição, categoria, conta…")

df = repo.lancamentos(u, escopo, ini, fim)
if df.empty:
    st.info("Nada lançado nesse período.")
    st.stop()

with st.expander("Conta e categoria"):
    g1, g2 = st.columns(2)
    f_contas = g1.multiselect("Conta / cartão", sorted(df["conta"].dropna().unique()))
    f_cats = g2.multiselect("Categoria", sorted(df["categoria"].dropna().unique()))

if status_f != "todos":
    df = df[df["status"] == status_f]
if f_contas:
    df = df[df["conta"].isin(f_contas)]
if f_cats:
    df = df[df["categoria"].isin(f_cats)]
if busca:
    alvo = (df["descricao"].fillna("") + " " + df["categoria"].fillna("") + " " +
            df["subcategoria"].fillna("") + " " + df["conta"].fillna("")).str.lower()
    df = df[alvo.str.contains(busca.lower(), regex=False)]

df = df.reset_index(drop=True)
df["valor"] = df["valor"].astype(float)
df["parcela"] = df.apply(lambda r: f"{int(r.parcela_num)}/{int(r.parcela_total)}"
                         if pd.notna(r.parcela_num) else "", axis=1)
df["sit"] = df["status"].map({"previsto": "⏳", "pago": "✅"})

desp = df.loc[df["tipo"] == "despesa", "valor"].sum()
rec = df.loc[df["tipo"] == "receita", "valor"].sum()
cartoes_kpi([("Despesas", brl(desp)), ("Receitas", brl(rec)),
             ("A pagar", brl(df.loc[(df["tipo"] == "despesa") & (df["status"] == "previsto"), "valor"].sum())),
             ("Lançamentos", str(len(df)))])

if cel:   # 3 colunas que cabem na tela: dia, o quê, quanto
    vis = pd.DataFrame({
        "dia": df["sit"] + " " + pd.to_datetime(df["data_vencimento"]).dt.strftime("%d/%m"),
        "item": df["descricao"] + df["parcela"].map(lambda p: f" ({p})" if p else "")
                + (" · " + df["dono_nome"].fillna("") if escopo == "nos" else ""),
        "valor": df["valor"]})
    cfg = {"dia": st.column_config.TextColumn("Venc.", width=78), "item": "Lançamento",
           "valor": col_rs()}
else:
    colunas = ["sit", "data_vencimento", "descricao", "parcela", "categoria", "subcategoria", "conta", "valor"]
    if escopo == "nos":
        colunas.insert(1, "dono_nome")
    vis = df[colunas].fillna({"conta": "—", "categoria": "—", "subcategoria": ""})
    cfg = {"sit": st.column_config.TextColumn("", width=30), "dono_nome": "De quem",
           "data_vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
           "descricao": "Descrição", "parcela": "Parc.", "categoria": "Categoria",
           "subcategoria": "Subcategoria", "conta": "Conta", "valor": col_rs()}
st.caption("Toque/clique na caixinha à esquerda para selecionar e marcar como pago ou excluir.")
sel = st.dataframe(em_reais(vis), hide_index=True, use_container_width=True,
                   height=min(560, 35 * len(df) + 38), on_select="rerun", selection_mode="multi-row",
                   column_config=cfg)

linhas = sel.selection.rows
if linhas:
    escolhidos = df.iloc[linhas]
    meus = escolhidos[escolhidos["meu"]]
    st.write(f"**{len(escolhidos)} selecionado(s)** · {brl(escolhidos['valor'].sum())}"
             + ("" if len(meus) == len(escolhidos) else " · só os seus podem ser alterados"))
    ids = list(meus["id"])
    b1, b2, b3, _ = st.columns(4)
    if b1.button("✅ Marcar como pago", disabled=not ids, use_container_width=True):
        repo.mudar_status(u, ids, "pago"); st.rerun()
    if b2.button("⏳ Voltar para previsto", disabled=not ids, use_container_width=True):
        repo.mudar_status(u, ids, "previsto"); st.rerun()
    tem_parcela = meus["grupo_parcela"].notna().any()
    with b3.popover("🗑️ Excluir", disabled=not ids, use_container_width=True):
        futuras = st.checkbox("Excluir também as parcelas seguintes", value=False, disabled=not tem_parcela)
        st.caption("Não dá para desfazer.")
        if st.button("Confirmar exclusão", type="primary"):
            repo.excluir(u, ids, parcelas_futuras=futuras); st.rerun()

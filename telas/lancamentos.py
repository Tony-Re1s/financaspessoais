import pandas as pd
import streamlit as st

from core import repo
from core.fmt import brl, hoje, mes_label, mes_ref, somar_meses
from telas import _ui
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, seletor_escopo, usuario

u = usuario()
topo_esq, topo_dir = st.columns([3, 1], vertical_alignment="bottom")
with topo_esq:
    _ui.titulo("Lançamentos", "📋")
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

_tipos = dict(zip(repo.contas(u, so_ativas=False)["nome"], repo.contas(u, so_ativas=False)["tipo"]))
_MEIO = {"cartao_credito": "💳 Cartão de crédito", "beneficio": "🍽️ VR/VA"}
df["meio"] = df["conta"].map(lambda c: "📄 Sem conta (boleto/pix)" if not isinstance(c, str)
                              else _MEIO.get(_tipos.get(c), "🏦 Conta corrente"))
ORIGENS = {"migracao": "📊 Planilha", "importacao": "📥 Fatura/extrato", "applepay": "📱 Caixa de entrada",
           "android": "📱 Caixa de entrada", "recorrencia": "🔁 Contas fixas", "manual": "✍️ Manual", "ia": "🤖 IA"}
df["origem_n"] = df["origem"].map(lambda o: ORIGENS.get(o, "Outro"))
df["categoria"] = df["categoria"].fillna("Sem categoria")
df["parc_tipo"] = df["parcela_num"].map(lambda p: "Parcelado" if pd.notna(p) else "À vista")
df["tipo_n"] = df["tipo"].map({"despesa": "↓ Despesas", "receita": "↑ Receitas", "transferencia": "🔁 Transferências"})

with st.container(border=True, key="filtros_lanc"):
    st.markdown("**Filtros**")
    q1, q2 = st.columns(2) if not cel else (st.container(), st.container())
    f_tipo = q1.pills("Tipo", sorted(df["tipo_n"].dropna().unique()), selection_mode="multi", key="f_tipo")
    f_meio = q2.pills("Meio de pagamento", sorted(df["meio"].unique()), selection_mode="multi", key="f_meio")
    g1, g2, g3 = st.columns(3) if not cel else (st.container(), st.container(), st.container())
    f_contas = g1.multiselect("Conta / cartão", sorted(df["conta"].dropna().unique()), placeholder="todas")
    f_cats = g2.multiselect("Categoria", sorted(df["categoria"].unique()), placeholder="todas")
    subs_disp = sorted(df[df["categoria"].isin(f_cats)]["subcategoria"].dropna().unique()) if f_cats else \
        sorted(df["subcategoria"].dropna().unique())
    f_subs = g3.multiselect("Subcategoria", subs_disp, placeholder="todas")
    h1, h2, h3 = st.columns([1.2, 1.2, 1.6]) if not cel else (st.container(), st.container(), st.container())
    f_parc = h1.pills("Parcelas", ["À vista", "Parcelado"], selection_mode="multi", key="f_parc")
    f_orig = h2.multiselect("Origem", sorted(df["origem_n"].unique()), placeholder="todas")
    vmax = float(df["valor"].astype(float).max() or 0)
    f_val = h3.slider("Valor (R$)", 0.0, max(vmax, 1.0), (0.0, max(vmax, 1.0)), step=10.0, key="f_val",
                      format="R$ %.0f")
    f_dup = st.toggle("Só possíveis duplicados (mesma descrição e valor no mesmo mês)", key="f_dup")

if f_tipo:
    df = df[df["tipo_n"].isin(f_tipo)]
if f_meio:
    df = df[df["meio"].isin(f_meio)]
if status_f != "todos":
    df = df[df["status"] == status_f]
if f_contas:
    df = df[df["conta"].isin(f_contas)]
if f_cats:
    df = df[df["categoria"].isin(f_cats)]
if f_subs:
    df = df[df["subcategoria"].isin(f_subs)]
if f_parc:
    df = df[df["parc_tipo"].isin(f_parc)]
if f_orig:
    df = df[df["origem_n"].isin(f_orig)]
if f_val and (f_val[0] > 0 or f_val[1] < vmax):
    df = df[(df["valor"].astype(float) >= f_val[0]) & (df["valor"].astype(float) <= f_val[1])]
if f_dup:
    _k = df["mes_ref"].astype(str) + "|" + df["descricao"].fillna("").map(_ui.sem_acento).str.replace(
        r"[^a-z0-9]", "", regex=True) + "|" + df["valor"].astype(float).round(2).astype(str)
    df = df[_k.duplicated(keep=False)]
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
periodo = mes_label(ini) if ini == fim else f"{mes_label(ini)} a {mes_label(fim)}"
cartoes_kpi([("Receitas − despesas", brl(rec - desp)), ("↓ Despesas", brl(desp)), ("↑ Receitas", brl(rec)),
             ("A pagar", brl(df.loc[(df["tipo"] == "despesa") & (df["status"] == "previsto"), "valor"].sum())),
             ("Lançamentos", str(len(df)))], titulo="Lançamentos", icone="📋", direita=periodo)

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

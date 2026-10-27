import pandas as pd
import streamlit as st

from core import repo
from core.fmt import brl, hoje, mes_label, mes_ref, somar_meses
from telas import _ui
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, seletor_escopo, usuario

u = usuario()
_ui.aviso_ok()
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

# --- tabela editável: muda direto na célula; a caixinha ✓ serve para pagar/excluir em lote -------------
from telas._comum import opcoes_categoria  # noqa: E402

_cats = repo.categorias(u)
_op_cat = opcoes_categoria(_cats, "despesa") | opcoes_categoria(_cats, "receita")
_rot_cat = {v: k for k, v in _op_cat.items()}           # rótulo -> id
_contas_df = repo.contas(u, so_ativas=False)
_op_conta = dict(zip(_contas_df["nome"], _contas_df["id"]))
SEM = "— sem categoria"
SEMC = "— sem conta"
SIT = {"pago": "✅ Pago", "previsto": "⏳ Previsto"}
SIT_R = {v: k for k, v in SIT.items()}


def _rotulo_cat(r):
    if not isinstance(r["categoria"], str) or r["categoria"] == "Sem categoria":
        return SEM
    rot = f"{r['categoria']} › {r['subcategoria']}" if isinstance(r["subcategoria"], str) else r["categoria"]
    return rot if rot in _rot_cat else (r["categoria"] if r["categoria"] in _rot_cat else rot)


base = pd.DataFrame({
    "sel": False,
    "situacao": df["status"].map(SIT).fillna(df["status"]),
    "data": pd.to_datetime(df["data_vencimento"]),
    "descricao": df["descricao"],
    "parcela": df["parcela"],
    "categoria": df.apply(_rotulo_cat, axis=1),
    "conta": df["conta"].fillna(SEMC),
    "valor": df["valor"].astype(float),
})
if escopo == "nos":
    base.insert(1, "de", df["dono_nome"])
op_cats_col = [SEM] + sorted(set(_op_cat.values()) | set(base["categoria"]) - {SEM})
op_contas_col = [SEMC] + sorted(set(_op_conta) | set(base["conta"]) - {SEMC})
cfg = {
    "sel": st.column_config.CheckboxColumn("✓", width=36, help="Marque para pagar ou excluir em lote"),
    "de": st.column_config.TextColumn("De quem", disabled=True),
    "situacao": st.column_config.SelectboxColumn("Situação", options=list(SIT.values()), width=110, required=True),
    "data": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY", width=110),
    "descricao": st.column_config.TextColumn("Descrição", width="medium"),
    "parcela": st.column_config.TextColumn("Parc.", disabled=True, width=60),
    "categoria": st.column_config.SelectboxColumn("Categoria › sub", options=op_cats_col, width="medium"),
    "conta": st.column_config.SelectboxColumn("Conta / cartão", options=op_contas_col, width=150),
    "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", min_value=0.0, step=0.01, width=110),
}
ordem = ["sel", "data", "descricao", "categoria", "valor"] if cel else \
    (["sel"] + (["de"] if escopo == "nos" else []) +
     ["situacao", "data", "descricao", "parcela", "categoria", "conta", "valor"])
st.caption("✏️ Edite direto na tabela (categoria, conta, situação, data, descrição, valor) — nada é gravado até "
           "você tocar em **Salvar alterações**. A coluna ✓ marca vários para pagar ou excluir de uma vez.")
chave_ed = f"ed_lanc_{ini}_{fim}_{escopo}_{len(df)}"
with st.form(f"form_{chave_ed}", border=False):
    editado = st.data_editor(base, column_config=cfg, column_order=ordem, hide_index=True, use_container_width=True,
                             height=min(600, 35 * len(base) + 40), key=chave_ed)
    mesma_desc = st.checkbox("Categoria nova vale também para os outros com a mesma descrição (todos os meses)")
    f1_, f2_, f3_, f4_ = st.columns([1.4, 1.2, 1.2, 1.2]) if not cel else (st.container(),) * 4
    salvar = f1_.form_submit_button("💾 Salvar alterações", type="primary", use_container_width=True)
    pagar = f2_.form_submit_button("✅ Marcados: pago", use_container_width=True)
    prever = f3_.form_submit_button("⏳ Marcados: previsto", use_container_width=True)
    apagar = f4_.form_submit_button("🗑️ Excluir marcados", use_container_width=True)
    a1_, a2_ = st.columns(2)
    conf_exc = a1_.checkbox("Confirmo a exclusão dos marcados (não dá para desfazer)")
    futuras = a2_.checkbox("Ao excluir, levar também as parcelas seguintes")

from core import db as _db  # noqa: E402

if salvar:
    campos = ["situacao", "data", "descricao", "categoria", "conta", "valor"]
    mud = (editado[campos].astype(str) != base[campos].astype(str)).any(axis=1)
    alterados = editado[mud]
    if alterados.empty:
        st.info("Nada foi alterado na tabela.")
    else:
        n, pulados = 0, 0
        _atual = _db.consultar("select id, categoria_id, conta_id from lancamentos where dono_id = :u and id = any(:ids)",
                               u=u["id"], ids=list(df.loc[alterados.index, "id"])).set_index("id")
        for idx, r in alterados.iterrows():
            orig = df.loc[idx]
            if not orig["meu"] or orig["id"] not in _atual.index:
                pulados += 1
                continue
            cat_id = _atual.loc[orig["id"], "categoria_id"] if r["categoria"] == base.loc[idx, "categoria"] else \
                (None if r["categoria"] == SEM else _rot_cat.get(r["categoria"], _atual.loc[orig["id"], "categoria_id"]))
            conta_id = _atual.loc[orig["id"], "conta_id"] if r["conta"] == base.loc[idx, "conta"] else \
                (None if r["conta"] == SEMC else _op_conta.get(r["conta"]))
            cat_id = None if pd.isna(cat_id) else cat_id
            conta_id = None if pd.isna(conta_id) else conta_id
            dv = pd.Timestamp(r["data"]).date() if pd.notna(r["data"]) else orig["data_vencimento"]
            dc = orig["data_compra"] if pd.notna(orig["data_compra"]) else dv
            repo.atualizar_lancamento(u, orig["id"], dict(descricao=str(r["descricao"] or orig["descricao"]).strip(),
                                                           valor=float(r["valor"]), categoria_id=cat_id,
                                                           conta_id=conta_id, data_compra=dc, data_vencimento=dv,
                                                           status=SIT_R.get(r["situacao"], orig["status"])))
            if mesma_desc and r["categoria"] != base.loc[idx, "categoria"]:
                _db.executar("""update lancamentos set categoria_id = :c, atualizado_em = now()
                                 where dono_id = :u and lower(descricao) = lower(:d)""",
                             c=cat_id, u=u["id"], d=orig["descricao"])
            n += 1
        st.session_state["_ui_ok"] = f"{n} lançamentos salvos." + (
            f" {pulados} do outro membro ficaram como estavam." if pulados else "")
        st.session_state.pop(chave_ed, None)
        st.rerun()

if pagar or prever or apagar:
    marcados = editado[editado["sel"]]
    escolhidos = df.loc[marcados.index]
    ids = list(escolhidos[escolhidos["meu"]]["id"])
    if not ids:
        st.warning("Marque na coluna ✓ os lançamentos (seus) que quer alterar.")
    elif apagar and not conf_exc:
        st.warning("Marque **Confirmo a exclusão** para excluir.")
    else:
        if apagar:
            repo.excluir(u, ids, parcelas_futuras=futuras)
            msg = f"{len(ids)} lançamentos excluídos."
        else:
            repo.mudar_status(u, ids, "pago" if pagar else "previsto")
            msg = f"{len(ids)} lançamentos marcados como {'pagos' if pagar else 'previstos'}."
        st.session_state["_ui_ok"] = msg
        st.session_state.pop(chave_ed, None)
        st.rerun()

import hashlib

import pandas as pd
import streamlit as st

from core import extratos, ia, repo
from core.fmt import brl
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, opcoes_categoria, usuario

u = usuario()
cel = e_celular()
st.title("Importar extrato de conta")
st.caption("Suba o extrato da conta corrente. O app separa o que é gasto, o que é pagamento de fatura (não conta "
           "de novo), Pix no crédito e transferência entre suas contas, e liga com o que já estava lançado.")

if msg := st.session_state.pop("_ok_ext", None):
    st.success(msg, icon=":material/check_circle:")

with st.expander("Bancos que o app já lê"):
    st.markdown("\n".join(f"- {n}" for n, *_ in extratos.LEITORES))
    st.caption("Outro banco? Mande um arquivo de exemplo que o leitor dele é acrescentado.")

arqs = st.file_uploader("Arquivo(s) do extrato — pode subir vários meses do mesmo banco",
                        type=["xls", "xlsx", "csv"], accept_multiple_files=True, key="up_extrato")
if not arqs:
    st.stop()
try:
    ex = extratos.ler([(a.name, a.getvalue()) for a in arqs])
except extratos.FormatoDesconhecido as e:
    st.warning(f"Ainda não conheço o formato de **{e}**. Mande um exemplo que eu crio o leitor.")
    st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"Não consegui ler: {e}")
    st.stop()
for a in ex.avisos:
    st.info(a, icon=":material/info:")
assinatura = hashlib.sha1(b"".join(a.getvalue() for a in arqs)).hexdigest()[:12]

# --- conta ------------------------------------------------------------------------------------
contas = repo.contas(u)
cc = contas[contas["tipo"].isin(["conta_corrente", "poupanca"])]
sug = extratos.conta_sugerida(u, ex, contas)
op = {"__nova__": f"➕ Criar conta “{ex.banco}”"} | dict(zip(cc["id"], cc["nome"]))
ids = list(op)
c1, c2 = st.columns([1.4, 1])
conta_id = c1.selectbox("Conta no app", ids, format_func=op.get,
                        index=ids.index(sug) if sug in ids else 0,
                        help=f"{ex.banco}" + (f" · conta {ex.conta_banco}" if ex.conta_banco else ""))
if conta_id == "__nova__":
    nome_nova = c2.text_input("Nome da conta", ex.banco)
    if st.button("Criar conta", type="primary"):
        repo.salvar_conta(u, dict(nome=nome_nova.strip(), tipo="conta_corrente", instituicao=ex.banco,
                                  visibilidade="privado", ativa=True))
        st.rerun()
    st.stop()

regs = extratos.preparar(u, conta_id, ex)
ini, fim = min(ln.data for ln in ex.linhas), max(ln.data for ln in ex.linhas)
lanc = regs[(regs["acao"] == "lancar")]
novas = lanc[lanc["situacao"] == "nova"].copy()
transf = regs[regs["acao"].isin(["transf_entra", "transf_saida"]) & (regs["situacao"] != "ja_importada")]
ja = regs[regs["situacao"].isin(["ja_no_app", "ja_importada"]) & (regs["acao"] == "lancar")]
fora = regs[regs["situacao"].isin(["fatura", "pix_credito"])]

ent = lanc.loc[lanc["valor"] > 0, "valor"].sum()
sai = -lanc.loc[lanc["valor"] < 0, "valor"].sum()
kpis = [("Período", f"{ini:%d/%m} a {fim:%d/%m}"), ("Entradas (sem transf.)", brl(ent)), ("Gastos", brl(sai))]
if ex.saldos:
    kpis.append((f"Saldo no banco {ex.saldos[-1][0]:%d/%m}", brl(ex.saldos[-1][1])))
cartoes_kpi(kpis)

# --- categorias -------------------------------------------------------------------------------
cats = repo.categorias(u)
op_cat = opcoes_categoria(cats, "despesa") | opcoes_categoria(cats, "receita")
id_por_rot = {v: k for k, v in op_cat.items()}
por_caminho = extratos.categorias_por_caminho(u)
hist = extratos.sugerir_por_historico(u, list(novas["nome_curto"]))
chave_ia = f"ext_ia_{assinatura}_{conta_id}"


def _cat_inicial(r):
    if r.categoria_path:
        c = por_caminho.get(extratos._sem_acento(r.categoria_path).lower())
        if c:
            return c
    if hist.get(r.nome_curto):
        return hist[r.nome_curto]
    return st.session_state.get(chave_ia, {}).get(r.i)


novas["categoria_id"] = [_cat_inicial(r) for r in novas.itertuples()]

if not novas.empty:
    st.subheader(f"Lançamentos novos ({len(novas)})")
    sem = novas["categoria_id"].isna().sum()
    if sem and ia.chave() and (u.get("admin") or u.get("permissoes", {}).get("ia")):
        if st.button(f"✨ Sugerir categoria dos {sem} sem categoria com IA", key="ia_cat"):
            alvo = novas[novas["categoria_id"].isna()]
            with st.spinner("Classificando…"):
                try:
                    res = ia.categorizar([(r.descricao, r.valor) for r in alvo.itertuples()], op_cat)
                    st.session_state[chave_ia] = {i: c for i, c in zip(alvo["i"], res) if c}
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"IA indisponível: {e}")
    ed = pd.DataFrame({"importar": True, "data": pd.to_datetime(novas["data"]), "descricao": novas["nome_curto"],
                       "valor": novas["valor"].astype(float),
                       "categoria": novas["categoria_id"].map(lambda c: op_cat.get(c))}, index=novas.index)
    cfg = {"importar": st.column_config.CheckboxColumn("✓", width=40),
           "data": st.column_config.DateColumn("Data", format="DD/MM", disabled=True),
           "descricao": st.column_config.TextColumn("Descrição"),
           "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", disabled=True),
           "categoria": st.column_config.SelectboxColumn("Categoria", options=list(id_por_rot), width="medium")}
    editado = st.data_editor(ed, column_config=cfg, hide_index=True, use_container_width=True,
                             column_order=["importar", "descricao", "valor", "categoria"] if cel else list(cfg),
                             key=f"ed_ext_{assinatura}_{conta_id}", height=min(38 + 35 * len(ed), 560))
    st.caption("Valor positivo = entrada. Edite a descrição se quiser; o texto original fica guardado na observação.")
else:
    editado = None
    st.success("Nenhum lançamento novo — tudo já está no app.", icon=":material/done_all:")

if not transf.empty:
    with st.expander(f"🔁 Transferências entre contas e resgates ({len(transf)}) — não contam como gasto/receita"):
        v = transf.assign(situ=transf["situacao"].map({"nova": "nova", "ja_no_app": "liga com a outra conta"}))
        st.dataframe(em_reais(v[["data", "descricao", "valor", "situ"]]), hide_index=True, use_container_width=True,
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM"),
                                    "descricao": "Descrição", "valor": col_rs(), "situ": "Situação"})
if not ja.empty:
    with st.expander(f"✅ Já estavam no app ({len(ja)}) — viram pagos com o valor do extrato"):
        v = ja.assign(no_app=ja["existente_desc"].fillna("importado antes"))
        st.dataframe(em_reais(v[["data", "nome_curto", "valor", "no_app"]]), hide_index=True,
                     use_container_width=True,
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM"),
                                    "nome_curto": "No extrato", "valor": col_rs(), "no_app": "No app como"})
if not fora.empty:
    with st.expander(f"💳 Faturas e Pix no crédito ({len(fora)}) — não contam como gasto"):
        v = fora.assign(motivo=fora["situacao"].map({"fatura": "pagamento de fatura — sai da conta, mas não é gasto (as compras estão no cartão)",
                                                    "pix_credito": "Pix no crédito (gasto já está no cartão)"}))
        st.dataframe(em_reais(v[["data", "descricao", "valor", "motivo"]]), hide_index=True,
                     use_container_width=True,
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM"),
                                    "descricao": "Descrição", "valor": col_rs(), "motivo": "Por quê"})
        st.caption("Pagamento de fatura: se a fatura de mesmo valor está no app, ela é marcada como paga; senão entra "
                   "como transferência para o cartão (o saldo da conta bate e o gasto não conta duas vezes).")

# --- gravar -----------------------------------------------------------------------------------
regs["importar"] = True
if editado is not None:
    regs.loc[editado.index, "importar"] = editado["importar"].values
    regs.loc[editado.index, "nome_curto"] = editado["descricao"].values
    regs["categoria_id"] = None
    regs.loc[editado.index, "categoria_id"] = editado["categoria"].map(id_por_rot.get).values
n_novas = int(editado["importar"].sum()) if editado is not None else 0
st.markdown(f"**{n_novas}** novos · **{len(ja[ja['situacao'] == 'ja_no_app'])}** viram pagos · "
            f"**{len(transf)}** transferências" + (f" · **{len(ex.saldos)}** saldos diários" if ex.saldos else ""))
if st.button("Importar extrato", type="primary", icon=":material/download_done:", use_container_width=True):
    r = extratos.gravar(u, conta_id, ex, regs, ", ".join(a.name for a in arqs))
    st.session_state["_ok_ext"] = (f"Extrato importado: {r['novos']} lançamentos novos, {r['pagos']} marcados como "
                                   f"pagos, {r['transf']} transferências, {r['faturas']} faturas baixadas"
                                   + (f", {r['saldos']} saldos" if r["saldos"] else "") + ".")
    st.rerun()

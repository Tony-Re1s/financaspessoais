from datetime import date

import pandas as pd
import streamlit as st

from core import recorrencias as rec
from core import repo
from core.fmt import brl, hoje
from core.padroes import VISIBILIDADES
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, opcoes_categoria, usuario

u = usuario()
st.title("Contas fixas")
st.caption("Aluguel, condomínio, escola, assinaturas… Cadastre uma vez: o app lança os próximos 12 meses como "
           "*previstos* e vai completando sozinho. Se o lançamento já existir (planilha, fatura), ele só liga.")

if msg := st.session_state.pop("_ok_rec", None):
    st.success(msg, icon=":material/check_circle:")

contas = repo.contas(u)
op_contas = {None: "— sem conta (boleto, pix…)"} | {r.id: r.nome for r in contas.itertuples()}
cats = repo.categorias(u)
op_cat = opcoes_categoria(cats, "despesa") | opcoes_categoria(cats, "receita")
df = rec.listar(u)

ativas = df[df["ativa"]] if not df.empty else df
desp = ativas[ativas["tipo"] == "despesa"]["valor"].astype(float).sum() if not ativas.empty else 0
rec_ = ativas[ativas["tipo"] == "receita"]["valor"].astype(float).sum() if not ativas.empty else 0
cartoes_kpi([("Contas fixas ativas", str(len(ativas))), ("Saem por mês", brl(desp)),
             ("Entram por mês", brl(rec_)), ("Saldo fixo", brl(rec_ - desp))])

if not df.empty:
    v = df.copy()
    v["valor"] = v["valor"].astype(float)
    v["quando"] = v.apply(lambda r: f"dia {int(r.dia_vencimento)}" if pd.notna(r.dia_vencimento) else "—", axis=1)
    v["sit"] = v["ativa"].map({True: "✅", False: "⏸️"})
    cols = ["sit", "descricao", "quando", "valor"] if e_celular() else \
        ["sit", "descricao", "quando", "conta", "proxima", "valor"]
    st.dataframe(em_reais(v[cols].fillna({"conta": "—"})), hide_index=True, use_container_width=True,
                 column_config={"sit": st.column_config.TextColumn("", width=30), "descricao": "Conta fixa",
                                "quando": "Cobra", "conta": "Conta/cartão",
                                "proxima": st.column_config.DateColumn("Próxima", format="DD/MM/YY"),
                                "valor": col_rs()})

# --- sugestões a partir do que já está lançado ------------------------------------------------
sug = rec.sugestoes(u)
if not sug.empty:
    with st.expander(f"💡 {len(sug)} gastos que parecem fixos (repetem o mesmo valor todo mês)"):
        st.caption("Marque os que são contas fixas. Os lançamentos que já existem são aproveitados.")
        s = pd.DataFrame({"usar": False, "descricao": sug["descricao"], "conta": sug["conta"].fillna("—"),
                          "valor": sug["valor"].astype(float), "meses": sug["meses"],
                          "ate": pd.to_datetime(sug["ultimo"])})
        ed = st.data_editor(s, hide_index=True, use_container_width=True, key="ed_sug",
                            column_config={"usar": st.column_config.CheckboxColumn("✓", width=40),
                                           "descricao": st.column_config.TextColumn("Descrição", disabled=True),
                                           "conta": st.column_config.TextColumn("Conta", disabled=True),
                                           "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f",
                                                                                  disabled=True),
                                           "meses": st.column_config.NumberColumn("Meses", disabled=True),
                                           "ate": st.column_config.DateColumn("Lançado até", format="MM/YY",
                                                                              disabled=True)})
        st.caption("Se a série termina antes de um ano (ex.: parcelas sem número), a conta fixa acaba junto.")
        marcados = ed.index[ed["usar"]].tolist()
        if st.button(f"Transformar {len(marcados)} em contas fixas", disabled=not marcados, type="primary"):
            for i in marcados:
                r = sug.loc[i]
                conta = contas[contas["id"] == r["conta_id"]]
                dia = int(r["dia"]) if pd.notna(r["dia"]) else 10
                if not conta.empty and conta.iloc[0]["tipo"] == "cartao_credito" and pd.notna(conta.iloc[0]["dia_vencimento"]):
                    dia = max(1, int(conta.iloc[0]["dia_vencimento"]) - 10)   # cai na fatura daquele mês
                ultimo = pd.Timestamp(r["ultimo"]).date()
                acaba = ultimo if (ultimo - hoje()).days < 330 else None   # série curta = parcelas, não fixa
                rec.salvar(u, dict(descricao=r["descricao"], valor=float(r["valor"]), conta_id=r["conta_id"],
                                   categoria_id=r["categoria_id"], tipo="despesa", frequencia="mensal",
                                   dia_vencimento=dia, inicio=pd.Timestamp(r["primeiro"]).date(), fim=acaba,
                                   visibilidade=None, ativa=True))
            st.session_state["_ok_rec"] = f"{len(marcados)} contas fixas criadas."
            st.rerun()

# --- cadastro / edição ------------------------------------------------------------------------
st.divider()
op = {None: "➕ Nova conta fixa"} | {r.id: f"Editar: {r.descricao}" for r in df.itertuples()}
escolha = st.selectbox("O que fazer", list(op), format_func=op.get, key="rec_escolha")
a = df[df["id"] == escolha].iloc[0].to_dict() if escolha else {}


def _v(k, padrao=None):
    x = a.get(k)
    return padrao if x is None or (not isinstance(x, str) and pd.isna(x)) else x


with st.form(f"rec_{escolha}"):
    tipo = st.segmented_control("Tipo", ["despesa", "receita"], default=_v("tipo", "despesa"),
                                format_func=lambda t: "💸 Despesa" if t == "despesa" else "💰 Receita (salário…)")
    c1, c2 = st.columns([2, 1])
    descricao = c1.text_input("Descrição", _v("descricao", ""), placeholder="Ex.: Condomínio")
    valor = c2.number_input("Valor (R$)", 0.0, value=float(_v("valor", 0.0)), step=10.0, format="%.2f")
    c1, c2 = st.columns(2)
    cat_ids = list(op_cat)
    categoria_id = c1.selectbox("Categoria", cat_ids, format_func=op_cat.get, placeholder="Categoria",
                                index=cat_ids.index(a["categoria_id"]) if a.get("categoria_id") in cat_ids else None)
    conta_ids = list(op_contas)
    conta_id = c2.selectbox("Conta / cartão", conta_ids, format_func=op_contas.get,
                            index=conta_ids.index(a["conta_id"]) if a.get("conta_id") in conta_ids else 0,
                            help="No cartão, o dia abaixo é o dia da cobrança; o app joga na fatura certa.")
    c1, c2, c3 = st.columns(3)
    dia = c1.number_input("Dia", 1, 31, int(_v("dia_vencimento", hoje().day)))
    freq = c2.selectbox("Repete", ["mensal", "anual"], index=1 if _v("frequencia") == "anual" else 0,
                        format_func=str.capitalize)
    inicio = c3.date_input("A partir de", _v("inicio", date(hoje().year, hoje().month, 1)), format="DD/MM/YYYY")
    c1, c2 = st.columns(2)
    tem_fim = c1.toggle("Tem data para acabar", value=_v("fim") is not None)
    fim = c2.date_input("Até", _v("fim", hoje()), format="DD/MM/YYYY", disabled=not tem_fim)
    op_vis = {None: "Herdar da categoria/conta"} | VISIBILIDADES
    vis_ids = list(op_vis)
    vis = st.selectbox("Quem vê", vis_ids, format_func=op_vis.get,
                       index=vis_ids.index(a["visibilidade"]) if a.get("visibilidade") in vis_ids else 0)
    ok = st.form_submit_button("Salvar", type="primary", icon=":material/save:")

if ok:
    if not descricao.strip() or valor <= 0:
        st.error("Preencha descrição e valor.")
    else:
        rec.salvar(u, dict(descricao=descricao.strip(), valor=valor, conta_id=conta_id, categoria_id=categoria_id,
                           tipo=tipo or "despesa", frequencia=freq, dia_vencimento=int(dia), inicio=inicio,
                           fim=fim if tem_fim else None, visibilidade=vis, ativa=True), escolha)
        st.session_state["_ok_rec"] = f"**{descricao}** salva — lançamentos dos próximos 12 meses prontos."
        st.rerun()

if escolha:
    c1, c2 = st.columns(2)
    if a.get("ativa"):
        if c1.button("⏸️ Encerrar", use_container_width=True,
                     help="Para de gerar e tira os previstos futuros. O que já passou fica."):
            rec.encerrar(u, escolha)
            st.session_state["_ok_rec"] = "Conta fixa encerrada."
            st.rerun()
    else:
        if c1.button("▶️ Reativar", use_container_width=True):
            rec.salvar(u, a | {"ativa": True}, escolha)
            st.rerun()
    with c2.popover("🗑️ Excluir", use_container_width=True):
        st.caption("Apaga a conta fixa e os previstos futuros. Pagos e passados ficam.")
        if st.button("Excluir de vez", type="primary"):
            rec.encerrar(u, escolha, apagar=True)
            st.session_state["_ok_rec"] = "Conta fixa excluída."
            st.rerun()

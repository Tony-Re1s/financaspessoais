import pandas as pd
import streamlit as st

from core import repo
from core.padroes import TIPOS_CONTA, VISIBILIDADES
from telas._comum import col_rs, e_celular, em_reais, usuario

u = usuario()
st.title("Contas e cartões")
if msg := st.session_state.pop("_ok_conta", None):
    st.success(msg)

df = repo.contas(u, so_ativas=False)

if df.empty:
    st.info("Nenhuma conta ainda. Cadastre abaixo — ou rode a migração da planilha, que já cria os cartões.")
else:
    vis = df.copy()
    vis["tipo"] = vis["tipo"].map(TIPOS_CONTA)
    vis["visibilidade"] = vis["visibilidade"].map(lambda v: VISIBILIDADES[v].split(" — ")[0])
    vis["limite"] = vis["limite"].astype(float)
    cols = (["nome", "tipo", "dia_vencimento"] if e_celular() else
            ["nome", "tipo", "instituicao", "dia_fechamento", "dia_vencimento", "limite", "visibilidade", "ativa"])
    st.dataframe(em_reais(vis, "limite")[cols],
                 hide_index=True, use_container_width=True,
                 column_config={"nome": "Nome", "tipo": "Tipo", "instituicao": "Instituição",
                                "dia_fechamento": "Fecha dia", "dia_vencimento": "Vence dia",
                                "limite": col_rs("Limite"), "visibilidade": "Quem vê", "ativa": "Ativa"})

st.divider()
op = {None: "➕ Nova conta"} | {r.id: f"Editar: {r.nome}" for r in df.itertuples()}
escolha = st.selectbox("O que fazer", list(op), format_func=op.get)
atual = df[df["id"] == escolha].iloc[0].to_dict() if escolha else {}


def _int(v):
    return None if v is None or pd.isna(v) else int(v)


with st.form("conta", border=True):
    c1, c2, c3 = st.columns(3)
    nome = c1.text_input("Nome", atual.get("nome", ""), placeholder="Ex.: Latam Black")
    tipos = list(TIPOS_CONTA)
    tipo = c2.selectbox("Tipo", tipos, index=tipos.index(atual.get("tipo", "conta_corrente")),
                        format_func=TIPOS_CONTA.get)
    instituicao = c3.text_input("Instituição", atual.get("instituicao") or "", placeholder="Itaú, Nubank…")

    st.caption("Só para cartão de crédito:")
    c1, c2, c3 = st.columns(3)
    fech = c1.number_input("Dia de fechamento", 0, 31, _int(atual.get("dia_fechamento")) or 0,
                           help="0 = não sei (o app assume 7 dias antes do vencimento)")
    venc = c2.number_input("Dia de vencimento", 0, 31, _int(atual.get("dia_vencimento")) or 0)
    limite = c3.number_input("Limite (R$)", 0.0, value=float(atual.get("limite") or 0), step=500.0)
    bancos = df[df["tipo"].isin(["conta_corrente", "poupanca", "carteira"]) & (df["id"] != escolha)]
    op_deb = {None: "— não tem função débito"} | {r.id: r.nome for r in bancos.itertuples()}
    deb_atual = atual.get("conta_debito_id")
    deb_atual = None if deb_atual is None or pd.isna(deb_atual) else deb_atual
    conta_deb = st.selectbox("Função débito sai da conta", list(op_deb), format_func=op_deb.get,
                             index=list(op_deb).index(deb_atual) if deb_atual in op_deb else 0,
                             help="Se este cartão também passa no débito, de qual conta corrente sai o dinheiro. "
                                  "Usado pela Caixa de entrada quando você escolhe Débito.")

    c1, c2 = st.columns(2)
    vis_keys = list(VISIBILIDADES)
    visib = c1.selectbox("Quem vê os lançamentos desta conta", vis_keys,
                         index=vis_keys.index(atual.get("visibilidade", "privado")),
                         format_func=VISIBILIDADES.get)
    ativa = c2.toggle("Conta ativa", value=bool(atual.get("ativa", True)))

    if st.form_submit_button("Salvar", type="primary"):
        if not nome.strip():
            st.error("Dê um nome para a conta.")
        else:
            repo.salvar_conta(u, dict(nome=nome.strip(), tipo=tipo, instituicao=instituicao or None,
                                      dia_fechamento=fech or None, dia_vencimento=venc or None,
                                      limite=limite or None, visibilidade=visib, ativa=ativa,
                                      conta_debito_id=conta_deb if tipo == "cartao_credito" else None,
                                      saldo_inicial=atual.get("saldo_inicial"),
                                      data_saldo_inicial=atual.get("data_saldo_inicial")),
                              conta_id=escolha)
            st.session_state["_ok_conta"] = f"Conta **{nome}** salva."
            st.rerun()

st.caption("Saldos e aplicações entram no próximo módulo (Saldos e patrimônio).")

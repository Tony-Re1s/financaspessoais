import pandas as pd
import streamlit as st

from core import repo
from core.fmt import brl, hoje, vencimento_fatura
from core.padroes import FORMAS_PAGAMENTO, TIPOS_CONTA, VISIBILIDADES
from telas._comum import col_rs, em_reais, opcoes_categoria, usuario

u = usuario()
st.title("Novo lançamento")

if msg := st.session_state.pop("_ok_lanc", None):
    st.success(msg, icon=":material/check_circle:")

contas = repo.contas(u)
cats = repo.categorias(u)

# --- o essencial, na ordem de um app de banco: tipo, valor, o quê, onde ----------------
tipo = st.segmented_control("Tipo", ["despesa", "receita"], default="despesa", label_visibility="collapsed",
                            format_func=lambda t: "💸 Despesa" if t == "despesa" else "💰 Receita") or "despesa"

c1, c2 = st.columns([2, 1])
valor = c1.number_input("Valor (R$)", min_value=0.0, step=10.0, format="%.2f", key="f_valor")
total_parc = c2.number_input("Parcelas", 1, 120, 1, key="f_ptot")
descricao = st.text_input("Descrição", placeholder="Ex.: Mercado, Aluguel, Salário", key="f_desc")

c1, c2 = st.columns(2)
op_cat = opcoes_categoria(cats, tipo)
categoria_id = c1.selectbox("Categoria", list(op_cat), format_func=op_cat.get, index=None,
                            placeholder="Escolha a categoria", key="f_cat")
op_contas = {None: "— sem conta (boleto, pix avulso…)"} | {
    r.id: f"{r.nome} · {TIPOS_CONTA.get(r.tipo, r.tipo)}" for r in contas.itertuples()}
conta_id = c2.selectbox("Conta / cartão", list(op_contas), format_func=op_contas.get, key="f_conta")

conta = contas[contas["id"] == conta_id].iloc[0] if conta_id else None
e_cartao = conta is not None and conta["tipo"] == "cartao_credito"

# --- o resto fica recolhido; os padrões já servem na maioria das vezes -------------------
with st.expander("Mais opções"):
    c1, c2 = st.columns(2)
    data_compra = c1.date_input("Data da compra", value=hoje(), format="DD/MM/YYYY")
    if e_cartao and pd.notna(conta["dia_vencimento"]):
        venc_sugerido = vencimento_fatura(data_compra, None if pd.isna(conta["dia_fechamento"])
                                          else int(conta["dia_fechamento"]), int(conta["dia_vencimento"]))
        ajuda = "Calculado pelo fechamento/vencimento do cartão. Pode ajustar."
    else:
        venc_sugerido, ajuda = data_compra, None
    data_venc = c2.date_input("Vencimento (quando sai do caixa)", value=venc_sugerido, format="DD/MM/YYYY",
                              help=ajuda, key=f"venc_{conta_id}_{data_compra}")

    c1, c2 = st.columns(2)
    forma_padrao = ("Cartao de Credito" if e_cartao else
                    "Debito em Conta" if conta is not None and conta["tipo"] == "conta_corrente" else "Boleto")
    forma = c1.selectbox("Forma de pagamento", FORMAS_PAGAMENTO, index=FORMAS_PAGAMENTO.index(forma_padrao),
                         key=f"forma_{conta_id}")
    op_vis = {None: "Herdar da categoria/conta"} | VISIBILIDADES
    visibilidade = c2.selectbox("Quem vê", list(op_vis), format_func=op_vis.get)

    status = st.radio("Situação", ["previsto", "pago"], horizontal=True,
                      format_func=lambda s: "⏳ A pagar / previsto" if s == "previsto" else "✅ Já pago")

    c1, c2 = st.columns(2)
    inicial = c1.number_input("Começar na parcela nº", 1, int(total_parc), 1, key="f_pini",
                              disabled=total_parc == 1,
                              help="Para cadastrar uma compra que já está correndo (ex.: hoje é a 4/10).")
    valor_e_total = c2.radio("O valor digitado é…", ["de cada parcela", "o total da compra"],
                             disabled=total_parc == 1) == "o total da compra"
    observacao = st.text_input("Observação", key="f_obs")

dados = dict(conta_id=conta_id, categoria_id=categoria_id, tipo=tipo, descricao=descricao.strip(),
             valor=valor, data_compra=data_compra, data_vencimento=data_venc, forma_pagamento=forma,
             status=status, visibilidade=visibilidade, observacao=observacao or None, origem="manual")
linhas = repo.plano_parcelas(dados, int(inicial), int(total_parc), valor_e_total)

# resumo do que vai ser gravado (mostra os padrões que ficaram recolhidos)
resumo = [f"Vence **{data_venc:%d/%m/%Y}**", forma.replace("Cartao de Credito", "cartão"),
          "já pago" if status == "pago" else "a pagar"]
if len(linhas) > 1:
    resumo.append(f"{len(linhas)}× · total {brl(sum(l['valor'] for l in linhas))}")
st.caption(" · ".join(resumo))

if len(linhas) > 1 and valor > 0:
    with st.expander(f"Ver as {len(linhas)} parcelas"):
        prev = pd.DataFrame([{"Parcela": f"{l['parcela_num']}/{l['parcela_total']}",
                              "Vencimento": l["data_vencimento"], "valor": l["valor"]} for l in linhas])
        st.dataframe(em_reais(prev), hide_index=True, use_container_width=True,
                     height=min(35 * len(prev) + 38, 300),
                     column_config={"Vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                    "valor": col_rs()})

faltando = [n for n, v in [("valor", valor > 0), ("descrição", descricao.strip()), ("categoria", categoria_id)]
            if not v]
if st.button("Salvar", type="primary", icon=":material/save:", disabled=bool(faltando),
             use_container_width=True, help=f"Falta: {', '.join(faltando)}" if faltando else None):
    n = repo.inserir_lancamentos(u, linhas)
    st.session_state["_ok_lanc"] = (f"{n} parcelas lançadas." if n > 1 else "Lançamento salvo.") + \
        f" {descricao} · {brl(sum(l['valor'] for l in linhas))}"
    for k in ("f_desc", "f_valor", "f_ptot", "f_pini", "f_obs", "f_cat"):
        st.session_state.pop(k, None)
    st.rerun()

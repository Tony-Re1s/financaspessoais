import pandas as pd
import streamlit as st

from core import caixa, repo
from core.fmt import FUSO, brl, vencimento_fatura
from core.padroes import TIPOS_CONTA
from telas._comum import opcoes_categoria, usuario

u = usuario()
st.title("Caixa de entrada")
st.caption("Compras que chegaram sozinhas (Apple Pay). Confira a categoria e o cartão e toque em **Lançar**.")

if msg := st.session_state.pop("_ok_caixa", None):
    st.success(msg, icon=":material/check_circle:")

pend = caixa.pendentes(u)
if pend.empty:
    st.info("Nada pendente. Quando você pagar com o Apple Pay, a compra aparece aqui.", icon=":material/inbox:")
    st.page_link("telas/atalho.py", label="Configurar o Atalho do iPhone", icon=":material/phone_iphone:")
else:
    contas = repo.contas(u)
    op_contas = {None: "— escolha o cartão/conta"} | {
        r.id: f"{r.nome} · {TIPOS_CONTA.get(r.tipo, r.tipo)}" for r in contas.itertuples()}
    op_cat = opcoes_categoria(repo.categorias(u), "despesa")

    for item in pend.itertuples():
        valor = caixa.valor_de_texto(item.valor_texto)
        quando = pd.Timestamp(item.recebido_em).tz_convert(FUSO)
        k = str(item.id)
        with st.container(border=True):
            topo, preco = st.columns([3, 1.3], vertical_alignment="center")
            topo.markdown(f"**{item.estabelecimento or 'Sem estabelecimento'}**  \n"
                          f"<small>{quando:%d/%m %H:%M} · {item.cartao or 'cartão?'}</small>",
                          unsafe_allow_html=True)
            preco.markdown(f"<div style='text-align:right;font-size:1.15rem;font-weight:600'>"
                           f"{brl(valor) if valor is not None else item.valor_texto}</div>",
                           unsafe_allow_html=True)

            sug_cat = caixa.sugerir_categoria(u, item.estabelecimento)
            sug_conta = caixa.conta_do_cartao(u, item.cartao)
            c1, c2 = st.columns(2)
            cat_ids = list(op_cat)
            categoria_id = c1.selectbox("Categoria", cat_ids, format_func=op_cat.get, key=f"cat_{k}",
                                        index=cat_ids.index(sug_cat) if sug_cat in cat_ids else None,
                                        placeholder="Categoria")
            conta_ids = list(op_contas)
            conta_id = c2.selectbox("Cartão / conta", conta_ids, format_func=op_contas.get, key=f"conta_{k}",
                                    index=conta_ids.index(sug_conta) if sug_conta in conta_ids else 0)

            with st.expander("Ajustar"):
                descricao = st.text_input("Descrição", item.estabelecimento or "", key=f"desc_{k}")
                a1, a2 = st.columns(2)
                valor_ed = a1.number_input("Valor (R$)", min_value=0.0, value=float(valor or 0), step=1.0,
                                           format="%.2f", key=f"val_{k}")
                parcelas = a2.number_input("Parcelas", 1, 48, 1, key=f"parc_{k}")
                lembrar = st.checkbox(f"Lembrar que “{item.cartao}” é este cartão", value=sug_conta is None,
                                      key=f"lemb_{k}", disabled=not item.cartao)

            b1, b2 = st.columns([2, 1])
            pode = bool(categoria_id) and bool(conta_id) and valor_ed > 0
            if b1.button("Lançar", key=f"ok_{k}", type="primary", icon=":material/check:",
                         disabled=not pode, use_container_width=True,
                         help=None if pode else "Escolha categoria e cartão"):
                compra = quando.date()
                conta = contas[contas["id"] == conta_id].iloc[0]
                if conta["tipo"] == "cartao_credito" and pd.notna(conta["dia_vencimento"]):
                    venc = vencimento_fatura(compra, None if pd.isna(conta["dia_fechamento"])
                                             else int(conta["dia_fechamento"]), int(conta["dia_vencimento"]))
                    forma = "Cartao de Credito"
                else:
                    venc, forma = compra, "Debito em Conta"
                dados = dict(conta_id=conta_id, categoria_id=categoria_id, descricao=descricao.strip() or "Apple Pay",
                             valor=valor_ed, data_compra=compra, data_vencimento=venc, forma_pagamento=forma,
                             visibilidade=None)
                linhas = repo.plano_parcelas(dados, 1, int(parcelas), valor_e_total=True)
                caixa.lancar(u, item.id, linhas)
                if lembrar and item.cartao:
                    caixa.lembrar_cartao(u, item.cartao, conta_id)
                st.session_state["_ok_caixa"] = f"Lançado: {descricao} · {brl(valor_ed)} · vence {venc:%d/%m}"
                st.rerun()
            if b2.button("Ignorar", key=f"ig_{k}", use_container_width=True):
                caixa.marcar(u, item.id, "ignorado")
                st.rerun()

hist = caixa.historico(u)
if not hist.empty:
    with st.expander("Já tratados"):
        hist["recebido_em"] = pd.to_datetime(hist["recebido_em"]).dt.tz_convert(FUSO).dt.strftime("%d/%m %H:%M")
        hist["status"] = hist["status"].map({"lancado": "✅ lançado", "ignorado": "🚫 ignorado"})
        st.dataframe(hist, hide_index=True, use_container_width=True,
                     column_config={"recebido_em": "Quando", "estabelecimento": "Onde",
                                    "valor_texto": "Valor", "cartao": "Cartão", "status": "Situação"})

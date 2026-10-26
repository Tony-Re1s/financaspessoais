import pandas as pd
import streamlit as st

from core import caixa, ia, repo
from core.fmt import FUSO, brl, hoje, vencimento_fatura
from telas import _ui
from telas._comum import cartoes_kpi, opcoes_categoria, usuario

u = usuario()
_ui.titulo("Caixa de entrada", "📥")
st.caption("Compras que chegaram sozinhas (Apple Pay no iPhone, notificações no Android). Confira crédito ou débito, a categoria e o cartão e toque em **Lançar**.")

if msg := st.session_state.pop("_ok_caixa", None):
    st.success(msg, icon=":material/check_circle:")

pend = caixa.pendentes(u)
if not pend.empty:
    _tot = sum(v for v in (caixa.valor_de_texto(x) for x in pend["valor_texto"]) if v)
    _velha = pd.Timestamp(pend["recebido_em"].min()).tz_convert(FUSO)
    cartoes_kpi([("Total para conferir", brl(_tot)), ("Compras", str(len(pend))),
                 ("Mais antiga", f"{_velha:%d/%m %H:%M}")], titulo="Compras chegando",
                icone="📥", destaque=0, c1="#123B5C", c2="#1F6FA8")
if pend.empty:
    st.info("Nada pendente. Quando você pagar (Apple Pay ou notificação no Android), a compra aparece aqui.",
            icon=":material/inbox:")
    st.page_link("telas/atalho.py", label="Configurar o celular (iPhone ou Android)", icon=":material/smartphone:")
else:
    contas = repo.contas(u)
    cartoes = contas[contas["tipo"] == "cartao_credito"]
    bancos = contas[contas["tipo"].isin(["conta_corrente", "poupanca", "carteira"])]
    op_cartoes = {None: "— escolha o cartão"} | {r.id: r.nome for r in cartoes.itertuples()}
    op_bancos = {None: "— escolha a conta"} | {r.id: r.nome for r in bancos.itertuples()}
    op_cat = opcoes_categoria(repo.categorias(u), "despesa")
    FUNCOES = {"credito": "💳 Crédito", "debito": "🏦 Débito"}

    def _id(v):
        return None if v is None or pd.isna(v) else v

    @st.cache_data(ttl=3600, show_spinner=False)
    def _ia_notificacao(item_id, texto):
        """Notificação em formato que o leitor não conhece: a IA separa valor e loja (1x por item)."""
        r = ia.interpretar({}, {}, hoje(), texto=f"Notificação de compra do banco: {texto}")
        return r.get("valor_total"), r.get("descricao")

    for item in pend.itertuples():
        if item.origem == "android" and (item.estabelecimento is None or caixa.valor_de_texto(item.valor_texto) is None) \
                and ia.chave() and item.texto_original:
            try:
                v_ia, loja_ia = _ia_notificacao(str(item.id), item.texto_original)
                item = item._replace(valor_texto=item.valor_texto if caixa.valor_de_texto(item.valor_texto) else str(v_ia),
                                     estabelecimento=item.estabelecimento or loja_ia)
            except Exception:  # noqa: BLE001 — sem IA, segue com o que tem
                pass
        valor = caixa.valor_de_texto(item.valor_texto)
        quando = pd.Timestamp(item.recebido_em).tz_convert(FUSO)
        k = str(item.id)
        _lig = caixa.conta_do_cartao(u, item.cartao)
        _cl = contas[contas["id"] == _lig]
        _selo = _ui.selo(_cl.iloc[0]["nome"], _cl.iloc[0]["instituicao"], 40) if not _cl.empty \
            else _ui.selo(item.cartao or "", None, 40)
        with st.container(border=True):
            _ui.render(f"""<div class="ui-item" style="margin-bottom:4px">
                {_selo}
                <div class="ui-tx"><div class="t" style="font-size:1rem">{_ui.esc(item.estabelecimento or 'Sem estabelecimento')}</div>
                <div class="s">{quando:%d/%m %H:%M} · {_ui.esc(item.cartao or 'cartão?')}</div></div>
                <div class="ui-val neg" style="font-size:1.12rem">{'− ' + brl(valor) if valor is not None else _ui.esc(item.valor_texto)}</div>
                </div>""")
            if item.origem == "android" and item.texto_original:
                st.caption(f"🔔 {item.texto_original}")

            # o que já sabemos deste cartão da Carteira
            ligada = caixa.conta_do_cartao(u, item.cartao)
            cartao_sug = ligada if ligada in op_cartoes else None
            banco_sug = ligada if ligada in op_bancos else None
            if cartao_sug is not None:
                banco_sug = _id(cartoes.loc[cartoes["id"] == cartao_sug, "conta_debito_id"].iloc[0])
            funcao_sug = (item.funcao or caixa.ultima_funcao(u, item.cartao)
                          or ("debito" if ligada is not None and cartao_sug is None else "credito"))

            funcao = st.segmented_control("Função", list(FUNCOES), format_func=FUNCOES.get,
                                          default=funcao_sug, key=f"fn_{k}", label_visibility="collapsed")
            funcao = funcao or funcao_sug
            debito = funcao == "debito"

            c1, c2 = st.columns(2)
            cat_ids = list(op_cat)
            sug_cat = caixa.sugerir_categoria(u, item.estabelecimento)
            categoria_id = c1.selectbox("Categoria", cat_ids, format_func=op_cat.get, key=f"cat_{k}",
                                        index=cat_ids.index(sug_cat) if sug_cat in cat_ids else None,
                                        placeholder="Categoria")
            ops, sug = (op_bancos, banco_sug) if debito else (op_cartoes, cartao_sug)
            ids = list(ops)
            conta_id = c2.selectbox("Sai da conta" if debito else "Cartão", ids, format_func=ops.get,
                                    key=f"conta_{k}_{funcao}", index=ids.index(sug) if sug in ids else 0)

            with st.expander("Ajustar"):
                descricao = st.text_input("Descrição", item.estabelecimento or "", key=f"desc_{k}")
                a1, a2 = st.columns(2)
                valor_ed = a1.number_input("Valor (R$)", min_value=0.0, value=float(valor or 0), step=1.0,
                                           format="%.2f", key=f"val_{k}")
                parcelas = a2.number_input("Parcelas", 1, 48, 1, key=f"parc_{k}", disabled=debito,
                                           help="Débito é sempre à vista" if debito else None)

            b1, b2 = st.columns([2, 1])
            pode = bool(categoria_id) and bool(conta_id) and valor_ed > 0
            if b1.button("Lançar", key=f"ok_{k}", type="primary", icon=":material/check:",
                         disabled=not pode, use_container_width=True,
                         help=None if pode else "Escolha categoria e conta"):
                compra = quando.date()
                conta = contas[contas["id"] == conta_id].iloc[0]
                if debito:
                    venc, forma, status, n_parc = compra, "Debito em Conta", "pago", 1
                else:
                    fech = None if pd.isna(conta["dia_fechamento"]) else int(conta["dia_fechamento"])
                    venc = (vencimento_fatura(compra, fech, int(conta["dia_vencimento"]))
                            if pd.notna(conta["dia_vencimento"]) else compra)
                    forma, status, n_parc = "Cartao de Credito", "previsto", int(parcelas)
                dados = dict(conta_id=conta_id, categoria_id=categoria_id, descricao=descricao.strip() or "Apple Pay",
                             valor=valor_ed, data_compra=compra, data_vencimento=venc, forma_pagamento=forma,
                             status=status, visibilidade=None,
                             origem="android" if item.origem == "android" else "applepay")
                linhas = repo.plano_parcelas(dados, 1, n_parc, valor_e_total=True)
                caixa.lancar(u, item.id, linhas)
                if item.cartao:   # sempre aprende: próxima compra deste cartão já vem preenchida
                    if debito and cartao_sug is not None:
                        caixa.ligar_debito(u, cartao_sug, conta_id)
                    else:
                        caixa.lembrar_cartao(u, item.cartao, conta_id)
                        if not debito and banco_sug is not None and cartao_sug is None:
                            caixa.ligar_debito(u, conta_id, banco_sug)   # era só débito; agora é o mesmo cartão
                quando_txt = "pago hoje" if debito else f"vence {venc:%d/%m}"
                st.session_state["_ok_caixa"] = f"Lançado: {descricao} · {brl(valor_ed)} · {quando_txt}"
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

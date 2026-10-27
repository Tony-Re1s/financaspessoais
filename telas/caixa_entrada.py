import pandas as pd
import streamlit as st

from core import beneficios as bn
from core import caixa, ia, repo
from core.fmt import FUSO, brl, hoje, vencimento_fatura
from telas import _ui
from telas._comum import cartoes_kpi, opcoes_categoria, usuario

from core import deducoes as _dd

u = usuario()
_ui.titulo("Caixa de entrada", "📥")
st.caption("Compras que chegaram sozinhas (Apple Pay no iPhone, notificações no Android). Confira crédito, débito ou VR/VA, a categoria e o cartão e toque em **Lançar**.")

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
    beneficios = contas[contas["tipo"] == "beneficio"]
    op_cartoes = {None: "— escolha o cartão"} | {r.id: r.nome for r in cartoes.itertuples()}
    op_bancos = {None: "— escolha a conta"} | {r.id: r.nome for r in bancos.itertuples()}
    op_benef = {r.id: r.nome for r in beneficios.itertuples()}
    op_cat = opcoes_categoria(repo.categorias(u), "despesa")
    FUNCOES = {"credito": "💳 Crédito", "debito": "🏦 Débito", "beneficio": "🍽️ VR/VA"}

    def _debito_do_cartao(cartao_id):
        """De qual conta sai o débito deste cartão: o que foi definido no cadastro, senão a conta corrente
        do mesmo banco, senão a conta que paga a fatura."""
        c = cartoes[cartoes["id"] == cartao_id]
        if c.empty:
            return None
        c = c.iloc[0]
        if _id(c["conta_debito_id"]) in op_bancos:
            return _id(c["conta_debito_id"])
        inst = _ui.sem_acento(c["instituicao"] or c["nome"])
        for b in bancos.itertuples():
            bi = _ui.sem_acento(b.instituicao or b.nome)
            if bi and inst and (bi in inst or inst in bi):
                return b.id
        return _id(c["conta_pagamento_id"]) if _id(c["conta_pagamento_id"]) in op_bancos else None

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
            benef_sug = ligada if ligada in op_benef else next(
                (i for i, n in op_benef.items() if not bn.fora_dos_gastos(u, i)), next(iter(op_benef), None))
            if cartao_sug is not None:
                banco_sug = _debito_do_cartao(cartao_sug)
            funcao_sug = ("beneficio" if ligada in op_benef else
                          (item.funcao or caixa.ultima_funcao(u, item.cartao)
                           or ("debito" if ligada is not None and cartao_sug is None else "credito")))

            funcao = st.segmented_control("Função", list(FUNCOES), format_func=FUNCOES.get,
                                          default=funcao_sug, key=f"fn_{k}", label_visibility="collapsed")
            funcao = funcao or funcao_sug
            debito = funcao == "debito"
            beneficio = funcao == "beneficio"
            if beneficio:
                st.caption("🍽️ Benefício: o gasto entra nas categorias, mas não sai de conta corrente nem vai "
                           "para fatura.")

            c1, c2 = st.columns(2)
            cat_ids = list(op_cat)
            sug_cat = caixa.sugerir_categoria(u, item.estabelecimento)
            categoria_id = c1.selectbox("Categoria", cat_ids, format_func=op_cat.get, key=f"cat_{k}",
                                        index=cat_ids.index(sug_cat) if sug_cat in cat_ids else None,
                                        placeholder="Categoria")
            if beneficio and not op_benef:
                c2.caption("Você ainda não tem o cartão VR/VA cadastrado.")
                if c2.button("Criar VR e VA", key=f"cria_vr_{k}", icon=":material/add_card:"):
                    bn.criar_padrao(u)
                    st.rerun()
                conta_id = None
            else:
                ops, sug, rot = ((op_benef, benef_sug, "Cartão benefício") if beneficio else
                                 (op_bancos, banco_sug, "Sai da conta") if debito else (op_cartoes, cartao_sug, "Cartão"))
                ids = list(ops)
                conta_id = c2.selectbox(rot, ids, format_func=ops.get,
                                        key=f"conta_{k}_{funcao}", index=ids.index(sug) if sug in ids else 0)
            fora = beneficio and conta_id is not None and bn.fora_dos_gastos(u, conta_id)
            if fora:
                st.caption("🛒 Este benefício está **fora dos seus gastos**: a compra só baixa o saldo dele "
                           "(categoria não precisa).")

            with st.expander("Ajustar"):
                descricao = st.text_input("Descrição", item.estabelecimento or "", key=f"desc_{k}")
                a1, a2 = st.columns(2)
                valor_ed = a1.number_input("Valor (R$)", min_value=0.0, value=float(valor or 0), step=1.0,
                                           format="%.2f", key=f"val_{k}")
                parcelas = a2.number_input("Parcelas", 1, 48, 1, key=f"parc_{k}", disabled=debito or beneficio,
                                           help="Débito e VR/VA são sempre à vista" if debito or beneficio else None)

            b1, b2 = st.columns([2, 1])
            pode = (bool(categoria_id) or fora) and bool(conta_id) and valor_ed > 0
            if b1.button("Lançar", key=f"ok_{k}", type="primary", icon=":material/check:",
                         disabled=not pode, use_container_width=True,
                         help=None if pode else "Escolha categoria e conta"):
                compra = quando.date()
                if fora:
                    lid = bn.registrar_uso(u, conta_id, descricao.strip() or "Compra no benefício", valor_ed,
                                           compra, fora=True)
                    caixa.marcar(u, item.id, "lancado", lid)
                    st.session_state["_ok_caixa"] = f"Uso registrado no {op_benef.get(conta_id, 'benefício')}: " \
                                                    f"{descricao} · {brl(valor_ed)}"
                    st.rerun()
                conta = contas[contas["id"] == conta_id].iloc[0]
                if beneficio:
                    venc, forma, status, n_parc = compra, "Beneficio (VR/VA)", "pago", 1
                elif debito:
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
                if item.cartao and beneficio:
                    caixa.lembrar_cartao(u, item.cartao, conta_id)   # este cartão da Carteira é o VR (nos gastos)
                elif item.cartao:   # sempre aprende: próxima compra deste cartão já vem preenchida
                    if debito and cartao_sug is not None:
                        caixa.ligar_debito(u, cartao_sug, conta_id)
                    else:
                        caixa.lembrar_cartao(u, item.cartao, conta_id)
                        if not debito and banco_sug is not None and cartao_sug is None:
                            caixa.ligar_debito(u, conta_id, banco_sug)   # era só débito; agora é o mesmo cartão
                quando_txt = "no VR/VA" if beneficio else ("pago hoje" if debito else f"vence {venc:%d/%m}")
                st.session_state["_ok_caixa"] = f"Lançado: {descricao} · {brl(valor_ed)} · {quando_txt}" \
                    + _dd.aviso_lancamento(descricao, categoria_id)
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

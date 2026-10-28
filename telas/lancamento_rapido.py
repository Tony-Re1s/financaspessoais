import json

import pandas as pd
import streamlit as st

from core import db, ia, repo
from core.fmt import brl, hoje, vencimento_fatura
from telas import _ui
from telas._comum import opcoes_categoria, usuario

from core import deducoes as _dd

u = usuario()
_ui.titulo("Lançamento rápido", "⚡")
st.caption("Tire foto do comprovante, fale ou escreva do seu jeito (“mercado 45 nubank débito”). "
           "A IA preenche e você só confere.")

if msg := st.session_state.pop("_ok_rapido", None):
    st.success(msg, icon=":material/check_circle:")

if not ia.chave():
    st.warning("Para usar a IA, coloque a sua chave da Anthropic nos **Secrets** do app:", icon=":material/key:")
    st.code('[anthropic]\napi_key = "sk-ant-..."', language="toml")
    st.caption("No Streamlit: Manage app → ⋮ → Settings → Secrets. Cole no fim, salve e reabra o app.")
    st.stop()

contas = repo.contas(u)
cartoes = contas[contas["tipo"] == "cartao_credito"]
bancos = contas[contas["tipo"].isin(["conta_corrente", "poupanca", "carteira"])]
op_todas = {r.id: r.nome for r in contas.itertuples()}
op_cat_d = opcoes_categoria(repo.categorias(u), "despesa")
op_cat_r = opcoes_categoria(repo.categorias(u), "receita")

modo = st.segmented_control("Como", ["foto", "voz", "texto"], default="foto", label_visibility="collapsed",
                            format_func={"foto": "📷 Foto", "voz": "🎤 Voz", "texto": "✍️ Texto"}.get) or "foto"
_VOZ_JS = __import__("pathlib").Path(__file__).parent.parent / "static" / "voz.js"
auto = False

with st.container(border=True):
    if modo == "foto":
        foto = st.file_uploader("Tirar foto ou escolher da galeria", type=["jpg", "jpeg", "png", "heic", "webp"],
                                key="rap_foto")
        obs = st.text_input("Algo a acrescentar? (opcional)", placeholder="ex.: foi no débito do Itaú, 3x",
                            key="rap_obs")
        pronto = foto is not None
    else:
        if modo == "voz":
            st.markdown("""<style>
.st-key-voz_btn {align-items: center; text-align: center;}
.fin-mic {width: 100%; padding: 22px 16px; border-radius: 18px; border: 0; cursor: pointer; font-size: 1.15rem;
  font-weight: 800; color: #fff; background: linear-gradient(135deg, #0F766E, #14B8A6);
  box-shadow: 0 8px 24px rgba(15,118,110,.25);}
.fin-mic.on {background: linear-gradient(135deg, #B91C1C, #EF4444); animation: fin-pulso 1.2s infinite;}
.fin-mic:disabled {opacity: .5; cursor: default;}
.fin-mic-info {font-size: .82rem; opacity: .75; margin-top: 8px; min-height: 1em;}
@keyframes fin-pulso {0%,100% {box-shadow: 0 0 0 0 rgba(239,68,68,.45);} 50% {box-shadow: 0 0 0 14px rgba(239,68,68,0);}}
</style>""", unsafe_allow_html=True)
            with st.container(key="voz_btn"):
                st.html(f"<script>{_VOZ_JS.read_text(encoding='utf-8')}</script>", unsafe_allow_javascript=True)
            st.caption("Fale valor, onde, e como pagou: “farmácia 120 em 3 vezes no Itaú”, “uber 23 ontem no "
                       "Nubank”, “mercado 85 e 90 no débito” (= R$ 85,90). Dá para corrigir o texto antes de lançar.")
        obs = st.text_area("O que você falou" if modo == "voz" else "O que você gastou?",
                           placeholder="almoço 38,90 ontem no latam\nuber 23 nubank\nfarmácia 120 em 3x no itaú",
                           key="rap_txt", height=90)
        foto, pronto = None, bool(obs.strip())
        # voz: quando o ditado termina, já manda ler (uma vez por texto)
        if modo == "voz" and pronto and st.session_state.get("_voz_lido") != obs.strip():
            st.session_state["_voz_lido"] = obs.strip()
            auto = True
    if st.button("Ler com IA", type="primary", icon=":material/auto_awesome:", disabled=not pronto,
                 use_container_width=True) or auto:
        try:
            with st.spinner("Lendo…"):
                img = ia.preparar_imagem(foto.getvalue()) if foto else None
                r = ia.interpretar(op_todas, op_cat_d | op_cat_r, hoje(), texto=obs.strip() or None,
                                   imagem_jpeg=img)
            st.session_state["rap_res"] = r
            st.session_state["rap_img"] = ia.preparar_imagem(foto.getvalue(), lado=1000, qualidade=60) if foto else None
            for k in [k for k in st.session_state if str(k).startswith("rc_")]:
                del st.session_state[k]
        except Exception as e:  # noqa: BLE001
            st.error(f"Não consegui ler: {e}")

r = st.session_state.get("rap_res")
if not r:
    st.stop()

# --- conferir e salvar -----------------------------------------------------------------------
st.subheader("Confira")
if r.get("duvida"):
    st.info(f"A IA ficou em dúvida: {r['duvida']}", icon=":material/help:")

FUNCOES = {"credito": "💳 Crédito", "debito": "🏦 Débito", "pix": "⚡ Pix", "dinheiro": "💵 Dinheiro",
           "boleto": "🧾 Boleto"}
conta_ia = r.get("conta_id")
func_ia = r.get("funcao") if r.get("funcao") in FUNCOES else (
    "credito" if conta_ia in set(cartoes["id"]) else "debito")
funcao = st.segmented_control("Função", list(FUNCOES), format_func=FUNCOES.get, default=func_ia,
                              key="rc_funcao", label_visibility="collapsed") or func_ia
credito = funcao == "credito"

tipo = r.get("tipo") if r.get("tipo") in ("despesa", "receita") else "despesa"
c1, c2 = st.columns([2, 1])
valor = c1.number_input("Valor total (R$)", 0.0, value=float(r["valor_total"]), step=1.0, format="%.2f",
                        key="rc_valor")
parcelas = c2.number_input("Parcelas", 1, 48, int(r["parcelas"]) if credito else 1, key=f"rc_parc_{funcao}",
                           disabled=not credito)
descricao = st.text_input("Descrição", r.get("descricao") or "", key="rc_desc")

op_cat = op_cat_r if tipo == "receita" else op_cat_d
cat_ids = list(op_cat)
c1, c2 = st.columns(2)
categoria_id = c1.selectbox("Categoria", cat_ids, format_func=op_cat.get, key="rc_cat", placeholder="Categoria",
                            index=cat_ids.index(r["categoria_id"]) if r.get("categoria_id") in cat_ids else None)
if credito:
    ops = {r_.id: r_.nome for r_ in cartoes.itertuples()}
else:
    ops = {None: "— sem conta"} | {r_.id: r_.nome for r_ in bancos.itertuples()}
    # débito no cartão: a conta ligada à função débito
    if conta_ia in set(cartoes["id"]):
        lig = cartoes.loc[cartoes["id"] == conta_ia, "conta_debito_id"].iloc[0]
        conta_ia = None if pd.isna(lig) else lig
ids = list(ops)
conta_id = c2.selectbox("Cartão" if credito else "Conta", ids, format_func=ops.get, key=f"rc_conta_{funcao}",
                        index=ids.index(conta_ia) if conta_ia in ids else (None if credito else 0),
                        placeholder="Escolha")
data_compra = st.date_input("Data", value=r["data"], format="DD/MM/YYYY", key="rc_data")
if r.get("itens"):
    st.caption(f"Itens: {r['itens']}")
if st.session_state.get("rap_img"):
    with st.expander("Ver foto"):
        st.image(st.session_state["rap_img"])

if credito and conta_id:
    conta = cartoes[cartoes["id"] == conta_id].iloc[0]
    venc = (vencimento_fatura(data_compra, None if pd.isna(conta["dia_fechamento"]) else int(conta["dia_fechamento"]),
                              int(conta["dia_vencimento"])) if pd.notna(conta["dia_vencimento"]) else data_compra)
    forma, status = "Cartao de Credito", "previsto"
    st.caption(f"Vai para a fatura que vence em **{venc:%d/%m/%Y}**"
               + (f" · {int(parcelas)}× de {brl(valor / parcelas)}" if parcelas > 1 else ""))
else:
    venc = data_compra
    forma = {"debito": "Debito em Conta", "pix": "Pix", "dinheiro": "Dinheiro", "boleto": "Boleto"}[funcao]
    status = "previsto" if funcao == "boleto" else "pago"

faltando = [n for n, ok in [("valor", valor > 0), ("descrição", descricao.strip()), ("categoria", categoria_id),
                            ("cartão", conta_id or not credito)] if not ok]
b1, b2 = st.columns([2, 1])
if b1.button("Salvar", type="primary", icon=":material/save:", use_container_width=True, disabled=bool(faltando),
             help=f"Falta: {', '.join(faltando)}" if faltando else None):
    comp_id = None
    if st.session_state.get("rap_img"):
        comp_id = db.gravar_retornando("""insert into comprovantes (dono_id, imagem, mime, dados_ia)
                           values (:u, :img, 'image/jpeg', cast(:d as jsonb)) returning id""",
                        u=u["id"], img=st.session_state["rap_img"], d=r.get("_bruto") or json.dumps({}))["id"]
    dados = dict(conta_id=conta_id, categoria_id=categoria_id, tipo=tipo, descricao=descricao.strip(),
                 valor=valor, data_compra=data_compra, data_vencimento=venc, forma_pagamento=forma, status=status,
                 visibilidade=None, observacao=r.get("itens") or None,
                 origem="camera" if comp_id else "ia", comprovante_id=comp_id)
    linhas = repo.plano_parcelas(dados, 1, int(parcelas) if credito else 1, valor_e_total=True)
    repo.inserir_lancamentos(u, linhas)
    for k in ["rap_res", "rap_img", "rap_foto", "rap_obs", "rap_txt"] + [k for k in st.session_state
                                                                         if str(k).startswith("rc_")]:
        st.session_state.pop(k, None)
    st.session_state["_ok_rapido"] = f"Lançado: {descricao} · {brl(valor)}" \
        + (_dd.aviso_lancamento(descricao, categoria_id) if tipo == "despesa" else "")
    st.rerun()
if b2.button("Descartar", use_container_width=True):
    st.session_state.pop("rap_res", None)
    st.session_state.pop("rap_img", None)
    st.rerun()

import pandas as pd
import streamlit as st

from core import repo
from core.padroes import TIPOS_CONTA, VISIBILIDADES
from core.fmt import brl
from telas import _ui
from telas._comum import col_rs, e_celular, em_reais, usuario

u = usuario()
cel = e_celular()
_ui.titulo("Contas e cartões", "🏦")
if msg := st.session_state.pop("_ok_conta", None):
    st.success(msg)

df = repo.contas(u, so_ativas=False)

if df.empty:
    st.info("Nenhuma conta ainda.")
if not df.empty:
    vis = df.copy()
    vis["tipo"] = vis["tipo"].map(TIPOS_CONTA)
    vis["visibilidade"] = vis["visibilidade"].map(lambda v: VISIBILIDADES[v].split(" — ")[0])
    vis["limite"] = vis["limite"].astype(float)


def _int(v):
    return None if v is None or pd.isna(v) else int(v)


def _incompleto(r) -> bool:
    """Cartão sem vencimento ou sem conta que paga a fatura: a fatura não entra certinho no fluxo."""
    return r.tipo == "cartao_credito" and (pd.isna(r.dia_vencimento) or pd.isna(r.conta_pagamento_id))


def _n(x):
    return None if x is None or (not isinstance(x, str) and pd.isna(x)) else x


def _cadastro(escolha):
    atual = df[df["id"] == escolha].iloc[0].to_dict() if escolha else {}
    ch = f"conta_{escolha or 'nova'}"
    cor_atual = atual.get("cor") if isinstance(atual.get("cor"), str) and atual.get("cor") else None
    r = _ui.rascunho(ch, dict(
        nome=atual.get("nome", ""), tipo=atual.get("tipo", "conta_corrente"), instituicao=atual.get("instituicao") or "",
        fech=_int(atual.get("dia_fechamento")) or 0, venc=_int(atual.get("dia_vencimento")) or 0,
        limite=float(atual.get("limite") or 0), deb=_n(atual.get("conta_debito_id")), pag=_n(atual.get("conta_pagamento_id")),
        visib=atual.get("visibilidade", "privado"), ativa=bool(atual.get("ativa", True)),
        cor_propria=cor_atual is not None,
        cor=cor_atual or _ui.banco(atual.get("nome", ""), atual.get("instituicao"))["c1"]))
    cartao = r["tipo"] == "cartao_credito"
    passos = ["Básico", "Cartão", "Opções"] if cartao else ["Básico", "Opções"]
    i = _ui.etapas(ch, passos)
    etapa = passos[i]
    bancos = df[df["tipo"].isin(["conta_corrente", "poupanca", "carteira"]) & (df["id"] != escolha)]

    if etapa == "Básico":
        _ui.campo(r, ch, "nome", st.text_input, "Nome", placeholder="Ex.: Latam Black")
        tipos = list(TIPOS_CONTA)
        _ui.campo(r, ch, "tipo", st.selectbox, "Tipo", tipos, format_func=TIPOS_CONTA.get)
        _ui.campo(r, ch, "instituicao", st.text_input, "Instituição", placeholder="Itaú, Nubank…")
    elif etapa == "Cartão":
        c1, c2 = st.columns(2)
        _ui.campo(r, ch, "fech", c1.number_input, "Fecha dia", 0, 31,
                  help="0 = não sei (o app assume 7 dias antes do vencimento)")
        _ui.campo(r, ch, "venc", c2.number_input, "Vence dia", 0, 31)
        _ui.campo(r, ch, "limite", st.number_input, "Limite (R$)", 0.0, step=500.0)
        op_pag = {None: "— não definida"} | {b.id: b.nome for b in bancos.itertuples()}
        if r["pag"] not in op_pag:
            st.session_state.pop(f"{ch}__pag", None); r["pag"] = None
        _ui.campo(r, ch, "pag", st.selectbox, "Fatura paga pela conta", list(op_pag), format_func=op_pag.get,
                  help="A fatura sai desta conta corrente no vencimento (entra no fluxo de caixa).")
        op_deb = {None: "— não tem função débito"} | {b.id: b.nome for b in bancos.itertuples()}
        if r["deb"] not in op_deb:
            st.session_state.pop(f"{ch}__deb", None); r["deb"] = None
        _ui.campo(r, ch, "deb", st.selectbox, "Função débito sai da conta", list(op_deb), format_func=op_deb.get,
                  help="Se este cartão também passa no débito, de qual conta corrente sai o dinheiro. "
                       "Usado pela Caixa de entrada quando você escolhe Débito.")
    else:
        if not cartao:
            _ui.campo(r, ch, "limite", st.number_input, "Limite (R$)", 0.0, step=500.0,
                      help="Cheque especial, se tiver.")
        vis_keys = list(VISIBILIDADES)
        _ui.campo(r, ch, "visib", st.selectbox, "Quem vê os lançamentos desta conta", vis_keys,
                  format_func=VISIBILIDADES.get)
        _ui.campo(r, ch, "ativa", st.toggle, "Conta ativa")
        c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
        _ui.campo(r, ch, "cor_propria", c1.toggle, "Escolher a cor",
                  help="Desligado: usa a cor do banco/cartão. Ligado: usa a cor que você escolher.")
        _ui.campo(r, ch, "cor", c2.color_picker, "Cor do cartão/conta")

    if _ui.etapas_botoes(ch, len(passos), [("nome", "o nome")] if etapa == "Básico" else []):
        if not str(r["nome"] or "").strip():
            st.error("Dê um nome para a conta.")
        else:
            cartao = r["tipo"] == "cartao_credito"
            repo.salvar_conta(u, dict(nome=r["nome"].strip(), tipo=r["tipo"], instituicao=r["instituicao"] or None,
                                      dia_fechamento=r["fech"] or None, dia_vencimento=r["venc"] or None,
                                      limite=r["limite"] or None, visibilidade=r["visib"], ativa=r["ativa"],
                                      conta_debito_id=r["deb"] if cartao else None,
                                      conta_pagamento_id=r["pag"] if cartao else None,
                                      cor=r["cor"] if r["cor_propria"] else None,
                                      saldo_inicial=atual.get("saldo_inicial"),
                                      data_saldo_inicial=atual.get("data_saldo_inicial")),
                              conta_id=escolha)
            _ui.rascunho_limpar(ch)
            st.session_state["_ok_conta"] = f"Conta **{r['nome'].strip()}** salva."
            st.rerun()

    if escolha:
        n_lanc = repo.qtd_lancamentos_conta(u, escolha)
        with st.popover("🗑️ Excluir conta", width="stretch"):
            if n_lanc:
                st.caption(f"Esta conta tem **{n_lanc} lançamentos**. Excluir apaga a conta e deixa os lançamentos "
                           "sem conta. Se só não usa mais, prefira desligar **Conta ativa** (some das listas, "
                           "mas o histórico fica).")
            else:
                st.caption("Conta sem lançamentos — pode excluir sem perder nada.")
            if st.button("Excluir de vez", type="primary", key=f"{ch}__exc"):
                repo.excluir_conta(u, escolha)
                _ui.rascunho_limpar(ch)
                st.session_state["_ok_conta"] = "Conta excluída."
                st.rerun()


@st.dialog("Conta / cartão")
def _ficha(escolha):
    _cadastro(escolha)


if cel:
    if st.button("Nova conta ou cartão", icon=":material/add:", type="primary", width="stretch", key="nova_conta"):
        _ui.rascunho_limpar("conta_nova")
        _ficha(None)
if cel and not df.empty:
    ordem = {"conta_corrente": 0, "carteira": 1, "poupanca": 2, "cartao_credito": 3}
    lst = df.assign(_o=df["tipo"].map(ordem).fillna(9), _a=~df["ativa"].astype(bool)).sort_values(["_a", "_o", "nome"])
    with st.container(key="llista_contas"):
        for r in lst.itertuples():
            sub = [TIPOS_CONTA.get(r.tipo, r.tipo)]
            if isinstance(r.instituicao, str) and r.instituicao and r.instituicao not in r.nome:
                sub.append(r.instituicao)
            if r.tipo == "cartao_credito" and pd.notna(r.dia_vencimento):
                sub.append(f"vence dia {int(r.dia_vencimento)}")
            lim = float(r.limite) if pd.notna(r.limite) and r.limite else 0
            if _ui.linha(f"c_{r.id}", f"<div class='sel'>{_ui.selo(r.nome, r.instituicao, 42)}</div>", r.nome,
                         " · ".join(sub), valor=brl(lim) if lim else "",
                         chip=("Completar" if _incompleto(r) else "") if r.ativa else "Inativa",
                         chip_cls="warn" if r.ativa else "mute"):
                _ui.rascunho_limpar(f"conta_{r.id}")
                _ficha(r.id)
if not cel and not df.empty:
    cols = ["nome", "tipo", "instituicao", "dia_fechamento", "dia_vencimento", "limite", "visibilidade", "ativa"]
    st.dataframe(em_reais(vis, "limite")[cols],
                 hide_index=True, use_container_width=True,
                 column_config={"nome": "Nome", "tipo": "Tipo", "instituicao": "Instituição",
                                "dia_fechamento": "Fecha dia", "dia_vencimento": "Vence dia",
                                "limite": col_rs("Limite"), "visibilidade": "Quem vê", "ativa": "Ativa"})
if not cel:
    st.divider()
    op = {None: "➕ Nova conta"} | {r.id: f"Editar: {r.nome}" for r in df.itertuples()}
    _cadastro(st.selectbox("O que fazer", list(op), format_func=op.get))


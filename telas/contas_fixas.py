from datetime import date

import pandas as pd
import streamlit as st

from core import recorrencias as rec
from core import repo
from core.fmt import brl, hoje
from core.padroes import VISIBILIDADES
from telas import _ui
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, opcoes_categoria, usuario

u = usuario()
cel = e_celular()
_ui.titulo("Contas fixas", "🔁")

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
cartoes_kpi([("Saem por mês", brl(desp)), ("Contas fixas ativas", str(len(ativas))),
             ("↑ Entram por mês", brl(rec_)), ("Saldo fixo", brl(rec_ - desp)), ("Por ano", brl(desp * 12))],
            titulo="Compromissos fixos", icone="🔁", c1="#4A2A12", c2="#9A5A1E")

if not df.empty and not cel:
    v = df.copy()
    v["valor"] = v["valor"].astype(float)
    v["quando"] = v.apply(lambda r: f"dia {int(r.dia_vencimento)}" if pd.notna(r.dia_vencimento) else "—", axis=1)
    v["sit"] = v["ativa"].map({True: "✅", False: "⏸️"})
    cols = ["sit", "descricao", "quando", "conta", "proxima", "valor"]
    st.dataframe(em_reais(v[cols].fillna({"conta": "—"})), hide_index=True, use_container_width=True,
                 column_config={"sit": st.column_config.TextColumn("", width=30), "descricao": "Conta fixa",
                                "quando": "Cobra", "conta": "Conta/cartão",
                                "proxima": st.column_config.DateColumn("Próxima", format="DD/MM/YY"),
                                "valor": col_rs()})

# --- sugestões a partir do que já está lançado ------------------------------------------------
sug = rec.sugestoes(u)
if not sug.empty:
    with st.expander(f"💡 {len(sug)} gastos que parecem fixos (repetem o mesmo valor todo mês)"):
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
def _cadastro(escolha):
    a = df[df["id"] == escolha].iloc[0].to_dict() if escolha else {}

    def _v(k, padrao=None):
        x = a.get(k)
        return padrao if x is None or (not isinstance(x, str) and pd.isna(x)) else x

    ch = f"rec_{escolha or 'nova'}"
    r = _ui.rascunho(ch, dict(
        tipo=_v("tipo", "despesa"), descricao=_v("descricao", ""), valor=float(_v("valor", 0.0)),
        dia=int(_v("dia_vencimento", hoje().day)), freq="anual" if _v("frequencia") == "anual" else "mensal",
        inicio=_v("inicio", date(hoje().year, hoje().month, 1)), tem_fim=_v("fim") is not None, fim=_v("fim", hoje()),
        categoria_id=a.get("categoria_id") if a.get("categoria_id") in op_cat else None,
        conta_id=a.get("conta_id") if a.get("conta_id") in op_contas else None,
        vis=a.get("visibilidade") if a.get("visibilidade") in VISIBILIDADES else None))
    passos = ["O quê", "Quando", "Onde"]
    i = _ui.etapas(ch, passos)

    if i == 0:
        _ui.campo(r, ch, "tipo", st.segmented_control, "Tipo", ["despesa", "receita"],
                  format_func=lambda t: "💸 Despesa" if t == "despesa" else "💰 Receita (salário…)")
        _ui.campo(r, ch, "descricao", st.text_input, "Descrição", placeholder="Ex.: Condomínio")
        _ui.campo(r, ch, "valor", st.number_input, "Valor (R$)", 0.0, step=10.0, format="%.2f")
    elif i == 1:
        c1, c2 = st.columns(2)
        _ui.campo(r, ch, "dia", c1.number_input, "Dia", 1, 31,
                  help="No cartão, é o dia da cobrança; o app joga na fatura certa.")
        _ui.campo(r, ch, "freq", c2.selectbox, "Repete", ["mensal", "anual"], format_func=str.capitalize)
        _ui.campo(r, ch, "inicio", st.date_input, "A partir de", format="DD/MM/YYYY")
        c1, c2 = st.columns(2)
        _ui.campo(r, ch, "tem_fim", c1.toggle, "Tem data para acabar")
        _ui.campo(r, ch, "fim", c2.date_input, "Até", format="DD/MM/YYYY", disabled=not r["tem_fim"])
    else:
        _ui.campo(r, ch, "categoria_id", st.selectbox, "Categoria", list(op_cat), format_func=op_cat.get,
                  placeholder="Categoria")
        _ui.campo(r, ch, "conta_id", st.selectbox, "Conta / cartão", list(op_contas), format_func=op_contas.get)
        op_vis = {None: "Herdar da categoria/conta"} | VISIBILIDADES
        _ui.campo(r, ch, "vis", st.selectbox, "Quem vê", list(op_vis), format_func=op_vis.get)

    if _ui.etapas_botoes(ch, len(passos), [("descricao", "a descrição"), ("valor", "o valor")] if i == 0 else []):
        if not str(r["descricao"] or "").strip() or not r["valor"]:
            st.error("Preencha descrição e valor.")
        else:
            rec.salvar(u, dict(descricao=r["descricao"].strip(), valor=r["valor"], conta_id=r["conta_id"],
                               categoria_id=r["categoria_id"], tipo=r["tipo"] or "despesa", frequencia=r["freq"],
                               dia_vencimento=int(r["dia"]), inicio=r["inicio"],
                               fim=r["fim"] if r["tem_fim"] else None, visibilidade=r["vis"], ativa=True), escolha)
            _ui.rascunho_limpar(ch)
            st.session_state["_ok_rec"] = f"**{r['descricao'].strip()}** salva — lançamentos dos próximos 12 meses prontos."
            st.rerun()

    if escolha:
        c1, c2 = st.columns(2)
        if a.get("ativa"):
            if c1.button("⏸️ Encerrar", use_container_width=True, key=f"{ch}__enc",
                         help="Para de gerar e tira os previstos futuros. O que já passou fica."):
                rec.encerrar(u, escolha)
                _ui.rascunho_limpar(ch)
                st.session_state["_ok_rec"] = "Conta fixa encerrada."
                st.rerun()
        else:
            if c1.button("▶️ Reativar", use_container_width=True, key=f"{ch}__reat"):
                rec.salvar(u, a | {"ativa": True}, escolha)
                st.rerun()
        with c2.popover("🗑️ Excluir", use_container_width=True):
            st.caption("Apaga a conta fixa e os previstos futuros. Pagos e passados ficam.")
            if st.button("Excluir de vez", type="primary", key=f"{ch}__exc"):
                rec.encerrar(u, escolha, apagar=True)
                _ui.rascunho_limpar(ch)
                st.session_state["_ok_rec"] = "Conta fixa excluída."
                st.rerun()


@st.dialog("Conta fixa")
def _ficha(escolha):
    _cadastro(escolha)


if cel:
    if st.button("Nova conta fixa", icon=":material/add:", type="primary", width="stretch", key="nova_rec"):
        _ui.rascunho_limpar("rec_nova")
        _ficha(None)
    if not df.empty:
        lst = df.assign(_a=~df["ativa"].astype(bool), _d=df["dia_vencimento"].fillna(99)).sort_values(["_a", "_d"])
        with st.container(key="llista_rec"):
            for r in lst.itertuples():
                rec_ = r.tipo == "receita"
                dia = f"<b>{int(r.dia_vencimento):02d}</b><span>DIA</span>" if pd.notna(r.dia_vencimento) else "<b>—</b>"
                sub = [r.conta if isinstance(r.conta, str) else "sem conta",
                       "anual" if r.frequencia == "anual" else "mensal"]
                if pd.notna(r.proxima):
                    sub.append(f"próxima {pd.Timestamp(r.proxima):%d/%m}")
                if _ui.linha(f"r_{r.id}", f"<div class='dia'>{dia}</div>", r.descricao, " · ".join(sub),
                             valor=f"{'+' if rec_ else '−'} {brl(float(r.valor))}", valor_cls="pos" if rec_ else "",
                             chip=("Completar" if pd.isna(r.categoria_id) else "") if r.ativa else "Encerrada",
                             chip_cls="warn" if r.ativa else "mute"):
                    _ui.rascunho_limpar(f"rec_{r.id}")
                    _ficha(r.id)
else:
    st.divider()
    op = {None: "➕ Nova conta fixa"} | {r.id: f"Editar: {r.descricao}" for r in df.itertuples()}
    _cadastro(st.selectbox("O que fazer", list(op), format_func=op.get, key="rec_escolha"))

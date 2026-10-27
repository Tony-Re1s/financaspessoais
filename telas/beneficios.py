from datetime import date

import pandas as pd
import streamlit as st

from core import beneficios as bn
from core import saldos
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref, somar_meses
from telas import _ui
from telas._comum import cartoes_kpi, e_celular, usuario

u = usuario()
cel = e_celular()
_ui.aviso_ok()
_ui.titulo("Benefícios", "🍽️", sub="VR e VA: quanto entrou, quanto foi usado e em quê. Ficam fora do fluxo das "
                                     "contas correntes e das faturas.")

ct = bn.contas(u)
if ct.empty:
    st.info("Você ainda não tem os cartões de benefício cadastrados.")
    if st.button("Criar VR e VA", type="primary", icon=":material/add_card:"):
        bn.criar_padrao(u)
        st.session_state["_ui_ok"] = "VR e VA criados — configure o crédito mensal de cada um."
        st.rerun()
    st.stop()

try:
    bn.gerar_creditos(u)
except Exception:  # noqa: BLE001 — nunca impede a tela de abrir
    pass
cfg = bn.config(u)
atual = mes_ref(hoje())
meses = [somar_meses(atual, k) for k in range(-4, 3)]
sel = st.segmented_control("Mês", meses, default=atual, key="benef_mes",
                           format_func=lambda m: ("Hoje · " if m == atual else "") + mes_label(m),
                           label_visibility="collapsed") or atual

CORES = {"VR": ("#9A3412", "#EA580C"), "VA": ("#166534", "#16A34A")}
ct = ct.assign(_fora=ct["id"].astype(str).map(lambda i: bool(cfg.get(i, {}).get("fora")))).sort_values(["_fora", "nome"])
for c in ct.itertuples():
    cid = str(c.id)
    conf = cfg.get(cid, {})
    fora = bool(conf.get("fora"))
    r = bn.resumo(u, c.id, sel)
    c1, c2 = CORES.get(c.nome.upper()[:2], ("#1F2A44", "#3B4C75"))
    if isinstance(c.cor, str) and c.cor:
        b = _ui.banco(c.nome, None, c.cor)
        c1, c2 = b["c1"], b["c2"]
    credito, dia = float(conf.get("credito") or 0), int(conf.get("dia") or 1)
    prox_m = atual if dia_no_mes(atual // 100, atual % 100, dia) >= hoje() else somar_meses(atual, 1)
    prox = dia_no_mes(prox_m // 100, prox_m % 100, dia)
    rot = "Saldo hoje" if sel == atual else (f"Saldo em {dia_no_mes(sel // 100, sel % 100, 31):%d/%m}")
    cartoes_kpi([(rot, brl(r["saldo"] if sel == atual else r["saldo_fim"])),
                 ("Saldo inicial", brl(r["saldo_inicial"])), ("↑ Créditos", brl(r["creditos"])),
                 ("↓ Usado", brl(r["uso"])),
                 ("Próximo crédito", f"{brl(credito)} · {prox:%d/%m}" if credito else "configure abaixo")],
                titulo=c.nome, icone="🍽️" if not fora else "🛒", c1=c1, c2=c2, direita=mes_label(sel),
                sub="Fora dos meus gastos — só acompanho o saldo" if fora else "Conta nos meus gastos por categoria")

    ext = r["extrato"]
    usos = ext[(ext["valor"] < 0) & (ext["fonte"] != "ajuste")] if not ext.empty else ext
    if not fora and not usos.empty:
        esq, dir_ = (st.container(), st.container()) if cel else st.columns(2)
        with esq:
            st.markdown(f"<div class='ui-sec'>Em quê foi o {_ui.esc(c.nome)}</div>", unsafe_allow_html=True)
            cat = usos.assign(v=-usos["valor"], categoria=usos["categoria"].replace({"—": "Sem categoria"})) \
                .groupby("categoria", as_index=False)["v"].sum().sort_values("v", ascending=False)
            tot = float(cat["v"].sum()) or 1.0
            linhas = "".join(f"""<div class="ui-cat"><div class="t"><span>{_ui.esc(x.categoria)}</span>
                <span class="v">{brl(x.v)}</span></div><div class="barra"><div style="width:{x.v / tot * 100:.0f}%">
                </div></div><div class="p">{x.v / tot:.0%}</div></div>""" for x in cat.itertuples())
            _ui.render(f"<div class='ui-lista-html'>{linhas}</div>")
            onde = (usos.assign(v=-usos["valor"]).groupby("descricao")["v"].agg(total="sum", vezes="count")
                    .reset_index().sort_values("total", ascending=False).head(6))
            st.caption("Onde mais usou: " + " · ".join(f"{o.descricao} {brl(o.total)} ({o.vezes}x)"
                                                       for o in onde.itertuples()))
        alvo = dir_
    else:
        alvo = st.container()
    with alvo:
        st.markdown(f"<div class='ui-sec'>Movimentos · {mes_label(sel)}</div>", unsafe_allow_html=True)
        if ext.empty:
            st.caption("Nada neste mês.")
        else:
            with st.container(key=f"uilista_b{cid}"):
                for i, x in ext.sort_values("data", ascending=False).iterrows():
                    d = x["data"]
                    ic = (f"<div style='font-size:.62rem;line-height:1;text-align:center'><b style='font-size:.95rem'>"
                          f"{d.day:02d}</b><br>{_ui.MESES[d.month - 1]}</div>")
                    prev = x["status"] == "previsto"
                    sub = x["categoria"] if isinstance(x["categoria"], str) and x["categoria"] not in ("—",) else ""
                    acao = (lambda lid=x["id"]: _ui.editar_lancamento(u, lid)) if pd.notna(x["id"]) else (lambda: None)
                    _ui.linha_editavel(f"b{cid}_{i}", _ui.item_html(ic, x["descricao"], sub,
                                                                   "previsto" if prev else "", "", prev),
                                       _ui.valor_html(float(x["valor"]), prev), acao)

    with st.expander(f"⚙️ Configurar {c.nome}"):
        with st.form(f"cfg_{cid}"):
            a, b_, c_ = st.columns(3)
            v = a.number_input("Crédito mensal (R$)", 0.0, value=credito, step=50.0, format="%.2f")
            d_ = b_.number_input("Dia do crédito", 1, 31, dia)
            f_ = c_.toggle("Fora dos meus gastos", value=fora,
                           help="Ligado: o uso só baixa o saldo (ex.: VA usado por outra pessoa). Desligado: cada "
                                "compra entra nos gastos por categoria.")
            s1, s2 = st.columns(2)
            saldo_real = s1.number_input("Saldo de hoje no app do benefício (opcional)", value=None, step=10.0,
                                         format="%.2f", placeholder="deixe em branco se não quiser informar")
            if st.form_submit_button("Salvar", type="primary"):
                bn.configurar(u, c.id, v, d_, f_)
                if saldo_real is not None:
                    saldos.informar_saldo(c.id, hoje(), float(saldo_real))
                st.session_state["_ui_ok"] = f"{c.nome} atualizado."
                st.rerun()
    st.divider()

st.caption("💡 O cartão é um só (híbrido)? Na **Caixa de entrada**, escolha **VR/VA** e depois qual dos dois: "
           "compras no VR entram nos gastos; no VA (fora dos gastos) só baixam o saldo.")

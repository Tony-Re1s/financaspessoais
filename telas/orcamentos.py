import pandas as pd
import streamlit as st

from core import orcamentos as orc
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref, somar_meses
from telas import _ui
from telas._comum import cartoes_kpi, e_celular, usuario

u = usuario()
cel = e_celular()
_ui.aviso_ok()
_ui.titulo("Orçamentos", "🎯", sub="Quanto você quer gastar por categoria no mês — e quanto ainda pode gastar.")

hj = hoje()
atual = mes_ref(hj)
meses = [somar_meses(atual, k) for k in range(-3, 4)]
sel = st.segmented_control("Mês", meses, default=st.session_state.get("_orc_mes", atual), key="orc_mes",
                           format_func=lambda m: ("Hoje · " if m == atual else "") + mes_label(m),
                           label_visibility="collapsed") or atual
st.session_state["_orc_mes"] = sel

q = orc.quadro(u, sel)
com = q[q["orcado"].notna()]
orcado = float(com["orcado"].sum())
gasto_orc = float(com["gasto"].sum())
gasto_tot = float(q["gasto"].sum())
fora = gasto_tot - gasto_orc
disp = orcado - gasto_orc
fim = dia_no_mes(sel // 100, sel % 100, 31)
dias = (fim - hj).days + 1 if sel == atual else None

if com.empty:
    st.info("Você ainda não tem orçamento. Defina abaixo, em **✏️ Definir orçamentos** — dá para começar "
            "pela média dos últimos 3 meses.")
else:
    ok = disp >= 0
    itens = [("Ainda posso gastar" if ok else "Passou do orçamento", brl(abs(disp))),
             ("Orçado", brl(orcado)), ("Gasto + a pagar", brl(gasto_orc))]
    if dias and ok:
        itens.append(("Por dia até o fim do mês", brl(disp / max(dias, 1))))
    if fora > 0.005:
        itens.append(("Fora do orçamento", brl(fora)))
    c1, c2 = ("#0B4F45", "#12907F") if ok else ("#7A1D2B", "#C2334A")
    cartoes_kpi(itens, titulo=f"Orçamento de {mes_label(sel)}", icone="🎯", c1=c1, c2=c2,
                direita=f"{gasto_orc / orcado:.0%} usado" if orcado else "",
                sub=(f"Faltam {dias} dias" if dias else "") +
                    (" · inclui o que já está previsto (faturas, contas fixas)" if sel >= atual else ""))

# --- categorias ------------------------------------------------------------------------------------
st.markdown("<div class='ui-sec'>Por categoria</div>", unsafe_allow_html=True)


def _linha(r):
    g, o = float(r.gasto), r.orcado
    if pd.notna(o) and o:
        pct = g / o
        cor = "#16A34A, #4ADE80" if pct < .8 else ("#D97706, #FBBF24" if pct <= 1 else "#DC2626, #F87171")
        resto = o - g
        frase = (f"sobra {brl(resto)}" if resto >= 0 else f"<b style='color:#DC2626'>passou {brl(-resto)}</b>")
        barra = (f"<div class='barra'><div style='width:{min(pct, 1) * 100:.0f}%;"
                 f"background:linear-gradient(90deg,{cor})'></div></div>")
        dir_ = f"{brl(g)} <span style='opacity:.55;font-weight:500'>de {brl(o)}</span>"
        p = f"{pct:.0%} · {frase} · pago {brl(r.pago)} · a pagar {brl(r.previsto)}"
    else:
        barra, dir_ = "", brl(g)
        p = f"sem orçamento · pago {brl(r.pago)} · a pagar {brl(r.previsto)}"
    if r.media3:
        p += f" · média dos últimos meses {brl(r.media3)}"
    return (f"<div class='ui-cat'><div class='t'><span>{_ui.esc(r.categoria)}</span><span class='v'>{dir_}</span>"
            f"</div>{barra}<div class='p'>{p}</div></div>")


vis = q[(q["gasto"] > 0) | q["orcado"].notna()].copy()
if vis.empty:
    st.caption("Nada lançado neste mês.")
else:
    vis["_o"] = vis["orcado"].notna()
    vis["_pct"] = vis.apply(lambda r: r.gasto / r.orcado if r._o and r.orcado else -1, axis=1)
    vis = vis.sort_values(["_o", "_pct", "gasto"], ascending=[False, False, False])
    html = "".join(_linha(r) for r in vis.itertuples())
    _ui.render(f"<div class='ui-lista-html'>{html}</div>")
    estour = vis[vis["_pct"] > 1]
    if not estour.empty:
        st.caption("🔴 Passaram do orçamento: " + ", ".join(estour["categoria"]) + ". Toque na categoria no "
                   "**Painel** para ver o que entrou nela.")

# --- definir ---------------------------------------------------------------------------------------
with st.expander("✏️ Definir orçamentos", expanded=com.empty):
    st.caption("O valor vale para **todos os meses**. Quer um valor diferente só em "
               f"{mes_label(sel)} (ex.: dezembro com presentes)? Use a coluna do mês.")
    pad = orc.padrao(u)
    mes_esp = orc.valores(u, sel)
    base = pd.DataFrame({
        "categoria": q.loc[q["id"].notna(), "categoria"],
        "media3": q.loc[q["id"].notna(), "media3"].round(2),
        "mensal": [pad.get(i) for i in q.loc[q["id"].notna(), "id"]],
        "so_mes": [mes_esp.get(i) if mes_esp.get(i) != pad.get(i) else None for i in q.loc[q["id"].notna(), "id"]],
    }).reset_index(drop=True)
    ids = list(q.loc[q["id"].notna(), "id"])
    if st.button("Preencher o que está vazio com a média dos últimos 3 meses", icon=":material/auto_fix_high:"):
        n = 0
        for i, r in zip(ids, base.itertuples()):
            if (r.mensal is None or pd.isna(r.mensal)) and r.media3 > 0:
                orc.salvar(u, i, round(r.media3 / 10) * 10 or r.media3)
                n += 1
        st.session_state["_ui_ok"] = f"{n} categorias preenchidas pela média (arredondada)."
        st.rerun()
    with st.form("orc_form"):
        ed = st.data_editor(base, hide_index=True, use_container_width=True, key=f"orc_ed_{sel}",
                            disabled=["categoria", "media3"],
                            column_config={
                                "categoria": st.column_config.TextColumn("Categoria"),
                                "media3": st.column_config.NumberColumn("Média (até 3 meses)", format="R$ %.2f"),
                                "mensal": st.column_config.NumberColumn("Todo mês (R$)", format="R$ %.2f",
                                                                        min_value=0.0, step=10.0),
                                "so_mes": st.column_config.NumberColumn(f"Só em {mes_label(sel)} (R$)",
                                                                        format="R$ %.2f", min_value=0.0, step=10.0),
                            })
        if st.form_submit_button("💾 Salvar orçamentos", type="primary"):
            n = 0
            for i, (a, b) in enumerate(zip(base.itertuples(), ed.itertuples())):
                for col, mes in (("mensal", 0), ("so_mes", sel)):
                    va, vb = getattr(a, col), getattr(b, col)
                    va = None if va is None or pd.isna(va) else float(va)
                    vb = None if vb is None or pd.isna(vb) else float(vb)
                    if va != vb:
                        orc.salvar(u, ids[i], vb, mes)
                        n += 1
            st.session_state["_ui_ok"] = f"{n} valores salvos." if n else "Nada mudou."
            st.rerun()

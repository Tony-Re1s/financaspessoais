from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core import cartoes, repo, saldos
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref, somar_meses
from telas import _ui
from telas._comum import cartoes_kpi, e_celular, seletor_escopo, usuario

u = usuario()
cel = e_celular()
_ui.aviso_ok()
topo_esq, topo_dir = st.columns([3, 1], vertical_alignment="bottom")
with topo_esq:
    _ui.titulo("Painel", "🏠")
with topo_dir:
    escopo = seletor_escopo()

hj = hoje()
atual = mes_ref(hj)
ANTES, DEPOIS = 5, 6
meses = [somar_meses(atual, k) for k in range(-ANTES, DEPOIS + 1)]


def _ini(m):
    return date(m // 100, m % 100, 1)


def _fim(m):
    return dia_no_mes(m // 100, m % 100, 31)


# --- escolha do mês ----------------------------------------------------------------------------
sel = st.segmented_control("Mês", meses, default=st.session_state.get("_painel_mes", atual), key="painel_mes",
                           format_func=lambda m: ("Hoje · " if m == atual else "") + mes_label(m),
                           label_visibility="collapsed") or atual
st.session_state["_painel_mes"] = sel

# --- fluxo de caixa das contas (as minhas): uma leitura para a janela toda ---------------------
contas = repo.contas(u)
caixa = contas[contas["tipo"].isin(saldos.TIPOS_CAIXA)]
ids = list(caixa["id"])
ini_w, fim_w = _ini(meses[0]), _fim(meses[-1])
s0, ext = saldos.extrato(u, ids, ini_w, fim_w) if ids else (0.0, pd.DataFrame())

if not ext.empty:
    ext = ext.copy()
    ext["mes"] = ext["data"].map(mes_ref)
    # transferência entre as próprias contas: sai de uma e entra na outra — não é entrada nem saída
    entram = set(ext.loc[ext["fonte"] == "entrada_transf", "id"].dropna())
    ext["interna"] = ext["id"].isin(entram) & (
        (ext["fonte"] == "entrada_transf") | ((ext["valor"] < 0) & (ext["fonte"] != "fatura")))

linhas_mes, saldo = [], s0
for m in meses:
    d = ext[ext["mes"] == m] if not ext.empty else ext
    real = d[(d["fonte"] != "ajuste") & (~d["interna"])] if not d.empty else d
    ent = float(real.loc[real["valor"] > 0, "valor"].sum()) if not real.empty else 0.0
    sai = float(-real.loc[real["valor"] < 0, "valor"].sum()) if not real.empty else 0.0
    aj = float(d.loc[d["fonte"] == "ajuste", "valor"].sum()) if not d.empty else 0.0
    total = float(d["valor"].sum()) if not d.empty else 0.0
    linhas_mes.append(dict(mes=m, rotulo=mes_label(m), inicial=saldo, entradas=ent, saidas=sai, ajustes=aj,
                           final=saldo + total, resultado=ent - sai))
    saldo += total
fluxo = pd.DataFrame(linhas_mes)

# saldo no fim de cada dia (real até hoje, previsto depois)
por_dia = ext.groupby("data")["valor"].sum() if not ext.empty else pd.Series(dtype=float)
dias, corr = [], s0
for d in pd.date_range(ini_w, fim_w, freq="D").date:
    corr += float(por_dia.get(d, 0.0))
    dias.append({"data": pd.Timestamp(d), "saldo": round(corr, 2), "tipo": "Real" if d <= hj else "Previsto"})
diario = pd.DataFrame(dias)
saldo_hoje = float(diario.loc[diario["data"] == pd.Timestamp(hj), "saldo"].iloc[0]) if not diario.empty else 0.0

# --- card do mês escolhido -----------------------------------------------------------------------
f = fluxo[fluxo["mes"] == sel].iloc[0]
if sel == atual:
    rot, val = "Saldo hoje", saldo_hoje
    rot_fim = f"Previsto {_fim(sel):%d/%m}"
elif sel < atual:
    rot, val, rot_fim = f"Saldo em {_fim(sel):%d/%m}", f["final"], "Saldo final"
else:
    rot, val, rot_fim = f"Saldo previsto em {_fim(sel):%d/%m}", f["final"], "Previsto no fim"
c1, c2 = ("#0B4F45", "#12907F") if f["final"] >= 0 else ("#7A1D2B", "#C2334A")
minis = [("Saldo inicial", brl(f["inicial"])), ("↑ Entradas", brl(f["entradas"])), ("↓ Saídas", brl(f["saidas"])),
         (rot_fim, brl(f["final"]))]
cartoes_kpi([(rot, brl(val))] + minis, titulo=f"Fluxo de caixa · {mes_label(sel)}", icone="💧",
            sub=("Resultado do mês: " + ("+" if f["resultado"] >= 0 else "−") + " " + brl(abs(f["resultado"]))
                 + (f" · ajustes {brl(f['ajustes'])}" if abs(f["ajustes"]) > 0.004 else "")),
            direita="real" if sel < atual else ("real + previsto" if sel == atual else "previsão"), c1=c1, c2=c2)

futuro = diario[diario["data"] > pd.Timestamp(hj)] if not diario.empty else diario
if not futuro.empty:
    pior = futuro.loc[futuro["saldo"].idxmin()]
    if pior["saldo"] < 0:
        st.markdown(f"<div class='ui-aviso'>⚠️ O saldo fica <b>negativo</b> — chega a <b>{brl(pior['saldo'])}</b> "
                    f"em {pior['data']:%d/%m/%Y}. Confira se o salário está em <b>Contas fixas</b> ou planeje um "
                    "resgate.</div>", unsafe_allow_html=True)

# --- previsão de caixa (dia a dia) ---------------------------------------------------------------
st.markdown("<div class='ui-sec'>Previsão de caixa</div>", unsafe_allow_html=True)
with st.container(border=True):
    if diario.empty:
        st.caption("Cadastre suas contas correntes para ver a previsão.")
    else:
        faixa = pd.DataFrame({"ini": [pd.Timestamp(_ini(sel))], "fim": [pd.Timestamp(_fim(sel))]})
        base = alt.Chart(diario).encode(x=alt.X("data:T", title=None, axis=alt.Axis(format="%b/%y", grid=False)))
        area = base.mark_area(opacity=.14, color="#0F766E", interpolate="step-after").encode(
            y=alt.Y("saldo:Q", title=None, axis=alt.Axis(format=",.0f", gridOpacity=.2)))
        linha = base.mark_line(strokeWidth=2.4, interpolate="step-after").encode(
            y="saldo:Q",
            color=alt.Color("tipo:N", scale=alt.Scale(domain=["Real", "Previsto"], range=["#0F766E", "#6366F1"]),
                            legend=alt.Legend(title=None, orient="top")),
            strokeDash=alt.StrokeDash("tipo:N", scale=alt.Scale(domain=["Real", "Previsto"],
                                                                range=[[1, 0], [6, 4]]), legend=None),
            tooltip=[alt.Tooltip("data:T", title="Dia", format="%d/%m/%Y"),
                     alt.Tooltip("saldo:Q", title="Saldo", format=",.2f"), alt.Tooltip("tipo:N", title="")])
        mes_sel = alt.Chart(faixa).mark_rect(color="#FDE68A", opacity=.25).encode(x="ini:T", x2="fim:T")
        hoje_r = alt.Chart(pd.DataFrame({"d": [pd.Timestamp(hj)]})).mark_rule(color="#334155", strokeDash=[2, 3]
                                                                               ).encode(x="d:T")
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#e5484d", strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart((mes_sel + area + linha + hoje_r + zero).properties(height=230 if cel else 260),
                        use_container_width=True)
        prox90 = futuro[futuro["data"] <= pd.Timestamp(hj + timedelta(days=90))]
        if not prox90.empty:
            m = prox90.loc[prox90["saldo"].idxmin()]
            st.caption(f"Faixa amarela = {mes_label(sel)} · linha tracejada = previsão · menor saldo nos próximos "
                       f"90 dias: **{brl(m['saldo'])}** em {m['data']:%d/%m}")

# --- fluxo de caixa mês a mês --------------------------------------------------------------------
st.markdown("<div class='ui-sec'>Fluxo de caixa mês a mês</div>", unsafe_allow_html=True)
with st.container(border=True):
    barras = fluxo.melt(id_vars=["rotulo", "mes"], value_vars=["entradas", "saidas"], var_name="tipo",
                        value_name="valor")
    barras["tipo"] = barras["tipo"].map({"entradas": "Entradas", "saidas": "Saídas"})
    ordem = list(fluxo["rotulo"])
    b = alt.Chart(barras).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, opacity=.9).encode(
        x=alt.X("rotulo:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0 if not cel else -45)),
        xOffset=alt.XOffset("tipo:N", sort=["Entradas", "Saídas"]),
        y=alt.Y("valor:Q", title=None, axis=alt.Axis(format=",.0f", gridOpacity=.2)),
        color=alt.Color("tipo:N", scale=alt.Scale(domain=["Entradas", "Saídas", "Saldo final"],
                                                  range=["#16A34A", "#E5484D", "#6366F1"]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("rotulo:N", title="Mês"), alt.Tooltip("tipo:N", title=""),
                 alt.Tooltip("valor:Q", title="R$", format=",.2f")])
    sf = fluxo.assign(tipo="Saldo final")
    ln = alt.Chart(sf).mark_line(point=True, strokeWidth=2.4).encode(
        x=alt.X("rotulo:N", sort=ordem), y="final:Q", color=alt.Color("tipo:N"),
        tooltip=[alt.Tooltip("rotulo:N", title="Mês"), alt.Tooltip("final:Q", title="Saldo final", format=",.2f")])
    st.altair_chart((b + ln).properties(height=250 if cel else 270), use_container_width=True)

    # tabela: meses nas colunas, mês escolhido em destaque
    cab = "".join(f"<th class='{'sel' if r.mes == sel else ''}{' fut' if r.mes > atual else ''}'>{r.rotulo}</th>"
                  for r in fluxo.itertuples())

    def _linha(nome, campo, cls=""):
        tds = "".join(f"<td class='{'sel' if r.mes == sel else ''} {cls}'>{brl(getattr(r, campo))}</td>"
                      for r in fluxo.itertuples())
        return f"<tr><th>{nome}</th>{tds}</tr>"

    tem_aj = (fluxo["ajustes"].abs() > 0.004).any()
    _ui.render(f"""<div class="ui-fluxo"><table><thead><tr><th></th>{cab}</tr></thead><tbody>
        {_linha('Saldo inicial', 'inicial')}{_linha('↑ Entradas', 'entradas', 'pos')}{_linha('↓ Saídas', 'saidas', 'neg')}
        {_linha('Ajustes', 'ajustes') if tem_aj else ''}{_linha('Saldo final', 'final', 'fim')}
        </tbody></table></div>""")
    st.caption("Contas correntes suas. Faturas de cartão entram como saída no vencimento, na conta que paga. "
               "Transferências entre as suas contas não contam como entrada nem saída. Meses à frente = previsão "
               "(contas fixas, parcelas e faturas já lançadas).")

# --- contas e cartões ---------------------------------------------------------------------------
cards = []
for r in caixa.itertuples():
    try:
        sh = saldos.saldo_em(u, r.id, min(hj, _fim(sel)) if sel <= atual else _fim(sel))
    except Exception:  # noqa: BLE001
        sh = 0.0
    cards.append(f"<div class='ui-card'>{_ui.selo(r.nome, r.instituicao, 38)}"
                 f"<div style='min-width:0'><div class='n'>{_ui.esc(r.nome)}</div>"
                 f"<div class='s'>{brl(sh)}</div>"
                 f"<div class='n' style='font-size:.7rem'>{'hoje' if sel == atual else ('em ' + f'{_fim(sel):%d/%m}')}"
                 f"</div></div></div>")
try:
    from core import beneficios as _bn
    for b in _bn.contas(u).itertuples():
        sb = saldos.saldo_em(u, b.id, hj if sel == atual else _fim(sel))
        cards.append(f"<div class='ui-card'><div class='ui-selo ui-selo-txt' style='width:38px;height:38px;"
                     f"background:linear-gradient(135deg,#9A3412,#EA580C)'>🍽️</div>"
                     f"<div style='min-width:0'><div class='n'>{_ui.esc(b.nome)}</div><div class='s'>{brl(sb)}</div>"
                     f"<div class='n' style='font-size:.7rem'>benefício · fora do fluxo</div></div></div>")
except Exception:  # noqa: BLE001
    pass
fat = cartoes.faturas(u)
if not fat.empty:
    info = contas.set_index("id")
    for r in fat[fat["mes_ref"] == sel].sort_values("vencimento").itertuples():
        if r.cartao_id not in info.index:
            continue
        c = info.loc[r.cartao_id]
        cards.append(f"<div class='ui-card'>{_ui.selo(c['nome'], c['instituicao'], 38)}"
                     f"<div style='min-width:0'><div class='n'>{_ui.esc(c['nome'])}</div>"
                     f"<div class='s'>{brl(r.total)}</div>"
                     f"<div class='n' style='font-size:.7rem'>{'paga' if r.paga else 'fatura'} · vence "
                     f"{r.vencimento:%d/%m}</div></div></div>")
if cards:
    st.markdown(f"<div class='ui-sec'>Contas e cartões · {mes_label(sel)}</div>", unsafe_allow_html=True)
    _ui.render(f"<div class='ui-grade'>{''.join(cards)}</div>")
    l1, l2, _ = st.columns([1, 1, 2] if not cel else [1, 1, 0.01])
    l1.page_link("telas/contas_correntes.py", label="Ver extratos", icon=":material/account_balance_wallet:")
    l2.page_link("telas/cartoes.py", label="Ver faturas", icon=":material/credit_card:")

# --- gastos do mês por categoria e próximos vencimentos -----------------------------------------
tot = repo.totais_por_mes(u, escopo, sel, sel)
desp = tot[tot["tipo"] == "despesa"].copy() if not tot.empty else tot
if not desp.empty:
    desp["valor"] = desp["valor"].astype(float)

esq, dir_ = (st.container(), st.container()) if cel else st.columns(2)
with esq:
    st.markdown(f"<div class='ui-sec'>Gastos de {mes_label(sel)} por categoria</div>", unsafe_allow_html=True)
    if desp.empty:
        st.caption("Nada lançado neste mês.")
    else:
        pago = float(desp.loc[desp["status"] == "pago", "valor"].sum())
        aberto = float(desp.loc[desp["status"] == "previsto", "valor"].sum())
        cat = desp.groupby("categoria", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
        total_cat = float(cat["valor"].sum()) or 1.0
        linhas = [f"<div class='ui-cat'><div class='t'><span>Total do mês</span><span class='v'>{brl(total_cat)}</span>"
                  f"</div><div class='p'>pago {brl(pago)} · a pagar {brl(aberto)}</div></div>"]
        for r in cat.itertuples():
            pct = float(r.valor) / total_cat
            linhas.append(f"""<div class="ui-cat"><div class="t"><span>{_ui.esc(r.categoria or 'Sem categoria')}</span>
                <span class="v">{brl(r.valor)}</span></div>
                <div class="barra"><div style="width:{pct * 100:.0f}%"></div></div>
                <div class="p">{pct:.0%} do mês</div></div>""")
        _ui.render(f"<div class='ui-lista-html'>{''.join(linhas)}</div>")

with dir_:
    if sel == atual:
        titulo_v, de, ate = "Vencendo nos próximos 15 dias", hj, hj + timedelta(days=15)
    elif sel > atual:
        titulo_v, de, ate = f"A pagar em {mes_label(sel)}", _ini(sel), _fim(sel)
    else:
        titulo_v, de, ate = f"Ficou em aberto em {mes_label(sel)}", _ini(sel), _fim(sel)
    st.markdown(f"<div class='ui-sec'>{titulo_v}</div>", unsafe_allow_html=True)
    lanc = repo.lancamentos(u, escopo, mes_ref(de), mes_ref(ate))
    janela = pd.DataFrame()
    if not lanc.empty:
        lanc["data_vencimento"] = pd.to_datetime(lanc["data_vencimento"]).dt.date
        janela = lanc[(lanc["status"] == "previsto") & (lanc["tipo"] == "despesa")
                      & (lanc["data_vencimento"] >= de) & (lanc["data_vencimento"] <= ate)]
    if janela.empty:
        st.caption("Nada em aberto aqui. 🎉")
    else:
        mostrar = janela.sort_values(["data_vencimento", "valor"], ascending=[True, False]).head(25)
        with st.container(key="uilista_venc"):
            for r in mostrar.itertuples():
                d = r.data_vencimento
                ic = (f"<div style='font-size:.62rem;line-height:1;text-align:center'><b style='font-size:.95rem'>"
                      f"{d.day:02d}</b><br>{_ui.MESES[d.month - 1]}</div>")
                sub = " · ".join(x for x in [r.conta if isinstance(r.conta, str) else "",
                                             r.categoria if isinstance(r.categoria, str) else ""] if x)
                acao = (lambda i=r.id: _ui.editar_lancamento(u, i)) if r.meu else (lambda: None)
                _ui.linha_editavel(f"pv{r.Index}", _ui.item_html(ic, r.descricao, sub),
                                   _ui.valor_html(-float(r.valor)), acao)
        extra = f" · mostrando 25 de {len(janela)}" if len(janela) > 25 else ""
        st.caption(f"Total: **{brl(janela['valor'].astype(float).sum())}**{extra}")

if escopo == "nos" and not desp.empty:
    outros = desp[~desp["meu"]]
    if not outros.empty:
        st.caption(f"Inclui {brl(outros['valor'].sum())} compartilhados pelo outro membro do casal "
                   "(itens marcados como “só o total” entram nas somas, mas não aparecem nas listas).")

st.markdown("""<style>
.ui-fluxo {overflow-x: auto; margin-top: 6px;}
.ui-fluxo table {border-collapse: separate; border-spacing: 0; width: 100%; font-size: .82rem; white-space: nowrap;}
.ui-fluxo th, .ui-fluxo td {padding: 7px 10px; text-align: right; border-bottom: 1px solid rgba(15,23,42,.06);}
.ui-fluxo thead th {font-size: .74rem; text-transform: uppercase; letter-spacing: .5px; color: #64748B;}
.ui-fluxo thead th.fut {color: #6366F1;}
.ui-fluxo tbody th {text-align: left; font-weight: 600; color: #334155; position: sticky; left: 0; background: #fff;}
.ui-fluxo td.pos {color: #16A34A;} .ui-fluxo td.neg {color: #E5484D;}
.ui-fluxo td.fim {font-weight: 800; color: #0F172A;}
.ui-fluxo .sel {background: rgba(15,118,110,.08);}
.ui-fluxo thead th.sel {color: #0F766E; font-weight: 800; border-bottom: 2px solid #0F766E;}
@media (max-width: 640px) {
  .st-key-painel_mes [role="radiogroup"] {flex-wrap: nowrap !important; overflow-x: auto; padding-bottom: 6px;
       scrollbar-width: none;}
  .st-key-painel_mes button {flex-shrink: 0;}
}
</style>""", unsafe_allow_html=True)

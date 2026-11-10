from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core import cartoes, cascata, repo, saldos
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref, somar_meses
from telas import _ui
from telas._comum import cartoes_kpi, e_celular, seletor_escopo, usuario

u = usuario()
cel = e_celular()
_ui.aviso_ok()
topo_esq, topo_dir = st.columns([3, 1], vertical_alignment="bottom")
with topo_esq:
    _ui.titulo("Fluxo de caixa", "💧")
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
    # "não contar": passa pela conta (saldo) mas fica fora de entradas/saídas e da sobra
    ext["interna"] |= ext["nao_contar"].fillna(False).astype(bool)

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
        area = base.mark_area(opacity=.14, color="#0B7A66", interpolate="step-after").encode(
            y=alt.Y("saldo:Q", title=None, axis=alt.Axis(format=",.0f", gridOpacity=.2)))
        linha = base.mark_line(strokeWidth=2.4, interpolate="step-after").encode(
            y="saldo:Q",
            color=alt.Color("tipo:N", scale=alt.Scale(domain=["Real", "Previsto"], range=["#0B7A66", "#64748B"]),
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

# --- fluxo de caixa em cascata: um mês por coluna ---------------------------------------------------
st.markdown("<div class='ui-sec'>Fluxo de caixa mês a mês</div>", unsafe_allow_html=True)
casc = cascata.montar(ext, meses, s0)
res = casc["resumo"]
with st.container(key="casc_barra"):
    cb1, cb2, cb3 = st.columns([2.2, 1.2, 1], vertical_alignment="center")
    abrir = cb1.toggle("Abrir as categorias", key="casc_abrir", value=False)
    janela = cb2.segmented_control("Meses", ["6", "12"], default="6" if cel else "12", key="casc_jan",
                                   label_visibility="collapsed")
    if not res.empty:
        cb3.download_button("Exportar Excel", cascata.excel(res, casc["linhas"], ext),
                            file_name=f"fluxo-de-caixa-{hj:%Y-%m-%d}.xlsx", icon=":material/download:",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True, key="casc_xlsx")

# simulação: gasto extra por mês e/ou retirada única
with st.expander("E se…? (simular)", icon=":material/tune:"):
    s1, s2, s3 = st.columns(3)
    extra = s1.number_input("Gasto a mais por mês (R$)", 0.0, step=100.0, key="sim_extra",
                            help="Ex.: 2.000 de cartão novo todo mês, que ainda não está lançado.")
    retirada = s2.number_input("Retirada única (R$)", 0.0, step=500.0, key="sim_ret",
                               help="Ex.: entrada de um intercâmbio, compra grande.")
    mes_ret = s3.selectbox("No mês", [m for m in meses if m >= atual], format_func=mes_label, key="sim_mes")
sim = cascata.simular(res, extra, retirada, mes_ret, a_partir=atual) if (extra or retirada) else None

# mostra só a janela escolhida, a partir do mês atual (passado fica no Excel)
vis = [m for m in meses if m >= atual][: int(janela or 12)]
res_v = res[res["mes"].isin(vis)]
det = casc["linhas"]
serie = (sim if sim is not None else res)[["mes", "saldo_fim"] + (["saldo_sim"] if sim is not None else [])]
y_col = "saldo_sim" if sim is not None else "saldo_fim"
y_min, y_max = float(min(0, serie[y_col].min())), float(max(serie[y_col].max(), 1))


def _spark(m):
    """Linha do saldo acumulado da janela, com o ponto deste mês."""
    pts = []
    n = max(len(vis) - 1, 1)
    for i, mm in enumerate(vis):
        v = float(serie.loc[serie["mes"] == mm, y_col].iloc[0])
        pts.append(f"{i / n * 100:.1f},{46 - (v - y_min) / (y_max - y_min) * 40:.1f}")
    i = vis.index(m)
    v = float(serie.loc[serie["mes"] == m, y_col].iloc[0])
    cy = 46 - (v - y_min) / (y_max - y_min) * 40
    zero = "" if y_min >= 0 else f"<line x1='0' x2='100' y1='{46 - (0 - y_min) / (y_max - y_min) * 40:.1f}' y2='{46 - (0 - y_min) / (y_max - y_min) * 40:.1f}' class='z'/>"
    return (f"<svg viewBox='0 0 100 48' preserveAspectRatio='none'>{zero}<polyline points='{' '.join(pts)}'/>"
            f"<circle cx='{i / n * 100:.1f}' cy='{cy:.1f}' r='3' class='{'neg' if v < 0 else ''}'/></svg>")


# com as categorias abertas, todos os meses mostram as MESMAS linhas em cada bloco (união das categorias,
# ordenadas pelo total da janela), com "—" onde não há valor — assim Aluguel fica na mesma altura em toda coluna
det_v = det[det["mes"].isin(vis)]
_ordem = {b: list(det_v[det_v["bloco"] == b].groupby("categoria")["valor"].sum().sort_values(ascending=False).index)
          for b in ["Entradas"] + cascata.BLOCOS}


def _rows(m, bloco, cls):
    d = det_v[(det_v["mes"] == m) & (det_v["bloco"] == bloco)].set_index("categoria")["valor"]
    out = []
    for cat in _ordem.get(bloco, []):
        v = float(d.get(cat, 0.0))
        out.append(f"<div class='r sub{' vazio' if v < 0.004 else ''}'><span>{_ui.esc(str(cat))}</span>"
                   f"<span>{brl(v) if v >= 0.004 else '—'}</span></div>")
    return "".join(out)


cols_html = []
for r in res_v.itertuples():
    m = r.mes
    sv = float(serie.loc[serie["mes"] == m, y_col].iloc[0])
    blocos = ""
    linha_m = res_v.loc[res_v["mes"] == m].iloc[0]
    for b_ in cascata.BLOCOS:
        v = float(linha_m[b_])
        if abs(v) < 0.004 and not (abrir and _ordem.get(b_)):
            continue
        blocos += (f"<div class='r blk'><span>{b_.replace('Faturas de cartão', 'Faturas').replace('Outras saídas', 'Outras')}</span>"
                   f"<span>{'− ' + brl(v) if abs(v) >= 0.004 else '—'}</span></div>")
        if abrir:
            blocos += _rows(m, b_, "sub")
    ent_rows = _rows(m, "Entradas", "sub") if abrir else ""
    sobra_cls = "neg" if r.sobra < 0 else "pos"
    sim_html = (f"<div class='r sim'><span>Simulado</span><span class='{'neg' if sv < 0 else ''}'>{brl(sv)}</span></div>"
                if sim is not None else "")
    cols_html.append(f"""<div class="mes {'hoje' if m == atual else ''}">
        <div class="h"><span>{r.rotulo}</span><b class="{'neg' if r.saldo_fim < 0 else ''}">{brl(r.saldo_fim)}</b></div>
        <div class="sp">{_spark(m)}</div>
        <div class="r in"><span>Entradas</span><span>+ {brl(r.entradas)}</span></div>{ent_rows}
        {blocos}
        <div class="r tot"><span>Sobra do mês</span><span class="{sobra_cls}">{'−' if r.sobra < 0 else '+'} {brl(abs(r.sobra))}</span></div>
        <div class="r saldo"><span>Saldo no fim do mês</span><span class="{'neg' if r.saldo_fim < 0 else ''}">{brl(r.saldo_fim)}</span></div>
        {sim_html}</div>""")
_ui.render(f"<div class='ui-casc'>{''.join(cols_html)}</div>")
if sim is not None:
    pior = sim[sim["mes"].isin(vis)].loc[lambda d: d["saldo_sim"].idxmin()]
    st.caption("Simulação: " + (f"{brl(extra)}/mês a mais " if extra else "") + ("e " if extra and retirada else "")
               + (f"retirada de {brl(retirada)} em {mes_label(mes_ret)} " if retirada else "")
               + f"→ menor saldo **{brl(pior['saldo_sim'])}** em {pior['rotulo']}.")

# --- por conta e por cartão, mês a mês ---------------------------------------------------------------
st.markdown("<div class='ui-sec'>Contas e cartões mês a mês</div>", unsafe_allow_html=True)
visao = st.segmented_control("Ver", ["contas", "cartoes"], default="contas", key="painel_visao",
                             format_func={"contas": "🏦 Saldo de cada conta", "cartoes": "💳 Quanto pagar de cada cartão"}.get,
                             label_visibility="collapsed") or "contas"
_cab_m = "".join(f"<th class='{'sel' if m == sel else ''}{' fut' if m > atual else ''}'>{mes_label(m)}</th>"
                 for m in meses)


def _td(v, m, cls=""):
    return f"<td class='{'sel' if m == sel else ''} {cls}'>{brl(v) if abs(v) > 0.004 else '—'}</td>"


if visao == "contas":
    if caixa.empty:
        st.caption("Cadastre suas contas correntes para ver o saldo de cada uma.")
    for c in caixa.itertuples():
        e = ext[ext["conta"].astype(str) == str(c.id)] if not ext.empty else ext
        try:
            s_c = saldos.saldo_em(u, c.id, ini_w - timedelta(days=1))
        except Exception:  # noqa: BLE001
            s_c = 0.0
        lin = {"ini": [], "ent": [], "fat": [], "out": [], "fim": []}
        for m in meses:
            d = e[e["mes"] == m] if not e.empty else e
            real = d[d["fonte"] != "ajuste"] if not d.empty else d
            ent = float(real.loc[real["valor"] > 0, "valor"].sum()) if not real.empty else 0.0
            fat_ = float(-real.loc[(real["valor"] < 0) & (real["fonte"] == "fatura"), "valor"].sum()) if not real.empty else 0.0
            out = float(-real.loc[(real["valor"] < 0) & (real["fonte"] != "fatura"), "valor"].sum()) if not real.empty else 0.0
            tot = float(d["valor"].sum()) if not d.empty else 0.0
            lin["ini"].append(s_c); lin["ent"].append(ent); lin["fat"].append(fat_); lin["out"].append(out)
            s_c += tot
            lin["fim"].append(s_c)
        linhas = "".join(
            f"<tr><th>{rot}</th>{''.join(_td(v, m, cls) for v, m in zip(lin[k], meses))}</tr>"
            for rot, k, cls in [("Saldo inicial", "ini", ""), ("↑ Entradas", "ent", "pos"),
                                ("↓ Faturas de cartão", "fat", "neg"), ("↓ Outras saídas", "out", "neg"),
                                ("Sobra no fim do mês", "fim", "fim")])
        _ui.render(f"""<div class="ui-lista-html" style="margin-bottom:12px">
            <div class="ui-item" style="padding:10px 0 4px">{_ui.selo(c.nome, c.instituicao, 34)}
              <div class="ui-tx"><div class="t">{_ui.esc(c.nome)}</div>
              <div class="s">em {mes_label(sel)}: sobra {brl(lin['fim'][meses.index(sel)])}</div></div></div>
            <div class="ui-fluxo"><table><thead><tr><th></th>{_cab_m}</tr></thead><tbody>{linhas}</tbody></table></div>
            </div>""")
else:
    fat_all = cartoes.faturas(u)
    info_c = contas.set_index("id")
    if fat_all.empty:
        st.caption("Nenhuma fatura no app ainda.")
    else:
        linhas, total = [], {m: 0.0 for m in meses}
        for cid, g in fat_all.groupby("cartao_id"):
            if cid not in info_c.index:
                continue
            c = info_c.loc[cid]
            por = dict(zip(g["mes_ref"], g["total"]))
            pagas = set(g.loc[g["paga"], "mes_ref"])
            for m in meses:
                total[m] += float(por.get(m, 0.0))
            paga_por = info_c.loc[c["conta_pagamento_id"], "nome"] if pd.notna(c.get("conta_pagamento_id")) and \
                c["conta_pagamento_id"] in info_c.index else "sem conta definida"
            tds = "".join(f"<td class='{'sel' if m == sel else ''} neg'>{brl(por[m]) if por.get(m) else '—'}"
                          f"{' ✓' if m in pagas else ''}</td>" for m in meses)
            linhas.append(f"<tr><th><div class='ui-item' style='gap:8px'>{_ui.selo(c['nome'], c['instituicao'], 26)}"
                          f"<div><div style='font-weight:700'>{_ui.esc(c['nome'])}</div>"
                          f"<div style='font-size:.7rem;opacity:.6;font-weight:500'>sai de {_ui.esc(paga_por)}</div>"
                          f"</div></div></th>{tds}</tr>")
        tds_t = "".join(f"<td class='{'sel' if m == sel else ''} fim'>{brl(total[m]) if total[m] else '—'}</td>"
                        for m in meses)
        _ui.render(f"""<div class="ui-lista-html"><div class="ui-fluxo"><table><thead><tr><th></th>{_cab_m}</tr></thead>
            <tbody>{''.join(linhas)}<tr><th>Total dos cartões</th>{tds_t}</tr></tbody></table></div></div>""")

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

# --- detalhe da categoria clicada (mostrado no lugar dos vencimentos) ---------------------------
_ORIG = {"migracao": "planilha", "importacao": "fatura/extrato", "applepay": "Caixa de entrada",
         "android": "Caixa de entrada", "recorrencia": "conta fixa", "manual": "manual", "ia": "IA"}


def _detalhe_cat(cat_sel):
    lm = repo.lancamentos(u, escopo, sel, sel)
    lm = lm[lm["tipo"] == "despesa"].copy() if not lm.empty else lm
    if not lm.empty:
        lm["categoria"] = lm["categoria"].fillna("Sem categoria")
        lm = lm[lm["categoria"] == cat_sel].copy()
    st.markdown(f"<div class='ui-sec'>🔎 {_ui.esc(cat_sel)} · {mes_label(sel)}</div>", unsafe_allow_html=True)
    if lm.empty:
        st.caption("Nada nesta categoria no mês.")
    else:
        lm["valor"] = lm["valor"].astype(float)
        lm["_chave"] = lm["descricao"].fillna("").map(_ui.sem_acento).str.replace(r"[^a-z0-9]", "", regex=True) \
            + "|" + lm["valor"].round(2).astype(str)
        dup = lm["_chave"].duplicated(keep=False)
        subs = lm.assign(sub=lm["subcategoria"].fillna("—")).groupby("sub")["valor"].sum().sort_values(ascending=False)
        k1, k3 = st.columns([4, 1], vertical_alignment="center")
        with k1:
            _ui.render(f"<div style='font-weight:800'>{len(lm)} lançamentos · {brl(lm['valor'].sum())}</div>"
                       f"<div style='font-size:.78rem;opacity:.7'>"
                       + " · ".join(f"{_ui.esc(n)} {brl(v)}" for n, v in subs.items()) + "</div>")
        if k3.button("", icon=":material/close:", key="fecha_cat", help="Fechar", use_container_width=True):
            st.session_state["_painel_cat"] = None
            st.rerun()
        if dup.any():
            st.markdown(f"<div class='ui-aviso'>⚠️ <b>{int(dup.sum())} lançamentos parecem duplicados</b> (mesma "
                        "descrição e mesmo valor no mês) — marcados abaixo. Confira e exclua o que estiver a mais "
                        "pelo ✏️.</div>", unsafe_allow_html=True)
        with st.container(key="uilista_catdet"):
            for i, r in lm.assign(_dup=dup).sort_values(["_dup", "valor"], ascending=[False, False]).iterrows():
                d = pd.to_datetime(r["data_vencimento"]).date()
                ic = (f"<div style='font-size:.62rem;line-height:1;text-align:center'><b style='font-size:.95rem'>"
                      f"{d.day:02d}</b><br>{_ui.MESES[d.month - 1]}</div>")
                parc = f"{int(r['parcela_num'])}/{int(r['parcela_total'])}" if pd.notna(r["parcela_num"]) else ""
                sub = " · ".join(x for x in [r["subcategoria"] if isinstance(r["subcategoria"], str) else "",
                                             r["conta"] if isinstance(r["conta"], str) else "sem conta",
                                             _ORIG.get(r["origem"], "")] if x)
                tag, tcls = ("duplicado?", "aj") if r["_dup"] else (parc, "")
                acao = (lambda lid=r["id"]: _ui.editar_lancamento(u, lid)) if r["meu"] else (lambda: None)
                _ui.linha_editavel(f"cd{i}", _ui.item_html(ic, r["descricao"], sub, tag, tcls, r["status"] == "previsto"),
                                   _ui.valor_html(-float(r["valor"]), r["status"] == "previsto"), acao)



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
        _ui.render(f"<div class='ui-lista-html' style='margin-bottom:6px'>{linhas[0]}</div>")
        cat_sel = st.session_state.get("_painel_cat")
        with st.container(key="uilista_cats"):
            for i, r in enumerate(cat.itertuples()):
                pct = float(r.valor) / total_cat
                nome_c = r.categoria or "Sem categoria"
                marcado = cat_sel == nome_c
                with st.container(key=f"uirow_cat{i}"):
                    a1, a2 = st.columns([6, 0.6], vertical_alignment="center")
                    a1.markdown(f"""<div class="ui-cat" style="border:none;padding:4px 0">
                        <div class="t"><span>{'👉 ' if marcado else ''}{_ui.esc(nome_c)}</span>
                        <span class="v">{brl(r.valor)}</span></div>
                        <div class="barra"><div style="width:{pct * 100:.0f}%"></div></div>
                        <div class="p">{pct:.0%} do mês</div></div>""".replace("\n", ""), unsafe_allow_html=True)
                    if a2.button("", key=f"vercat_{i}", icon=":material/close:" if marcado else ":material/search:",
                                 help="Fechar" if marcado else f"Ver lançamentos de {nome_c}"):
                        st.session_state["_painel_cat"] = None if marcado else nome_c
                        st.rerun()

with dir_:
    _cat_sel = st.session_state.get("_painel_cat") if not desp.empty else None
    if _cat_sel:
        _detalhe_cat(_cat_sel)
    else:
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
.ui-fluxo thead th.fut {color: #64748B;}
.ui-fluxo tbody th {text-align: left; font-weight: 600; color: #334155; position: sticky; left: 0; background: #fff;}
.ui-fluxo td.pos {color: #16A34A;} .ui-fluxo td.neg {color: #E5484D;}
.ui-fluxo td.fim {font-weight: 800; color: #0F172A;}
.ui-fluxo .sel {background: rgba(11,122,102,.08);}
.ui-fluxo thead th.sel {color: #0B7A66; font-weight: 800; border-bottom: 2px solid #0B7A66;}
@media (max-width: 640px) {
  .st-key-painel_mes [role="radiogroup"] {flex-wrap: nowrap !important; overflow-x: auto; padding-bottom: 6px;
       scrollbar-width: none;}
  .st-key-painel_mes button {flex-shrink: 0;}
}
</style>""", unsafe_allow_html=True)

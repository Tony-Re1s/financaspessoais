from datetime import date

import pandas as pd
import streamlit as st

from core import ir, repo, saldos
from core import recorrencias as rec
from core.fmt import brl, hoje
from telas import _ui
from telas._comum import cartoes_kpi, e_celular, usuario

u = usuario()
cel = e_celular()
_ui.aviso_ok()
_ui.titulo("Imposto de Renda", "🦁",
           sub="Suba os holerites do ano: o app soma tudo, projeta até dezembro e mostra como fica a declaração.")

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

# --- subir holerites ------------------------------------------------------------------------------
with st.expander("📄 Subir holerites (PDF)", expanded=not ir.anos(u)):
    arqs = st.file_uploader("Holerites", type=["pdf"], accept_multiple_files=True, key="up_hol",
                            label_visibility="collapsed")
    if arqs:
        lidos, erros = [], []
        for a in arqs:
            try:
                lidos.append(ir.ler_holerite(a.name, a.getvalue()))
            except Exception as e:  # noqa: BLE001
                erros.append(f"{a.name}: {e}")
        for e in erros:
            st.warning(e)
        if lidos:
            lidos.sort(key=lambda h: (h["ano"], h["mes"]))
            st.caption(" · ".join(f"{MESES[h['mes'] - 1]}/{h['ano']} ({brl(h['liquido'])})" for h in lidos))
            if st.button(f"Salvar {len(lidos)} holerites", type="primary", icon=":material/save:"):
                for h in lidos:
                    ir.salvar(u, h)
                st.session_state["_ui_ok"] = f"{len(lidos)} holerites salvos."
                st.session_state.pop("up_hol", None)
                st.rerun()

anos = ir.anos(u)
if not anos:
    st.info("Nenhum holerite ainda. Suba os PDFs do ano acima (pode selecionar vários de uma vez).")
    st.stop()

c1, c2, c3 = st.columns([1, 1.2, 1.2], vertical_alignment="center")
ano = c1.selectbox("Ano", anos, index=0, label_visibility="collapsed", format_func=lambda a: f"Ano {a}")
projetar = c2.toggle("Projetar até dezembro", value=True,
                     help="Repete o último mês normal nos meses que faltam e estima o 13º.")
dep = c3.number_input("Dependentes", 0, 10, 0, help="Filhos, cônjuge sem renda… (dedução por dependente)")

hol = ir.holerites(u, ano)
pm = ir.por_mes(hol)
r = ir.resumo(pm, projetar=projetar, dependentes=dep)
melhor = r[r["melhor"]]
saldo = melhor["saldo"]
restitui = saldo < 0
c1_, c2_ = ("#0B4F45", "#12907F") if restitui else ("#7A1D2B", "#C2334A")
cartoes_kpi([("A restituir" if restitui else "A pagar", brl(abs(saldo))),
             ("Rendimentos tributáveis", brl(r["tributavel"])), ("IR já retido", brl(r["irrf"])),
             ("INSS", brl(r["inss"])), ("Melhor opção", "Simplificada" if r["melhor"] == "simplificada" else "Completa")],
            titulo=f"Declaração {ano + 1} · ano-calendário {ano}", icone="🦁", c1=c1_, c2=c2_,
            direita="com projeção" if r["projetado"] else "só o que já recebeu",
            sub=f"Holerites de {len(r['meses'])} meses"
                + (f" · projeção de {MESES[max(r['meses'])]} a dez" if r["projetado"] and max(r["meses"]) < 12 else ""))
if r["reducao_possivel"]:
    st.markdown("<div class='ui-aviso'>ℹ️ Rendimentos abaixo de R$ 88.200 no ano podem ter a redução extra da "
                "Lei 15.270/2025 — o app ainda não calcula essa parte.</div>", unsafe_allow_html=True)

# --- simplificada x completa -----------------------------------------------------------------------
st.markdown("<div class='ui-sec'>Simplificada ou completa?</div>", unsafe_allow_html=True)
cards = []
for k, nome, expl in [("simplificada", "Simplificada", f"20% dos tributáveis, até {brl(ir.LIMITE_SIMPLIFICADO)}"),
                      ("completa", "Completa", "INSS + saúde + previdência privada + dependentes")]:
    d = r[k]
    s = d["saldo"]
    sel = " style='outline:3px solid #0F766E;outline-offset:2px'" if r["melhor"] == k else ""
    cards.append(f"""<div class="ui-card"{sel}><div style="min-width:0;width:100%">
        <div class="n">{nome}{' · ✓ melhor' if r['melhor'] == k else ''}</div>
        <div class="s">{'Restitui' if s < 0 else 'Paga'} {brl(abs(s))}</div>
        <div class="n" style="font-size:.74rem">Deduções {brl(d['deducoes'])} · base {brl(d['base'])} ·
        imposto {brl(d['devido'])}</div><div class="n" style="font-size:.7rem">{expl}</div></div></div>""")
_ui.render(f"<div class='ui-grade' style='grid-template-columns:repeat(auto-fill,minmax(260px,1fr))'>{''.join(cards)}</div>")

# --- mês a mês -------------------------------------------------------------------------------------
st.markdown("<div class='ui-sec'>Mês a mês</div>", unsafe_allow_html=True)
with st.container(border=True):
    real = pm.groupby("mes").sum(numeric_only=True)
    ultimo_normal = pm[(pm["isento"] == 0) & (pm["plr"] == 0)].sort_values("mes").tail(1)
    linhas_def = [("Tributável", "tributavel", ""), ("INSS", "inss", "neg"), ("IR retido", "irrf", "neg"),
                  ("Plano de saúde", "saude", ""), ("PLR", "plr", "pos"), ("Isentos (abono)", "isento", "pos"),
                  ("Líquido", "liquido", "fim")]
    cab = "".join(f"<th class='{'' if m in real.index else 'fut'}'>{MESES[m - 1]}</th>" for m in range(1, 13))

    def _cel(m, campo):
        if m in real.index:
            return f"<td>{brl(real.loc[m, campo]) if real.loc[m, campo] else '—'}</td>"
        if projetar and not ultimo_normal.empty and campo in ("tributavel", "inss", "irrf", "saude", "liquido") \
                and m > max(real.index):
            v = float(ultimo_normal.iloc[0][campo])
            return f"<td class='proj'>{brl(v) if v else '—'}</td>"
        return "<td class='proj'>—</td>"

    corpo = "".join(f"<tr><th>{nome}</th>{''.join(_cel(m, campo).replace('<td', f'<td data-c={cls}', 1) for m in range(1, 13))}"
                    f"<td class='tot'>{brl(real[campo].sum())}</td></tr>" for nome, campo, cls in linhas_def)
    _ui.render(f"""<div class="ui-fluxo"><table><thead><tr><th></th>{cab}<th>Recebido</th></tr></thead>
        <tbody>{corpo}</tbody></table></div>""")
    st.caption("Em cinza: projeção. O 13º e a PLR têm tributação exclusiva — não entram no cálculo acima.")

# --- como declarar ---------------------------------------------------------------------------------
st.markdown("<div class='ui-sec'>Como fica na declaração</div>", unsafe_allow_html=True)
emp = pm["empresa"].dropna().iloc[-1] if not pm["empresa"].dropna().empty else "Empresa"
cnpj = pm["cnpj"].dropna().iloc[-1] if not pm["cnpj"].dropna().empty else "—"


def ficha(titulo_f, icone, linhas):
    itens = "".join(f"<div class='ui-cat'><div class='t'><span>{_ui.esc(a)}</span><span class='v'>{b}</span></div></div>"
                    for a, b in linhas)
    return (f"<div class='ui-lista-html' style='margin-bottom:12px'><div class='ui-cat' style='font-weight:800'>"
            f"{icone} {_ui.esc(titulo_f)}</div>{itens}</div>")


est13 = " (estimado)" if r["decimo_projetado"] else ""
html = ficha("Rendimentos tributáveis recebidos de PJ", "🏢", [
    ("Fonte pagadora", f"{_ui.esc(emp)} · {cnpj}"),
    ("Rendimentos recebidos", brl(r["tributavel"])),
    ("Contribuição previdenciária oficial (INSS)", brl(r["inss"])),
    ("Imposto retido na fonte", brl(r["irrf"])),
    (f"13º salário{est13}", brl(r["decimo"])),
    (f"IRRF sobre o 13º{est13}", brl(r["irrf_13"])),
])
html += ficha("Rendimentos sujeitos à tributação exclusiva", "🎯", [
    (f"13º salário (líquido de INSS){est13}", brl(r["decimo"] - r["inss_13"])),
    ("Participação nos lucros (PLR)", brl(r["plr"])),
    ("IR retido sobre a PLR (só informativo)", brl(r["irrf_plr"])),
])
html += ficha("Rendimentos isentos e não tributáveis", "🟢", [
    ("Abono pecuniário de férias + 1/3", brl(r["isento"])),
    ("FGTS depositado no ano (não declara)", brl(r["fgts"])),
])
html += ficha("Pagamentos efetuados (dedução na completa)", "🩺", [
    ("Plano de saúde / coparticipação (operadora: ver informe)", brl(r["saude"])),
])
if cel:
    _ui.render(html)
else:
    _ui.render(f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>{html}</div>")
st.caption("Confira com o **informe de rendimentos** que a empresa manda até o fim de fevereiro — ele é o "
           "documento oficial. Este resumo é uma estimativa para planejar e não substitui a orientação de um contador.")

# --- salário nas contas fixas ----------------------------------------------------------------------
st.markdown("<div class='ui-sec'>Salário no fluxo de caixa</div>", unsafe_allow_html=True)
ult = hol.sort_values(["ano", "mes"]).iloc[-1]
itens_ult = ult["itens"] if isinstance(ult["itens"], list) else __import__("json").loads(ult["itens"])
adto = sum(float(i["valor"]) for i in itens_ult if i["classe"] == "pagamento" and "adiant" in _ui.sem_acento(i["descricao"]))
liq = float(ult["liquido"] or 0)
sal_base = float(ult["salario_base"] or 0)
e13 = ir.estimar_13(sal_base, float(pm.sort_values("mes").iloc[-1]["inss"]))
recs = rec.listar(u)
ja = set(recs["descricao"].str.lower()) if not recs.empty else set()
contas = repo.contas(u)
caixa = contas[contas["tipo"].isin(saldos.TIPOS_CAIXA)]
princ = saldos.conta_principal(u)
op_c = {r_.id: r_.nome for r_ in caixa.itertuples()}
with st.container(border=True):
    st.markdown(f"Pelo holerite de **{MESES[int(ult['mes']) - 1]}/{int(ult['ano'])}**:")
    a1, a2 = st.columns(2)
    v_adto = a1.number_input("Adiantamento (R$)", 0.0, value=round(adto, 2), step=10.0, format="%.2f")
    d_adto = a2.number_input("Cai no dia", 1, 31, 10, key="d_adto")
    b1, b2 = st.columns(2)
    v_liq = b1.number_input("Salário — 2ª parte (R$)", 0.0, value=round(liq, 2), step=10.0, format="%.2f")
    d_liq = b2.number_input("Cai no dia", 1, 31, 25, key="d_liq")
    ids_c = list(op_c)
    conta = st.selectbox("Entra na conta", ids_c, format_func=op_c.get,
                         index=ids_c.index(next((i for i in ids_c if str(i) == str(princ)), ids_c[0])) if ids_c else None)
    com13 = st.checkbox(f"Prever também o 13º: 1ª parcela {brl(e13['p1'])} em 30/11 e 2ª parcela "
                        f"{brl(e13['p2'])} em 18/12 (estimativa, já sem INSS e IR)".replace("$", "\\$"), value=True)
    nomes = ["salário · adiantamento", "salário · 2ª parte"]
    from core import db as _db
    tem13 = _db.consultar("""select descricao, valor, data_vencimento from lancamentos
                              where dono_id = :u and descricao ilike '13%% sal%%' and extract(year from data_vencimento) = :a
                              order by data_vencimento""", u=u["id"], a=hoje().year)
    if not tem13.empty:
        st.caption("✅ 13º na previsão: " + " · ".join(f"{x.descricao} {brl(x.valor)} em {x.data_vencimento:%d/%m}"
                                                       for x in tem13.itertuples()))
    if any(n in ja for n in nomes):
        st.caption("✅ O salário já está nas Contas fixas — para mudar valor ou dia, use a tela **Contas fixas**.")
        if tem13.empty and st.button("Colocar o 13º na previsão", type="primary", icon=":material/savings:",
                                     disabled=not conta):
            cats = repo.categorias(u, "receita")
            cat13 = next((c.id for c in cats.itertuples() if "13" in c.nome),
                         next((c.id for c in cats.itertuples() if _ui.sem_acento(c.nome) == "salario"), None))
            repo.inserir_lancamentos(u, [
                dict(conta_id=conta, categoria_id=cat13, tipo="receita", descricao="13º salário · 1ª parcela",
                     valor=e13["p1"], data_compra=date(hoje().year, 11, 30), data_vencimento=date(hoje().year, 11, 30),
                     status="previsto", forma_pagamento="Transferencia", origem="manual",
                     observacao="Estimativa (Imposto de Renda)"),
                dict(conta_id=conta, categoria_id=cat13, tipo="receita", descricao="13º salário · 2ª parcela",
                     valor=e13["p2"], data_compra=date(hoje().year, 12, 18), data_vencimento=date(hoje().year, 12, 18),
                     status="previsto", forma_pagamento="Transferencia", origem="manual",
                     observacao="Estimativa (Imposto de Renda)")])
            st.session_state["_ui_ok"] = "13º na previsão de caixa (novembro e dezembro)."
            st.rerun()
    elif st.button("Colocar o salário nas Contas fixas", type="primary", icon=":material/event_repeat:",
                   disabled=not conta):
        cats = repo.categorias(u, "receita")
        cat = next((c.id for c in cats.itertuples() if _ui.sem_acento(c.nome) == "salario"), None)
        inicio = date(hoje().year, hoje().month, 1)
        prox = date(inicio.year + (inicio.month == 12), inicio.month % 12 + 1, 1)
        for desc, v, dia in [("Salário · adiantamento", v_adto, d_adto), ("Salário · 2ª parte", v_liq, d_liq)]:
            # começa no mês que vem se o dia deste mês já passou (já entrou pelo extrato)
            rec.salvar(u, dict(descricao=desc, valor=v, conta_id=conta, categoria_id=cat, tipo="receita",
                               frequencia="mensal", dia_vencimento=int(dia),
                               inicio=inicio if hoje().day < dia else prox, fim=None, visibilidade=None,
                               ativa=True, forma_pagamento="Transferencia"))
        if com13 and tem13.empty:
            cat13 = next((c.id for c in cats.itertuples() if "13" in c.nome), cat)
            repo.inserir_lancamentos(u, [
                dict(conta_id=conta, categoria_id=cat13, tipo="receita", descricao="13º salário · 1ª parcela",
                     valor=e13["p1"], data_compra=date(hoje().year, 11, 30), data_vencimento=date(hoje().year, 11, 30),
                     status="previsto", forma_pagamento="Transferencia", origem="manual",
                     observacao="Estimativa (Imposto de Renda)"),
                dict(conta_id=conta, categoria_id=cat13, tipo="receita", descricao="13º salário · 2ª parcela",
                     valor=e13["p2"], data_compra=date(hoje().year, 12, 18), data_vencimento=date(hoje().year, 12, 18),
                     status="previsto", forma_pagamento="Transferencia", origem="manual",
                     observacao="Estimativa (Imposto de Renda)")])
        st.session_state["_ui_ok"] = "Salário nas Contas fixas — o Painel já mostra a nova previsão."
        st.rerun()

# --- holerites lidos -------------------------------------------------------------------------------
with st.expander(f"Holerites de {ano} ({len(hol)})"):
    for h in hol.itertuples():
        a, b, c = st.columns([3, 2, 0.8], vertical_alignment="center")
        a.markdown(f"**{MESES[int(h.mes) - 1]}/{int(h.ano)}** · {_ui.esc(h.folha)}")
        b.markdown(f"Líquido {brl(h.liquido)}")
        if c.button("", icon=":material/delete:", key=f"delhol_{h.id}", help="Apagar este holerite"):
            ir.excluir(u, h.id)
            st.rerun()

st.markdown("""<style>
.ui-fluxo {overflow-x: auto;}
.ui-fluxo table {border-collapse: separate; border-spacing: 0; width: 100%; font-size: .8rem; white-space: nowrap;}
.ui-fluxo th, .ui-fluxo td {padding: 7px 9px; text-align: right; border-bottom: 1px solid rgba(15,23,42,.06);}
.ui-fluxo thead th {font-size: .72rem; text-transform: uppercase; letter-spacing: .5px; color: #64748B;}
.ui-fluxo thead th.fut, .ui-fluxo td.proj {color: #94A3B8; font-style: italic;}
.ui-fluxo tbody th {text-align: left; font-weight: 600; color: #334155; position: sticky; left: 0; background: #fff;}
.ui-fluxo td[data-c=neg] {color: #E5484D;} .ui-fluxo td[data-c=pos] {color: #16A34A;}
.ui-fluxo td[data-c=fim] {font-weight: 800;} .ui-fluxo td.tot {font-weight: 800; background: rgba(15,118,110,.06);}
</style>""", unsafe_allow_html=True)

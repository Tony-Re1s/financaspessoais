"""Seção 'Deduções' da tela de Imposto de Renda (saúde e educação)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import deducoes as dd
from core import ia
from core.fmt import brl, hoje
from telas import _ui
from telas._comum import cartoes_kpi

ROT_VER = {"sim": "✅ dedutível", "talvez": "🤔 confira", "nao": "🚫 não"}
ROT_TIPO = {"saude": "🩺 Saúde", "educacao": "🎓 Educação"}


def secao(u, ano: int, ded: dict, economia: float, cel: bool, r: dict | None = None):
    st.markdown("<div class='ui-sec'>Deduções · saúde e educação</div>", unsafe_allow_html=True)
    cand = ded["candidatos"]
    conf = ded["confirmadas"]
    abertos = cand[(cand["veredito"] != "nao") & ~cand["ignorado"]] if not cand.empty else cand
    nao = cand[cand["veredito"] == "nao"] if not cand.empty else cand

    cartoes_kpi([("Economia no IR", brl(economia)),
                 ("🩺 Saúde (sem limite)", brl(ded["saude"])),
                 ("🎓 Educação dedutível", brl(ded["educacao"])),
                 ("Na declaração", f"{len(conf)} itens"),
                 ("Sem comprovante", str(ded["sem_comprovante"]))],
                c1="#3B1F6E", c2="#6D3FC0")
    st.toggle("Contar também as sugestões ✅ que ainda não confirmei", value=True, key="ir_inc_sug",
              help="Desligado: só entra na conta o que está em 'Na declaração'.")
    if ded["educacao_pessoa"]:
        st.caption(("Educação por pessoa (limite " + brl(dd.LIMITE_EDUCACAO) + "/ano): " + " · ".join(
            f"{b} {brl(v)}" + (" ⚠️ passou do limite" if v > dd.LIMITE_EDUCACAO else "")
            for b, v in ded["educacao_pessoa"].items())).replace("$", "\\$"))
    if r and r.get("melhor") == "simplificada":
        falta = r["simplificada"]["deducoes"] - r["completa"]["deducoes"]
        if falta > 0:
            st.caption(f"💡 Hoje a **simplificada** ganha (desconto de {brl(r['simplificada']['deducoes'])}). "
                       f"As deduções só passam a diminuir o imposto se a completa somar mais "
                       f"{brl(falta)} em deduções.".replace("$", "\\$"))

    t1, t2, t3, t4 = st.tabs([f"💡 Sugestões ({len(abertos)})", f"✅ Na declaração ({len(conf)})",
                              "➕ Recibo / nota", f"🚫 Não dedutíveis ({len(nao)})"])
    with t1:
        _sugestoes(u, ano, abertos)
    with t2:
        _confirmadas(u, ano, conf)
    with t3:
        _adicionar(u, ano)
    with t4:
        _nao_dedutiveis(u, nao)
    st.caption("Regras: saúde sem limite (médico, dentista, psicólogo, fisioterapeuta, fonoaudiólogo, terapeuta "
               "ocupacional, hospital, exames, plano); educação até R$ 3.561,50 por pessoa (escola, graduação, "
               "pós, técnico). Conta o ano em que foi **pago**. Guarde recibos com CPF/CNPJ por 5 anos."
               .replace("$", "\\$"))


def _sugestoes(u, ano, df):
    if df.empty:
        st.caption("Nada novo nos lançamentos do ano. Pagou algo fora do app? Use ➕ Recibo / nota.")
        return
    st.caption("O app achou estes pagamentos do ano. Marque o que entra, ajuste o valor dedutível "
               "(ex.: só a mensalidade da escola) e o beneficiário, e inclua.")
    base = pd.DataFrame({
        "incluir": df["veredito"] == "sim",
        "data": pd.to_datetime(df["data"]).dt.date,
        "descricao": df["descricao"],
        "tipo": df["tipo"].map(ROT_TIPO),
        "valor": df["valor"].astype(float),
        "dedutivel": df["valor"].astype(float),
        "beneficiario": "Titular",
        "avaliacao": df["veredito"].map(ROT_VER),
        "motivo": df["motivo"],
        "situacao": df["status"].map({"pago": "pago", "previsto": "previsto"}).fillna(df["status"]),
    })
    with st.form(f"ded_sug_{ano}"):
        ed = st.data_editor(base, hide_index=True, use_container_width=True, key=f"ded_sug_ed_{ano}",
                            disabled=["data", "descricao", "tipo", "valor", "avaliacao", "motivo", "situacao"],
                            column_config={
                                "incluir": st.column_config.CheckboxColumn("✓", width="small"),
                                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY", width="small"),
                                "descricao": st.column_config.TextColumn("Pagamento"),
                                "tipo": st.column_config.TextColumn("Tipo", width="small"),
                                "valor": st.column_config.NumberColumn("Pago", format="R$ %.2f", width="small"),
                                "dedutivel": st.column_config.NumberColumn("Dedutível", format="R$ %.2f",
                                                                           min_value=0.0, width="small"),
                                "beneficiario": st.column_config.TextColumn("Para quem", width="small"),
                                "avaliacao": st.column_config.TextColumn("App diz", width="small"),
                                "motivo": st.column_config.TextColumn("Por quê"),
                                "situacao": st.column_config.TextColumn("Situação", width="small"),
                            })
        b1, b2 = st.columns(2)
        incluir = b1.form_submit_button("✅ Incluir marcados na declaração", type="primary", use_container_width=True)
        ignorar = b2.form_submit_button("🙈 Ignorar marcados", use_container_width=True)
    marcados = [i for i in range(len(ed)) if bool(ed.iloc[i]["incluir"])]
    if incluir and marcados:
        for i in marcados:
            x, o = ed.iloc[i], df.iloc[i]
            dd.salvar(u, dict(ano=ano, tipo=o["tipo"], beneficiario=x["beneficiario"], prestador=o["descricao"],
                              descricao=next((v for v in (o["subcategoria"], o["categoria"]) if isinstance(v, str)), None), valor_pago=float(o["valor"]),
                              valor=float(x["dedutivel"] if pd.notna(x["dedutivel"]) else o["valor"]),
                              data=o["data"], lancamento_id=o["id"],
                              observacao=None if o["status"] == "pago" else "previsto quando foi incluído"))
        st.session_state["_ui_ok"] = f"{len(marcados)} na declaração — falta anexar os comprovantes."
        st.rerun()
    if ignorar and marcados:
        dd.ignorar(u, [df.iloc[i]["id"] for i in marcados])
        st.session_state["_ui_ok"] = f"{len(marcados)} sugestões ignoradas."
        st.rerun()


def _confirmadas(u, ano, df):
    if df.empty:
        st.caption("Nada ainda. Inclua pelas 💡 Sugestões ou pelo ➕ Recibo / nota.")
        return
    base = pd.DataFrame({
        "excluir": False,
        "tipo": df["tipo"].map(ROT_TIPO),
        "beneficiario": df["beneficiario"],
        "prestador": df["prestador"].fillna(""),
        "documento": df["documento"].fillna(""),
        "data": pd.to_datetime(df["data"]).dt.date,
        "valor_pago": df["valor_pago"].astype(float),
        "valor": df["valor"].astype(float),
        "comprovante": df["tem_arquivo"].map({True: "📎 anexado", False: "⚠️ falta"}),
    })
    with st.form(f"ded_conf_{ano}"):
        ed = st.data_editor(base, hide_index=True, use_container_width=True, key=f"ded_conf_ed_{ano}",
                            disabled=["comprovante"],
                            column_config={
                                "excluir": st.column_config.CheckboxColumn("🗑️", width="small"),
                                "tipo": st.column_config.SelectboxColumn("Tipo", options=list(ROT_TIPO.values()),
                                                                         width="small", required=True),
                                "beneficiario": st.column_config.TextColumn("Para quem", width="small"),
                                "prestador": st.column_config.TextColumn("Prestador"),
                                "documento": st.column_config.TextColumn("CPF/CNPJ", width="small"),
                                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY", width="small"),
                                "valor_pago": st.column_config.NumberColumn("Pago", format="R$ %.2f", width="small"),
                                "valor": st.column_config.NumberColumn("Dedutível", format="R$ %.2f", width="small"),
                                "comprovante": st.column_config.TextColumn("Comprovante", width="small"),
                            })
        b1, b2, b3 = st.columns([1.2, 1, 1])
        salvar = b1.form_submit_button("💾 Salvar alterações", type="primary", use_container_width=True)
        excluir = b2.form_submit_button("🗑️ Tirar marcados", use_container_width=True)
        b3.form_submit_button("↺ Descartar", use_container_width=True)
    if salvar:
        inv = {v: k for k, v in ROT_TIPO.items()}
        n = 0
        for i in range(len(ed)):
            x, o = ed.iloc[i], base.iloc[i]
            if any(str(x[c]) != str(o[c]) for c in ["tipo", "beneficiario", "prestador", "documento", "data",
                                                    "valor_pago", "valor"]):
                r = df.iloc[i]
                dd.salvar(u, dict(ano=ano, tipo=inv.get(x["tipo"], r["tipo"]), beneficiario=x["beneficiario"],
                                  prestador=x["prestador"], documento=x["documento"], descricao=r["descricao"],
                                  valor_pago=x["valor_pago"], valor=x["valor"], data=x["data"],
                                  lancamento_id=r["lancamento_id"], observacao=r["observacao"]), ded_id=r["id"])
                n += 1
        st.session_state["_ui_ok"] = f"{n} alterados." if n else "Nada mudou."
        st.rerun()
    if excluir:
        ids = [df.iloc[i]["id"] for i in range(len(ed)) if bool(ed.iloc[i]["excluir"])]
        if ids:
            dd.excluir(u, ids)
            st.session_state["_ui_ok"] = f"{len(ids)} tirados da declaração (voltam para as sugestões)."
            st.rerun()

    st.markdown("**Comprovantes**")
    op = {r.id: f"{'📎' if r.tem_arquivo else '⚠️'} {r.prestador or '—'} · {r.data:%d/%m} · {brl(r.valor)}"
          for r in df.itertuples()}
    c1, c2 = st.columns([1.4, 1])
    sel = c1.selectbox("Item", list(op), format_func=op.get, key=f"ded_item_{ano}", label_visibility="collapsed")
    if sel is not None and bool(df.loc[df["id"] == sel, "tem_arquivo"].iloc[0]):
        a = dd.arquivo(u, sel)
        if a:
            c2.download_button("⬇️ Baixar comprovante", a[2], file_name=a[0], mime=a[1] or None,
                               use_container_width=True, key=f"ded_down_{sel}")
    arq = st.file_uploader("Anexar recibo/nota a este item", type=["pdf", "jpg", "jpeg", "png", "heic"],
                           key=f"ded_up_{ano}_{sel}")
    if arq and st.button("📎 Anexar", type="primary", key=f"ded_anx_{sel}"):
        if arq.size > 8 * 1024 * 1024:
            st.error("Arquivo maior que 8 MB — reduza a foto ou o PDF.")
        else:
            dd.anexar(u, sel, arq.name, arq.type or "application/octet-stream", arq.getvalue())
            st.session_state["_ui_ok"] = "Comprovante anexado."
            st.rerun()


def _adicionar(u, ano):
    st.caption("Para o que não passou pelo app (ou para conferir a nota que a escola/clínica mandou). "
               "Com a chave da IA configurada, o app lê o PDF/foto e preenche sozinho.")
    arq = st.file_uploader("Recibo ou nota fiscal", type=["pdf", "jpg", "jpeg", "png", "heic"], key=f"ded_novo_{ano}")
    lido = st.session_state.get("_ded_lido") or {}
    if arq and ia.chave() and st.button("✨ Ler com IA", key="ded_ler"):
        try:
            with st.spinner("Lendo o comprovante…"):
                st.session_state["_ded_lido"] = ia.ler_comprovante_ir(arq.getvalue(), arq.name, hoje())
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    if lido.get("duvida"):
        st.info(f"A IA ficou com dúvida: {lido['duvida']}")
    if lido and lido.get("tipo") == "outro":
        st.warning("Pela leitura, este documento não parece ser de saúde nem de educação.")
    with st.form(f"ded_form_{ano}"):
        a, b, c = st.columns(3)
        tipos = list(dd.TIPOS)
        tipo = a.selectbox("Tipo", tipos, format_func=lambda t: ROT_TIPO[t],
                           index=tipos.index(lido["tipo"]) if lido.get("tipo") in tipos else 0)
        benef = b.text_input("Para quem", value=lido.get("beneficiario") or "Titular")
        _d0 = lido.get("data") or hoje()
        _d0 = min(max(_d0, date(ano, 1, 1)), date(ano, 12, 31))
        data = c.date_input("Data do pagamento", value=_d0, format="DD/MM/YYYY",
                            min_value=date(ano, 1, 1), max_value=date(ano, 12, 31))
        d, e = st.columns(2)
        prest = d.text_input("Prestador (clínica, médico, escola…)", value=lido.get("prestador") or "")
        doc = e.text_input("CPF/CNPJ do prestador", value=lido.get("documento") or "")
        f, g = st.columns(2)
        pago = f.number_input("Valor pago (R$)", 0.0, value=float(lido.get("valor_pago") or 0), step=10.0, format="%.2f")
        dedut = g.number_input("Valor dedutível (R$)", 0.0, value=float(lido.get("valor_dedutivel") or pago or 0),
                               step=10.0, format="%.2f", help="Educação: só a mensalidade. Saúde: pago − reembolso.")
        desc = st.text_input("Serviço", value=lido.get("descricao") or "")
        if st.form_submit_button("Salvar na declaração", type="primary"):
            if not prest.strip() or not dedut:
                st.error("Informe o prestador e o valor.")
            else:
                novo = dd.salvar(u, dict(ano=data.year, tipo=tipo, beneficiario=benef, prestador=prest.strip(),
                                         documento=doc.strip() or None, descricao=desc or None, valor_pago=pago or dedut,
                                         valor=dedut, data=data))
                if arq and novo:
                    dd.anexar(u, novo, arq.name, arq.type or "application/octet-stream", arq.getvalue())
                st.session_state.pop("_ded_lido", None)
                st.session_state["_ui_ok"] = "Incluído na declaração" + (" com o comprovante." if arq else ".")
                st.rerun()


def _nao_dedutiveis(u, df):
    if df.empty:
        st.caption("Nenhum gasto do ano caiu nas regras de 'não dedutível'.")
        return
    g = df.groupby(["descricao", "motivo"], as_index=False).agg(valor=("valor", "sum"), vezes=("id", "count")) \
        .sort_values("valor", ascending=False)
    linhas = "".join(f"""<div class="ui-cat"><div class="t"><span>{_ui.esc(x.descricao)} · {x.vezes}x</span>
        <span class="v">{brl(x.valor)}</span></div><div class="p" style="text-align:left">{_ui.esc(x.motivo)}</div></div>"""
                     for x in g.itertuples())
    _ui.render(f"<div class='ui-lista-html'>{linhas}</div>")
    st.caption("Achou que algum destes conta (ex.: nota emitida por médico)? Use ➕ Recibo / nota.")

"""Assistente financeiro (Claude) — conversa e análises com os dados do próprio usuário.

A IA não recebe o banco inteiro: ela chama ferramentas SÓ DE LEITURA (abaixo) e o app responde com
os números. Nada é gravado por aqui.

Secrets:
    [anthropic]
    api_key = "sk-ant-..."
    modelo_analise = "claude-sonnet-5-5"   # opcional (padrão abaixo)
"""
from __future__ import annotations

import json
from datetime import date

import httpx
import pandas as pd
import streamlit as st

from core import cartoes, investimentos, orcamentos, patrimonio, recorrencias, repo, saldos
from core.fmt import dia_no_mes, hoje, mes_label, mes_ref, somar_meses
from core.ia import URL, chave

MODELO_ANALISE = "claude-sonnet-5-5"
MAX_VOLTAS = 8


def modelo() -> str:
    try:
        return st.secrets["anthropic"].get("modelo_analise") or MODELO_ANALISE
    except Exception:  # noqa: BLE001
        return MODELO_ANALISE


# ---------------------------------------------------------------------------
# ferramentas (leitura)
# ---------------------------------------------------------------------------
def _m(txt, padrao: int) -> int:
    """'2026-10' -> 202610."""
    try:
        a, m = str(txt).split("-")[:2]
        return int(a) * 100 + int(m)
    except Exception:  # noqa: BLE001
        return padrao


def _csv(df: pd.DataFrame, limite=150) -> str:
    if df is None or df.empty:
        return "(nada)"
    extra = f"\n… e mais {len(df) - limite} linhas" if len(df) > limite else ""
    return df.head(limite).to_csv(index=False, float_format="%.2f") + extra


def _resumo_geral(u, _a):
    hj = hoje()
    contas = repo.contas(u)
    linhas = []
    for c in contas.itertuples():
        if c.tipo in saldos.TIPOS_CAIXA or c.tipo in ("beneficio", "fgts"):
            linhas.append({"conta": c.nome, "tipo": c.tipo, "saldo_hoje": round(saldos.saldo_em(u, c.id, hj), 2)})
    fat = cartoes.resumo(u)
    if not fat.empty:
        fat = fat[["cartao", "venc_atual", "fatura_atual", "venc_prox", "fatura_prox", "atrasadas", "limite",
                   "disponivel"]]
    pat = patrimonio.calcular(u)
    grupos = pat.groupby("grupo", as_index=False)["valor"].sum() if not pat.empty else pat
    liquido = float(pat["valor"].sum()) if not pat.empty else 0.0
    return (f"Hoje: {hj:%Y-%m-%d}\n\nSALDOS DAS CONTAS\n{_csv(pd.DataFrame(linhas))}\n"
            f"FATURAS DE CARTÃO (abertas)\n{_csv(fat)}\n"
            f"PATRIMÔNIO LÍQUIDO: {liquido:.2f}\nPor grupo:\n{_csv(grupos)}\nItens:\n{_csv(pat)}")


def _fluxo_caixa(u, a):
    """Dinheiro nas contas correntes mês a mês: entradas, saídas (faturas incluídas), saldo no fim."""
    atual = mes_ref(hoje())
    ini, fim = _m(a.get("mes_inicio"), somar_meses(atual, -3)), _m(a.get("mes_fim"), somar_meses(atual, 6))
    contas = repo.contas(u)
    ids = list(contas[contas["tipo"].isin(saldos.TIPOS_CAIXA)]["id"])
    if not ids:
        return "Sem contas correntes cadastradas."
    d0, d1 = date(ini // 100, ini % 100, 1), dia_no_mes(fim // 100, fim % 100, 31)
    s0, ext = saldos.extrato(u, ids, d0, d1)
    if ext.empty:
        return f"Saldo inicial {s0:.2f}; sem movimentos."
    ext = ext.copy()
    ext["mes"] = ext["data"].map(mes_ref)
    entram = set(ext.loc[ext["fonte"] == "entrada_transf", "id"].dropna())
    ext["interna"] = ext["id"].isin(entram) & ((ext["fonte"] == "entrada_transf")
                                               | ((ext["valor"] < 0) & (ext["fonte"] != "fatura")))
    out, saldo, m = [], s0, ini
    while m <= fim:
        d = ext[ext["mes"] == m]
        real = d[(d["fonte"] != "ajuste") & (~d["interna"])]
        ent = float(real.loc[real["valor"] > 0, "valor"].sum())
        sai = float(-real.loc[real["valor"] < 0, "valor"].sum())
        fat = float(-real.loc[(real["valor"] < 0) & (real["fonte"] == "fatura"), "valor"].sum())
        saldo += float(d["valor"].sum())
        out.append({"mes": f"{m // 100}-{m % 100:02d}", "entradas": ent, "saidas": sai, "faturas_cartao": fat,
                    "sobra_do_mes": ent - sai, "saldo_fim_do_mes": saldo,
                    "situacao": "passado" if m < atual else ("atual" if m == atual else "previsto")})
        m = somar_meses(m, 1)
    return ("Contas correntes somadas. Transferências entre as próprias contas excluídas. Meses futuros = previsto "
            f"(contas fixas, parcelas, faturas, salário).\n{_csv(pd.DataFrame(out))}")


def _gastos_por_categoria(u, a):
    atual = mes_ref(hoje())
    ini, fim = _m(a.get("mes_inicio"), somar_meses(atual, -3)), _m(a.get("mes_fim"), atual)
    sub = bool(a.get("por_subcategoria"))
    lanc = repo.lancamentos(u, "eu", ini, fim)
    if lanc.empty:
        return "(nada)"
    d = lanc[lanc["tipo"] == "despesa"].copy()
    d["valor"] = d["valor"].astype(float)
    d["mes"] = d["mes_ref"].map(lambda m: f"{int(m) // 100}-{int(m) % 100:02d}")
    d["categoria"] = d["categoria"].fillna("Sem categoria")
    chaves = ["mes", "categoria"] + (["subcategoria"] if sub else [])
    g = d.groupby(chaves + ["status"], dropna=False, as_index=False)["valor"].sum()
    g = g.pivot_table(index=chaves, columns="status", values="valor", aggfunc="sum", fill_value=0).reset_index()
    g["total"] = g.drop(columns=chaves).sum(axis=1)
    return f"Despesas por mês de referência (competência da fatura/vencimento).\n{_csv(g.sort_values(['mes', 'total'], ascending=[True, False]), 300)}"


def _buscar_lancamentos(u, a):
    atual = mes_ref(hoje())
    ini, fim = _m(a.get("mes_inicio"), somar_meses(atual, -2)), _m(a.get("mes_fim"), atual)
    lanc = repo.lancamentos(u, "eu", ini, fim)
    if lanc.empty:
        return "(nada)"
    d = lanc.copy()
    if t := a.get("texto"):
        from core.deducoes import _sa
        d = d[d["descricao"].map(_sa).str.contains(_sa(t), regex=False)]
    if c := a.get("categoria"):
        from core.deducoes import _sa
        d = d[d["categoria"].fillna("").map(_sa).str.contains(_sa(c), regex=False)
              | d["subcategoria"].fillna("").map(_sa).str.contains(_sa(c), regex=False)]
    if tp := a.get("tipo"):
        d = d[d["tipo"] == tp]
    d = d.assign(valor=d["valor"].astype(float))
    cols = ["data_vencimento", "data_compra", "descricao", "valor", "tipo", "categoria", "subcategoria", "conta",
            "forma_pagamento", "status", "parcela_num", "parcela_total"]
    d = d[cols].sort_values("data_vencimento", ascending=False)
    return f"{len(d)} lançamentos, total {d['valor'].sum():.2f}\n{_csv(d, int(a.get('limite') or 80))}"


def _orcamento(u, a):
    m = _m(a.get("mes"), mes_ref(hoje()))
    q = orcamentos.quadro(u, m)
    q = q[(q["gasto"] > 0) | q["orcado"].notna()].drop(columns=["id"])
    return f"Orçamento de {mes_label(m)} (gasto = pago + a pagar):\n{_csv(q)}" if not q.empty else "Sem orçamento nem gastos."


def _contas_fixas(u, _a):
    r = recorrencias.listar(u)
    if r.empty:
        return "(nenhuma)"
    r = r[r["ativa"]][["descricao", "tipo", "valor", "dia_vencimento", "frequencia", "conta", "inicio", "fim", "proxima"]]
    return _csv(r)


def _investimentos(u, _a):
    a = investimentos.ativos(u)
    if a.empty:
        return "(nenhum)"
    cols = [c for c in ["instituicao", "nome", "classe", "indexador", "taxa", "vencimento", "aplicado", "valor_atual",
                        "rendimentos"] if c in a.columns]
    return _csv(a[cols])


FERRAMENTAS = {
    "resumo_geral": (_resumo_geral, "Saldos de hoje de cada conta, faturas de cartão abertas e o patrimônio "
                                    "(tem − deve, por grupo e item).", {}),
    "fluxo_caixa": (_fluxo_caixa, "Dinheiro nas contas correntes mês a mês (entradas, saídas, faturas, sobra e saldo "
                                  "no fim do mês). Inclui meses futuros previstos. Use para 'quanto vai sobrar'.",
                    {"mes_inicio": {"type": "string", "description": "AAAA-MM"},
                     "mes_fim": {"type": "string", "description": "AAAA-MM"}}),
    "gastos_por_categoria": (_gastos_por_categoria, "Despesas por mês e categoria (pago e previsto).",
                             {"mes_inicio": {"type": "string", "description": "AAAA-MM"},
                              "mes_fim": {"type": "string", "description": "AAAA-MM"},
                              "por_subcategoria": {"type": "boolean"}}),
    "buscar_lancamentos": (_buscar_lancamentos, "Lista lançamentos (filtra por texto na descrição, categoria, tipo).",
                           {"mes_inicio": {"type": "string", "description": "AAAA-MM"},
                            "mes_fim": {"type": "string", "description": "AAAA-MM"},
                            "texto": {"type": "string"}, "categoria": {"type": "string"},
                            "tipo": {"type": "string", "enum": ["despesa", "receita", "transferencia"]},
                            "limite": {"type": "integer"}}),
    "orcamento": (_orcamento, "Orçamento do mês por categoria: orçado, pago, a pagar, média dos 3 meses anteriores.",
                  {"mes": {"type": "string", "description": "AAAA-MM"}}),
    "contas_fixas": (_contas_fixas, "Contas fixas e receitas recorrentes ativas (salário, aluguel, assinaturas…).", {}),
    "investimentos": (_investimentos, "Aplicações financeiras: aplicado e valor atual.", {}),
}


def _tools_api():
    return [{"name": n, "description": d, "input_schema": {"type": "object", "properties": p}}
            for n, (_, d, p) in FERRAMENTAS.items()]


def _sistema(u) -> str:
    hj = hoje()
    nome = (u.get("nome") or "").split(" ")[0] or "você"
    return (
        f"Você é o assistente financeiro do app de finanças pessoais de {nome}. Hoje é {hj:%d/%m/%Y} "
        f"({mes_label(mes_ref(hj))}). Responda em português do Brasil, direto e preciso, como um bom analista "
        "financeiro conversando: números em R$ no formato brasileiro (R$ 1.234,56), meses por extenso curto.\n"
        "- SEMPRE busque os números com as ferramentas antes de afirmar algo; nunca invente valores. Se faltar dado, "
        "diga o que falta.\n"
        "- Mostre a conta quando fizer cálculo (média, quanto guardar, projeção).\n"
        "- Dê recomendações práticas e específicas (qual categoria, quanto, a partir de quando).\n"
        "- Regras do app: VA marcado 'fora dos gastos' não é gasto; transferências entre contas próprias não são "
        "entrada nem saída; faturas de cartão saem da conta no vencimento; parcelas do apartamento (incorporadora) "
        "aumentam o patrimônio, juros de evolução de obra e cartório são despesa.\n"
        "- Sobre investimentos: explique conceitos e compare alternativas de forma geral (liquidez, risco, custo), mas "
        "não indique um produto específico para comprar ou vender.\n"
        "- Depois de consultar, SEMPRE escreva a resposta final completa para o usuário.\n"
        "- Use markdown leve: frases curtas, listas quando ajudar, no máximo uma tabela pequena."
    )


def conversar(u, historico: list[dict], ao_usar=None) -> tuple[str, list[dict]]:
    """historico: mensagens no formato da API (role/content). Devolve (texto final, histórico atualizado)."""
    k = chave()
    if not k:
        raise RuntimeError("Falta a chave da Anthropic nos Secrets ([anthropic] api_key).")
    msgs = list(historico)
    for _ in range(MAX_VOLTAS):
        r = httpx.post(URL, timeout=120, headers={"x-api-key": k, "anthropic-version": "2023-06-01",
                                                  "content-type": "application/json"},
                       json={"model": modelo(), "max_tokens": 6000, "system": _sistema(u),
                             "tools": _tools_api(), "messages": msgs})
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except Exception:  # noqa: BLE001
                msg = r.text[:300]
            raise RuntimeError(f"A IA respondeu erro {r.status_code}: {msg}")
        resp = r.json()
        conteudo = resp["content"]
        msgs.append({"role": "assistant", "content": conteudo})
        usos = [b for b in conteudo if b.get("type") == "tool_use"]
        parada = resp.get("stop_reason")
        if parada in ("max_tokens", "pause_turn") and not usos:
            msgs.append({"role": "user", "content": "Continue de onde parou."})
            continue
        if parada != "tool_use" or not usos:
            # texto da última resposta; se vier vazio, o que escreveu entre as consultas
            texto = "\n".join(b.get("text", "") for b in conteudo if b.get("type") == "text").strip()
            if not texto:
                texto = "\n\n".join(b.get("text", "") for m in msgs[len(historico):] if m["role"] == "assistant"
                                    for b in (m["content"] if isinstance(m["content"], list) else [])
                                    if b.get("type") == "text").strip()
            if not texto:
                texto = f"(A IA não escreveu a resposta — parada: {parada}. Tente perguntar de novo.)"
            return texto, msgs
        resultados = []
        for b in usos:
            fn = FERRAMENTAS.get(b["name"], (None,))[0]
            if ao_usar:
                ao_usar(b["name"], b.get("input") or {})
            try:
                saida = fn(u, b.get("input") or {}) if fn else f"Ferramenta {b['name']} não existe."
            except Exception as e:  # noqa: BLE001
                saida = f"Erro ao consultar: {e}"
            resultados.append({"type": "tool_result", "tool_use_id": b["id"], "content": str(saida)[:60000]})
        msgs.append({"role": "user", "content": resultados})
    return "Precisei de consultas demais para responder — tente uma pergunta mais específica.", msgs


ROTULOS = {"resumo_geral": "saldos e patrimônio", "fluxo_caixa": "fluxo de caixa",
           "gastos_por_categoria": "gastos por categoria", "buscar_lancamentos": "lançamentos",
           "orcamento": "orçamento", "contas_fixas": "contas fixas", "investimentos": "investimentos"}



"""Orçamento mensal por categoria (categoria-pai de despesa).

Tabela orcamentos (schema 001): um valor por categoria valendo para todo mês (mes_ref null) e, se
quiser, um valor diferente num mês específico (mes_ref = AAAAMM), que tem prioridade.
Gasto = mesma conta do Painel (repo.totais_por_mes: mes_ref do lançamento, pago + previsto).
"""
from __future__ import annotations

import pandas as pd
from core import db, repo
from core.fmt import somar_meses


def _tabela() -> bool:
    return True   # tabela orcamentos vem do schema (001): mes_ref null = todo mês, valor_limite


def categorias_pai(u) -> pd.DataFrame:
    cats = repo.categorias(u, "despesa")
    return cats[cats["pai_id"].isna()][["id", "nome"]].sort_values("nome").reset_index(drop=True)


def valores(u, mes: int) -> dict:
    """{categoria_id: valor} valendo no mês (específico do mês > padrão)."""
    _tabela()
    df = db.consultar("""select categoria_id, coalesce(mes_ref, 0) as mes_ref, valor_limite as valor from orcamentos
                          where dono_id = :u and (mes_ref is null or mes_ref = :m)""", u=u["id"], m=mes)
    out: dict = {}
    for r in df.sort_values("mes_ref").itertuples():      # todo mês primeiro, o do mês sobrescreve
        out[str(r.categoria_id)] = float(r.valor)
    return out


def padrao(u) -> dict:
    _tabela()
    df = db.consultar("""select categoria_id, valor_limite as valor from orcamentos
                          where dono_id = :u and mes_ref is null""", u=u["id"])
    return {str(r.categoria_id): float(r.valor) for r in df.itertuples()}


def salvar(u, cat_id, valor: float | None, mes: int = 0):
    """mes = 0: vale para todo mês."""
    m = mes or None
    db.executar("""delete from orcamentos where dono_id = :u and categoria_id = :c
                     and mes_ref is not distinct from cast(:m as int)""", u=u["id"], c=cat_id, m=m)
    if valor is not None and valor > 0:
        db.executar("""insert into orcamentos (dono_id, categoria_id, mes_ref, valor_limite)
                       values (:u, :c, cast(:m as int), :v)""", u=u["id"], c=cat_id, m=m, v=float(valor))


def gastos(u, mes_ini: int, mes_fim: int, escopo="eu") -> pd.DataFrame:
    """mes_ref, categoria, status, valor — só despesas."""
    t = repo.totais_por_mes(u, escopo, mes_ini, mes_fim)
    if t.empty:
        return pd.DataFrame(columns=["mes_ref", "categoria", "status", "valor"])
    t = t[t["tipo"] == "despesa"].copy()
    t["valor"] = t["valor"].astype(float)
    return t.groupby(["mes_ref", "categoria", "status"], as_index=False)["valor"].sum()


def quadro(u, mes: int, escopo="eu") -> pd.DataFrame:
    """Uma linha por categoria: orçado, pago, previsto, média dos 3 meses anteriores."""
    cats = categorias_pai(u)
    orc = valores(u, mes)
    g = gastos(u, somar_meses(mes, -3), mes, escopo)
    no_mes = g[g["mes_ref"] == mes]
    antes = g[g["mes_ref"] < mes]
    linhas = []
    nomes = set(cats["nome"])
    n_meses = max(antes["mes_ref"].nunique(), 1) if not antes.empty else 1   # meses que têm dados
    for c in cats.itertuples():
        d = no_mes[no_mes["categoria"] == c.nome]
        a = antes[antes["categoria"] == c.nome]
        linhas.append({"id": str(c.id), "categoria": c.nome, "orcado": orc.get(str(c.id)),
                       "pago": float(d.loc[d["status"] == "pago", "valor"].sum()),
                       "previsto": float(d.loc[d["status"] == "previsto", "valor"].sum()),
                       "media3": float(a["valor"].sum()) / n_meses if not a.empty else 0.0})
    sem = no_mes[~no_mes["categoria"].isin(nomes)]
    if not sem.empty:
        linhas.append({"id": None, "categoria": "Sem categoria", "orcado": None,
                       "pago": float(sem.loc[sem["status"] == "pago", "valor"].sum()),
                       "previsto": float(sem.loc[sem["status"] == "previsto", "valor"].sum()), "media3": 0.0})
    df = pd.DataFrame(linhas)
    df["gasto"] = df["pago"] + df["previsto"]
    return df

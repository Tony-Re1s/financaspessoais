"""Patrimônio = o que você tem − o que você deve.

Tem:  saldo das contas (corrente, poupança, carteira), investimentos, previdência, FGTS, bens.
Deve: dívida dos bens (financiamento / saldo a pagar do imóvel), faturas de cartão em aberto
      (atual e próxima), contas de financiamento com saldo informado.

Bem com 'categorias de pagamento' (ex.: Imóvel › Construtora): o que já foi pago nessas
categorias abate a dívida. Sem dívida informada: dívida = preço − pago.
Lançamentos previstos com vencimento já passado contam como pagos (como no fluxo de caixa).
"""
from __future__ import annotations

import json

import pandas as pd

from core import cartoes, db, investimentos, saldos
from core.fmt import hoje, mes_ref, somar_meses


def bens(u) -> pd.DataFrame:
    df = db.consultar("""
        select b.id, b.descricao, b.data_aquisicao, b.valor_aquisicao, b.valor_atual, b.divida_vinculada,
               b.categorias_pagamento,
               coalesce((select sum(l.valor) from lancamentos l
                          where l.dono_id = b.dono_id and l.status <> 'cancelado' and l.tipo = 'despesa'
                            and (l.status = 'pago' or l.data_vencimento < current_date)
                            and (l.categoria_id = any(b.categorias_pagamento)
                                 or l.categoria_id in (select id from categorias
                                                        where pai_id = any(b.categorias_pagamento)))), 0) as pago,
               coalesce((select sum(l.valor) from lancamentos l
                          where l.dono_id = b.dono_id and l.status = 'previsto' and l.tipo = 'despesa'
                            and l.data_vencimento >= current_date
                            and (l.categoria_id = any(b.categorias_pagamento)
                                 or l.categoria_id in (select id from categorias
                                                        where pai_id = any(b.categorias_pagamento)))), 0) as a_pagar
          from bens b where b.dono_id = :u order by b.descricao""", u=u["id"])
    for c in ("valor_aquisicao", "valor_atual", "divida_vinculada", "pago", "a_pagar"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if not df.empty:
        df["valor"] = df["valor_atual"].fillna(df["valor_aquisicao"]).fillna(0)
        df["divida"] = df.apply(lambda r: r.divida_vinculada if pd.notna(r.divida_vinculada)
                                else max((r.valor_aquisicao or 0) - r.pago, 0) if r.categorias_pagamento else 0,
                                axis=1)
        df["pct_quitado"] = df.apply(lambda r: min(r.pago / r.valor_aquisicao, 1) if r.valor_aquisicao else None,
                                     axis=1)
    return df


def salvar_bem(u, d: dict, bem_id=None):
    p = {k: d.get(k) for k in ["descricao", "data_aquisicao", "valor_aquisicao", "valor_atual", "divida_vinculada"]}
    p |= {"u": u["id"], "id": bem_id, "cats": [str(c) for c in (d.get("categorias_pagamento") or [])]}
    if bem_id:
        db.executar("""update bens set descricao=:descricao, data_aquisicao=:data_aquisicao,
                         valor_aquisicao=:valor_aquisicao, valor_atual=:valor_atual,
                         divida_vinculada=:divida_vinculada, categorias_pagamento=cast(:cats as uuid[])
                       where id=:id and dono_id=:u""", **p)
    else:
        db.executar("""insert into bens (dono_id, descricao, data_aquisicao, valor_aquisicao, valor_atual,
                         divida_vinculada, categorias_pagamento)
                       values (:u, :descricao, :data_aquisicao, :valor_aquisicao, :valor_atual, :divida_vinculada,
                         cast(:cats as uuid[]))""", **p)


def excluir_bem(u, bem_id):
    db.executar("delete from bens where id = :id and dono_id = :u", id=bem_id, u=u["id"])


def calcular(u) -> pd.DataFrame:
    """Linhas: grupo, item, valor (+ tem / − deve)."""
    linhas = []
    contas = db.consultar("""select id, nome, tipo::text as tipo from contas
                             where dono_id = :u and ativa
                               and tipo in ('conta_corrente','poupanca','carteira','fgts','financiamento')""",
                          u=u["id"])
    tem_ativo = set(db.consultar("""select distinct a.conta_id from ativos a join contas c on c.id = a.conta_id
                                    where a.ativo and c.dono_id = :u""", u=u["id"])["conta_id"])
    for c in contas.itertuples():
        if c.tipo == "poupanca" and c.id in tem_ativo:
            continue                                          # já entra pelos investimentos
        s = saldos.saldo_em(u, c.id, hoje())
        if c.tipo == "financiamento":
            linhas.append(("Dívidas", c.nome, -abs(s)))
        elif c.tipo == "fgts":
            linhas.append(("FGTS", c.nome, s))
        else:
            linhas.append(("Contas", c.nome, s))
    a = investimentos.ativos(u)
    for r in a.itertuples():
        grupo = "Previdência" if str(r.classe).startswith("previdencia") else "Investimentos"
        linhas.append((grupo, f"{r.instituicao} · {r.nome}", float(r.valor_atual or 0)))
    b = bens(u)
    for r in b.itertuples():
        linhas.append(("Bens", r.descricao, float(r.valor)))
        if r.divida:
            linhas.append(("Dívidas", f"{r.descricao} (a pagar)", -float(r.divida)))
    res = cartoes.resumo(u)
    if not res.empty:
        for r in res.itertuples():
            aberto = r.fatura_atual + r.atrasadas
            if aberto:
                linhas.append(("Dívidas", f"Fatura {r.cartao}", -float(aberto)))
    return pd.DataFrame(linhas, columns=["grupo", "item", "valor"])


def registrar_mes(u, comp: pd.DataFrame):
    ativos_ = float(comp.loc[comp["valor"] > 0, "valor"].sum())
    passivos = float(-comp.loc[comp["valor"] < 0, "valor"].sum())
    det = comp.groupby("grupo")["valor"].sum().round(2).to_dict()
    db.executar("""insert into patrimonio_mensal (dono_id, mes_ref, ativos, passivos, detalhe)
                   values (:u, :m, :a, :p, cast(:d as jsonb))
                   on conflict (dono_id, mes_ref) do update set ativos = excluded.ativos,
                     passivos = excluded.passivos, detalhe = excluded.detalhe, atualizado_em = now()""",
                u=u["id"], m=mes_ref(hoje()), a=ativos_, p=passivos, d=json.dumps(det))


def historico(u) -> pd.DataFrame:
    df = db.consultar("""select mes_ref, ativos, passivos, ativos - passivos as liquido, detalhe
                           from patrimonio_mensal where dono_id = :u order by mes_ref""", u=u["id"])
    for c in ("ativos", "passivos", "liquido"):
        df[c] = df[c].astype(float)
    return df


def mes_anterior(u) -> float | None:
    r = db.um("select ativos - passivos as l from patrimonio_mensal where dono_id = :u and mes_ref = :m",
              u=u["id"], m=somar_meses(mes_ref(hoje()), -1))
    return float(r["l"]) if r else None

"""Saldo e fluxo de caixa das contas (corrente, poupança, carteira, FGTS…).

Saldo numa data = último saldo informado (tabela saldos) até essa data
                  + tudo o que foi lançado na conta depois dele.
Sem saldo informado, parte de contas.saldo_inicial (0 se vazio).

O que mexe numa conta:
  - lançamentos com conta_id = conta (receita +, despesa −, transferência −)
  - transferências com conta_destino_id = conta (+)
  - a FATURA de cada cartão cuja conta pagadora é esta (uma linha por fatura, no vencimento)
  - lançamentos sem conta (boleto, pix avulso), se esta for a conta principal
Previstos contam na data deles (é uma projeção); o app avisa os vencidos sem confirmação.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from core import db
from core.fmt import dia_no_mes, hoje

TIPOS_CAIXA = ("conta_corrente", "poupanca", "carteira")


# ---------------------------------------------------------------------------
# preferências: conta principal (de onde saem os lançamentos sem conta)
# ---------------------------------------------------------------------------
def conta_principal(u):
    r = db.um("select preferencias->>'conta_principal' as c from usuarios where id = :u", u=u["id"])
    return r["c"] if r and r["c"] else None


def definir_conta_principal(u, conta_id):
    db.executar("""update usuarios set preferencias = coalesce(preferencias, '{}'::jsonb)
                          || jsonb_build_object('conta_principal', cast(:c as text)) where id = :u""",
                c=str(conta_id) if conta_id else None, u=u["id"])


# ---------------------------------------------------------------------------
# movimentos
# ---------------------------------------------------------------------------
def _faturas(u, conta_ids: list) -> pd.DataFrame:
    """Uma linha por fatura (cartão × mês) dos cartões pagos por estas contas."""
    df = db.consultar("""
        select card.id as cartao_id, card.nome as cartao, card.dia_vencimento, card.conta_pagamento_id as conta,
               l.mes_ref, max(l.data_vencimento) as venc,
               sum(case when l.tipo = 'receita' then -l.valor else l.valor end) as total,
               bool_and(l.status = 'pago') as paga
          from lancamentos l join contas card on card.id = l.conta_id and card.tipo = 'cartao_credito'
         where l.dono_id = :u and l.status <> 'cancelado' and card.conta_pagamento_id = any(:c)
         group by 1, 2, 3, 4, 5""", u=u["id"], c=list(conta_ids))
    if df.empty:
        return pd.DataFrame(columns=["id", "data", "descricao", "categoria", "valor", "status", "conta", "fonte"])
    df["data"] = df.apply(lambda r: dia_no_mes(r.mes_ref // 100, r.mes_ref % 100, int(r.dia_vencimento))
                          if pd.notna(r.dia_vencimento) else r.venc, axis=1)
    return pd.DataFrame({"id": None, "data": df["data"], "descricao": "Fatura " + df["cartao"],
                         "categoria": "Cartão de crédito", "grupo": "Cartão de crédito", "nao_contar": False,
                         "valor": -df["total"].astype(float),
                         "status": df["paga"].map({True: "pago", False: "previsto"}), "conta": df["conta"],
                         "fonte": "fatura"})


_VAZIO = ["id", "data", "descricao", "categoria", "grupo", "nao_contar", "valor", "status", "conta", "fonte"]


def _contas_caixa_ids(u) -> list:
    df = db.consultar("select id from contas where dono_id = :u and tipo = any(:t)", u=u["id"], t=list(TIPOS_CAIXA))
    return list(df["id"]) if not df.empty else []


def movimentos(u, conta_ids: list, ini: date | None = None, fim: date | None = None) -> pd.DataFrame:
    """Movimentos das contas pedidas. Por baixo, busca de uma vez os de TODAS as contas de caixa do usuário
    (uma consulta, guardada em cache) e filtra em memória — o painel chama isto dezenas de vezes."""
    if not conta_ids:
        return pd.DataFrame(columns=_VAZIO)
    todas = _contas_caixa_ids(u)
    pedidas = set(conta_ids)
    if pedidas <= set(todas):
        df = _movimentos_brutos(u, todas)
        df = df[df["conta"].isin(pedidas)] if not df.empty else df
    else:
        df = _movimentos_brutos(u, list(conta_ids))
    if df.empty:
        return df
    if ini:
        df = df[df["data"] >= ini]
    if fim:
        df = df[df["data"] <= fim]
    return df.sort_values(["data", "valor"], ascending=[True, False]).reset_index(drop=True)


def _movimentos_brutos(u, conta_ids: list) -> pd.DataFrame:
    principal = conta_principal(u)
    df = db.consultar("""
        select l.id, coalesce(l.data_pagamento, l.data_vencimento) as data, l.descricao,
               coalesce(cat.nome, '—') as categoria, coalesce(pai.nome, cat.nome, '—') as grupo,
               l.nao_contar,
               case when l.tipo = 'receita' then l.valor else -l.valor end as valor,
               l.status::text as status, coalesce(l.conta_id, cast(:p as uuid)) as conta,
               case when l.conta_id is null then 'sem_conta' else 'lancamento' end as fonte
          from lancamentos l left join categorias cat on cat.id = l.categoria_id
          left join categorias pai on pai.id = cat.pai_id
         where l.dono_id = :u and l.status <> 'cancelado'
           and (l.conta_id = any(:c)
                or (l.conta_id is null and cast(:p as uuid) = any(:c) and l.tipo <> 'transferencia'
                    and coalesce(l.forma_pagamento, '') <> 'Cartao de Credito'))
        union all
        select l.id, coalesce(l.data_pagamento, l.data_vencimento), l.descricao, coalesce(cat.nome, '—'),
               coalesce(pai.nome, cat.nome, '—'), false, l.valor, l.status::text, l.conta_destino_id, 'entrada_transf'
          from lancamentos l left join categorias cat on cat.id = l.categoria_id
          left join categorias pai on pai.id = cat.pai_id
         where l.dono_id = :u and l.status <> 'cancelado' and l.tipo = 'transferencia'
           and l.conta_destino_id = any(:c)""", u=u["id"], c=list(conta_ids), p=principal)
    df = pd.concat([df, _faturas(u, conta_ids)], ignore_index=True) if not df.empty else _faturas(u, conta_ids)
    if df.empty:
        return pd.DataFrame(columns=_VAZIO)
    df["data"] = pd.to_datetime(df["data"]).dt.date
    df["valor"] = df["valor"].astype(float)
    return df


# ---------------------------------------------------------------------------
# saldos
# ---------------------------------------------------------------------------
def _todas_ancoras(u) -> pd.DataFrame:
    """Todos os saldos informados das contas do usuário + saldo inicial de cada conta, numa consulta só.
    A tabela é pequena (uma linha por saldo informado); antes eram 3-4 idas ao banco por conta por chamada."""
    t = db.consultar("""
        select c.id as conta_id, c.saldo_inicial, c.data_saldo_inicial, s.data, s.valor
          from contas c left join saldos s on s.conta_id = c.id
         where c.dono_id = :u order by c.id, s.data""", u=u["id"])
    if t.empty:
        return t
    t = t.copy()
    t["data"] = [None if pd.isna(x) else pd.Timestamp(x).date() for x in t["data"]]
    t["data_saldo_inicial"] = [None if pd.isna(x) else pd.Timestamp(x).date() for x in t["data_saldo_inicial"]]
    return t


def ancoras(conta_id, u=None) -> pd.DataFrame:
    if u is not None:
        t = _todas_ancoras(u)
        t = t[(t["conta_id"] == conta_id) & t["data"].notna()][["data", "valor"]]
        return t.reset_index(drop=True)
    return db.consultar("select data, valor from saldos where conta_id = :c order by data", c=conta_id)


def _ancora_ate(conta_id, d: date, u=None) -> tuple[date, float]:
    if u is not None:
        t = _todas_ancoras(u)
        t = t[t["conta_id"] == conta_id]
        if t.empty:
            return date(1900, 1, 1) - timedelta(days=1), 0.0
        ate = t[[x is not None and x <= d for x in t["data"]]]
        if not ate.empty:
            r = ate.iloc[-1]
            return r["data"], float(r["valor"])
        c = t.iloc[0]
        d0 = c["data_saldo_inicial"] or date(1900, 1, 1)
        return d0 - timedelta(days=1), float(c["saldo_inicial"] or 0)
    r = db.um("select data, valor from saldos where conta_id = :c and data <= :d order by data desc limit 1",
              c=conta_id, d=d)
    if r:
        return r["data"], float(r["valor"])
    c = db.um("select saldo_inicial, data_saldo_inicial from contas where id = :c", c=conta_id)
    return (c["data_saldo_inicial"] or date(1900, 1, 1)) - timedelta(days=1), float(c["saldo_inicial"] or 0)


def saldo_em(u, conta_id, d: date) -> float:
    anc = ancoras(conta_id, u)
    datas = [pd.Timestamp(x).date() for x in anc["data"]] if not anc.empty else []
    if not any(x <= d for x in datas):
        # nenhum saldo informado até d, mas há um depois: volta a conta a partir dele
        depois = [(x, v) for x, v in zip(datas, anc["valor"]) if x > d]
        if depois:
            dd, vv = depois[0]
            r = {"data": dd, "valor": vv}
            mov = movimentos(u, [conta_id], d + timedelta(days=1), dd)
            return float(r["valor"]) - (float(mov["valor"].sum()) if not mov.empty else 0.0)
    a_data, a_valor = _ancora_ate(conta_id, d, u)
    mov = movimentos(u, [conta_id], a_data + timedelta(days=1), d)
    return a_valor + (float(mov["valor"].sum()) if not mov.empty else 0.0)


def informar_saldo(conta_id, d: date, valor: float):
    db.executar("""insert into saldos (conta_id, data, valor) values (:c, :d, :v)
                   on conflict (conta_id, data) do update set valor = excluded.valor""", c=conta_id, d=d, v=valor)


def saldo_informado(conta_id, d: date) -> float | None:
    r = db.um("select valor from saldos where conta_id = :c and data = :d", c=conta_id, d=d)
    return float(r["valor"]) if r else None


def remover_saldo(conta_id, d: date):
    db.executar("delete from saldos where conta_id = :c and data = :d", c=conta_id, d=d)


def extrato(u, conta_ids: list, ini: date, fim: date) -> tuple[float, pd.DataFrame]:
    """(saldo no dia anterior a ini, linhas com saldo acumulado). Saldos informados no meio do período
    entram como 'Ajuste' para o acumulado bater com o banco."""
    partes, inicial = [], 0.0
    for c in conta_ids:
        s0 = saldo_em(u, c, ini - timedelta(days=1))
        inicial += s0
        mov = movimentos(u, [c], ini, fim)
        anc = ancoras(c, u)
        anc = anc[(pd.to_datetime(anc["data"]).dt.date >= ini) & (pd.to_datetime(anc["data"]).dt.date <= fim)] \
            if not anc.empty else anc
        if not anc.empty:
            linhas, corrente = [], s0
            dias = sorted(set(mov["data"]) | set(pd.to_datetime(anc["data"]).dt.date)) if not mov.empty else \
                sorted(set(pd.to_datetime(anc["data"]).dt.date))
            mapa = dict(zip(pd.to_datetime(anc["data"]).dt.date, anc["valor"].astype(float)))
            for d in dias:
                dia = mov[mov["data"] == d] if not mov.empty else mov
                linhas.append(dia)
                corrente += float(dia["valor"].sum()) if not dia.empty else 0.0
                if d in mapa and abs(mapa[d] - corrente) > 0.004:
                    linhas.append(pd.DataFrame([{"id": None, "data": d, "descricao": "Ajuste (saldo informado)",
                                                 "categoria": "Ajuste", "grupo": "Ajuste", "nao_contar": False,
                                                 "valor": round(mapa[d] - corrente, 2),
                                                 "status": "pago", "conta": c, "fonte": "ajuste"}]))
                    corrente = mapa[d]
            mov = pd.concat(linhas, ignore_index=True) if linhas else mov
        partes.append(mov)
    df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if df.empty:
        return inicial, df
    df = df.sort_values(["data"], kind="stable").reset_index(drop=True)
    df["saldo"] = inicial + df["valor"].cumsum()
    return inicial, df


def projecao_diaria(u, conta_ids: list, ini: date, dias: int = 90) -> pd.DataFrame:
    """Saldo no fim de cada dia, de ini até ini+dias."""
    fim = ini + timedelta(days=dias)
    s0, df = extrato(u, conta_ids, ini, fim)
    datas = pd.date_range(ini, fim, freq="D").date
    por_dia = df.groupby("data")["valor"].sum() if not df.empty else pd.Series(dtype=float)
    saldo, out = s0, []
    for d in datas:
        saldo += float(por_dia.get(d, 0.0))
        out.append({"data": d, "saldo": round(saldo, 2)})
    return pd.DataFrame(out)


def vencidos_sem_confirmar(u, conta_ids: list) -> pd.DataFrame:
    mov = movimentos(u, conta_ids, None, hoje() - timedelta(days=1))
    return mov[mov["status"] == "previsto"] if not mov.empty else mov

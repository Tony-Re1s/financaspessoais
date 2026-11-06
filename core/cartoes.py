"""Faturas dos cartões, montadas a partir dos lançamentos (uma fatura = cartão × mês de vencimento)."""
from __future__ import annotations

import pandas as pd

from core import db
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref, somar_meses


def faturas(u) -> pd.DataFrame:
    df = db.consultar("""
        select card.id as cartao_id, card.nome as cartao, card.dia_vencimento, card.limite, l.mes_ref,
               max(l.data_vencimento) as venc_max,
               sum(case when l.tipo = 'receita' then -l.valor else l.valor end) as total,
               sum(case when l.status = 'pago' then (case when l.tipo = 'receita' then -l.valor else l.valor end)
                        else 0 end) as pago,
               count(*) as itens, bool_and(l.status = 'pago') as paga
          from lancamentos l join contas card on card.id = l.conta_id and card.tipo = 'cartao_credito'
         where l.dono_id = :u and l.status <> 'cancelado' and card.ativa
         group by 1, 2, 3, 4, 5 order by 2, 5""", u=u["id"])
    if df.empty:
        return df
    df["vencimento"] = df.apply(lambda r: dia_no_mes(r.mes_ref // 100, r.mes_ref % 100, int(r.dia_vencimento))
                                if pd.notna(r.dia_vencimento) else r.venc_max, axis=1)
    for c in ("total", "pago", "limite"):
        df[c] = df[c].astype(float)
    return df


def resumo(u, faturas_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Uma linha por cartão: fatura atual (a próxima a vencer ainda aberta), próxima, total comprometido."""
    f = faturas(u) if faturas_df is None else faturas_df
    if f.empty:
        return f
    hj = mes_ref(hoje())
    linhas = []
    for (cid, nome), g in f.groupby(["cartao_id", "cartao"], sort=False):
        abertas = g[~g["paga"]].sort_values("mes_ref")
        atrasadas = abertas[abertas["vencimento"] < hoje()]
        futuras = abertas[abertas["vencimento"] >= hoje()]
        atual = futuras.iloc[0] if not futuras.empty else None
        prox = futuras.iloc[1] if len(futuras) > 1 else None
        comprometido = float(abertas["total"].sum() - abertas["pago"].sum())
        limite = g["limite"].iloc[0]
        linhas.append({
            "cartao_id": cid, "cartao": nome,
            "venc_atual": atual["vencimento"] if atual is not None else None,
            "fatura_atual": float(atual["total"]) if atual is not None else 0.0,
            "venc_prox": prox["vencimento"] if prox is not None else None,
            "fatura_prox": float(prox["total"]) if prox is not None else 0.0,
            "atrasadas": float(atrasadas["total"].sum()), "n_atrasadas": len(atrasadas),
            "comprometido": comprometido, "limite": None if pd.isna(limite) else float(limite),
            "disponivel": None if pd.isna(limite) else float(limite) - comprometido,
            "mes_hoje": hj,
        })
    return pd.DataFrame(linhas)


def itens(u, cartao_id, mes: int) -> pd.DataFrame:
    """Lançamentos de uma fatura, com o grupo para a tela: parcela, assinatura (repete todo mês) ou compra."""
    df = db.consultar("""
        with rep as (select lower(descricao) d, valor v, count(distinct mes_ref) n, max(mes_ref) ultimo from lancamentos
                      where dono_id = :u and conta_id = :c and status <> 'cancelado' and parcela_num is null
                      group by 1, 2)
        select l.id, l.data_compra, l.descricao, l.parcela_num, l.parcela_total, l.valor, l.tipo::text as tipo,
               l.status::text as status, coalesce(c.nome, 'Sem categoria') as categoria, p.nome as categoria_pai,
               l.origem::text as origem,
               case when l.parcela_num is not null then 'Parcelas'
                    when l.recorrencia_id is not null then 'Assinaturas'
                    when coalesce(rep.n, 0) >= 3 and rep.ultimo < :lim then 'Parcelas'
                    when coalesce(rep.n, 0) >= 3 then 'Assinaturas'
                    else 'Compras' end as grupo,
               rep.ultimo as ultimo_mes
          from lancamentos l left join categorias c on c.id = l.categoria_id
          left join categorias p on p.id = c.pai_id
          left join rep on rep.d = lower(l.descricao) and rep.v = l.valor
         where l.dono_id = :u and l.conta_id = :c and l.mes_ref = :m and l.status <> 'cancelado'
         order by l.valor desc""", u=u["id"], c=cartao_id, m=mes, lim=somar_meses(mes_ref(hoje()), 11))
    return df


def pago_no_mes(u, mes: int) -> float:
    """Quanto saiu das contas para pagar faturas no mês (transferências para cartões vindas dos extratos)."""
    r = db.um("""select coalesce(sum(l.valor), 0) as v from lancamentos l left join contas c on c.id = l.conta_destino_id
                  where l.dono_id = :u and l.tipo = 'transferencia'
                    and (c.tipo = 'cartao_credito' or l.descricao ilike 'Pagamento de fatura%%')
                    and to_char(coalesce(l.data_pagamento, l.data_vencimento), 'YYYYMM')::int = :m""",
              u=u["id"], m=mes)
    return float(r["v"]) if r else 0.0


def marcar_fatura(u, cartao_id, mes: int, paga: bool, data_pag=None):
    db.executar("""update lancamentos
                      set status = cast(:s as status_lancamento),
                          data_pagamento = case when :s = 'pago' then coalesce(cast(:d as date), data_vencimento) end,
                          atualizado_em = now()
                    where dono_id = :u and conta_id = :c and mes_ref = :m and status <> 'cancelado'""",
                s="pago" if paga else "previsto", d=data_pag, u=u["id"], c=cartao_id, m=mes)


def total_fatura(u, cartao_id, mes: int) -> float:
    r = db.um("""select coalesce(sum(case when tipo = 'receita' then -valor else valor end), 0) as v
                   from lancamentos where dono_id = :u and conta_id = :c and mes_ref = :m and status <> 'cancelado'""",
              u=u["id"], c=cartao_id, m=mes)
    return float(r["v"]) if r else 0.0


def pagar_fatura(u, cartao_id, mes: int, valor_pago: float, data_pag=None) -> float:
    """Paga a fatura inteira ou parte dela.

    Marca TODOS os lançamentos da fatura como pagos (o cartão já cobrou tudo) e, se o valor pago
    for menor que o total, cria na fatura seguinte um lançamento "Saldo anterior" com a diferença,
    previsto, na categoria Juros e Multas — ali você ajusta o valor quando o banco mostrar os juros.
    Devolve o valor que foi para a próxima fatura (0 se pagou tudo)."""
    from core.semente import garantir_categoria
    from sqlalchemy import text
    total = total_fatura(u, cartao_id, mes)
    resto = round(total - float(valor_pago), 2)
    marcar_fatura(u, cartao_id, mes, True, data_pag)
    if resto <= 0.004:
        return 0.0
    prox = somar_meses(mes, 1)
    card = db.um("select dia_vencimento from contas where id = :c", c=cartao_id)
    y, m = divmod(prox, 100)
    venc = dia_no_mes(y, m, int(card["dia_vencimento"] or 10))
    with db.transacao() as s:
        pai = garantir_categoria(s, u["id"], "Servicos Financeiros")
        cat = garantir_categoria(s, u["id"], "Juros e Multas", pai)
        s.execute(text("""
            insert into lancamentos (dono_id, conta_id, categoria_id, tipo, descricao, valor, data_compra,
                                     data_vencimento, status, visibilidade, observacao, origem)
            values (:u, :c, :cat, 'despesa', :d, :v, :dc, :dv, 'previsto', 'privado', :obs, 'manual')"""),
            dict(u=u["id"], c=cartao_id, cat=cat, d=f"Saldo anterior · fatura de {mes_label(mes)}", v=resto,
                 dc=data_pag or venc, dv=venc,
                 obs=f"Pagamento parcial: fatura {brl(total)}, pago {brl(float(valor_pago))}. "
                     "Ajuste o valor quando o banco mostrar os juros do rotativo."))
    return resto

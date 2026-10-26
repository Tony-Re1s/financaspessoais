"""Contas fixas: cadastradas uma vez, viram lançamentos previstos dos próximos meses.

Não duplica: se já existe um lançamento com o mesmo nome no mesmo mês e conta
(ex.: veio da planilha), ele é ligado à conta fixa em vez de criar outro.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import text

from core import db
from core.fmt import dia_no_mes, hoje, mes_ref, somar_meses, vencimento_fatura

HORIZONTE = 12   # meses à frente


def listar(u) -> pd.DataFrame:
    return db.consultar("""
        select r.id, r.descricao, r.valor, r.dia_vencimento, r.frequencia, r.inicio, r.fim, r.ativa,
               r.conta_id, c.nome as conta, c.tipo::text as conta_tipo, r.categoria_id, r.tipo::text as tipo,
               r.forma_pagamento, r.visibilidade::text as visibilidade,
               (select min(l.data_vencimento) from lancamentos l where l.recorrencia_id = r.id
                  and l.status = 'previsto' and l.data_vencimento >= current_date) as proxima
          from recorrencias r left join contas c on c.id = r.conta_id
         where r.dono_id = :u order by r.ativa desc, r.descricao""", u=u["id"])


def salvar(u, d: dict, rec_id=None):
    p = {k: d.get(k) for k in ["conta_id", "categoria_id", "tipo", "descricao", "valor", "frequencia",
                               "dia_vencimento", "inicio", "fim", "forma_pagamento", "visibilidade", "ativa"]}
    p |= {"u": u["id"], "id": rec_id, "tipo": p["tipo"] or "despesa", "frequencia": p["frequencia"] or "mensal"}
    with db.transacao() as s:
        if rec_id:
            s.execute(text("""update recorrencias set conta_id=:conta_id, categoria_id=:categoria_id,
                                tipo=cast(:tipo as tipo_lancamento), descricao=:descricao, valor=:valor,
                                frequencia=:frequencia, dia_vencimento=:dia_vencimento, inicio=:inicio, fim=:fim,
                                forma_pagamento=:forma_pagamento, visibilidade=cast(:visibilidade as visibilidade),
                                ativa=coalesce(:ativa, true)
                              where id=:id and dono_id=:u"""), p)
            _limpar_futuro(s, u, rec_id, so_gerados=True)
            # os que vieram de fora (planilha) e foram ligados: acompanham valor/categoria/conta
            s.execute(text("""update lancamentos set valor=:valor, categoria_id=:categoria_id, conta_id=:conta_id
                               where recorrencia_id=:id and dono_id=:u and status='previsto'
                                 and data_vencimento >= :hoje"""), p | {"hoje": hoje()})
        else:
            rec_id = s.execute(text("""insert into recorrencias (dono_id, conta_id, categoria_id, tipo, descricao,
                                         valor, frequencia, dia_vencimento, inicio, fim, forma_pagamento,
                                         visibilidade, ativa)
                                       values (:u, :conta_id, :categoria_id, cast(:tipo as tipo_lancamento),
                                         :descricao, :valor, :frequencia, :dia_vencimento, :inicio, :fim,
                                         :forma_pagamento, cast(:visibilidade as visibilidade),
                                         coalesce(:ativa, true))
                                       returning id"""), p).scalar()
    if p.get("ativa") is False:
        encerrar(u, rec_id, desativar=False)
    else:
        gerar(u, rec_id)
    return rec_id


def _limpar_futuro(s, u, rec_id, so_gerados: bool):
    s.execute(text(f"""delete from lancamentos where recorrencia_id = :id and dono_id = :u
                         and status = 'previsto' and data_vencimento >= :hoje
                         {"and origem = 'recorrencia'" if so_gerados else ""}"""),
              {"id": rec_id, "u": u["id"], "hoje": hoje()})


def encerrar(u, rec_id, desativar=True, apagar=False):
    """Para de gerar e tira os previstos futuros (pagos e passados ficam)."""
    with db.transacao() as s:
        _limpar_futuro(s, u, rec_id, so_gerados=False)
        if apagar:
            s.execute(text("delete from recorrencias where id = :id and dono_id = :u"), {"id": rec_id, "u": u["id"]})
        elif desativar:
            s.execute(text("update recorrencias set ativa = false where id = :id and dono_id = :u"),
                      {"id": rec_id, "u": u["id"]})


def _vencimentos(r, ate: int) -> list[tuple[int, date, date]]:
    """(mes_ref, data da cobrança, vencimento) de cada ocorrência de hoje até 'ate'."""
    ini = max(mes_ref(r["inicio"]), mes_ref(hoje()))
    fim = min(ate, mes_ref(r["fim"])) if r["fim"] is not None and pd.notna(r["fim"]) else ate
    dia = int(r["dia_vencimento"] or r["inicio"].day)
    out, m = [], ini
    while m <= fim:
        if r["frequencia"] != "anual" or m % 100 == r["inicio"].month:
            cobranca = dia_no_mes(m // 100, m % 100, dia)
            if r["conta_tipo"] == "cartao_credito" and r["dia_venc_cartao"] is not None and pd.notna(r["dia_venc_cartao"]):
                fech = None if pd.isna(r["dia_fech_cartao"]) else int(r["dia_fech_cartao"])
                venc = vencimento_fatura(cobranca, fech, int(r["dia_venc_cartao"]))
            else:
                venc = cobranca
            if venc >= hoje():
                out.append((mes_ref(venc), cobranca, venc))
        m = somar_meses(m, 1)
    return out


def gerar(u, rec_id=None) -> int:
    """Cria o que falta até HORIZONTE meses à frente. Seguro chamar várias vezes."""
    recs = db.consultar(f"""
        select r.*, c.tipo::text as conta_tipo, c.dia_vencimento as dia_venc_cartao,
               c.dia_fechamento as dia_fech_cartao
          from recorrencias r left join contas c on c.id = r.conta_id
         where r.dono_id = :u and r.ativa {"and r.id = :id" if rec_id else ""}""", u=u["id"], id=rec_id)
    ate = somar_meses(mes_ref(hoje()), HORIZONTE)
    n = 0
    with db.transacao() as s:
        for r in recs.to_dict("records"):
            cartao = r["conta_tipo"] == "cartao_credito"
            forma = r["forma_pagamento"] or ("Cartao de Credito" if cartao else
                                             "Debito em Conta" if r["conta_tipo"] == "conta_corrente" else "Boleto")
            for m, cobranca, venc in _vencimentos(r, ate):
                k = f"rec:{r['id']}:{m}"
                if s.execute(text("select 1 from lancamentos where chave_importacao = :k"), {"k": k}).first():
                    continue
                # já existe (planilha, fatura, manual)? liga em vez de duplicar
                ligado = s.execute(text("""
                    update lancamentos set recorrencia_id = :rid
                     where id = (select id from lancamentos
                                  where dono_id = :u and mes_ref = :m and status <> 'cancelado'
                                    and (recorrencia_id is null or recorrencia_id = :rid)
                                    and conta_id is not distinct from :c
                                    and (lower(descricao) = lower(:d)
                                         or (recorrencia_id = :rid))
                                  limit 1)
                    returning id"""), {"rid": r["id"], "u": u["id"], "m": m, "c": r["conta_id"],
                                       "d": r["descricao"]}).first()
                if ligado:
                    continue
                s.execute(text("""
                    insert into lancamentos (dono_id, conta_id, categoria_id, tipo, descricao, valor, data_compra,
                        data_vencimento, forma_pagamento, status, visibilidade, origem, recorrencia_id,
                        chave_importacao)
                    values (:u, :c, :cat, cast(:tipo as tipo_lancamento), :d, :v, :dc, :dv, :f, 'previsto',
                        cast(:vis as visibilidade), 'recorrencia', :rid, :k)
                    on conflict do nothing"""),
                    {"u": u["id"], "c": r["conta_id"], "cat": r["categoria_id"], "tipo": r["tipo"],
                     "d": r["descricao"], "v": r["valor"], "dc": cobranca, "dv": venc, "f": forma,
                     "vis": r["visibilidade"], "rid": r["id"], "k": k})
                n += 1
    return n


def sugestoes(u) -> pd.DataFrame:
    """Gastos que se repetem com o mesmo valor em 3+ meses e ainda não são conta fixa."""
    return db.consultar("""
        select min(l.descricao) as descricao, l.conta_id, min(c.nome) as conta, l.valor,
               (array_agg(l.categoria_id order by l.criado_em desc))[1] as categoria_id,
               count(distinct l.mes_ref) as meses, min(l.data_vencimento) as primeiro,
               max(l.data_vencimento) as ultimo,
               mode() within group (order by extract(day from coalesce(l.data_compra, l.data_vencimento))) as dia
          from lancamentos l left join contas c on c.id = l.conta_id
         where l.dono_id = :u and l.tipo = 'despesa' and l.parcela_num is null and l.recorrencia_id is null
           and l.status <> 'cancelado'
         group by lower(l.descricao), l.conta_id, l.valor
        having count(distinct l.mes_ref) >= 3
         order by l.valor desc""", u=u["id"])

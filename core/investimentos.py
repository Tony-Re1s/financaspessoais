"""Aplicações: cada uma fica dentro de uma 'instituição' (conta tipo investimento/previdência/poupança).

Valor atual = última posição informada + aportes − resgates depois dela;
sem posição informada = aportes − resgates + rendimentos − IR − taxas.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from core import db
from core.fmt import hoje

CLASSES = {
    "renda_fixa": "Renda fixa (CDB, LCI, LCA…)", "tesouro": "Tesouro Direto", "fundo": "Fundos",
    "acao": "Ações", "fii": "Fundos imobiliários", "etf": "ETFs", "previdencia_pgbl": "Previdência PGBL",
    "previdencia_vgbl": "Previdência VGBL", "cripto": "Cripto", "poupanca": "Poupança", "outro": "Outro",
}
TIPOS_INSTITUICAO = ("investimento", "previdencia", "poupanca")


def ativos(u, so_ativos=True) -> pd.DataFrame:
    df = db.consultar(f"""
        with mov as (
          select ativo_id,
                 sum(case tipo when 'aporte' then valor when 'resgate' then -valor else 0 end) as aplicado,
                 sum(case tipo when 'rendimento' then valor when 'ir_retido' then -valor
                               when 'taxa' then -valor else 0 end) as rendimentos,
                 min(case when tipo = 'aporte' then data end) as primeiro_aporte
            from ativo_movimentos group by ativo_id),
        pos as (
          select distinct on (ativo_id) ativo_id, data as data_posicao, valor_bruto, valor_liquido
            from ativo_posicoes order by ativo_id, data desc),
        depois as (
          select m.ativo_id, sum(case m.tipo when 'aporte' then m.valor when 'resgate' then -m.valor else 0 end) as liq
            from ativo_movimentos m join pos p on p.ativo_id = m.ativo_id and m.data > p.data_posicao
           group by m.ativo_id),
        -- pagamentos vinculados (ex.: "CAP PIC" debitado todo mês): contam como aporte depois da última posição
        vinc as (
          select a2.id as ativo_id, sum(l.valor) as pago
            from ativos a2 join contas c2 on c2.id = a2.conta_id
            left join pos p2 on p2.ativo_id = a2.id
            join lancamentos l on l.dono_id = c2.dono_id and l.status = 'pago' and l.tipo = 'despesa'
                              and lower(l.descricao) = lower(a2.vinculo_descricao)
                              and coalesce(l.data_pagamento, l.data_vencimento) > coalesce(p2.data_posicao, a2.data_aplicacao,
                                                                                          date '1900-01-01')
           where a2.vinculo_descricao is not null and c2.dono_id = :u
           group by a2.id)
        select a.id, a.nome, a.classe, a.indexador, a.taxa, a.data_aplicacao, a.vencimento, a.liquidez,
               a.ativo, a.conta_id, c.nome as instituicao, a.vinculo_descricao,
               coalesce(mov.aplicado, 0) + coalesce(vinc.pago, 0) as aplicado,
               coalesce(mov.rendimentos, 0) as rendimentos,
               pos.data_posicao, pos.valor_bruto, pos.valor_liquido,
               coalesce(pos.valor_bruto + coalesce(depois.liq, 0),
                        coalesce(mov.aplicado, 0) + coalesce(mov.rendimentos, 0)) + coalesce(vinc.pago, 0) as valor_atual
          from ativos a join contas c on c.id = a.conta_id
          left join mov on mov.ativo_id = a.id
          left join pos on pos.ativo_id = a.id
          left join depois on depois.ativo_id = a.id
          left join vinc on vinc.ativo_id = a.id
         where c.dono_id = :u {"and a.ativo" if so_ativos else ""}
         order by c.nome, a.nome""", u=u["id"])
    for col in ("aplicado", "rendimentos", "valor_bruto", "valor_liquido", "valor_atual", "taxa"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if not df.empty:
        df["ganho"] = df["valor_atual"] - df["aplicado"]
        df["ganho_pct"] = df.apply(lambda r: r.ganho / r.aplicado if r.aplicado else None, axis=1)
    return df


def salvar_ativo(d: dict, ativo_id=None):
    p = {k: d.get(k) for k in ["conta_id", "nome", "classe", "indexador", "taxa", "data_aplicacao",
                               "vencimento", "liquidez", "cnpj_emissor", "ativo", "vinculo_descricao"]} | {"id": ativo_id}
    p["vinculo_descricao"] = (p["vinculo_descricao"] or "").strip() or None
    if ativo_id:
        db.executar("""update ativos set conta_id=:conta_id, nome=:nome, classe=:classe, indexador=:indexador,
                         taxa=:taxa, data_aplicacao=:data_aplicacao, vencimento=:vencimento, liquidez=:liquidez,
                         cnpj_emissor=:cnpj_emissor, ativo=coalesce(:ativo, true),
                         vinculo_descricao=:vinculo_descricao where id=:id""", **p)
        return ativo_id
    return db.gravar_retornando("""insert into ativos (conta_id, nome, classe, indexador, taxa, data_aplicacao, vencimento,
                      liquidez, cnpj_emissor, ativo, vinculo_descricao)
                    values (:conta_id, :nome, :classe, :indexador, :taxa, :data_aplicacao, :vencimento, :liquidez,
                      :cnpj_emissor, coalesce(:ativo, true), :vinculo_descricao) returning id""", **p)["id"]


def movimentar(u, ativo_id, data, tipo: str, valor: float, conta_corrente_id=None, descricao=None):
    """Aporte/resgate/rendimento. Com conta corrente, aporte e resgate viram transferência no fluxo de caixa."""
    with db.transacao() as s:
        s.execute(text("insert into ativo_movimentos (ativo_id, data, tipo, valor) values (:a, :d, :t, :v)"),
                  {"a": ativo_id, "d": data, "t": tipo, "v": valor})
        if conta_corrente_id and tipo in ("aporte", "resgate"):
            inst = s.execute(text("select conta_id from ativos where id = :a"), {"a": ativo_id}).scalar()
            origem, destino = (conta_corrente_id, inst) if tipo == "aporte" else (inst, conta_corrente_id)
            s.execute(text("""insert into lancamentos (dono_id, conta_id, conta_destino_id, tipo, descricao, valor,
                                data_compra, data_vencimento, status, data_pagamento, origem, forma_pagamento)
                              values (:u, :o, :d, 'transferencia', :desc, :v, :dt, :dt, 'pago', :dt, 'manual',
                                'Transferencia')"""),
                      {"u": u["id"], "o": origem, "d": destino, "v": valor, "dt": data,
                       "desc": descricao or ("Aplicação" if tipo == "aporte" else "Resgate")})


def informar_posicao(ativo_id, data, valor_bruto: float, valor_liquido: float | None = None):
    db.executar("""insert into ativo_posicoes (ativo_id, data, valor_bruto, valor_liquido) values (:a, :d, :b, :l)
                   on conflict (ativo_id, data) do update set valor_bruto = excluded.valor_bruto,
                     valor_liquido = excluded.valor_liquido""", a=ativo_id, d=data, b=valor_bruto, l=valor_liquido)


def movimentos(ativo_id) -> pd.DataFrame:
    return db.consultar("""select data, tipo, valor from ativo_movimentos where ativo_id = :a
                           union all select data, 'posição', valor_bruto from ativo_posicoes where ativo_id = :a
                           order by data desc""", a=ativo_id)


def excluir(ativo_id):
    db.executar("delete from ativos where id = :a", a=ativo_id)


def total_hoje(u) -> float:
    a = ativos(u)
    return float(a["valor_atual"].sum()) if not a.empty else 0.0

"""Consultas e gravações. Toda função recebe o usuário logado e só devolve
o que ele pode ver (dele, ou do casal conforme a visibilidade)."""
import uuid
from datetime import date

import pandas as pd
from sqlalchemy import text

from core import db
from core.fmt import add_meses

# ---------------------------------------------------------------------------
# Escopo: "eu" = só meus registros; "nos" = meus + o que o casal compartilhou
# ---------------------------------------------------------------------------
_MEMBROS = "(select usuario_id from grupo_membros where grupo_id = :grupo)"


def _filtro_escopo(escopo: str, detalhe: bool) -> str:
    if escopo == "eu":
        return "l.dono_id = :uid"
    vis = "('compartilhado')" if detalhe else "('compartilhado','so_total')"
    return f"(l.dono_id = :uid or (l.dono_id in {_MEMBROS} and l.visibilidade_efetiva in {vis}))"


# ---------------------------------------------------------------------------
# Casal
# ---------------------------------------------------------------------------
def membros(u) -> pd.DataFrame:
    return db.consultar("""
        select u.id, u.nome, u.email, m.papel, m.entrou_em
          from grupo_membros m join usuarios u on u.id = m.usuario_id
         where m.grupo_id = :g order by m.entrou_em""", g=u["grupo_id"])


def convites(u) -> pd.DataFrame:
    return db.consultar("select email, criado_em from grupo_convites where grupo_id = :g order by criado_em",
                        g=u["grupo_id"])


def convidar(u, email: str):
    db.executar("""insert into grupo_convites (grupo_id, email, convidado_por) values (:g, :e, :u)
                   on conflict do nothing""", g=u["grupo_id"], e=email.strip().lower(), u=u["id"])


def cancelar_convite(u, email: str):
    db.executar("delete from grupo_convites where grupo_id = :g and email = :e", g=u["grupo_id"], e=email)


def grupo(u) -> dict:
    return db.um("select id, nome from grupos where id = :g", g=u["grupo_id"])


def renomear_grupo(u, nome: str):
    db.executar("update grupos set nome = :n where id = :g", n=nome, g=u["grupo_id"])


# ---------------------------------------------------------------------------
# Contas
# ---------------------------------------------------------------------------
def contas(u, so_ativas=True) -> pd.DataFrame:
    return db.consultar(f"""
        select id, nome, tipo::text as tipo, instituicao, dia_fechamento, dia_vencimento, limite,
               saldo_inicial, data_saldo_inicial, visibilidade::text as visibilidade, ativa,
               conta_debito_id, finais_cartao
          from contas where dono_id = :uid {"and ativa" if so_ativas else ""}
         order by tipo, nome""", uid=u["id"])


def salvar_conta(u, dados: dict, conta_id=None):
    campos = ["nome", "tipo", "instituicao", "dia_fechamento", "dia_vencimento", "limite",
              "saldo_inicial", "data_saldo_inicial", "visibilidade", "ativa", "conta_debito_id"]
    p = {k: dados.get(k) for k in campos} | {"uid": u["id"], "id": conta_id}
    if conta_id:
        db.executar("""update contas set nome=:nome, tipo=cast(:tipo as tipo_conta), instituicao=:instituicao,
                         dia_fechamento=:dia_fechamento, dia_vencimento=:dia_vencimento, limite=:limite,
                         saldo_inicial=coalesce(:saldo_inicial,0), data_saldo_inicial=:data_saldo_inicial,
                         visibilidade=cast(:visibilidade as visibilidade), ativa=coalesce(:ativa,true),
                         conta_debito_id=:conta_debito_id
                       where id=:id and dono_id=:uid""", **p)
    else:
        db.executar("""insert into contas (dono_id, nome, tipo, instituicao, dia_fechamento, dia_vencimento,
                         limite, saldo_inicial, data_saldo_inicial, visibilidade, ativa, conta_debito_id)
                       values (:uid, :nome, cast(:tipo as tipo_conta), :instituicao, :dia_fechamento,
                         :dia_vencimento, :limite, coalesce(:saldo_inicial,0), :data_saldo_inicial,
                         cast(:visibilidade as visibilidade), coalesce(:ativa,true), :conta_debito_id)""", **p)


# ---------------------------------------------------------------------------
# Categorias
# ---------------------------------------------------------------------------
def categorias(u, tipo: str | None = None) -> pd.DataFrame:
    """Uma linha por subcategoria (e por categoria sem filhos)."""
    return db.consultar("""
        select c.id, c.nome, c.pai_id, c.tipo::text as tipo, c.natureza_ir,
               c.visibilidade::text as visibilidade, c.ativa,
               p.nome as categoria_pai
          from categorias c left join categorias p on p.id = c.pai_id
         where c.dono_id = :uid and (cast(:tipo as text) is null or c.tipo::text = :tipo)
         order by coalesce(p.nome, c.nome), c.pai_id nulls first, c.nome""", uid=u["id"], tipo=tipo)


def salvar_categoria(u, nome, pai_id=None, tipo="despesa", natureza_ir=None, visibilidade=None, cat_id=None):
    if cat_id:
        db.executar("""update categorias set nome=:n, natureza_ir=:nat,
                         visibilidade=cast(:vis as visibilidade)
                       where id=:id and dono_id=:uid""",
                    n=nome, nat=natureza_ir, vis=visibilidade, id=cat_id, uid=u["id"])
    else:
        db.executar("""insert into categorias (dono_id, pai_id, nome, tipo, natureza_ir, visibilidade)
                       values (:uid, :pai, :n, cast(:tipo as tipo_lancamento), :nat, cast(:vis as visibilidade))""",
                    uid=u["id"], pai=pai_id, n=nome, tipo=tipo, nat=natureza_ir, vis=visibilidade)


# ---------------------------------------------------------------------------
# Lançamentos
# ---------------------------------------------------------------------------
def lancamentos(u, escopo="eu", mes_ini=None, mes_fim=None) -> pd.DataFrame:
    return db.consultar(f"""
        select l.id, l.dono_id, l.dono_nome, l.data_vencimento, l.mes_ref, l.descricao, l.valor,
               l.tipo::text as tipo, l.categoria, l.subcategoria, l.conta, l.forma_pagamento,
               l.status::text as status, l.parcela_num, l.parcela_total, l.grupo_parcela,
               l.data_compra, l.visibilidade_efetiva::text as visibilidade, l.origem::text as origem,
               l.observacao, (l.dono_id = :uid) as meu
          from v_lancamentos l
         where {_filtro_escopo(escopo, detalhe=True)}
           and (cast(:ini as int) is null or l.mes_ref >= :ini)
           and (cast(:fim as int) is null or l.mes_ref <= :fim)
           and l.status <> 'cancelado'
         order by l.data_vencimento, l.descricao""",
        uid=u["id"], grupo=u["grupo_id"], ini=mes_ini, fim=mes_fim)


def totais_por_mes(u, escopo="eu", mes_ini=None, mes_fim=None) -> pd.DataFrame:
    """Somas por mês/categoria/tipo — inclui o 'só total' do outro no escopo 'nos'."""
    return db.consultar(f"""
        select l.mes_ref, l.tipo::text as tipo, coalesce(l.categoria,'Sem categoria') as categoria,
               l.status::text as status, (l.dono_id = :uid) as meu, sum(l.valor) as valor
          from v_lancamentos l
         where {_filtro_escopo(escopo, detalhe=False)}
           and (cast(:ini as int) is null or l.mes_ref >= :ini)
           and (cast(:fim as int) is null or l.mes_ref <= :fim)
           and l.status <> 'cancelado'
         group by 1,2,3,4,5 order by 1""",
        uid=u["id"], grupo=u["grupo_id"], ini=mes_ini, fim=mes_fim)


def plano_parcelas(d: dict, parcela_inicial: int = 1, parcela_total: int = 1,
                   valor_e_total: bool = False) -> list[dict]:
    """Gera as linhas de um lançamento (1 linha) ou de uma compra parcelada.

    parcela_inicial > 1 serve para cadastrar uma compra que já está em andamento
    (ex.: hoje é a 4/10 -> cria da 4 à 10). d['data_vencimento'] é o da 1ª linha criada.
    valor_e_total=True divide d['valor'] pelo nº total de parcelas (centavos na 1ª)."""
    if parcela_total <= 1:
        return [d | {"parcela_num": None, "parcela_total": None, "grupo_parcela": None}]
    if valor_e_total:
        base = round(float(d["valor"]) / parcela_total, 2)
        resto = round(float(d["valor"]) - base * parcela_total, 2)
        valores = [base + resto if n == 1 else base for n in range(1, parcela_total + 1)]
    else:
        valores = [float(d["valor"])] * parcela_total
    grupo = uuid.uuid4()
    linhas = []
    for k, n in enumerate(range(parcela_inicial, parcela_total + 1)):
        linhas.append(d | {"valor": round(valores[n - 1], 2),
                           "data_vencimento": add_meses(d["data_vencimento"], k),
                           "parcela_num": n, "parcela_total": parcela_total, "grupo_parcela": grupo})
    return linhas


def inserir_lancamentos(u, linhas: list[dict]) -> int:
    """Grava as linhas geradas por plano_parcelas()."""
    linhas = [p | {"uid": u["id"]} for p in linhas]
    with db.transacao() as s:
        for p in linhas:
            s.execute(text("""
                insert into lancamentos (dono_id, conta_id, categoria_id, tipo, descricao, valor, data_compra,
                    data_vencimento, forma_pagamento, status, data_pagamento, parcela_num, parcela_total,
                    grupo_parcela, visibilidade, observacao, origem, comprovante_id, recorrencia_id,
                    chave_importacao)
                values (:uid, :conta_id, :categoria_id, cast(:tipo as tipo_lancamento), :descricao, :valor,
                    :data_compra, :data_vencimento, :forma_pagamento, cast(:status as status_lancamento),
                    case when :status = 'pago' then :data_vencimento end, :parcela_num, :parcela_total,
                    :grupo_parcela, cast(:visibilidade as visibilidade), :observacao,
                    cast(coalesce(:origem,'manual') as origem_registro), :comprovante_id, :recorrencia_id,
                    :chave_importacao)
                on conflict do nothing"""),
                {k: p.get(k) for k in ["uid", "conta_id", "categoria_id", "tipo", "descricao", "valor",
                                       "data_compra", "data_vencimento", "forma_pagamento", "status",
                                       "parcela_num", "parcela_total", "grupo_parcela", "visibilidade",
                                       "observacao", "origem", "comprovante_id", "recorrencia_id",
                                       "chave_importacao"]})
    return len(linhas)


def mudar_status(u, ids: list, status: str):
    db.executar("""update lancamentos
                      set status = cast(:st as status_lancamento),
                          data_pagamento = case when :st = 'pago' then coalesce(data_pagamento, current_date) end,
                          atualizado_em = now()
                    where dono_id = :uid and id = any(cast(:ids as uuid[]))""",
                st=status, uid=u["id"], ids=[str(i) for i in ids])


def excluir(u, ids: list, parcelas_futuras=False):
    ids = [str(i) for i in ids]
    if parcelas_futuras:
        db.executar("""delete from lancamentos x using lancamentos l
                        where l.id = any(cast(:ids as uuid[])) and l.dono_id = :uid
                          and x.grupo_parcela = l.grupo_parcela and x.dono_id = :uid
                          and x.data_vencimento >= l.data_vencimento""", ids=ids, uid=u["id"])
    db.executar("delete from lancamentos where dono_id = :uid and id = any(cast(:ids as uuid[]))",
                ids=ids, uid=u["id"])


def resumo_visibilidade(u) -> pd.DataFrame:
    return db.consultar("""select visibilidade_efetiva::text as visibilidade, count(*) as lancamentos,
                                  sum(valor) as valor
                             from v_lancamentos where dono_id = :uid group by 1 order by 1""", uid=u["id"])

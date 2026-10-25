"""Caixa de entrada: o que chega sozinho (Apple Pay…) e espera confirmação."""
import re
import secrets
from decimal import Decimal, InvalidOperation

import pandas as pd
from sqlalchemy import text

from core import db


def valor_de_texto(t) -> float | None:
    """'R$ 1.234,56' / '1234.56' / 'R$45' -> 1234.56 (sempre positivo)."""
    if t is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", str(t))
    if not s:
        return None
    if "," in s and "." in s:                       # 1.234,56 ou 1,234.56
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:                                  # 45,90
        s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(Decimal(s)))
    except InvalidOperation:
        return None


def token(u) -> str:
    """Token do Atalho do usuário (cria na primeira vez)."""
    r = db.um("select token_atalho from usuarios where id = :u", u=u["id"])
    if r and r["token_atalho"]:
        return r["token_atalho"]
    novo = "tk_" + secrets.token_urlsafe(18)
    db.executar("update usuarios set token_atalho = :t where id = :u", t=novo, u=u["id"])
    return novo


def novo_token(u) -> str:
    db.executar("update usuarios set token_atalho = null where id = :u", u=u["id"])
    return token(u)


def pendentes(u) -> pd.DataFrame:
    return db.consultar("""
        select c.id, c.recebido_em, c.origem, c.valor_texto, c.estabelecimento, c.cartao, c.nome
          from caixa_entrada c join usuarios us on us.token_atalho = c.token
         where us.id = :u and c.status = 'pendente'
         order by c.recebido_em desc""", u=u["id"])


def qtd_pendentes(u) -> int:
    r = db.um("""select count(*) as n from caixa_entrada c join usuarios us on us.token_atalho = c.token
                 where us.id = :u and c.status = 'pendente'""", u=u["id"])
    return int(r["n"]) if r else 0


def historico(u, limite=30) -> pd.DataFrame:
    return db.consultar("""
        select c.recebido_em, c.estabelecimento, c.valor_texto, c.cartao, c.status
          from caixa_entrada c join usuarios us on us.token_atalho = c.token
         where us.id = :u and c.status <> 'pendente'
         order by coalesce(c.tratado_em, c.recebido_em) desc limit :l""", u=u["id"], l=limite)


def sugerir_categoria(u, estabelecimento: str):
    """Última categoria usada para o mesmo estabelecimento (aprende com o uso)."""
    if not estabelecimento:
        return None
    r = db.um("""select categoria_id from lancamentos
                  where dono_id = :u and categoria_id is not null
                    and lower(descricao) = lower(:e)
                  order by criado_em desc limit 1""", u=u["id"], e=estabelecimento.strip())
    return r["categoria_id"] if r else None


def conta_do_cartao(u, cartao: str):
    if not cartao:
        return None
    r = db.um("""select id from contas where dono_id = :u and ativa
                  and lower(apelido_wallet) = lower(:c) limit 1""", u=u["id"], c=cartao.strip())
    return r["id"] if r else None


def lembrar_cartao(u, cartao: str, conta_id):
    db.executar("update contas set apelido_wallet = :c where id = :k and dono_id = :u",
                c=cartao.strip(), k=conta_id, u=u["id"])


def marcar(u, item_id, status: str, lancamento_id=None):
    db.executar("""update caixa_entrada c set status = :s, lancamento_id = :l, tratado_em = now()
                    from usuarios us
                   where c.id = :i and us.token_atalho = c.token and us.id = :u""",
                s=status, l=lancamento_id, i=item_id, u=u["id"])


def lancar(u, item_id, linhas: list[dict]):
    """Grava o(s) lançamento(s) e marca o item da caixa como lançado, numa transação só."""
    ids = []
    with db.transacao() as s:
        for p in linhas:
            r = s.execute(text("""
                insert into lancamentos (dono_id, conta_id, categoria_id, tipo, descricao, valor, data_compra,
                    data_vencimento, forma_pagamento, status, parcela_num, parcela_total, grupo_parcela,
                    visibilidade, origem)
                values (:uid, :conta_id, :categoria_id, 'despesa', :descricao, :valor, :data_compra,
                    :data_vencimento, :forma_pagamento, 'previsto', :parcela_num, :parcela_total, :grupo_parcela,
                    cast(:visibilidade as visibilidade), 'applepay')
                returning id"""), {"uid": u["id"]} | {k: p.get(k) for k in [
                    "conta_id", "categoria_id", "descricao", "valor", "data_compra", "data_vencimento",
                    "forma_pagamento", "parcela_num", "parcela_total", "grupo_parcela", "visibilidade"]})
            ids.append(r.scalar())
        s.execute(text("""update caixa_entrada c set status = 'lancado', lancamento_id = :l, tratado_em = now()
                            from usuarios us where c.id = :i and us.token_atalho = c.token and us.id = :u"""),
                  {"l": ids[0], "i": item_id, "u": u["id"]})
    return len(ids)

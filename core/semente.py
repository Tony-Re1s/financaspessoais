"""Rotinas de "primeiro acesso" que funcionam tanto no app (sessão do
st.connection) quanto em scripts (conexão SQLAlchemy pura).

Recebem qualquer objeto com .execute(text(...), params) — Session ou Connection.
"""
from sqlalchemy import text

from core.padroes import CATEGORIAS_DESPESA, CATEGORIAS_RECEITA


def garantir_categoria(cx, dono_id, nome, pai_id=None, tipo="despesa", natureza_ir=None):
    """Devolve o id da categoria (cria se não existir)."""
    row = cx.execute(text("""
        insert into categorias (dono_id, pai_id, nome, tipo, natureza_ir)
        values (:dono, :pai, :nome, cast(:tipo as tipo_lancamento), :nat)
        on conflict (dono_id, pai_id, nome) do update set nome = excluded.nome
        returning id
    """), dict(dono=dono_id, pai=pai_id, nome=nome, tipo=tipo, nat=natureza_ir)).first()
    return row[0]


def semear_categorias(cx, dono_id):
    for tipo, arvore in (("despesa", CATEGORIAS_DESPESA), ("receita", CATEGORIAS_RECEITA)):
        for cat, subs in arvore.items():
            pai = garantir_categoria(cx, dono_id, cat, None, tipo)
            for sub, nat in subs:
                garantir_categoria(cx, dono_id, sub, pai, tipo, nat)


def garantir_usuario(cx, email, nome=None):
    """Cria o usuário no 1º login, aceita convites pendentes, garante um grupo
    (casal) e as categorias padrão. Devolve dict com id, email, nome, grupo_id."""
    email = email.strip().lower()
    row = cx.execute(text("select id, nome from usuarios where email = :e"), {"e": email}).first()
    novo = row is None
    if novo:
        row = cx.execute(text("insert into usuarios (email, nome) values (:e, :n) returning id, nome"),
                         {"e": email, "n": nome}).first()
    elif nome and not row[1]:
        cx.execute(text("update usuarios set nome = :n where id = :id"), {"n": nome, "id": row[0]})
    uid = row[0]

    # convites pendentes -> vira membro do grupo de quem convidou
    cx.execute(text("""
        insert into grupo_membros (grupo_id, usuario_id, papel)
        select grupo_id, :uid, 'membro' from grupo_convites where email = :e
        on conflict do nothing
    """), {"uid": uid, "e": email})
    cx.execute(text("delete from grupo_convites where email = :e"), {"e": email})

    g = cx.execute(text("""select grupo_id from grupo_membros where usuario_id = :uid
                           order by entrou_em limit 1"""), {"uid": uid}).first()
    if g is None:
        g = cx.execute(text("insert into grupos (nome) values (:n) returning id"),
                       {"n": f"Finanças de {nome or email.split('@')[0]}"}).first()
        cx.execute(text("insert into grupo_membros (grupo_id, usuario_id, papel) values (:g, :u, 'admin')"),
                   {"g": g[0], "u": uid})

    tem_cat = cx.execute(text("select 1 from categorias where dono_id = :u limit 1"), {"u": uid}).first()
    if not tem_cat:
        semear_categorias(cx, uid)

    return {"id": uid, "email": email, "nome": nome or row[1] or email.split("@")[0], "grupo_id": g[0]}

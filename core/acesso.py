"""Quem entra no app e o que cada um pode fazer.

- Admin: e-mails em [app] admins nos Secrets (se não houver, o 1º de emails_permitidos).
  Admin pode tudo e gerencia os outros na tela "Usuários e permissões".
- Demais: convidados pelo admin dentro do app (tabela acessos), com permissões por função.
- Os dados continuam separados por dono; permissão aqui é sobre o que a pessoa pode USAR.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from core import db

# chave: (rótulo, explicação, padrão para quem é convidado)
PERMISSOES = {
    "lancar": ("Lançar gastos", "Novo lançamento, Caixa de entrada e celular (Apple Pay / Android)", True),
    "ia": ("Usar a IA", "Lançamento rápido por foto ou texto — consome os créditos da chave do admin", False),
    "patrimonio": ("Contas e patrimônio", "Contas correntes, cartões, investimentos e patrimônio", True),
    "importar": ("Importar", "Faturas de cartão e planilha", True),
    "contas_fixas": ("Contas fixas", "Cadastrar despesas e receitas que se repetem", True),
    "cadastros": ("Contas e categorias", "Criar e editar contas, cartões e categorias", True),
    "casal": ("Casal e privacidade", "Ver membros e regras de privacidade do casal", True),
}
PADRAO = {k: v[2] for k, v in PERMISSOES.items()}


def _cfg(chave, padrao=None):
    try:
        return st.secrets["app"].get(chave, padrao)
    except Exception:  # noqa: BLE001
        return padrao


def admins() -> list[str]:
    lista = _cfg("admins") or (_cfg("emails_permitidos") or [])[:1]
    return [e.strip().lower() for e in lista]


def e_admin(email: str) -> bool:
    return (email or "").strip().lower() in admins()


def situacao(email: str) -> tuple[bool, dict]:
    """(pode entrar?, permissões efetivas)."""
    email = (email or "").strip().lower()
    if e_admin(email):
        return True, {k: True for k in PERMISSOES}
    try:
        r = db.um("select ativo, permissoes from acessos where email = :e", e=email)
    except Exception:  # noqa: BLE001 — tabela ainda não criada
        r = None
    nos_secrets = email in [e.strip().lower() for e in _cfg("emails_permitidos", [])]
    if r is None:
        return nos_secrets, dict(PADRAO)
    perms = PADRAO | (r["permissoes"] if isinstance(r["permissoes"], dict) else json.loads(r["permissoes"] or "{}"))
    return bool(r["ativo"]), perms


def registrar_acesso(email: str):
    try:
        db.executar("update acessos set ultimo_acesso = now() where email = :e", e=email.strip().lower())
    except Exception:  # noqa: BLE001
        pass


def listar() -> pd.DataFrame:
    return db.consultar("""
        select a.email, u.nome, a.ativo, a.permissoes, a.criado_em, a.ultimo_acesso,
               (u.id is not null) as ja_entrou
          from acessos a left join usuarios u on u.email = a.email
         order by a.criado_em""")


def salvar(email: str, ativo: bool, permissoes: dict, por=None):
    db.executar("""insert into acessos (email, ativo, permissoes, convidado_por)
                   values (:e, :a, cast(:p as jsonb), :por)
                   on conflict (email) do update set ativo = excluded.ativo, permissoes = excluded.permissoes""",
                e=email.strip().lower(), a=ativo, p=json.dumps(permissoes), por=por)


def convidar(admin_u: dict, email: str, permissoes: dict, no_casal: bool):
    email = email.strip().lower()
    salvar(email, True, permissoes, por=admin_u["id"])
    if no_casal:
        db.executar("""insert into grupo_convites (grupo_id, email, convidado_por) values (:g, :e, :u)
                       on conflict do nothing""", g=admin_u["grupo_id"], e=email, u=admin_u["id"])


def remover(email: str):
    db.executar("delete from acessos where email = :e", e=email.strip().lower())
    db.executar("delete from grupo_convites where email = :e", e=email.strip().lower())

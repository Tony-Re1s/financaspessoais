"""Acesso ao banco (Neon Postgres) via st.connection.

A URL fica em .streamlit/secrets.toml:

    [connections.neon]
    url = "postgresql+psycopg://usuario:senha@host/banco?sslmode=require"
"""
from contextlib import contextmanager

import pandas as pd
import streamlit as st
from sqlalchemy import text


def _conn():
    # pool_pre_ping: o Neon "dorme" após 5 min sem uso; isso refaz a conexão sozinho
    return st.connection("neon", type="sql", pool_pre_ping=True, pool_recycle=240)


@contextmanager
def transacao():
    """Bloco com commit no fim (ou rollback se der erro)."""
    with _conn().session as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise


def consultar(sql: str, **params) -> pd.DataFrame:
    with _conn().session as s:
        res = s.execute(text(sql), params)
        return pd.DataFrame(res.mappings().all(), columns=list(res.keys()))


def um(sql: str, **params) -> dict | None:
    with _conn().session as s:
        row = s.execute(text(sql), params).mappings().first()
        return dict(row) if row else None


def executar(sql: str, **params) -> int:
    with transacao() as s:
        return s.execute(text(sql), params).rowcount


# (já aplicada?, comando) — a checagem evita pegar lock na tabela à toa a cada reinício
_MIGRACOES = [
    # 003 — cartão com função débito (ver db/003_cartao_debito.sql)
    ("select 1 from information_schema.columns where table_name = 'contas' and column_name = 'conta_debito_id'",
     "alter table contas add column if not exists conta_debito_id uuid references contas(id) on delete set null"),
    # 004 — finais do cartão (reconhece o cartão ao importar a fatura)
    ("select 1 from information_schema.columns where table_name = 'contas' and column_name = 'finais_cartao'",
     "alter table contas add column if not exists finais_cartao text"),
]


@st.cache_resource(show_spinner=False)
def migrar() -> bool:
    """Aplica as migrações idempotentes uma vez por processo do servidor."""
    with transacao() as s:
        for ja, cmd in _MIGRACOES:
            if s.execute(text(ja)).first() is None:
                s.execute(text(cmd))
    return True

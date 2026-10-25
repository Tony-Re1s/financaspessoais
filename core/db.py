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

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


# ---------------------------------------------------------------------------------------------
# Leituras guardadas em memória: cada clique refaz a tela inteira, e o Neon fica longe do servidor
# do app — dezenas de consultas por tela viravam 20-30 s. Qualquer gravação feita pelo app muda a
# "versão" e apaga o que estava guardado; o que muda por fora (Atalho do iPhone, console) vence em 2 min.
# ---------------------------------------------------------------------------------------------
_VERSAO = {"n": 0}
SEM_CACHE = ("caixa_entrada",)          # chega pelo celular a qualquer momento


def _mudou():
    _VERSAO["n"] += 1


@contextmanager
def transacao():
    """Bloco com commit no fim (ou rollback se der erro)."""
    with _conn().session as s:
        try:
            yield s
            s.commit()
            _mudou()
        except Exception:
            s.rollback()
            raise


def _ler(sql: str, params: dict):
    with _conn().session as s:
        res = s.execute(text(sql), params)
        return list(res.keys()), [tuple(r) for r in res.all()]


@st.cache_data(ttl=120, max_entries=3000, show_spinner=False)
def _ler_cache(sql: str, params: dict, versao: int):
    return _ler(sql, params)


def _buscar(sql: str, params: dict):
    if any(t in sql for t in SEM_CACHE) or "returning" in sql.lower():
        return _ler(sql, params)
    try:
        return _ler_cache(sql, params, _VERSAO["n"])
    except Exception:  # noqa: BLE001 — parâmetro que não dá para guardar: lê direto
        return _ler(sql, params)


def limpar_cache():
    _mudou()


def consultar(sql: str, **params) -> pd.DataFrame:
    cols, linhas = _buscar(sql, params)
    return pd.DataFrame(linhas, columns=cols)


def um(sql: str, **params) -> dict | None:
    cols, linhas = _buscar(sql, params)
    return dict(zip(cols, linhas[0])) if linhas else None


def gravar_retornando(sql: str, **params) -> dict | None:
    """INSERT/UPDATE ... RETURNING com commit (db.um() só lê, não grava)."""
    with transacao() as s:
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
    # 005 — origem 'android' (notificações lidas pelo MacroDroid)
    ("select 1 from pg_enum e join pg_type t on t.oid = e.enumtypid "
     "where t.typname = 'origem_registro' and e.enumlabel = 'android'",
     "alter type origem_registro add value if not exists 'android'"),
    # 006 — acessos: quem pode entrar e o que pode fazer (gerenciado pelo admin no app)
    ("select 1 from information_schema.tables where table_name = 'acessos'",
     """create table if not exists acessos (
          email          text primary key,
          ativo          boolean not null default true,
          permissoes     jsonb not null default '{}'::jsonb,
          convidado_por  uuid references usuarios(id) on delete set null,
          criado_em      timestamptz not null default now(),
          ultimo_acesso  timestamptz)"""),
    # 007 — cartão: de qual conta corrente sai o pagamento da fatura
    ("select 1 from information_schema.columns where table_name = 'contas' and column_name = 'conta_pagamento_id'",
     "alter table contas add column if not exists conta_pagamento_id uuid references contas(id) on delete set null"),
    # 008 — bem: categorias cujos pagamentos viram patrimônio (ex.: parcelas da construtora)
    ("select 1 from information_schema.columns where table_name = 'bens' and column_name = 'categorias_pagamento'",
     "alter table bens add column if not exists categorias_pagamento uuid[]"),
    # 009 — foto mensal do patrimônio (evolução)
    ("select 1 from information_schema.tables where table_name = 'patrimonio_mensal'",
     """create table if not exists patrimonio_mensal (
          dono_id        uuid not null references usuarios(id) on delete cascade,
          mes_ref        int not null,
          ativos         numeric(14,2) not null,
          passivos       numeric(14,2) not null,
          detalhe        jsonb,
          atualizado_em  timestamptz not null default now(),
          primary key (dono_id, mes_ref))"""),
    # 011 — cartão de benefício (VR/VA): gasto conta nas categorias, mas não no fluxo das contas nem em fatura
    ("select 1 from pg_enum e join pg_type t on t.oid = e.enumtypid "
     "where t.typname = 'tipo_conta' and e.enumlabel = 'beneficio'",
     "alter type tipo_conta add value if not exists 'beneficio'"),
    # 010 — cor escolhida pelo usuário para o cartão/conta (hex); vazio = cor do banco
    ("select 1 from information_schema.columns where table_name = 'contas' and column_name = 'cor'",
     "alter table contas add column if not exists cor text"),
]


@st.cache_resource(show_spinner=False)
def migrar() -> bool:
    """Aplica as migrações idempotentes uma vez por processo do servidor."""
    with transacao() as s:
        for ja, cmd in _MIGRACOES:
            if s.execute(text(ja)).first() is None:
                s.execute(text(cmd))
    return True

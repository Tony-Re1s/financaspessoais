-- =====================================================================
-- 002 — Caixa de entrada (Apple Pay e outras fontes automáticas)
-- Tudo que chega sozinho entra aqui como "pendente" e só vira lançamento
-- depois que o dono confirma no app.
-- O Atalho do iPhone grava com um papel do Postgres que só pode INSERIR
-- nesta tabela (criado à parte, fora do repositório, porque tem senha).
-- =====================================================================

alter type origem_registro add value if not exists 'applepay';

alter table usuarios add column if not exists token_atalho text unique;   -- identifica o dono no Atalho
alter table contas   add column if not exists apelido_wallet text;        -- nome do cartão na Carteira do iPhone

create table if not exists caixa_entrada (
  id               uuid primary key default gen_random_uuid(),
  token            text not null,                    -- token_atalho do dono
  recebido_em      timestamptz not null default now(),
  origem           text not null default 'applepay',
  valor_texto      text,                             -- como veio ("R$ 45,90")
  estabelecimento  text,
  cartao           text,                             -- nome do cartão na Carteira
  nome             text,
  extra            jsonb,
  status           text not null default 'pendente' check (status in ('pendente','lancado','ignorado')),
  lancamento_id    uuid references lancamentos(id) on delete set null,
  tratado_em       timestamptz
);
create index if not exists ix_caixa_token_status on caixa_entrada (token, status);

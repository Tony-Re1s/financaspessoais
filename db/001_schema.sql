-- =====================================================================
-- Finanças do Casal — schema completo (Postgres / Neon)
-- Rode uma vez no SQL Editor do Neon. Idempotente nos CREATEs principais.
-- Convenções:
--   * todo registro tem DONO (usuarios.id)
--   * VISIBILIDADE decide o que o outro membro do casal enxerga:
--       privado        -> só o dono
--       compartilhado  -> o outro vê o detalhe
--       so_total       -> o outro vê apenas somas (sem descrição/valor linha a linha)
--     Lançamento sem visibilidade própria herda da categoria; depois da conta;
--     na falta de tudo, é privado.
--   * valores em R$ com 2 casas (numeric(14,2)); sempre positivos —
--     o sentido vem de lancamentos.tipo (despesa/receita/transferencia).
-- =====================================================================

create extension if not exists pgcrypto;

do $$ begin
  create type visibilidade      as enum ('privado','compartilhado','so_total');
exception when duplicate_object then null; end $$;
do $$ begin
  create type tipo_conta        as enum ('conta_corrente','cartao_credito','investimento','poupanca',
                                         'fgts','previdencia','financiamento','carteira','outro');
exception when duplicate_object then null; end $$;
do $$ begin
  create type tipo_lancamento   as enum ('despesa','receita','transferencia');
exception when duplicate_object then null; end $$;
do $$ begin
  create type status_lancamento as enum ('previsto','pago','cancelado');
exception when duplicate_object then null; end $$;
do $$ begin
  create type origem_registro   as enum ('manual','importacao','camera','migracao','recorrencia','ia');
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------
-- 1. Pessoas e casal
-- ---------------------------------------------------------------------
create table if not exists usuarios (
  id            uuid primary key default gen_random_uuid(),
  email         text not null unique,
  nome          text,
  preferencias  jsonb not null default '{}'::jsonb,   -- renda, metas, perfil de risco etc.
  criado_em     timestamptz not null default now()
);

create table if not exists grupos (                    -- o "casal"
  id         uuid primary key default gen_random_uuid(),
  nome       text not null,
  criado_em  timestamptz not null default now()
);

create table if not exists grupo_membros (
  grupo_id    uuid not null references grupos(id)   on delete cascade,
  usuario_id  uuid not null references usuarios(id) on delete cascade,
  papel       text not null default 'membro' check (papel in ('admin','membro')),
  entrou_em   timestamptz not null default now(),
  primary key (grupo_id, usuario_id)
);

-- convite por e-mail: vira membro quando a pessoa fizer o 1º login
create table if not exists grupo_convites (
  grupo_id    uuid not null references grupos(id) on delete cascade,
  email       text not null,
  convidado_por uuid references usuarios(id) on delete set null,
  criado_em   timestamptz not null default now(),
  primary key (grupo_id, email)
);

-- ---------------------------------------------------------------------
-- 2. Contas, cartões, categorias
-- ---------------------------------------------------------------------
create table if not exists contas (
  id                 uuid primary key default gen_random_uuid(),
  dono_id            uuid not null references usuarios(id) on delete cascade,
  nome               text not null,
  tipo               tipo_conta not null,
  instituicao        text,
  dia_fechamento     smallint check (dia_fechamento between 1 and 31),   -- cartão
  dia_vencimento     smallint check (dia_vencimento between 1 and 31),   -- cartão
  limite             numeric(14,2),
  saldo_inicial      numeric(14,2) not null default 0,
  data_saldo_inicial date,
  visibilidade       visibilidade not null default 'privado',
  ativa              boolean not null default true,
  criado_em          timestamptz not null default now(),
  unique (dono_id, nome)
);

create table if not exists categorias (
  id            uuid primary key default gen_random_uuid(),
  dono_id       uuid not null references usuarios(id) on delete cascade,
  pai_id        uuid references categorias(id) on delete cascade,  -- null = categoria; preenchido = subcategoria
  nome          text not null,
  tipo          tipo_lancamento not null default 'despesa',
  cor           text,
  icone         text,
  natureza_ir   text check (natureza_ir in ('saude','educacao','previdencia_pgbl','pensao_alimenticia',
                                            'dependente','doacao','livro_caixa')),
  visibilidade  visibilidade,          -- null = herda da conta
  ativa         boolean not null default true,
  criado_em     timestamptz not null default now(),
  unique nulls not distinct (dono_id, pai_id, nome)
);

-- ---------------------------------------------------------------------
-- 3. Recorrências (assinaturas, aluguel, salário...) e lançamentos
-- ---------------------------------------------------------------------
create table if not exists recorrencias (
  id              uuid primary key default gen_random_uuid(),
  dono_id         uuid not null references usuarios(id) on delete cascade,
  conta_id        uuid references contas(id) on delete set null,
  categoria_id    uuid references categorias(id) on delete set null,
  tipo            tipo_lancamento not null default 'despesa',
  descricao       text not null,
  valor           numeric(14,2) not null check (valor >= 0),
  moeda           char(3) not null default 'BRL',      -- ex.: assinatura em USD
  frequencia      text not null default 'mensal' check (frequencia in ('semanal','mensal','anual')),
  dia_vencimento  smallint check (dia_vencimento between 1 and 31),
  inicio          date not null,
  fim             date,                                 -- null = sem fim
  forma_pagamento text,
  visibilidade    visibilidade,
  ativa           boolean not null default true,
  criado_em       timestamptz not null default now()
);

create table if not exists comprovantes (               -- foto do cupom (câmera) + leitura da IA
  id          uuid primary key default gen_random_uuid(),
  dono_id     uuid not null references usuarios(id) on delete cascade,
  imagem      bytea,                                     -- comprimida no app (~100 KB)
  mime        text,
  dados_ia    jsonb,                                     -- o que a IA extraiu
  criado_em   timestamptz not null default now()
);

create table if not exists lancamentos (
  id                uuid primary key default gen_random_uuid(),
  dono_id           uuid not null references usuarios(id) on delete cascade,
  conta_id          uuid references contas(id) on delete set null,
  conta_destino_id  uuid references contas(id) on delete set null,   -- só transferências
  categoria_id      uuid references categorias(id) on delete set null, -- categoria OU subcategoria
  tipo              tipo_lancamento not null default 'despesa',
  descricao         text not null,
  valor             numeric(14,2) not null check (valor >= 0),
  data_compra       date,                                -- quando a compra aconteceu
  data_vencimento   date not null,                       -- quando o dinheiro sai/entra (fatura, boleto)
  mes_ref           int generated always as
                      ((extract(year from data_vencimento))::int * 100
                       + (extract(month from data_vencimento))::int) stored,
  forma_pagamento   text,                                -- Cartao de Credito, Boleto, Debito em Conta, Pix...
  status            status_lancamento not null default 'previsto',
  data_pagamento    date,
  parcela_num       smallint,
  parcela_total     smallint,
  grupo_parcela     uuid,                                -- liga as N parcelas da mesma compra
  recorrencia_id    uuid references recorrencias(id) on delete set null,
  comprovante_id    uuid references comprovantes(id) on delete set null,
  visibilidade      visibilidade,                        -- null = herda (categoria -> conta -> privado)
  tag_ir            text,                                -- marcação manual p/ IR
  origem            origem_registro not null default 'manual',
  chave_importacao  text,                                -- evita duplicar na importação
  observacao        text,
  criado_em         timestamptz not null default now(),
  atualizado_em     timestamptz not null default now(),
  check (parcela_num is null or (parcela_total is not null and parcela_num between 1 and parcela_total))
);
create index if not exists ix_lanc_dono_mes   on lancamentos (dono_id, mes_ref);
create index if not exists ix_lanc_conta_venc on lancamentos (conta_id, data_vencimento);
create index if not exists ix_lanc_grupo_parc on lancamentos (grupo_parcela);
create unique index if not exists ux_lanc_importacao on lancamentos (dono_id, chave_importacao)
  where chave_importacao is not null;

create table if not exists importacoes (               -- histórico de faturas/extratos importados
  id                 uuid primary key default gen_random_uuid(),
  dono_id            uuid not null references usuarios(id) on delete cascade,
  conta_id           uuid references contas(id) on delete set null,
  arquivo            text,
  formato            text,                               -- itau_xlsx, nubank_csv, planilha...
  linhas_lidas       int,
  linhas_importadas  int,
  criado_em          timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 4. Orçamentos
-- ---------------------------------------------------------------------
create table if not exists orcamentos (
  id            uuid primary key default gen_random_uuid(),
  dono_id       uuid not null references usuarios(id) on delete cascade,
  categoria_id  uuid not null references categorias(id) on delete cascade,
  mes_ref       int,                                     -- null = vale para todo mês
  valor_limite  numeric(14,2) not null check (valor_limite >= 0),
  alerta_pct    smallint not null default 80 check (alerta_pct between 1 and 100),
  visibilidade  visibilidade,
  criado_em     timestamptz not null default now(),
  unique nulls not distinct (dono_id, categoria_id, mes_ref)
);

-- ---------------------------------------------------------------------
-- 5. Saldos, aplicações e patrimônio
-- ---------------------------------------------------------------------
create table if not exists saldos (                     -- foto do saldo de uma conta numa data
  id         uuid primary key default gen_random_uuid(),
  conta_id   uuid not null references contas(id) on delete cascade,
  data       date not null,
  valor      numeric(14,2) not null,
  origem     origem_registro not null default 'manual',
  criado_em  timestamptz not null default now(),
  unique (conta_id, data)
);

create table if not exists ativos (                     -- cada aplicação dentro de uma conta de investimento
  id               uuid primary key default gen_random_uuid(),
  conta_id         uuid not null references contas(id) on delete cascade,
  nome             text not null,                        -- "CDB Banco X 110% CDI"
  classe           text not null check (classe in ('renda_fixa','tesouro','fundo','acao','fii','etf',
                                                   'previdencia_pgbl','previdencia_vgbl','cripto','poupanca','outro')),
  indexador        text,                                 -- CDI, IPCA, PRE, SELIC...
  taxa             numeric(9,4),                         -- 110 (% CDI) ou 6.5 (IPCA+6,5)
  data_aplicacao   date,
  vencimento       date,
  liquidez         text,                                 -- diária, no vencimento, D+30...
  cnpj_emissor     text,                                 -- usado no IR (bens e direitos)
  ativo            boolean not null default true,
  criado_em        timestamptz not null default now()
);

create table if not exists ativo_movimentos (           -- aportes, resgates, rendimentos, IR retido
  id          uuid primary key default gen_random_uuid(),
  ativo_id    uuid not null references ativos(id) on delete cascade,
  data        date not null,
  tipo        text not null check (tipo in ('aporte','resgate','rendimento','ir_retido','taxa')),
  valor       numeric(14,2) not null,
  criado_em   timestamptz not null default now()
);

create table if not exists ativo_posicoes (             -- valor de mercado numa data
  ativo_id      uuid not null references ativos(id) on delete cascade,
  data          date not null,
  valor_bruto   numeric(14,2) not null,
  valor_liquido numeric(14,2),
  primary key (ativo_id, data)
);

create table if not exists bens (                       -- imóvel, veículo, outros bens (patrimônio e IR)
  id                 uuid primary key default gen_random_uuid(),
  dono_id            uuid not null references usuarios(id) on delete cascade,
  descricao          text not null,
  grupo_ir           text,                               -- grupo/código da ficha Bens e Direitos
  codigo_ir          text,
  data_aquisicao     date,
  valor_aquisicao    numeric(14,2),
  valor_atual        numeric(14,2),                      -- estimativa de mercado (patrimônio)
  divida_vinculada   numeric(14,2),                      -- ex.: saldo do financiamento
  visibilidade       visibilidade,
  criado_em          timestamptz not null default now()
);

create table if not exists bens_valores_ir (            -- "situação em 31/12" por ano
  bem_id   uuid not null references bens(id) on delete cascade,
  ano      int not null,
  valor    numeric(14,2) not null,
  primary key (bem_id, ano)
);

-- ---------------------------------------------------------------------
-- 6. IA (histórico de análises)
-- ---------------------------------------------------------------------
create table if not exists ia_analises (
  id          uuid primary key default gen_random_uuid(),
  dono_id     uuid not null references usuarios(id) on delete cascade,
  tipo        text not null,                             -- pergunta, projecao, previdencia, ir...
  pergunta    text,
  resposta    text,
  contexto    jsonb,
  criado_em   timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 7. Visão com a visibilidade efetiva de cada lançamento
-- ---------------------------------------------------------------------
create or replace view v_lancamentos as
select l.*,
       coalesce(l.visibilidade, c.visibilidade, cp.visibilidade, k.visibilidade, 'privado'::visibilidade)
         as visibilidade_efetiva,
       coalesce(cp.nome, c.nome) as categoria,
       case when cp.id is not null then c.nome end as subcategoria,
       k.nome  as conta,
       u.nome  as dono_nome,
       u.email as dono_email
  from lancamentos l
  left join categorias c  on c.id  = l.categoria_id
  left join categorias cp on cp.id = c.pai_id
  left join contas     k  on k.id  = l.conta_id
  join usuarios        u  on u.id  = l.dono_id;

-- =====================================================================
-- 003 — Cartão com função crédito e débito
-- Um cartão de crédito pode apontar para a conta corrente de onde sai o
-- débito (mesmo plástico na Carteira do iPhone). A Caixa de entrada usa
-- isso para lançar na fatura (crédito) ou direto na conta (débito).
-- O app aplica sozinho na primeira execução (core/db.py: migrar()).
-- =====================================================================
alter table contas add column if not exists conta_debito_id uuid references contas(id) on delete set null;

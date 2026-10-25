# 💰 Finanças do Casal

App de controle financeiro pessoal **para dois**: cada pessoa tem as suas contas e os seus lançamentos,
e escolhe o que o outro vê. Feito com **Streamlit + Neon (Postgres) + GitHub**, com login Google.

## O que já tem (Fase 1 — Fundação)

| Tela | O que faz |
|---|---|
| **Painel** | A pagar / pago no mês, comprometido no mês seguinte e nos próximos 12 meses, gráfico por categoria, vencimentos dos próximos 15 dias. Alterna **Só eu / Nós**. |
| **Novo lançamento** | Despesa ou receita, conta/cartão, categoria, **vencimento calculado pelo fechamento do cartão**, parcelado (inclusive compra já em andamento, ex. 4/10), quem vê. |
| **Lançamentos** | Filtros por período, situação, conta, categoria e busca; marcar pago, voltar a previsto, excluir (com opção de apagar as parcelas seguintes). |
| **Importar** | Sobe a planilha `Compromissos_Financeiros.xlsx` (não duplica se importar de novo). |
| **Contas e cartões** | Cadastro com dia de fechamento/vencimento, limite e visibilidade. |
| **Categorias** | Árvore categoria › subcategoria, marcação de **dedutível no IR** e visibilidade. |
| **Casal e privacidade** | Convite por e-mail e resumo do que você está mostrando. |

O banco já tem as tabelas dos próximos módulos: recorrências, orçamentos, saldos, aplicações,
bens (IR), comprovantes da câmera e histórico de análises da IA.

### Privacidade

Cada lançamento é `privado`, `compartilhado` ou `só o total`. Sem valor próprio, herda da **categoria**,
depois da **conta**; sem nada definido, é **privado**. Na visão **Nós**, o "só o total" do outro entra nas
somas e gráficos, mas não aparece linha a linha.

## Estrutura

```
app.py                  entrada: login + menu
core/
  auth.py               login Google + e-mails autorizados
  db.py                 conexão com o Neon (st.connection)
  repo.py               consultas e gravações (sempre filtradas pelo usuário)
  semente.py            1º acesso: cria usuário, casal e categorias padrão
  importar.py           importadores (planilha; depois faturas)
  padroes.py            categorias padrão, tipos de conta, rótulos
  fmt.py                R$, meses, cálculo de vencimento de fatura
telas/                  uma tela por arquivo
db/001_schema.sql       todas as tabelas
scripts/migrar_planilha.py   importação pelo terminal (opcional)
```

---

## Como colocar no ar (uma vez, ~30 min)

### 1. Banco — Neon
1. Entre em **neon.com** → *Sign up* → **Continue with GitHub**.
2. *New project*: nome `financas`, Postgres 17, região **AWS US East** (fica perto dos servidores do Streamlit Cloud).
3. No menu **SQL Editor**, cole todo o conteúdo de `db/001_schema.sql` e clique **Run**.
4. Em **Connect**, copie a *connection string*. Troque o começo `postgresql://` por **`postgresql+psycopg://`**.
   Guarde — vai nos *secrets*.

> Free do Neon: 1 GB por projeto e 100 horas de computação/mês. O banco "dorme" após 5 min sem uso e
> acorda sozinho no próximo acesso (o primeiro clique pode levar ~1 s a mais). Não pausa o projeto.

### 2. Código — GitHub
1. Crie um repositório **privado** (ex.: `financaspessoais`).
2. Suba os arquivos desta pasta (arrastar e soltar no site do GitHub funciona), **menos** `.streamlit/secrets.toml`.

### 3. Login — Google
1. **console.cloud.google.com** → crie um projeto (ex.: `financaspessoais`).
2. *APIs e serviços* → **Tela de consentimento OAuth** → tipo **Externo** → nome do app e seu e-mail.
   Em **Usuários de teste**, adicione os dois e-mails (o seu e o da outra pessoa). Deixe em modo *Teste*:
   só esses e-mails conseguem entrar.
3. *Credenciais* → **Criar credenciais → ID do cliente OAuth** → *Aplicativo da Web*.
   Em **URIs de redirecionamento autorizados**, adicione:
   - `https://SEU-APP.streamlit.app/oauth2callback`
   - `http://localhost:8501/oauth2callback` (para rodar no seu PC)
4. Copie **ID do cliente** e **Chave secreta**.

### 4. App — Streamlit Community Cloud
1. **share.streamlit.io** → *Create app* → escolha o repositório, branch `main`, arquivo `app.py`,
   e defina o endereço (ex.: `financas-tony`).
2. *Advanced settings*: Python **3.12** e, em **Secrets**, cole o conteúdo de `.streamlit/secrets.toml.example`
   preenchido (Neon, Google e e-mails). Gere o `cookie_secret` com:
   `python -c "import secrets; print(secrets.token_hex(32))"`.
3. Deploy. Como o repo é privado, o Streamlit cria o app como **privado**; vá em
   **Settings → Sharing** e deixe **público**. Quem protege é o login Google + a lista `emails_permitidos`,
   e assim você não gasta o seu único slot de app privado.

### 5. Seus dados
Entre no app → **Importar** → suba a `Compromissos_Financeiros.xlsx`. Pronto.

---

## Rodar no seu computador

```bash
python -m venv .venv && .venv\Scripts\activate          # Windows  (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # e preencha
streamlit run app.py
```
Para testar sem Google, descomente `dev_email` no `secrets.toml` **local** (nunca no Streamlit Cloud).

## Próximos módulos

1. ✅ Fundação
2. Faturas e recorrências — importar Itaú (.xlsx) e Nubank (.csv) só titular; assinaturas e salário automáticos
3. Saldos e patrimônio — saldo das contas, aplicações, FGTS, financiamento; patrimônio líquido
4. Orçamentos + câmera — limite por categoria, alerta de estouro, foto do cupom lida pela IA
5. Projeções e IA — fluxo de caixa futuro, "cabe uma previdência?", PGBL × VGBL, perguntas livres
6. Imposto de Renda — dedutíveis, bens e direitos, relatório anual

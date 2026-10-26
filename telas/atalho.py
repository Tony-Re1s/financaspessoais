from urllib.parse import urlparse

import streamlit as st

from core import caixa
from telas import _ui
from telas._comum import usuario

u = usuario()
_ui.titulo("Celular → Caixa de entrada", "📱")
st.caption("Toda compra cai sozinha na **Caixa de entrada** do app. Configura uma vez e esquece.")

try:
    url_atalho = st.secrets["atalho"]["url"]
except Exception:  # noqa: BLE001
    st.warning("Falta configurar `[atalho] url` nos Secrets do app.")
    st.stop()

host = urlparse(url_atalho).hostname
tk = caixa.token(u)

aba_ios, aba_android = st.tabs(["🍎 iPhone (Apple Pay)", "🤖 Android"])

with aba_ios:
    st.subheader("1. Crie a automação")
    st.markdown("""
    No iPhone, abra o app **Atalhos** → aba **Automação** → **+** (Nova automação) → **Transação**.
    - **Cartão**: marque todos os seus cartões da Carteira.
    - Marque **Executar Imediatamente** (e desligue *Notificar ao Executar*, se quiser).
    - Toque **Avançar** → **Nova Automação em Branco**.
    """)

    st.subheader("2. Adicione a ação “Obter Conteúdo do URL”")
    st.markdown("Busque a ação **Obter Conteúdo do URL** e preencha (toque em *Mostrar Mais*):")
    st.markdown("**URL**")
    st.code(f"https://{host}/sql", language=None)
    st.markdown("**Método:** `POST`  \n**Cabeçalhos** — adicione dois:")
    st.markdown("`Neon-Connection-String`")
    st.code(url_atalho, language=None)
    st.markdown("`Content-Type`")
    st.code("application/json", language=None)

    st.markdown("**Corpo da Solicitação:** `JSON`, com dois campos:")
    st.markdown("1) campo **Texto** chamado `query`, com este valor:")
    st.code("insert into caixa_entrada (token, valor_texto, estabelecimento, cartao, nome) "
            "values ($1, $2, $3, $4, $5)", language=None)
    st.markdown("2) campo **Matriz** chamado `params`, com **5 itens de Texto**, nesta ordem:")
    st.markdown(f"""
    | # | Item | O que colocar |
    |---|---|---|
    | 1 | seu token | `{tk}` |
    | 2 | valor | variável **Quantia** da *Entrada do Atalho* |
    | 3 | estabelecimento | variável **Estabelecimento** (*Comerciante*) |
    | 4 | cartão | variável **Cartão ou Passe** |
    | 5 | nome | variável **Nome** |
    """)
    st.caption("As variáveis aparecem tocando no campo e escolhendo *Entrada do Atalho* → toque nela de novo para "
               "escolher a propriedade (Quantia, Estabelecimento…). Os nomes podem variar um pouco conforme o iOS.")

    st.subheader("3. Teste")
    st.markdown("Pague qualquer coisa com o Apple Pay e abra a **Caixa de entrada**. "
                "Na primeira compra de cada cartão, escolha qual conta do app ele é e marque **Lembrar** — "
                "nas próximas o app já preenche sozinho.")


with aba_android:
    st.markdown("""
No Android quem faz o papel do Atalho é o app **MacroDroid** (grátis na Play Store): ele lê a notificação
de compra do banco ou da Google Carteira e manda para o app. O app separa valor, loja e cartão sozinho.
""")
    st.subheader("1. Instale e dê acesso às notificações")
    st.markdown("""
- Instale o **MacroDroid** na Play Store e abra.
- Quando pedir, permita **Acesso a notificações** (Configurações → Notificações → Acesso a notificações → MacroDroid).
- Nos apps dos bancos, deixe ligadas as **notificações de compra** (Nubank, Itaú, Inter… e a Google Carteira).
""")
    st.subheader("2. Crie a macro")
    st.markdown("""
**Adicionar macro** → em **Gatilhos** toque **+** → **Notificação** → **Notificação recebida**:
- **Aplicativos**: marque os bancos e a Google Carteira.
- **Conteúdo do texto**: *Contém* → `R$` (assim só entram notificações com valor).
""")
    st.markdown("Em **Ações** toque **+** → **Conectividade/Web** → **Requisição HTTP**:")
    st.markdown("**Método:** `POST`  \n**URL:**")
    st.code(f"https://{host}/sql", language=None)
    st.markdown("**Cabeçalhos** (Headers) — adicione dois:")
    st.markdown("`Neon-Connection-String`")
    st.code(url_atalho, language=None)
    st.markdown("`Content-Type`")
    st.code("application/json", language=None)
    st.markdown("**Corpo** (Body, tipo *texto/JSON*) — copie e cole tudo:")
    st.code('{"query": "insert into caixa_entrada (token, origem, valor_texto, estabelecimento, cartao) '
            'values ($1, \'android\', $2, $3, $4)", '
            f'"params": ["{tk}", "TEXTO", "TITULO", "APP"]}}', language="json")
    st.markdown("""
Depois troque, **mantendo as aspas**, usando o botão **…** (texto mágico / *magic text*) do MacroDroid:
- `TEXTO` → **Texto da notificação**
- `TITULO` → **Título da notificação**
- `APP` → **Nome do app da notificação**

Salve a macro com um nome (ex.: *Finanças*) e deixe ela **ativada**.
""")
    st.subheader("3. Teste")
    st.markdown("Faça uma compra e abra a **Caixa de entrada**. A notificação original aparece embaixo da compra "
                "(🔔) para você conferir. Na primeira de cada cartão, escolha qual conta do app ele é — "
                "nas próximas já vem preenchido.")
    st.caption("Se o celular economizar bateria, coloque o MacroDroid como *sem restrição de bateria*, "
               "senão ele pode parar de ler as notificações.")

with st.expander("Segurança"):
    st.markdown("""
- O atalho (iPhone ou Android) usa um usuário do banco que **só consegue inserir** na caixa de entrada — não lê nem altera nada.
- O **token** é o que liga a compra a você. Se ele vazar, gere outro (o atalho antigo para de valer).
- Nada vira lançamento sem você confirmar no app.
""")
    if st.button("Gerar novo token"):
        caixa.novo_token(u)
        st.rerun()

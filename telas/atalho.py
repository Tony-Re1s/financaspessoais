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

def _macro_android(host: str, token: str) -> str:
    """Macro do MacroDroid (formato de exportação): notificação da carteira com "R$" → POST no Neon.
    O cabeçalho com a conexão fica de fora — a pessoa cola pelo app (o formato dos cabeçalhos varia)."""
    import json
    import random
    corpo = json.dumps({"query": "insert into caixa_entrada (token, origem, valor_texto, estabelecimento, cartao) "
                                 "values ($1, 'android', $2, $3, $4)",
                        "params": [token, "[notification]", "[notification_title]", "[app_name]"]},
                       ensure_ascii=False)
    gid = lambda: random.randint(-2**62, 2**62)  # noqa: E731
    req = {"allFilesAccessPath": "", "allowAnyCertificate": False, "basicAuthEnabled": False,
           "basicAuthPassword": "", "basicAuthUsername": "", "blockNextAction": False, "clientCertEnabled": False,
           "clientCertKeyStoreDisplayName": "", "clientCertKeyStoreUri": "", "clientCertPassword": "",
           "contentBodyDynamicFileName": "", "contentBodyFileDisplayName": "", "contentBodyFileUri": "",
           "contentBodyFolderDisplayName": "", "contentBodyFolderUri": "", "contentBodySource": 0,
           "contentBodyText": corpo, "contentType": "application/json", "followRedirects": True,
           "headerParams": [], "localFileUri": "", "maxTotalDurationSeconds": 3600, "prettifyJson": False,
           "proxyEnabled": False, "proxyHost": "", "proxyPort": 8080, "proxyType": 0, "queryParams": [],
           "requestTimeOutSeconds": 30, "requestType": 1, "saveResponseAllFilesAccessPath": "",
           "saveResponseFileName": "", "saveResponseFolderPathDisplayName": "", "saveResponseFolderPathUri": "",
           "saveResponseType": 0, "saveResponseUseAllFilesAccess": False, "saveReturnCodeToVariable": False,
           "saveReturnHeadersToVariable": False, "urlToOpen": f"https://{host}/sql", "useAllFilesAccess": False,
           "useLocalFileUri": False, "useStaticContentBodyFile": True}
    macro = {"aiGenerated": 0, "breakpoints": [], "disabledTimestamp": 0, "exportedActionBlocks": [],
             "exportedSharedScenes": [], "forceEvenIfNotEnabledTimestamp": 0, "isActionBlock": False,
             "isExtra": False, "isFavourite": False, "lastEditedTimestamp": 0, "localVariableSeparators": [],
             "localVariables": [], "localVarsAlphabetical": True, "loggingLevel": 0, "m_GUID": gid(),
             "m_actionList": [{"requestConfig": req, "disableLogging": False, "m_SIGUID": gid(),
                               "m_classType": "HttpRequestAction", "m_constraintList": [], "m_isDisabled": False,
                               "m_isOrCondition": False}],
             "m_category": "Finanças", "m_completed": True, "m_constraintList": [], "m_description":
                 "Manda as compras por aproximação para a Caixa de entrada do app de finanças.",
             "m_descriptionOpen": False, "m_enabled": True, "m_excludeLog": False, "m_headingColor": 0,
             "m_isOrCondition": False, "m_name": "Finanças · aproximação",
             "m_triggerList": [{"enableRegex": False, "ignoreCase": True,
                                "m_applicationNameList": ["Carteira do Google", "Samsung Wallet"],
                                "m_exactMatch": False, "m_excludeApps": False, "m_excludes": False,
                                "m_ignoreOngoing": True, "m_option": 0,
                                "m_packageNameList": ["com.google.android.apps.walletnfcrel",
                                                      "com.samsung.android.spay"],
                                "m_soundOption": 0, "m_supressMultiples": True, "m_textContent": "R$",
                                "matchOptionMessage": 0, "matchOptionTitle": 0, "separateTitleAndMessage": False,
                                "disableLogging": False, "m_SIGUID": gid(), "m_classType": "NotificationTrigger",
                                "m_constraintList": [], "m_isDisabled": False, "m_isOrCondition": False}]}
    return json.dumps({"globalVariables": [], "macro": macro, "macroExportVersion": 1},
                      ensure_ascii=False, separators=(",", ":"))


aba_ios, aba_android = st.tabs(["🍎 iPhone (Apple Pay)", "🤖 Android"])

with aba_ios:
    st.markdown("""
Funciona **mesmo sem internet** na hora do pagamento: cada compra é guardada num arquivo no iPhone e enviada
quando der — na próxima compra com rede ou no horário programado. Se chegar duas vezes, o app descarta a repetição.
São **dois atalhos** e **duas automações**.
""")

    st.subheader("1. Atalho “Finanças · Enviar”")
    st.markdown("""
Abra o app **Atalhos** → aba **Atalhos** → **+** → nome **Finanças · Enviar**. Adicione, nesta ordem:

**a) Obter Arquivo** — toque em *Mostrar Mais*: **Serviço** `Atalhos (iCloud Drive)`, **Caminho do Arquivo**
`financas-pendentes.txt`, **Mostrar Seletor de Documento** desligado, **Erro Se Não Encontrado** desligado.

**b) Se** → `Arquivo` **não tem valor** → dentro do *Se*: **Parar Este Atalho**. (Apague o *Caso contrário*.)

**c) Obter Conteúdo do URL** (depois do *Fim do Se*) — toque em *Mostrar Mais*:
""")
    st.markdown("**URL**")
    st.code(f"https://{host}/sql", language=None)
    st.markdown("**Método:** `POST`  \n**Cabeçalhos** — adicione dois:")
    st.markdown("`Neon-Connection-String`")
    st.code(url_atalho, language=None)
    st.markdown("`Content-Type`")
    st.code("application/json", language=None)
    st.markdown("**Corpo da Solicitação:** `JSON`, com dois campos:")
    st.markdown("1) campo **Texto** chamado `query`, com este valor (copie inteiro):")
    st.code(caixa.SQL_ATALHO_FILA, language=None)
    st.markdown("2) campo **Matriz** chamado `params`, com **2 itens de Texto**, nesta ordem:")
    st.markdown(f"""
    | # | Item | O que colocar |
    |---|---|---|
    | 1 | seu token | `{tk}` |
    | 2 | compras | a variável **Arquivo** (da ação *Obter Arquivo*) |
    """)
    st.markdown("""
**d) Apagar Arquivos** → `Arquivo` — *Mostrar Mais*: **Perguntar Imediatamente** desligado.

Se o envio falhar (sem internet), o atalho para no passo *c* e o arquivo fica guardado para a próxima vez.
""")

    st.subheader("2. Automação de compra")
    st.markdown("""
Aba **Automação** → **+** → **Transação**: marque todos os cartões da Carteira, **Executar Imediatamente**
ligado, *Notificar ao Executar* desligado → **Avançar** → **Nova Automação em Branco**. Adicione:

**a) Texto** — uma linha só, com cinco variáveis da *Entrada do Atalho* separadas por **ponto e vírgula**:
""")
    st.code("Data;Quantia;Estabelecimento;Cartão ou Passe;Nome", language=None)
    st.caption("Toque no campo → *Entrada do Atalho* → toque nela de novo para escolher a propriedade (Data, "
               "Quantia, Estabelecimento, Cartão ou Passe, Nome). Na variável **Data**, toque nela e em "
               "**Formato de Data** escolha *Personalizado* com `yyyy-MM-dd HH:mm` — assim a compra entra com a hora "
               "certa mesmo que só seja enviada no dia seguinte.")
    st.markdown("""
**b) Anexar ao Arquivo de Texto** → o `Texto` acima — *Mostrar Mais*: **Serviço** `Atalhos (iCloud Drive)`,
**Caminho do Arquivo** `financas-pendentes.txt`, **Criar Nova Linha** ligado.

**c) Executar Atalho** → `Finanças · Enviar`.
""")

    st.subheader("3. Automação de horário (esvazia a fila)")
    st.markdown("""
Aba **Automação** → **+** → **Hora do Dia** → ex.: **20:00**, *Diariamente*, **Executar Imediatamente** →
**Avançar** → ação **Executar Atalho** → `Finanças · Enviar`. Se quiser, crie outra igual para as 12:00.
""")

    st.subheader("4. Teste")
    st.markdown("Pague qualquer coisa com o Apple Pay e abra a **Caixa de entrada**. Para testar o modo offline, "
                "ligue o modo avião, pague, desligue e rode o atalho **Finanças · Enviar** na mão: a compra aparece. "
                "Na primeira compra de cada cartão, escolha qual conta do app ele é e marque **Lembrar**.")
    with st.expander("Já tinha a automação antiga (uma ação só)?"):
        st.markdown("Ela continua funcionando, mas perde a compra quando não há internet. Troque pela versão acima: "
                    "apague a automação antiga e crie as duas novas.")


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
    st.subheader("2. Baixe a macro pronta")
    st.markdown("""
A macro já vem com o **seu token** e lê as compras por **aproximação** (Google Carteira e Samsung Wallet).
1. Toque em **Baixar macro** e abra o arquivo com o **MacroDroid** (ou no MacroDroid: **☰ → Exportar/Importar → Importar**).
2. Abra a macro → toque na ação **Requisição HTTP** → **Configurar** → deslize as abas até **Cabeçalhos** → **+**:
   - **Nome:** `Neon-Connection-String`
   - **Valor:** copie a caixa abaixo.
3. Toque no **✓** e deixe a macro **ativada**.
""")
    st.download_button("Baixar macro", _macro_android(host, tk), file_name="Financas_Aproximacao.macro",
                       mime="application/json", icon=":material/download:", type="primary")
    st.caption("Valor do cabeçalho `Neon-Connection-String`:")
    st.code(url_atalho, language=None)
    st.caption("A macro é sua: o token dentro dela manda as compras para a **sua** Caixa de entrada. "
               "Para outra pessoa, ela baixa aqui logada na conta dela.")
    with st.expander("Prefere montar à mão, ou quer pegar também as notificações dos bancos?"):
        st.markdown("""
**Adicionar macro** → em **Gatilhos** toque **+** → **Notificação** → **Notificação recebida**. Na janela que abre:
- **Aplicativos**: toque no quadradinho de **grade** ao lado de *Todos os aplicativos* e marque só os bancos
  e a Google Carteira (Nubank, Itaú, Santander, Mercado Pago, Neon, Carrefour…). Deixar *todos* faz entrar
  mensagem de WhatsApp com "R$". *Quer só as compras por aproximação?* Marque **só a carteira** que você usa
  para pagar (Google Carteira ou Samsung Wallet).
- **Usar filtros de título e texto diferentes**: deixe **desmarcado**.
- **Conteúdo do texto**: marque **Contém** e em *Texto a ser correspondido* escreva `R$`
  (assim só entram notificações com valor).
- **Ativar correspondência de expressão regular**: desmarcado.
- **Ignorar maiúsculas/minúsculas**: marcado.
- **Ignorar notificações em curso**: **marcado** (pula aquelas notificações fixas de "app em execução").
- **Impedir múltiplos disparos**: **marcado** (a mesma compra não entra duas vezes).
- **Som da notificação**: *Qualquer*. Toque **OK**.

*Android 15 ou mais novo:* se a macro não disparar, desligue **Notificações aprimoradas** em
Configurações → Notificações — ela pode esconder o texto das notificações de outros apps.
""")
        st.markdown("Em **Ações** toque **+** → **Interação Web** → **Requisição HTTP** (em versões antigas fica em *Conectividade*):")
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

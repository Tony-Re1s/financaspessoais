import streamlit as st

from core import assistente as ass
from core import ia
from telas import _ui
from telas._comum import usuario

u = usuario()
_ui.titulo("Assistente IA", "✨", sub="Converse sobre o seu dinheiro: como está o mês, quanto guardar, onde cortar. "
                                     "A IA consulta os seus números no app antes de responder.")

if not ia.chave():
    st.warning("Falta a chave da IA. No Streamlit Cloud: **Settings › Secrets** e acrescente:")
    st.code('[anthropic]\napi_key = "sk-ant-..."\n# opcional:\n# modelo_analise = "claude-sonnet-5-5"', language="toml")
    st.caption("A chave fica só nos Secrets do app — nunca no código nem no banco.")
    st.stop()

PRONTAS = {
    "📊 Análise do mês": "Faça uma análise completa do meu mês atual: entradas, saídas, faturas, como estou em "
                        "relação ao orçamento e à média dos últimos 3 meses, e o que merece atenção.",
    "🎯 Quanto ainda posso gastar": "Quanto ainda posso gastar até o fim deste mês sem ficar no negativo nem "
                                   "estourar o orçamento? Quebre por dia e pelas categorias que mais pesam.",
    "💰 Quanto guardar": "Quanto consigo guardar por mês de forma realista? Olhe o fluxo de caixa dos próximos 6 "
                        "meses (salário, contas fixas, parcelas, faturas) e sugira um valor e uma data.",
    "✂️ Onde cortar": "Onde dá para economizar? Compare os gastos por categoria e subcategoria dos últimos 3 meses, "
                     "mostre assinaturas e gastos recorrentes e diga quanto daria para cortar em cada um.",
    "🔮 Próximos meses": "Como ficam os próximos 6 meses? Mostre o saldo previsto no fim de cada mês e os meses "
                        "apertados, e o que fazer antes deles.",
    "🏠 Patrimônio": "Analise meu patrimônio: o que tenho, o que devo, o apartamento, investimentos e reserva de "
                    "emergência. Como evoluir nos próximos 12 meses?",
}

st.session_state.setdefault("_ia_hist", [])
st.session_state.setdefault("_ia_chat", [])

topo = st.columns([4, 1], vertical_alignment="center")
with topo[0]:
    escolha = st.pills("Análises prontas", list(PRONTAS), key="ia_pronta", label_visibility="collapsed")
with topo[1]:
    if st.session_state["_ia_chat"] and st.button("🧹 Nova conversa", use_container_width=True):
        st.session_state["_ia_hist"], st.session_state["_ia_chat"] = [], []
        st.session_state.pop("ia_pronta", None)
        st.rerun()

for m in st.session_state["_ia_chat"]:
    with st.chat_message(m["role"], avatar="✨" if m["role"] == "assistant" else "🙂"):
        st.markdown(m["texto"])
        if m.get("fontes"):
            st.caption("Consultou: " + ", ".join(m["fontes"]))

if not st.session_state["_ia_chat"]:
    st.caption("Exemplos: “quanto gastei com mercado em setembro?”, “o que vence semana que vem?”, "
               "“dá para antecipar a parcela anual do apê em dezembro?”")

pergunta = st.chat_input("Pergunte sobre suas finanças…")
if escolha and not pergunta and st.session_state.get("_ia_ultima_pronta") != escolha:
    pergunta = PRONTAS[escolha]
st.session_state["_ia_ultima_pronta"] = escolha

if pergunta:
    st.session_state["_ia_chat"].append({"role": "user", "texto": pergunta})
    with st.chat_message("user", avatar="🙂"):
        st.markdown(pergunta)
    hist = st.session_state["_ia_hist"] + [{"role": "user", "content": pergunta}]
    usadas = []
    with st.chat_message("assistant", avatar="✨"):
        with st.status("Consultando seus números…", expanded=False) as stt:
            def _ao_usar(nome, _args):
                rot = ass.ROTULOS.get(nome, nome)
                if rot not in usadas:
                    usadas.append(rot)
                stt.update(label=f"Consultando: {', '.join(usadas)}…")
            try:
                texto, hist = ass.conversar(u, hist, _ao_usar)
                stt.update(label="Pronto" + (f" · consultou {', '.join(usadas)}" if usadas else ""), state="complete")
            except Exception as e:  # noqa: BLE001
                stt.update(label="Não consegui responder", state="error")
                texto, hist = f"⚠️ {e}", st.session_state["_ia_hist"]
        st.markdown(texto)
    # guarda o histórico (corta o começo se ficar grande, sempre numa pergunta do usuário)
    while len(hist) > 40:
        hist = hist[1:]
        while hist and not (hist[0]["role"] == "user" and isinstance(hist[0]["content"], str)):
            hist = hist[1:]
    st.session_state["_ia_hist"] = hist
    st.session_state["_ia_chat"].append({"role": "assistant", "texto": texto, "fontes": usadas})

st.caption("As respostas são análises para te ajudar a planejar — confira os números nas telas do app. "
           "A IA só lê os dados; não grava nada.")

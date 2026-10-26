import streamlit as st

from core import db
from core.fmt import brl
from core.importar import importar_planilha_compromissos
from telas._comum import usuario

u = usuario()
st.title("Importar planilha")

st.subheader("Planilha de compromissos")
st.caption("A `Compromissos_Financeiros.xlsx` (aba **Compromissos**). Cria os cartões, as categorias "
           "que faltarem e os lançamentos como *previstos*. Pode importar de novo: o que já existe não duplica.")
arq = st.file_uploader("Arquivo .xlsx", type=["xlsx"], key="up_planilha")
if arq and st.button("Importar planilha", type="primary", icon=":material/upload:"):
    try:
        with db.transacao() as s:
            r = importar_planilha_compromissos(s, u["id"], arq, arq.name)
        st.success(f"{r['lidas']} linhas lidas · **{r['novas']} lançamentos novos** · "
                   f"{r['contas']} contas · total da planilha {brl(r['total'])}")
    except Exception as e:  # noqa: BLE001
        st.error(f"Não consegui importar: {e}")

st.page_link("telas/importar_fatura.py", label="Importar fatura de cartão", icon=":material/credit_card:")

hist = db.consultar("""select criado_em, arquivo, formato, linhas_lidas, linhas_importadas
                         from importacoes where dono_id = :u order by criado_em desc limit 20""", u=u["id"])
if not hist.empty:
    st.subheader("Histórico")
    st.dataframe(hist, hide_index=True, use_container_width=True,
                 column_config={"criado_em": st.column_config.DatetimeColumn("Quando", format="DD/MM/YYYY HH:mm"),
                                "arquivo": "Arquivo", "formato": "Formato",
                                "linhas_lidas": "Lidas", "linhas_importadas": "Novas"})

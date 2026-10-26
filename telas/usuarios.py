import json

import pandas as pd
import streamlit as st

from core import acesso
from telas import _ui
from telas._comum import usuario

u = usuario()
_ui.titulo("Usuários e permissões", "🛡️")
if not u.get("admin"):
    st.error("Só o administrador acessa esta tela.")
    st.stop()

st.caption(f"Você é o administrador ({', '.join(acesso.admins())}): pode tudo e decide o que cada pessoa "
           "convidada pode usar. Os **dados** continuam separados — cada um só vê o próprio e o que o outro "
           "compartilhar (em *Casal e privacidade*).")

if msg := st.session_state.pop("_ok_usu", None):
    st.success(msg, icon=":material/check_circle:")

ROT = {k: v[0] for k, v in acesso.PERMISSOES.items()}

# --- convidar ---------------------------------------------------------------------------------
with st.expander("➕ Convidar pessoa", expanded=False):
    with st.form("convidar", clear_on_submit=True):
        email = st.text_input("E-mail (conta Google)", placeholder="nome@gmail.com")
        no_casal = st.toggle("Entra no meu casal", value=True,
                             help="Vocês passam a se ver na visão “Nós” — só o que cada um marcar como "
                                  "compartilhado. Desligado: a pessoa usa o app sozinha.")
        st.markdown("**O que pode usar**")
        cols = st.columns(2)
        escolhas = {k: cols[i % 2].checkbox(rot, value=acesso.PADRAO[k], help=acesso.PERMISSOES[k][1])
                    for i, (k, rot) in enumerate(ROT.items())}
        if st.form_submit_button("Convidar", type="primary"):
            e = email.strip().lower()
            if "@" not in e or "." not in e.split("@")[-1]:
                st.error("E-mail inválido.")
            elif acesso.e_admin(e):
                st.error("Esse e-mail já é administrador.")
            else:
                acesso.convidar(u, e, escolhas, no_casal)
                st.session_state["_ok_usu"] = (f"**{e}** convidado. Falta um passo no Google — veja o aviso abaixo.")
                st.rerun()

st.info("**Para a pessoa conseguir entrar com o Google:** enquanto o app de login estiver em modo *teste*, "
        "o e-mail dela precisa estar em **Google Cloud → APIs e serviços → Tela de consentimento OAuth → "
        "Usuários de teste**. Sem isso o Google bloqueia antes de chegar aqui.", icon=":material/info:")

# --- lista e edição --------------------------------------------------------------------------
df = acesso.listar()
if df.empty:
    st.caption("Ninguém convidado ainda.")
    st.stop()

linhas = []
for r in df.itertuples():
    p = r.permissoes if isinstance(r.permissoes, dict) else json.loads(r.permissoes or "{}")
    p = acesso.PADRAO | p
    linhas.append({"email": r.email, "nome": r.nome or "", "ativo": bool(r.ativo),
                   "situacao": ("✅ já entrou" if r.ja_entrou else "⏳ ainda não entrou"),
                   **{k: bool(p.get(k)) for k in ROT}})
tab = pd.DataFrame(linhas)

st.subheader("Pessoas")
cfg = {"email": st.column_config.TextColumn("E-mail", disabled=True),
       "nome": st.column_config.TextColumn("Nome", disabled=True),
       "situacao": st.column_config.TextColumn("Situação", disabled=True),
       "ativo": st.column_config.CheckboxColumn("Acesso", help="Desmarque para bloquear a entrada")}
cfg |= {k: st.column_config.CheckboxColumn(rot, help=acesso.PERMISSOES[k][1]) for k, rot in ROT.items()}
ed = st.data_editor(tab, hide_index=True, use_container_width=True, column_config=cfg, key="ed_acessos",
                    column_order=["email", "situacao", "ativo", *ROT])
mudou = not ed.equals(tab)
if st.button("Salvar alterações", type="primary", disabled=not mudou, icon=":material/save:"):
    for r in ed.to_dict("records"):
        acesso.salvar(r["email"], bool(r["ativo"]), {k: bool(r[k]) for k in ROT})
    st.cache_data.clear()      # vale na hora (permissões ficam em cache de 1 min)
    st.session_state["_ok_usu"] = "Permissões salvas — valem em até 1 minuto para a pessoa."
    st.rerun()

with st.expander("Remover pessoa"):
    alvo = st.selectbox("Quem", list(tab["email"]), index=None, placeholder="Escolha")
    st.caption("Tira o acesso e o convite. Os lançamentos que a pessoa já fez continuam guardados (são dela).")
    if st.button("Remover", disabled=alvo is None):
        acesso.remover(alvo)
        st.cache_data.clear()
        st.session_state["_ok_usu"] = f"{alvo} removido."
        st.rerun()

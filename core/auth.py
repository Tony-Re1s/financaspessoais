"""Login com Google (st.login) + lista de e-mails autorizados."""
import streamlit as st

from core import acesso, db
from core.semente import garantir_usuario


def _cfg(chave, padrao=None):
    try:
        return st.secrets["app"].get(chave, padrao)
    except (KeyError, FileNotFoundError):
        return padrao


def _segredo(*caminho):
    """Lê st.secrets[a][b]... sem quebrar se não existir."""
    try:
        v = st.secrets
        for k in caminho:
            v = v[k]
        return v
    except Exception:  # noqa: BLE001 — secrets ausentes/arquivo inexistente
        return None


EXIGIDOS = [("app", "emails_permitidos"), ("connections", "neon", "url"),
            ("auth", "redirect_uri"), ("auth", "cookie_secret"), ("auth", "client_id"),
            ("auth", "client_secret"), ("auth", "server_metadata_url")]


def _checar_configuracao():
    """Se faltar algo nos Secrets, mostra o que é em vez de um erro técnico."""
    if _cfg("dev_email"):
        exigidos = [e for e in EXIGIDOS if e[0] != "auth"]
    else:
        exigidos = EXIGIDOS
    faltando = [".".join(c) for c in exigidos if not _segredo(*c)]
    if faltando:
        st.title("💰 Finanças — falta configurar")
        st.warning("O app está no ar, mas ainda faltam itens nos **Secrets** "
                   "(Manage app → ⋮ → Settings → Secrets):")
        st.markdown("\n".join(f"- `{f}`" for f in faltando))
        st.stop()


def _tela_login():
    st.markdown("<div style='height:12vh'></div>", unsafe_allow_html=True)
    _, meio, _ = st.columns([1, 2, 1])
    with meio:
        st.title("💰 Finanças")
        st.caption("Controle financeiro do casal — cada um com o seu, juntos no que quiserem.")
        st.button("Entrar com Google", type="primary", icon=":material/login:",
                  on_click=st.login, use_container_width=True)
    st.stop()


def exigir_login() -> dict:
    """Garante usuário logado e autorizado. Devolve dict do usuário."""
    if "usuario" in st.session_state:
        return st.session_state["usuario"]
    _checar_configuracao()

    dev_email = _cfg("dev_email")          # só para rodar local; nunca no Streamlit Cloud
    if dev_email:
        email, nome = dev_email, _cfg("dev_nome")
    else:
        if not st.user.get("is_logged_in", False):
            _tela_login()
        email, nome = st.user.get("email"), st.user.get("name")

    pode, _ = acesso.situacao(email)
    if not email or not pode:
        st.error(f"O e-mail **{email}** não tem acesso a este app. Peça ao administrador para convidar você.")
        st.button("Sair", on_click=st.logout)
        st.stop()

    with db.transacao() as s:
        usuario = garantir_usuario(s, email, nome)
    usuario["admin"] = acesso.e_admin(email)
    try:
        usuario["foto"] = None if dev_email else st.user.get("picture")
    except Exception:  # noqa: BLE001
        usuario["foto"] = None
    acesso.registrar_acesso(email)
    st.session_state["usuario"] = usuario
    return usuario


@st.cache_data(ttl=60, show_spinner=False)
def permissoes(email: str) -> tuple[bool, dict]:
    """Relida a cada minuto: o que o admin muda vale sem a pessoa sair e entrar."""
    return acesso.situacao(email)


def sair():
    st.session_state.clear()
    if not _cfg("dev_email"):
        st.logout()

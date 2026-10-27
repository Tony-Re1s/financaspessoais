"""Finanças do Casal — ponto de entrada.

Rodar local:  streamlit run app.py
"""
import streamlit as st

from core import auth, caixa, db, recorrencias
from core.fmt import hoje
from telas import _ui
from telas._comum import CSS, e_celular

_OLHO_JS = __import__("pathlib").Path(__file__).parent / "static" / "olho.js"

st.set_page_config(page_title="Finanças", page_icon="💰", layout="wide",
                   initial_sidebar_state="auto")
st.markdown(CSS, unsafe_allow_html=True)
_ui.css()
_ST = __import__("pathlib").Path(__file__).parent / "static"
st.logo(str(_ST / "marca.svg"), size="large", icon_image=str(_ST / "marca-icone.svg"))

db.migrar()
usuario = auth.exigir_login()
ativo, perm = auth.permissoes(usuario["email"])
if not ativo:
    st.session_state.clear()
    st.error("Seu acesso foi desativado pelo administrador.")
    st.button("Sair", on_click=auth.sair)
    st.stop()
usuario["permissoes"] = perm
usuario.setdefault("admin", auth.acesso.e_admin(usuario["email"]))
if "foto" not in usuario:   # foto do Google (sessões abertas antes desta versão também)
    try:
        usuario["foto"] = st.user.get("picture")
    except Exception:  # noqa: BLE001
        usuario["foto"] = None   # sessões abertas antes desta versão

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _completar_fixas(uid, dia):
    """Uma vez por dia: completa as contas fixas até 12 meses à frente."""
    return recorrencias.gerar({"id": uid})


try:
    _completar_fixas(usuario["id"], hoje())
except Exception:  # noqa: BLE001 — nunca impede o app de abrir
    pass

try:
    n_caixa = caixa.qtd_pendentes(usuario)
except Exception:  # noqa: BLE001 — tabela ainda não criada
    n_caixa = 0

def _p(perm, *args, **kw):
    """Página só entra no menu se a pessoa tiver a permissão (None = todos)."""
    return st.Page(*args, **kw) if perm is None or perm == "admin" and usuario["admin"] \
        or perm != "admin" and perm_ok(perm) else None


def perm_ok(chave):
    return usuario["admin"] or usuario["permissoes"].get(chave, False)


paginas = {
    "Visão geral": [
        _p(None, "telas/painel.py", title="Painel", icon=":material/dashboard:", default=True),
        _p(None, "telas/orcamentos.py", title="Orçamentos", icon=":material/track_changes:"),
        _p(None, "telas/assistente.py", title="Assistente IA", icon=":material/auto_awesome:"),
        _p(None, "telas/imposto_renda.py", title="Imposto de Renda", icon=":material/receipt_long:"),
    ],
    "Movimento": [
        _p("lancar", "telas/caixa_entrada.py", title=f"Caixa de entrada{f' ({n_caixa})' if n_caixa else ''}",
           icon=":material/inbox:"),
        _p("ia", "telas/lancamento_rapido.py", title="Lançamento rápido", icon=":material/photo_camera:"),
        _p("lancar", "telas/novo_lancamento.py", title="Novo lançamento", icon=":material/add_circle:"),
        _p(None, "telas/lancamentos.py", title="Lançamentos", icon=":material/receipt_long:"),
        _p("contas_fixas", "telas/contas_fixas.py", title="Contas fixas", icon=":material/event_repeat:"),
    ],
    "Contas e patrimônio": [
        _p("patrimonio", "telas/contas_correntes.py", title="Contas correntes", icon=":material/account_balance_wallet:"),
        _p("patrimonio", "telas/cartoes.py", title="Cartões de crédito", icon=":material/credit_card:"),
        _p("patrimonio", "telas/beneficios.py", title="Benefícios (VR/VA)", icon=":material/restaurant:"),
        _p("patrimonio", "telas/investimentos.py", title="Investimentos", icon=":material/trending_up:"),
        _p("patrimonio", "telas/patrimonio.py", title="Patrimônio", icon=":material/savings:"),
    ],
    "Importar": [
        _p("importar", "telas/importar_extrato.py", title="Extrato de conta", icon=":material/account_balance:"),
        _p("importar", "telas/importar_fatura.py", title="Fatura de cartão", icon=":material/receipt:"),
        _p("importar", "telas/importar.py", title="Planilha", icon=":material/upload_file:"),
    ],
    "Cadastros": [
        _p("cadastros", "telas/contas.py", title="Contas e cartões", icon=":material/account_balance:"),
        _p("cadastros", "telas/categorias.py", title="Categorias", icon=":material/category:"),
        _p("casal", "telas/casal.py", title="Casal e privacidade", icon=":material/group:"),
        _p("lancar", "telas/atalho.py", title="Celular (iPhone e Android)", icon=":material/smartphone:"),
        _p("admin", "telas/usuarios.py", title="Usuários e permissões", icon=":material/admin_panel_settings:"),
    ],
}
paginas = {grupo: [p for p in lista if p is not None] for grupo, lista in paginas.items()}
paginas = {grupo: lista for grupo, lista in paginas.items() if lista}

nav = st.navigation(paginas, expanded=True)

# --- olho: esconder/mostrar valores — tudo no navegador (instantâneo), lembra a escolha no aparelho ---
with st.container(key="olhojs"):
    st.html(f"<script>{_OLHO_JS.read_text(encoding='utf-8')}</script>", unsafe_allow_javascript=True)

with st.sidebar:
    with st.container(key="perfil"):
        _nome = usuario.get("nome") or usuario["email"]
        _ui.render(f"""<div class="ui-perfil">{_ui.avatar(usuario, 38)}
            <div style="min-width:0"><div class="n">{_ui.esc(_nome)}{'<span class="adm">admin</span>' if usuario['admin'] else ''}</div>
            <div class="e">{_ui.esc(usuario['email'])}</div></div></div>""")
        st.toggle("📱 Layout de celular", value=e_celular(), key="modo_celular")
        st.button("Sair", icon=":material/logout:", on_click=auth.sair, use_container_width=True)

nav.run()

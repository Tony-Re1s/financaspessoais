import hashlib

import pandas as pd
import streamlit as st

from core import faturas, leitores, repo
from core.fmt import brl
from telas import _ui
from telas._comum import cartoes_kpi, col_rs, e_celular, em_reais, opcoes_categoria, usuario

u = usuario()
_ui.titulo("Importar fatura", "💳")

if msg := st.session_state.pop("_ok_fat", None):
    st.success(msg, icon=":material/check_circle:")

with st.expander("Bancos que o app já lê"):
    st.markdown("\n".join(f"- {nome}" for nome, *_ in faturas.LEITORES))
    st.markdown("- **Qualquer outro banco** (.csv, .xls, .xlsx, .pdf): o app aprende o formato na primeira "
                "importação e passa a ler sozinho nas seguintes.")

arqs = st.file_uploader("Arquivo da fatura — ou prints/fotos dela (pode ser mais de um)",
                        type=["xlsx", "xls", "csv", "ofx", "pdf", "jpg", "jpeg", "png", "webp", "heic"],
                        accept_multiple_files=True, key="up_fatura")
if not arqs:
    st.stop()
_imgs = [a for a in arqs if a.name.lower().rsplit(".", 1)[-1] in leitores.IMAGENS]
if _imgs and len(_imgs) != len(arqs):
    st.warning("Misturou imagem com arquivo: suba só os prints, ou só o arquivo da fatura.")
    st.stop()
if not _imgs and len(arqs) > 1:
    st.warning("Uma fatura por vez (vários arquivos só para prints/fotos da mesma fatura).")
    st.stop()
arq = arqs[0]

# PDF protegido: pede a senha (fica só na memória desta sessão)
senha = None
if not _imgs and arq.name.lower().endswith(".pdf") and leitores.pdf_protegido(arq.getvalue()):
    senha = st.text_input("Senha do PDF", type="password", key=f"senha_{arq.name}",
                          help="Normalmente parte do CPF ou a data de nascimento, como o banco indica no e-mail.")
    if not senha:
        st.info("Este PDF está protegido. Digite a senha para continuar.", icon=":material/lock:")
        st.stop()

# o arquivo é lido uma vez por sessão (formato novo/imagem chama a IA; não repetir a cada clique)
_k = "fat_lida_" + hashlib.sha1(b"".join(a.getvalue() for a in arqs) + (senha or "").encode()).hexdigest()[:16]
if _k not in st.session_state:
    try:
        with st.spinner("Lendo a fatura…" if not _imgs else f"Lendo {len(_imgs)} imagem(ns) com a IA…"):
            if _imgs:
                st.session_state[_k] = faturas.ler_imagens([(a.name, a.getvalue()) for a in arqs], u)
            else:
                st.session_state[_k] = faturas.ler(arq.name, arq.getvalue(), u, senha=senha)
    except leitores.PdfComSenha as e:
        st.error(str(e))
        st.stop()
    except faturas.FormatoDesconhecido as e:
        st.warning(f"Não consegui ler este arquivo ({e}).", icon=":material/help:")
        st.stop()
    except Exception as e:  # noqa: BLE001
        st.error(f"Não consegui ler o arquivo: {e}")
        st.stop()
fat = st.session_state[_k]

for a in fat.avisos:
    st.info(a)

contas = repo.contas(u)
cartoes = contas[contas["tipo"] == "cartao_credito"]
op_cartoes = {r.id: r.nome for r in cartoes.itertuples()}
if not op_cartoes:
    st.warning("Cadastre o cartão em **Contas e cartões** antes de importar.")
    st.stop()
sug = faturas.conta_sugerida(u, fat, contas)
ids = list(op_cartoes)

c1, c2 = st.columns(2)
conta_id = c1.selectbox("Cartão no app", ids, format_func=op_cartoes.get,
                        index=ids.index(sug) if sug in ids else None, placeholder="Escolha o cartão",
                        help=f"Fatura do {fat.banco}" + (f" · final {fat.final}" if fat.final else ""))
vencimento = c2.date_input("Vencimento da fatura", value=fat.vencimento, format="DD/MM/YYYY")
tem_adicional = any(not ln.titular for ln in fat.linhas)
incluir_adic = st.toggle("Incluir cartões adicionais", value=False, disabled=not tem_adicional,
                         help="Por padrão entram só as compras do titular.")
if not conta_id or not vencimento:
    st.stop()

regs = faturas.preparar(u, conta_id, fat, vencimento, incluir_adic)
novas = regs[regs["situacao"] == "nova"].copy()
ja = regs[regs["situacao"].isin(["ja_lancada", "ja_importada"])]
fora = regs[regs["situacao"].isin(["pagamento", "estorno", "estornada", "adicional"])]

cartoes_kpi([
    ("Total no banco", brl(fat.total_banco) if fat.total_banco is not None else "—"),
    ("Novas", f"{len(novas)} · {brl(novas['valor'].sum())}"),
    ("Já no app", f"{len(ja)} · {brl(ja['valor'].sum())}"),
    ("Fora", str(len(fora))),
])

# --- novas: o usuário confere a categoria e desmarca o que não quiser ----------------------
op_cat = opcoes_categoria(repo.categorias(u), "despesa")
rot_por_id = {k: v for k, v in op_cat.items()}
id_por_rot = {v: k for k, v in op_cat.items()}

if novas.empty:
    st.success("Nada novo nesta fatura — tudo já está no app.", icon=":material/done_all:")
else:
    st.subheader(f"Novas ({len(novas)})")
    ed = pd.DataFrame({
        "importar": True,
        "data": pd.to_datetime(novas["data"]),
        "descricao": novas["descricao"],
        "parcela": novas["parcela"],
        "valor": novas["valor"].astype(float),
        "categoria": novas["categoria_id"].map(lambda c: rot_por_id.get(c)),
    }, index=novas.index)
    cel = e_celular()
    cfg = {
        "importar": st.column_config.CheckboxColumn("✓", width=40),
        "data": st.column_config.DateColumn("Data", format="DD/MM", disabled=True),
        "descricao": st.column_config.TextColumn("Descrição"),
        "parcela": st.column_config.TextColumn("Parc.", disabled=True, width=60),
        "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", disabled=True),
        "categoria": st.column_config.SelectboxColumn("Categoria", options=list(id_por_rot), width="medium"),
    }
    ordem = ["importar", "descricao", "valor", "categoria"] if cel else list(cfg)
    editado = st.data_editor(ed, column_config=cfg, column_order=ordem, hide_index=True,
                             use_container_width=True, key=f"ed_{arq.name}_{conta_id}",
                             height=min(38 + 35 * len(ed), 520))
    sem_cat = int((editado["importar"] & editado["categoria"].isna()).sum())
    if sem_cat:
        st.caption(f"{sem_cat} sem categoria — entram como *Sem categoria* e dá para ajustar depois.")

if not ja.empty:
    with st.expander(f"Já estavam no app ({len(ja)}) — não serão duplicadas"):
        v = ja.assign(no_app=ja["existente_desc"].fillna("importada antes"))[
            ["data", "descricao", "parcela", "valor", "no_app"]]
        st.dataframe(em_reais(v), hide_index=True, use_container_width=True,
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM"),
                                    "descricao": "Na fatura", "parcela": "Parc.", "valor": col_rs(),
                                    "no_app": "No app como"})

if not fora.empty:
    rot = {"pagamento": "pagamento da fatura", "estorno": "estorno/crédito",
           "estornada": "compra estornada", "adicional": "cartão adicional"}
    with st.expander(f"Ficam de fora ({len(fora)})"):
        v = fora.assign(motivo=fora["situacao"].map(rot))[["data", "descricao", "portador", "valor", "motivo"]]
        st.dataframe(em_reais(v), hide_index=True, use_container_width=True,
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM"),
                                    "descricao": "Descrição", "portador": "Cartão de", "valor": col_rs(),
                                    "motivo": "Por quê"})

# --- gravar --------------------------------------------------------------------------------
if novas.empty:
    escolhidas = novas
else:
    escolhidas = novas.loc[editado.index[editado["importar"]]].copy()
    escolhidas["descricao"] = editado.loc[escolhidas.index, "descricao"]
    escolhidas["categoria_id"] = editado.loc[escolhidas.index, "categoria"].map(id_por_rot.get)
    # descrição editada vale para o lançamento
    for idx in escolhidas.index:
        fat.linhas[int(escolhidas.at[idx, "i"])].descricao = str(escolhidas.at[idx, "descricao"]).strip()

base_fut = pd.concat([escolhidas, regs[regs["situacao"] == "ja_lancada"]])
futuras = faturas.plano_futuras(u, conta_id, fat, base_fut, vencimento)

resumo = f"**{len(escolhidas)}** lançamentos · {brl(escolhidas['valor'].sum() if len(escolhidas) else 0)}"
if futuras:
    resumo += f" + **{len(futuras)}** parcelas futuras ({brl(sum(f['valor'] for f in futuras))})"
st.markdown(resumo)
if futuras:
    with st.expander("Ver parcelas futuras"):
        fv = pd.DataFrame(futuras)[["data_vencimento", "descricao", "parcela_num", "parcela_total", "valor"]]
        fv["parcela"] = fv["parcela_num"].astype(str) + "/" + fv["parcela_total"].astype(str)
        st.dataframe(em_reais(fv[["data_vencimento", "descricao", "parcela", "valor"]]), hide_index=True,
                     use_container_width=True,
                     column_config={"data_vencimento": st.column_config.DateColumn("Vence", format="DD/MM/YY"),
                                    "descricao": "Descrição", "parcela": "Parc.", "valor": col_rs()})

if st.button("Importar", type="primary", icon=":material/download_done:", use_container_width=True,
             disabled=escolhidas.empty and not futuras and ja.empty):
    r = faturas.gravar(u, conta_id, fat, vencimento, escolhidas, futuras, ", ".join(a.name for a in arqs),
                       vincular=regs[regs["situacao"] == "ja_lancada"])
    if fat.receita_nova and fat.impressao:
        try:
            leitores.guardar("fatura", fat.impressao, fat.motor, fat.receita_nova, u)
        except Exception:  # noqa: BLE001 — não trava a importação por causa da receita
            pass
    st.session_state.pop(_k, None)
    st.session_state["_ok_fat"] = (f"Fatura importada: {r['novas']} lançamentos"
                                   + (f" e {r['futuras']} parcelas futuras" if r["futuras"] else "")
                                   + (f"; {r['vinculadas']} já existentes conferidos" if r["vinculadas"] else "")
                                   + ".")
    st.session_state.pop("up_fatura", None)
    st.rerun()

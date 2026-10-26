"""IA (Claude, com a chave do próprio usuário) para entender comprovantes e textos livres.

Secrets:
    [anthropic]
    api_key = "sk-ant-..."
    modelo = "claude-haiku-5-5"     # opcional
"""
from __future__ import annotations

import base64
import io
import json
from datetime import date

import httpx
import streamlit as st

URL = "https://api.anthropic.com/v1/messages"
MODELO_PADRAO = "claude-haiku-5-5"


def chave() -> str | None:
    try:
        return st.secrets["anthropic"]["api_key"] or None
    except Exception:  # noqa: BLE001
        return None


def modelo() -> str:
    try:
        return st.secrets["anthropic"].get("modelo") or MODELO_PADRAO
    except Exception:  # noqa: BLE001
        return MODELO_PADRAO


def preparar_imagem(dados: bytes, lado=1568, qualidade=82) -> bytes:
    """Gira pela orientação da câmera, reduz e converte para JPEG."""
    from PIL import Image, ImageOps
    try:                                   # fotos .heic do iPhone
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(dados))).convert("RGB")
    img.thumbnail((lado, lado))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=qualidade, optimize=True)
    return out.getvalue()


FERRAMENTA = {
    "name": "registrar_lancamento",
    "description": "Registra o lançamento financeiro extraído do comprovante ou do texto.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo": {"type": "string", "enum": ["despesa", "receita"]},
            "descricao": {"type": "string", "description": "Nome curto do estabelecimento ou do gasto, ex.: 'Padaria Bom Gosto'"},
            "valor_total": {"type": "number", "description": "Valor total pago em reais (positivo)"},
            "data": {"type": "string", "description": "Data da compra AAAA-MM-DD; se não houver, hoje"},
            "parcelas": {"type": "integer", "description": "Número de parcelas (1 se à vista)"},
            "funcao": {"type": "string", "enum": ["credito", "debito", "pix", "dinheiro", "boleto", "desconhecido"]},
            "conta": {"type": ["integer", "null"], "description": "Número da conta/cartão da lista, se der para saber"},
            "categoria": {"type": ["integer", "null"], "description": "Número da categoria da lista que melhor se encaixa"},
            "itens": {"type": "string", "description": "Resumo curto dos itens comprados, se houver"},
            "duvida": {"type": "string", "description": "O que não ficou claro (vazio se nada)"},
        },
        "required": ["tipo", "descricao", "valor_total", "data", "parcelas", "funcao", "categoria"],
    },
}


def _contexto(contas: dict, categorias: dict, hoje: date) -> tuple[str, list, list]:
    lc, lk = list(contas.items()), list(categorias.items())
    txt = (f"Hoje é {hoje:%Y-%m-%d} (Brasil). Valores em reais.\n\n"
           "Contas e cartões do usuário:\n" + "\n".join(f"{i}. {n}" for i, (_, n) in enumerate(lc)) +
           "\n\nCategorias:\n" + "\n".join(f"{i}. {n}" for i, (_, n) in enumerate(lk)))
    return txt, lc, lk


INSTRUCOES = (
    "Você ajuda a lançar gastos num app de finanças pessoais brasileiro. Extraia UM lançamento e chame a "
    "ferramenta registrar_lancamento. Em cupom fiscal use o TOTAL pago (não subtotal, troco ou tributos). "
    "'ontem', 'sexta' etc. são relativos a hoje. Se o texto citar um banco/cartão, escolha a conta mais "
    "parecida; senão deixe conta nula. Escolha sempre a categoria mais provável. Descrição curta, sem CNPJ.")


def interpretar(contas: dict, categorias: dict, hoje: date, texto: str | None = None,
                imagem_jpeg: bytes | None = None) -> dict:
    """contas/categorias: {id: nome}. Devolve o lançamento com ids já resolvidos."""
    k = chave()
    if not k:
        raise RuntimeError("Falta a chave da Anthropic nos Secrets ([anthropic] api_key).")
    ctx, lc, lk = _contexto(contas, categorias, hoje)
    conteudo = [{"type": "text", "text": ctx}]
    if imagem_jpeg:
        conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.b64encode(imagem_jpeg).decode()}})
        conteudo.append({"type": "text", "text": "Comprovante acima." + (f" Observação do usuário: {texto}" if texto else "")})
    else:
        conteudo.append({"type": "text", "text": f"Gasto descrito pelo usuário: {texto}"})
    r = httpx.post(URL, timeout=60, headers={"x-api-key": k, "anthropic-version": "2023-06-01",
                                             "content-type": "application/json"},
                   json={"model": modelo(), "max_tokens": 800, "system": INSTRUCOES,
                         "tools": [FERRAMENTA], "tool_choice": {"type": "tool", "name": FERRAMENTA["name"]},
                         "messages": [{"role": "user", "content": conteudo}]})
    if r.status_code >= 400:
        try:
            msg = r.json()["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = r.text[:300]
        raise RuntimeError(f"A IA respondeu erro {r.status_code}: {msg}")
    bloco = next(b for b in r.json()["content"] if b.get("type") == "tool_use")
    d = dict(bloco["input"])

    def _pega(lista, idx):
        try:
            return lista[int(idx)][0] if idx is not None and 0 <= int(idx) < len(lista) else None
        except (TypeError, ValueError):
            return None

    d["conta_id"] = _pega(lc, d.get("conta"))
    d["categoria_id"] = _pega(lk, d.get("categoria"))
    try:
        d["data"] = date.fromisoformat(str(d.get("data"))[:10])
    except ValueError:
        d["data"] = hoje
    d["valor_total"] = abs(float(d.get("valor_total") or 0))
    d["parcelas"] = max(1, int(d.get("parcelas") or 1))
    d["_bruto"] = json.dumps(bloco["input"], ensure_ascii=False)
    return d


def categorizar(itens: list[tuple[str, float]], categorias: dict) -> list:
    """[(descrição, valor)] -> [categoria_id ou None], numa chamada só. valor < 0 = saída."""
    k = chave()
    if not k or not itens:
        return [None] * len(itens)
    lk = list(categorias.items())
    lista_cat = "\n".join(f"{i}. {n}" for i, (_, n) in enumerate(lk))
    lista_it = "\n".join(f"{i}. {d} | {'saída' if v < 0 else 'entrada'} R$ {abs(v):.2f}"
                         for i, (d, v) in enumerate(itens))
    ferramenta = {"name": "classificar", "description": "Categoria de cada item do extrato bancário.",
                  "input_schema": {"type": "object", "properties": {"itens": {"type": "array", "items": {
                      "type": "object", "properties": {"i": {"type": "integer"},
                                                       "categoria": {"type": ["integer", "null"]}},
                      "required": ["i", "categoria"]}}}, "required": ["itens"]}}
    r = httpx.post(URL, timeout=90, headers={"x-api-key": k, "anthropic-version": "2023-06-01",
                                             "content-type": "application/json"},
                   json={"model": modelo(), "max_tokens": 4000,
                         "system": "Você classifica lançamentos de extrato bancário brasileiro em categorias de "
                                   "finanças pessoais. Use null quando não der para saber (ex.: pix para pessoa "
                                   "física sem pista). Chame a ferramenta classificar.",
                         "tools": [ferramenta], "tool_choice": {"type": "tool", "name": "classificar"},
                         "messages": [{"role": "user", "content": f"Categorias:\n{lista_cat}\n\nItens:\n{lista_it}"}]})
    if r.status_code >= 400:
        raise RuntimeError(f"A IA respondeu erro {r.status_code}")
    bloco = next(b for b in r.json()["content"] if b.get("type") == "tool_use")
    out = [None] * len(itens)
    for x in bloco["input"].get("itens", []):
        try:
            i, c = int(x["i"]), x.get("categoria")
            if 0 <= i < len(itens) and c is not None and 0 <= int(c) < len(lk):
                out[i] = lk[int(c)][0]
        except (TypeError, ValueError, KeyError):
            pass
    return out

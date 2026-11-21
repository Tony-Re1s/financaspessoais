"""Leitores aprendidos: formato de fatura/extrato que o app ainda não conhece.

Na 1ª vez, a IA olha uma AMOSTRA do arquivo e devolve uma RECEITA (como ler: qual coluna é o quê,
formato de data e número, sinal, linhas a ignorar). O app aplica a receita no arquivo inteiro,
valida, e — se a importação for confirmada — guarda a receita em `leitores_aprendidos`, ligada à
"impressão digital" do formato. Da 2ª vez em diante a leitura é só código, sem IA, para qualquer
usuário. Quando não dá para aprender (PDF escaneado, foto, layout sem tabela) a IA lê as linhas
direto, toda vez.

Dois motores:
  tabela — csv / xls / xlsx (células)
  pdf    — PDF com texto: um padrão (regex) por linha de lançamento

Saída comum (lista de dict): data, descricao, valor, parcela_num, parcela_total, titular, portador,
final, ident, saldo. Quem chama (faturas.py / extratos.py) converte para a sua estrutura.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import date, datetime

import httpx
import pandas as pd
from sqlalchemy import text

from core import db, ia

MAX_PAGINAS_PDF = 8
MODELO_APRENDIZ = "claude-sonnet-5-5"       # a receita (regex, colunas) pede o modelo mais forte


class SemReceita(Exception):
    """Não deu para aprender uma receita confiável (a IA direta é a saída)."""


class PdfComSenha(Exception):
    """PDF protegido: precisa da senha (ou a senha dada está errada)."""


IMAGENS = ("jpg", "jpeg", "png", "webp", "heic", "heif")


def pdf_protegido(dados: bytes) -> bool:
    from pypdf import PdfReader
    try:
        return bool(PdfReader(io.BytesIO(dados)).is_encrypted)
    except Exception:  # noqa: BLE001
        return False


def abrir_pdf(dados: bytes, senha: str | None) -> bytes:
    """Devolve o PDF sem senha (para pdfplumber/pdfium). A senha fica só na memória."""
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(io.BytesIO(dados))
    if not r.is_encrypted:
        return dados
    if not senha:
        raise PdfComSenha("Este PDF tem senha.")
    try:
        ok = r.decrypt(senha.strip())
    except Exception as e:  # noqa: BLE001 — algoritmo não suportado etc.
        raise PdfComSenha(f"Não consegui abrir o PDF com essa senha ({e}).") from e
    if not ok:
        raise PdfComSenha("Senha do PDF incorreta.")
    w = PdfWriter()
    for pg in r.pages:
        w.add_page(pg)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _imagem_jpeg(dados: bytes, max_lado=1800) -> bytes:
    """Print/foto (inclusive HEIC do iPhone) → JPEG de tamanho razoável para a IA."""
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except Exception:  # noqa: BLE001
        pass
    im = Image.open(io.BytesIO(dados))
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > max_lado:
        im.thumbnail((max_lado, max_lado))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def ler_imagens(tipo: str, arquivos: list[tuple[str, bytes]]) -> "Lido":
    """Prints/fotos de fatura ou extrato (um ou vários): a IA lê direto, sem regra."""
    if not ia.chave():
        raise ValueError("Ler imagem precisa da IA configurada ([anthropic] api_key nos Secrets).")
    d = ler_direto(tipo, imagens=[_imagem_jpeg(b) for _, b in arquivos])
    ext = {}
    for k in ("vencimento", "final", "total", "conta"):
        if d.get(k):
            ext[k] = date.fromisoformat(str(d[k])[:10]) if k == "vencimento" and len(str(d[k])) >= 10 else d[k]
    n = len(arquivos)
    return Lido(d.get("banco") or "Banco", "ia", _linhas_direto(d), ext, motor="ia",
                avisos=[f"Lido de {n} imagem{'ns' if n > 1 else ''} pela IA: confira valores e total antes de gravar."])


# ---------------------------------------------------------------------------
# Impressão digital e matéria-prima
# ---------------------------------------------------------------------------
def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def _ext(nome: str) -> str:
    return (nome or "").lower().rsplit(".", 1)[-1] if "." in (nome or "") else ""


def _celula(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def tabela_bruta(nome: str, dados: bytes) -> list[list]:
    """Linhas × células, sem interpretar nada (header=None)."""
    e = _ext(nome)
    if e in ("xls", "xlsx", "xlsm"):
        df = pd.read_excel(io.BytesIO(dados), header=None, engine="xlrd" if e == "xls" else "openpyxl")
    else:
        txt = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                txt = dados.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        txt = txt or dados.decode("utf-8", errors="replace")
        try:
            sep = csv.Sniffer().sniff(txt[:4000], delimiters=";,\t|").delimiter
        except csv.Error:
            sep = ";" if txt.count(";") > txt.count(",") else ","
        rows = list(csv.reader(io.StringIO(txt), delimiter=sep))
        larg = max((len(r) for r in rows), default=0)
        return [[_celula(v) for v in r] + [None] * (larg - len(r)) for r in rows]
    return [[_celula(v) for v in r] for r in df.itertuples(index=False, name=None)]


def texto_pdf(dados: bytes) -> str:
    import pdfplumber
    partes = []
    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        for pg in pdf.pages[:MAX_PAGINAS_PDF]:
            partes.append(pg.extract_text(layout=False) or "")
    return "\n".join(partes)


def imagens_pdf(dados: bytes, escala=1.6) -> list[bytes]:
    """PDF escaneado → JPEGs (uma por página) para a IA olhar."""
    import pypdfium2 as pdfium
    out = []
    doc = pdfium.PdfDocument(dados)
    for i in range(min(len(doc), MAX_PAGINAS_PDF)):
        img = doc[i].render(scale=escala).to_pil().convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        out.append(buf.getvalue())
    return out


def _cabecalho_tabela(linhas: list[list]) -> list[str] | None:
    """A linha com mais células de texto curtas nas primeiras 30 — quase sempre o cabeçalho."""
    melhor, pts = None, 0
    for r in linhas[:30]:
        txt = [c for c in r if isinstance(c, str) and 1 < len(c) <= 40]
        if len(txt) >= 3 and len(txt) > pts:
            melhor, pts = txt, len(txt)
    return [_norm(c) for c in melhor] if melhor else None


def impressao(tipo: str, nome: str, dados: bytes, texto: str | None = None) -> str:
    """Identifica o FORMATO (não o arquivo): mesmo banco/leiaute → mesma impressão."""
    e = _ext(nome)
    if e == "pdf":
        toks = [t for t in _norm(texto or "")[:1500].split() if not any(ch.isdigit() for ch in t)]
        base = " ".join(toks[:40])
    else:
        cab = _cabecalho_tabela(tabela_bruta(nome, dados)) or []
        base = "|".join(cab)
    return f"{tipo}:{e}:" + hashlib.sha1(base.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Motores (determinísticos)
# ---------------------------------------------------------------------------
def _num(v, rec: dict) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("R$", "").replace("\xa0", "").replace(" ", "")
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-()+")
    dec = rec.get("decimal") or ","
    s = s.replace(".", "").replace(",", ".") if dec == "," else s.replace(",", "")
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return None


def _data(v, rec: dict, ano_padrao: int | None) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    fmts = [rec.get("formato_data") or "%d/%m/%Y", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d/%m", "%d-%m-%Y", "%d.%m.%Y"]
    for f in fmts:
        try:
            d = datetime.strptime(s, f)
            if "%y" not in f.lower():          # sem ano no formato
                d = d.replace(year=ano_padrao or date.today().year)
            return d.date()
        except ValueError:
            continue
    return None


def _sinal(valor: float, rec: dict, tipo: str) -> float:
    conv = rec.get("sinal") or ("compra_positiva" if tipo == "fatura" else "saida_negativa")
    if conv in ("compra_negativa", "saida_positiva"):
        return -valor
    return valor


def _ignorar(desc: str, rec: dict) -> bool:
    return any(re.search(p, desc or "", re.I) for p in rec.get("ignorar") or [])


def _parcela(txt) -> tuple[int | None, int | None]:
    if not txt:
        return None, None
    m = re.search(r"(\d{1,2})\s*(?:de|/)\s*(\d{1,2})\b", str(txt), re.I)
    if not m:
        return None, None
    n, t = int(m.group(1)), int(m.group(2))
    return (n, t) if 1 <= n <= t <= 99 else (None, None)


def _tira_parcela(desc: str) -> str:
    return re.sub(r"\s*-?\s*(parc(?:ela)?\.?\s*)?\d{1,2}\s*(?:de|/)\s*\d{1,2}\s*$", "", desc, flags=re.I).strip() or desc


def _ano_padrao(rec: dict, texto: str) -> int | None:
    m = re.search(rec.get("ano_regex") or r"\b(20\d{2})\b", texto or "")
    return int(m.group(1)) if m else None


def aplicar_tabela(rec: dict, linhas: list[list], tipo: str) -> list[dict]:
    cab_alvo = [_norm(c) for c in rec.get("cabecalho") or []]
    cols = rec.get("colunas") or {}
    ini, idx = None, {}
    for i, r in enumerate(linhas):
        nr = [_norm(c) if c is not None else "" for c in r]
        if cab_alvo and sum(1 for c in cab_alvo if c in nr) >= max(2, int(len(cab_alvo) * 0.7)):
            idx = {papel: nr.index(_norm(nome)) for papel, nome in cols.items()
                   if nome and _norm(nome) in nr}
            ini = i + 1
            break
    if ini is None:
        raise SemReceita("cabeçalho da receita não aparece no arquivo")
    if "data" not in idx or ("valor" not in idx and not ("credito" in idx and "debito" in idx)):
        raise SemReceita("receita sem coluna de data ou valor")
    texto_tudo = " ".join(str(c) for r in linhas for c in r if c is not None)
    ano = _ano_padrao(rec, texto_tudo)
    out = []

    def _g(r, papel):
        j = idx.get(papel)
        return r[j] if j is not None and j < len(r) else None

    for r in linhas[ini:]:
        d = _data(_g(r, "data"), rec, ano)
        if d is None:
            continue
        desc = re.sub(r"\s{2,}", " ", str(_g(r, "descricao") or "")).strip()
        if _ignorar(desc, rec):
            continue
        if "valor" in idx:
            v = _num(_g(r, "valor"), rec)
        else:
            c, dbt = _num(_g(r, "credito"), rec) or 0.0, _num(_g(r, "debito"), rec) or 0.0
            v = (c - abs(dbt)) if (c or dbt) else None
            if tipo == "fatura":
                v = -v if v is not None else None       # fatura: compra positiva
        if v is None or v == 0:
            continue
        v = _sinal(v, rec, tipo)
        pn, pt = _parcela(_g(r, "parcela")) if "parcela" in idx else _parcela(desc if rec.get("parcela_na_descricao") else None)
        if pn and rec.get("parcela_na_descricao"):
            desc = _tira_parcela(desc)
        tit_v = _g(r, "titular")
        tit = True if tit_v is None else _norm(tit_v).startswith(_norm(rec.get("titular_valor") or "titular"))
        fim = str(_g(r, "final") or "")
        out.append(dict(data=d, descricao=desc, valor=v, parcela_num=pn, parcela_total=pt, titular=tit,
                        portador=_g(r, "portador"), final=re.sub(r"\D", "", fim)[-4:] or None,
                        ident=str(_g(r, "ident")) if _g(r, "ident") is not None else None,
                        saldo=_num(_g(r, "saldo"), rec) if "saldo" in idx else None))
    return out


def aplicar_pdf(rec: dict, texto: str, tipo: str) -> list[dict]:
    try:
        rx = re.compile(rec["linha"], re.M)
    except (KeyError, re.error) as e:
        raise SemReceita(f"regex inválida: {e}")
    ano = _ano_padrao(rec, texto)
    out = []
    for m in rx.finditer(texto):
        g = m.groupdict()
        d = _data(g.get("data"), rec, ano)
        if d is None:
            continue
        desc = re.sub(r"\s{2,}", " ", (g.get("descricao") or "")).strip()
        if _ignorar(desc, rec):
            continue
        v = _num(g.get("valor"), rec)
        if v is None or v == 0:
            continue
        if g.get("credito") or g.get("debito"):
            v = (_num(g.get("credito"), rec) or 0.0) - abs(_num(g.get("debito"), rec) or 0.0)
        v = _sinal(v, rec, tipo)
        pn, pt = _parcela(g.get("parcela") or (desc if rec.get("parcela_na_descricao") else None))
        if pn and rec.get("parcela_na_descricao"):
            desc = _tira_parcela(desc)
        out.append(dict(data=d, descricao=desc, valor=v, parcela_num=pn, parcela_total=pt, titular=True,
                        portador=None, final=None, ident=None, saldo=_num(g.get("saldo"), rec)))
    return out


def extras_pdf_ou_tabela(rec: dict, texto: str) -> dict:
    """Vencimento / final do cartão / total do banco / conta, se a receita souber achar no texto."""
    out = {}
    for k, conv in (("vencimento_regex", "data"), ("final_regex", "txt"), ("total_regex", "num"),
                    ("conta_regex", "txt"), ("titular_regex", "txt")):
        p = rec.get(k)
        if not p:
            continue
        try:
            m = re.search(p, texto, re.I | re.S)
        except re.error:
            continue
        if not m:
            continue
        val = m.group(1) if m.groups() else m.group(0)
        nome = k.replace("_regex", "")
        out[nome] = _data(val, rec, None) if conv == "data" else (_num(val, rec) if conv == "num" else val.strip())
    return out


# ---------------------------------------------------------------------------
# IA: aprender a receita / ler direto
# ---------------------------------------------------------------------------
_CAMPOS_TABELA = {
    "type": "object",
    "properties": {
        "banco": {"type": "string", "description": "Nome do banco/emissor, curto (ex.: Bradesco, Inter, C6)"},
        "cabecalho": {"type": "array", "items": {"type": "string"},
                      "description": "Textos EXATOS das células da linha de cabeçalho da tabela de lançamentos"},
        "colunas": {"type": "object", "description": "Nome exato da coluna (do cabeçalho) para cada papel; omita os que não existem",
                    "properties": {k: {"type": "string"} for k in
                                   ["data", "descricao", "valor", "credito", "debito", "saldo", "parcela",
                                    "titular", "portador", "final", "ident"]}},
        "formato_data": {"type": "string", "description": "strftime da coluna data, ex.: %d/%m/%Y, %d/%m, %Y-%m-%d"},
        "decimal": {"type": "string", "enum": [",", "."], "description": "Separador decimal dos valores"},
        "sinal": {"type": "string", "enum": ["compra_positiva", "compra_negativa", "saida_negativa", "saida_positiva"],
                  "description": "fatura: compra_positiva se compras são positivas; extrato: saida_negativa se saídas são negativas"},
        "ignorar": {"type": "array", "items": {"type": "string"},
                    "description": "Regex (descrição) de linhas que NÃO são lançamentos: saldo, total, 'pagamento efetuado', subtotal…"},
        "parcela_na_descricao": {"type": "boolean", "description": "true se '3/10' ou 'Parcela 3 de 10' aparece dentro da descrição"},
        "titular_valor": {"type": "string", "description": "Valor da coluna titular que indica o titular (ex.: Titular)"},
        "vencimento_regex": {"type": "string", "description": "Regex com 1 grupo que captura a data de vencimento no texto do arquivo (fatura)"},
        "final_regex": {"type": "string", "description": "Regex com 1 grupo: últimos 4 dígitos do cartão principal (fatura)"},
        "total_regex": {"type": "string", "description": "Regex com 1 grupo: total da fatura (fatura)"},
        "conta_regex": {"type": "string", "description": "Regex com 1 grupo: número da conta (extrato)"},
        "titular_regex": {"type": "string", "description": "Regex com 1 grupo: nome do titular"},
        "ano_regex": {"type": "string", "description": "Regex com 1 grupo (ano) se a coluna data não tem ano"},
        "observacao": {"type": "string", "description": "Dúvidas ou algo que a receita não cobre (vazio se nada)"},
    },
    "required": ["banco", "cabecalho", "colunas", "formato_data", "decimal", "sinal"],
}
_CAMPOS_PDF = {
    "type": "object",
    "properties": {
        "banco": _CAMPOS_TABELA["properties"]["banco"],
        "linha": {"type": "string", "description":
                  "Regex Python (flag MULTILINE) que casa UMA linha de lançamento, com grupos nomeados: "
                  "(?P<data>…) (?P<descricao>…) (?P<valor>…) obrigatórios (ou credito/debito no lugar de valor); "
                  "opcionais (?P<parcela>…) (?P<saldo>…). Deve casar todos os lançamentos e nenhum cabeçalho/total."},
        "formato_data": _CAMPOS_TABELA["properties"]["formato_data"],
        "decimal": _CAMPOS_TABELA["properties"]["decimal"],
        "sinal": _CAMPOS_TABELA["properties"]["sinal"],
        "ignorar": _CAMPOS_TABELA["properties"]["ignorar"],
        "parcela_na_descricao": _CAMPOS_TABELA["properties"]["parcela_na_descricao"],
        "vencimento_regex": _CAMPOS_TABELA["properties"]["vencimento_regex"],
        "final_regex": _CAMPOS_TABELA["properties"]["final_regex"],
        "total_regex": _CAMPOS_TABELA["properties"]["total_regex"],
        "conta_regex": _CAMPOS_TABELA["properties"]["conta_regex"],
        "titular_regex": _CAMPOS_TABELA["properties"]["titular_regex"],
        "ano_regex": _CAMPOS_TABELA["properties"]["ano_regex"],
        "observacao": _CAMPOS_TABELA["properties"]["observacao"],
    },
    "required": ["banco", "linha", "formato_data", "decimal", "sinal"],
}
_CAMPOS_LINHAS = {
    "type": "object",
    "properties": {
        "banco": _CAMPOS_TABELA["properties"]["banco"],
        "vencimento": {"type": "string", "description": "AAAA-MM-DD (fatura), se aparecer"},
        "final": {"type": "string", "description": "últimos 4 dígitos do cartão principal, se aparecer"},
        "total": {"type": "number", "description": "total da fatura / do período, se aparecer"},
        "conta": {"type": "string", "description": "número da conta (extrato), se aparecer"},
        "linhas": {"type": "array", "items": {"type": "object", "properties": {
            "data": {"type": "string", "description": "AAAA-MM-DD"},
            "descricao": {"type": "string"},
            "valor": {"type": "number", "description": "fatura: compra positiva, estorno negativo; extrato: entrada positiva, saída negativa"},
            "parcela_num": {"type": ["integer", "null"]}, "parcela_total": {"type": ["integer", "null"]},
            "titular": {"type": "boolean", "description": "false se for cartão adicional"},
            "portador": {"type": ["string", "null"]}, "final": {"type": ["string", "null"]},
            "saldo": {"type": ["number", "null"], "description": "saldo após a linha (extrato), se houver"},
        }, "required": ["data", "descricao", "valor"]}},
    },
    "required": ["banco", "linhas"],
}


def _chamar(payload: dict, modelo_: str) -> dict:
    k = ia.chave()
    if not k:
        raise RuntimeError("Falta a chave da Anthropic nos Secrets ([anthropic] api_key).")
    r = httpx.post(ia.URL, timeout=120, headers={"x-api-key": k, "anthropic-version": "2023-06-01",
                                                  "content-type": "application/json"},
                   json=payload | {"model": modelo_})
    if r.status_code >= 400:
        try:
            msg = r.json()["error"]["message"]
        except Exception:  # noqa: BLE001
            msg = r.text[:300]
        raise RuntimeError(f"A IA respondeu erro {r.status_code}: {msg}")
    blocos = r.json().get("content") or []
    uso = next((b for b in blocos if b.get("type") == "tool_use"), None)
    if uso is None:
        txt = " ".join(b.get("text", "") for b in blocos if b.get("type") == "text")[:300]
        raise RuntimeError("A IA não devolveu a leitura no formato esperado" + (f": {txt}" if txt else "."))
    return uso["input"]


def _ferramenta(nome, schema, descricao):
    # tool_choice "auto": alguns modelos não aceitam forçar a ferramenta; a instrução pede para sempre usá-la
    return {"tools": [{"name": nome, "description": descricao, "input_schema": schema}],
            "tool_choice": {"type": "auto"}}


def _modelos():
    """Aprendiz forte primeiro; se a conta não tiver esse modelo, o configurado."""
    return [MODELO_APRENDIZ, ia.modelo()] if MODELO_APRENDIZ != ia.modelo() else [ia.modelo()]


def _tentar(payload):
    erro = None
    for m in _modelos():
        try:
            return _chamar(payload, m)
        except RuntimeError as e:
            erro = e
            if "404" not in str(e) and "not_found" not in str(e):
                raise
    raise erro


_O_QUE_E = {"fatura": "fatura de CARTÃO DE CRÉDITO (compras; 'pagamento efetuado', juros e totais não são compras)",
            "extrato": "extrato de CONTA CORRENTE (entradas e saídas; linhas de saldo e total não são lançamentos)"}


def amostra_tabela(linhas: list[list], n=25) -> str:
    out = []
    for i, r in enumerate(linhas[:n]):
        cel = ["" if c is None else (c.strftime("%Y-%m-%d %H:%M") if isinstance(c, datetime) else str(c)) for c in r]
        while cel and cel[-1] == "":
            cel.pop()
        if cel:
            out.append(f"L{i}: " + " | ".join(cel))
    return "\n".join(out)


def aprender_tabela(tipo: str, linhas: list[list], dica: str | None = None) -> dict:
    sis = (f"Você escreve a RECEITA para um programa ler um arquivo de {_O_QUE_E[tipo]} brasileiro, em formato de tabela. "
           "Receba uma amostra (linha a linha, células separadas por ' | ') e responda SOMENTE chamando a ferramenta. Use os textos EXATOS "
           "do cabeçalho. Em 'ignorar' ponha regex para linhas que não são lançamentos. Seja preciso: o programa vai "
           "aplicar a receita no arquivo inteiro sem olhar.")
    msg = amostra_tabela(linhas) + (f"\n\n---\n{dica}" if dica else "")
    return _tentar({"max_tokens": 1500, "system": sis, "messages": [{"role": "user", "content": msg}]}
                   | _ferramenta("receita_tabela", _CAMPOS_TABELA, "Receita de leitura de tabela"))


def aprender_pdf(tipo: str, texto: str, dica: str | None = None) -> dict:
    sis = (f"Você escreve a RECEITA para um programa ler o TEXTO extraído de um PDF de {_O_QUE_E[tipo]} brasileiro. "
           "Receba o começo do texto e responda SOMENTE chamando a ferramenta. A regex 'linha' (Python, re.M) precisa casar cada "
           "lançamento inteiro numa linha, com grupos nomeados data/descricao/valor (ou credito/debito), e não casar "
           "cabeçalhos, saldos nem totais. Prefira âncoras ^ e $ e classes explícitas (\\d{2}/\\d{2}).")
    msg = texto[:9000] + (f"\n\n---\n{dica}" if dica else "")
    return _tentar({"max_tokens": 1500, "system": sis, "messages": [{"role": "user", "content": msg}]}
                   | _ferramenta("receita_pdf", _CAMPOS_PDF, "Receita de leitura de PDF"))


def ler_direto(tipo: str, texto: str | None = None, imagens: list[bytes] | None = None) -> dict:
    """Sem receita: a IA devolve as linhas. {'banco','vencimento','final','total','conta','linhas':[...]}"""
    import base64
    sis = (f"Extraia TODOS os lançamentos de um(a) {_O_QUE_E[tipo]} brasileiro(a) e responda SOMENTE chamando a ferramenta. "
           "Datas em AAAA-MM-DD (se faltar o ano, deduza pelo documento). Não invente linhas; não some nada.")
    cont = []
    for im in imagens or []:
        cont.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(im).decode()}})
    if texto:
        cont.append({"type": "text", "text": texto[:60000]})
    if not cont:
        raise ValueError("Nada para ler.")
    return _tentar({"max_tokens": 16000, "system": sis, "messages": [{"role": "user", "content": cont}]}
                   | _ferramenta("linhas_lidas", _CAMPOS_LINHAS, "Lançamentos extraídos"))


def _linhas_direto(d: dict) -> list[dict]:
    out = []
    for ln in d.get("linhas") or []:
        try:
            dt = date.fromisoformat(str(ln.get("data"))[:10])
            v = float(ln.get("valor"))
        except (TypeError, ValueError):
            continue
        if not v:
            continue
        out.append(dict(data=dt, descricao=str(ln.get("descricao") or "").strip(), valor=v,
                        parcela_num=ln.get("parcela_num"), parcela_total=ln.get("parcela_total"),
                        titular=ln.get("titular", True) is not False, portador=ln.get("portador"),
                        final=(re.sub(r"\D", "", str(ln.get("final") or ""))[-4:] or None), ident=None,
                        saldo=ln.get("saldo")))
    return out


# ---------------------------------------------------------------------------
# Receitas guardadas
# ---------------------------------------------------------------------------
def receita_guardada(tipo: str, imp: str) -> dict | None:
    r = db.um("select id, banco, motor, receita from leitores_aprendidos where tipo = :t and impressao = :i",
              t=tipo, i=imp)
    if not r:
        return None
    rec = dict(r["receita"]) if isinstance(r["receita"], dict) else json.loads(r["receita"])
    rec["_id"], rec["banco"], rec["motor"] = str(r["id"]), r["banco"], r["motor"]
    return rec


def guardar(tipo: str, imp: str, motor: str, rec: dict, u) -> None:
    limpo = {k: v for k, v in rec.items() if not k.startswith("_") and k != "motor"}
    db.executar("""insert into leitores_aprendidos (tipo, impressao, banco, motor, receita, criado_por)
                   values (:t, :i, :b, :m, cast(:r as jsonb), :u)
                   on conflict (tipo, impressao) do update set receita = excluded.receita, banco = excluded.banco,
                       motor = excluded.motor, usos = leitores_aprendidos.usos + 1, ultimo_uso = now()""",
                t=tipo, i=imp, b=rec.get("banco") or "Banco", m=motor,
                r=json.dumps(limpo, ensure_ascii=False), u=u["id"] if u else None)


def marcar_uso(rec_id: str) -> None:
    try:
        db.executar("update leitores_aprendidos set usos = usos + 1, ultimo_uso = now() where id = :i",
                    mudar=False, i=rec_id)
    except Exception:  # noqa: BLE001
        pass


def listar() -> pd.DataFrame:
    return db.consultar("""select l.id, l.tipo, l.banco, l.motor, l.usos, l.criado_em, l.ultimo_uso, u.nome as criado_por
                           from leitores_aprendidos l left join usuarios u on u.id = l.criado_por
                           order by l.tipo, l.banco""")


def apagar(rec_id: str) -> None:
    db.executar("delete from leitores_aprendidos where id = :i", i=rec_id)


# ---------------------------------------------------------------------------
# Entrada única
# ---------------------------------------------------------------------------
class Lido:
    """Resultado de ler_desconhecido: linhas no formato comum + metadados + a receita nova (se houver)."""

    def __init__(self, banco, formato, linhas, extras, receita_nova=None, impressao_=None, motor=None, avisos=None):
        self.banco, self.formato, self.linhas, self.extras = banco, formato, linhas, extras
        self.receita_nova, self.impressao, self.motor, self.avisos = receita_nova, impressao_, motor, avisos or []


def _linhas_com_data(texto_ref: str) -> list[str]:
    """Linhas do arquivo que COMEÇAM com data (ou cuja 1ª célula é data): candidatas a lançamento."""
    out = []
    for ln in texto_ref.splitlines():
        t = re.sub(r"^L\d+:\s*", "", ln).strip()
        if re.match(r"^\d{2}[/.-]\d{2}([/.-]\d{2,4})?\b|^\d{4}-\d{2}-\d{2}\b", t):
            out.append(t)
    return out


def _valida(linhas: list[dict], tipo: str, total: float | None, texto_ref: str) -> None:
    """A receita só vale se leu um tanto razoável.
    1) total do banco conhecido e soma batendo → vale (independe de contagem);
    2) senão, tem de ler pelo menos metade das linhas que começam com data."""
    if len(linhas) < 1:
        raise SemReceita("a receita não leu nenhuma linha")
    if total and tipo == "fatura":
        soma = sum(ln["valor"] for ln in linhas if ln["titular"]) if any(not ln["titular"] for ln in linhas) \
            else sum(ln["valor"] for ln in linhas)
        soma_tudo = sum(ln["valor"] for ln in linhas)
        if min(abs(soma - total), abs(soma_tudo - total)) <= 0.05:
            return
        if abs(soma_tudo - total) / max(abs(total), 1) > 0.02:
            raise SemReceita(f"soma das linhas {soma_tudo:.2f} ≠ total do banco {total:.2f}")
    cand = _linhas_com_data(texto_ref)
    if cand and len(linhas) < 0.5 * min(len(cand), 400):
        raise SemReceita(f"leu {len(linhas)} de ~{len(cand)} linhas com data")


def _faltantes(rec: dict, linhas: list[dict], texto_ref: str, motor: str, n=12) -> str:
    """Linhas com data que a receita deixou de fora — para a 2ª tentativa da IA."""
    lidas = {(ln["data"], round(abs(ln["valor"]), 2)) for ln in linhas}
    fora = []
    for t in _linhas_com_data(texto_ref):
        nums = [v for v in (_num(x, rec) for x in re.findall(r"-?[\d.]+,\d{2}|-?\d+\.\d{2}", t)) if v is not None]
        if not any((d, round(abs(v), 2)) in lidas for d in {ln["data"] for ln in linhas} for v in nums):
            fora.append(t)
        if len(fora) >= n:
            break
    return "\n".join(fora)


def ler_desconhecido(tipo: str, nome: str, dados: bytes, u=None, senha: str | None = None) -> Lido:
    """1) receita guardada → 2) aprender com a IA e validar → 3) IA lê direto."""
    e = _ext(nome)
    if e in IMAGENS:
        return ler_imagens(tipo, [(nome, dados)])
    if e not in ("csv", "txt", "xls", "xlsx", "xlsm", "pdf"):
        raise ValueError(f"Não sei ler .{e}")
    if e == "pdf":
        dados = abrir_pdf(dados, senha)          # PdfComSenha se precisar
    texto = texto_pdf(dados) if e == "pdf" else None
    escaneado = e == "pdf" and len((texto or "").strip()) < 80
    linhas_tab = None if e == "pdf" else tabela_bruta(nome, dados)
    texto_ref = texto if e == "pdf" else amostra_tabela(linhas_tab, n=100000)
    imp = None if escaneado else impressao(tipo, nome, dados, texto)
    motor = "pdf" if e == "pdf" else "tabela"

    def _aplica(rec):
        lns = aplicar_pdf(rec, texto, tipo) if motor == "pdf" else aplicar_tabela(rec, linhas_tab, tipo)
        ext = extras_pdf_ou_tabela(rec, texto_ref)
        return lns, ext

    # 1) já aprendido
    if imp:
        rec = receita_guardada(tipo, imp)
        if rec:
            try:
                lns, ext = _aplica(rec)
                _valida(lns, tipo, ext.get("total"), texto_ref)
                marcar_uso(rec["_id"])
                return Lido(rec.get("banco") or "Banco", f"aprendido:{rec['_id'][:8]}", lns, ext,
                            impressao_=imp, motor=motor)
            except SemReceita as err:
                avis = [f"A receita guardada deste formato não serviu ({err}); aprendendo de novo."]
            else:
                avis = []
        else:
            avis = []
    else:
        avis = []

    # 2) aprender (até 2 tentativas: a 2ª recebe o que a 1ª deixou de fora)
    if not escaneado and ia.chave():
        try:
            rec, lns, ext, erro, dica = None, [], {}, None, None
            for tentativa in range(2):
                if tentativa:
                    dica = (f"A receita anterior {json.dumps({k: v for k, v in rec.items() if k != 'observacao'}, ensure_ascii=False)} "
                            f"falhou: {erro}. Linhas com data que ficaram de fora:\n{_faltantes(rec, lns, texto_ref, motor)}\n"
                            "Corrija a receita para cobrir essas linhas também.")
                rec = aprender_pdf(tipo, texto, dica) if motor == "pdf" else aprender_tabela(tipo, linhas_tab, dica)
                try:
                    lns, ext = _aplica(rec)
                except SemReceita as e2:          # nem aplicou (cabeçalho/regex inválidos)
                    erro, lns, ext = e2, [], {}
                    continue
                try:
                    _valida(lns, tipo, ext.get("total"), texto_ref)
                    break
                except SemReceita as e2:
                    erro = e2
            else:
                raise SemReceita(str(erro))
            obs = rec.get("observacao")
            if obs:
                avis.append(f"Observação da leitura: {obs}")
            return Lido(rec.get("banco") or "Banco", "aprendendo", lns, ext, receita_nova=rec, impressao_=imp,
                        motor=motor, avisos=avis)
        except SemReceita as err:
            avis.append(f"Não deu para fixar uma regra de leitura ({err}); a IA leu as linhas diretamente.")

    # 3) IA direta
    if not ia.chave():
        raise ValueError("Formato desconhecido e a IA não está configurada ([anthropic] api_key nos Secrets).")
    d = ler_direto(tipo, texto=None if escaneado else texto_ref, imagens=imagens_pdf(dados) if escaneado else None)
    ext = {}
    for k in ("vencimento", "final", "total", "conta"):
        if d.get(k):
            ext[k] = date.fromisoformat(str(d[k])[:10]) if k == "vencimento" and len(str(d[k])) >= 10 else d[k]
    avis.append("Leitura feita pela IA, sem regra fixa: confira o total antes de gravar.")
    return Lido(d.get("banco") or "Banco", "ia", _linhas_direto(d), ext, motor="ia", avisos=avis)

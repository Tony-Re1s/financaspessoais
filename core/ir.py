"""Imposto de Renda: leitura dos holerites (PDF) e resumo do ano para a declaração.

Valores de referência do ano-calendário 2026 (declaração 2027). Confira sempre com o informe de rendimentos
da empresa e com a Receita Federal — isto é uma estimativa para planejar, não substitui o programa da Receita.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata

import pandas as pd
import streamlit as st

from core import db

# tabela anual progressiva (ano-calendário 2026)
TABELA_ANUAL = [(29145.60, 0.0, 0.0), (33919.80, .075, 2185.92), (45012.60, .15, 4729.91),
                (55976.16, .225, 8105.85), (float("inf"), .275, 10904.66)]
TABELA_MENSAL = [(2428.80, 0.0, 0.0), (2826.65, .075, 182.16), (3751.05, .15, 394.16),
                 (4664.68, .225, 675.49), (float("inf"), .275, 908.73)]
LIMITE_SIMPLIFICADO = 17640.00      # desconto simplificado: 20% dos tributáveis, até este teto
TETO_REDUCAO_ANUAL = 88200.00        # Lei 15.270/2025: abaixo disto pode haver redução extra (não calculada aqui)
DEDUCAO_DEPENDENTE = 2275.08         # por dependente, no ano

CLASSES = {
    "tributavel": "Rendimento tributável", "isento": "Rendimento isento", "plr": "PLR (tributação exclusiva)",
    "decimo": "13º salário (tributação exclusiva)", "decimo_adto": "Adiantamento do 13º (desconto)",
    "nao_tributavel": "Reembolso / indenização", "inss": "INSS", "inss_13": "INSS sobre 13º",
    "irrf": "IR retido na fonte", "irrf_plr": "IR sobre PLR", "irrf_13": "IR sobre 13º",
    "saude": "Plano de saúde (dedutível)", "pgbl": "Previdência privada (PGBL)", "pensao": "Pensão alimentícia",
    "pagamento": "Pagamento (adiantamento/líquido)", "ignorar": "Lançamento contábil", "outros": "Outros descontos",
}


def _sa(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


VARIAVEIS = r"comiss|\bdsr\b|premi|bonus|bonif|gratifica|hora extra|\bh\.?e\b|adicional noturno"


def variavel(desc: str) -> bool:
    """Verba que muda todo mês (comissão, DSR sobre comissão, prêmio, hora extra…)."""
    return bool(re.search(VARIAVEIS, _sa(desc)))


def classificar(desc: str, provento: bool) -> str:
    d = _sa(desc)
    d = d.replace(".", "")                     # "I.N.S.S." -> "inss"; "DESC.ADIANT" -> "descadiant"
    treze = bool(re.search(r"\b13|decimo", d))
    if re.search(r"\btroco\b", d):
        return "ignorar"
    if provento:
        if re.search(r"devolucao provis|contrapartida", d):
            return "ignorar"
        if re.search(r"reembolso|ajuda de custo|indeniza|diaria|auxilio aliment|aux aliment|vale aliment|"
                     r"vale refei|auxilio refei|auxilio creche|vale transp", d):
            return "nao_tributavel"
        if "abono pecuniario" in d:
            return "isento"
        if re.search(r"participacao nos resultados|\bplr\b|\bppr\b", d):
            return "plr"
        if treze:
            return "decimo"
        return "tributavel"
    if re.search(r"devolucao provis|contrapartida", d):
        return "ignorar"
    if "inss" in d:
        return "inss_13" if treze else "inss"
    if re.search(r"imposto de renda|\birrf\b", d):
        if re.search(r"\bppr\b|\bplr\b|participacao", d):
            return "irrf_plr"
        return "irrf_13" if treze else "irrf"
    if re.search(r"adiant.*13|13.*adiant", d):
        return "decimo_adto"
    if re.search(r"adiant|liquido de|liquido", d):
        return "pagamento"
    if re.search(r"assist.*medic|plano de saude|odonto|copart|saude", d):
        return "saude"
    if re.search(r"previdencia privada|pgbl", d):
        return "pgbl"
    if "pensao" in d:
        return "pensao"
    return "outros"


# ---------------------------------------------------------------------------
# leitura do PDF
# ---------------------------------------------------------------------------
_RX_VALOR = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
_MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
          "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_COL_QTD = {"qtde", "referencia", "ref", "ref.", "quantidade", "qtd"}
_COL_PROV = {"vencimento", "vencimentos", "proventos", "provento", "creditos"}
_COL_DESC = {"descontos", "desconto", "debitos"}


def _rotulo_valor(palavras, rotulo: list[str], abaixo=True) -> float | None:
    """Valor escrito embaixo (ou à direita) de um rótulo de várias palavras, ex.: ['base','calc.','irrf']."""
    alvo = [_sa(x) for x in rotulo]
    ws = sorted(palavras, key=lambda w: (round(w["top"]), w["x0"]))
    for i in range(len(ws) - len(alvo) + 1):
        grupo = ws[i:i + len(alvo)]
        if [_sa(w["text"]) for w in grupo] != alvo or len({round(w["top"]) for w in grupo}) != 1:
            continue
        x0, x1, top = grupo[0]["x0"], grupo[-1]["x1"], grupo[0]["top"]
        cand = [w for w in palavras if _RX_VALOR.match(w["text"])]
        if abaixo:
            cand = [w for w in cand if 0 < w["top"] - top <= 16 and w["x1"] >= x0 - 12 and w["x0"] <= x1 + 12]
        else:
            cand = [w for w in cand if abs(w["top"] - top) <= 3 and w["x0"] > x1]
        if cand:
            return _num(min(cand, key=lambda w: (abs(w["top"] - top), abs(w["x0"] - x0)))["text"])
    return None


def _ler_layout(nome: str, dados: bytes) -> dict:
    """Demonstrativo em colunas (Código / Descrição / Qtde ou Referência / Vencimentos / Descontos).
    Serve para o layout 'Referência mm/aaaa' e para o 'Mensalista Mês de aaaa' (recibo em duas vias)."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        pg = pdf.pages[0]
        # só texto na horizontal (a margem do recibo tem "Declaro ter recebido…" escrito em pé)
        palavras = [w for w in pg.extract_words() if w.get("upright", True)]
        texto = pg.extract_text() or ""
    # agrupa por linha com tolerância (código e descrição às vezes saem 1pt desalinhados)
    linhas: dict[float, list] = {}
    for w in sorted(palavras, key=lambda w: w["top"]):
        k = next((t for t in linhas if abs(t - w["top"]) <= 2.0), None)
        linhas.setdefault(w["top"] if k is None else k, []).append(w)
    col = {}
    for w in sorted(palavras, key=lambda w: w["top"]):
        t = _sa(w["text"])
        for nome_c, conj in (("qtd", _COL_QTD), ("prov", _COL_PROV), ("desc", _COL_DESC)):
            if t in conj and nome_c not in col:
                col[nome_c] = (w["x1"], w["top"])
    if "prov" not in col or "desc" not in col:
        raise ValueError("Não reconheci o layout do holerite (colunas de vencimentos/descontos).")
    topo = min(col["prov"][1], col["desc"][1])
    # recibo em duas vias na mesma folha: o cabeçalho da coluna aparece de novo mais abaixo — lê só a 1ª via
    outros = sorted(w["top"] for w in palavras if _sa(w["text"]) in _COL_PROV and w["top"] > col["prov"][1] + 40
                    and abs(w["x1"] - col["prov"][0]) < 30)
    limite = outros[0] - 30 if outros else float("inf")

    t_sa = _sa(texto)
    m = re.search(r"refer[eê]ncia\s+(\d{1,2})/(\d{4})", t_sa)
    if m:
        mes, ano = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\b(" + "|".join(_MESES) + r")\s+de\s+(\d{4})", t_sa)
        if not m:
            raise ValueError("Não achei o mês de referência no holerite.")
        mes, ano = _MESES[m.group(1)], int(m.group(2))
    cnpj = (re.search(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto) or [None, None])[1]
    emp = re.search(r"Empresa\s+\d+\s+(.+?)\s+C\.N\.P\.J", texto) or re.search(r"^(.+?)\s*\n\s*CNPJ", texto, re.M)
    folha = re.search(r"Folha\s+\d+\s+(.+?)\s+Refer", texto) or re.search(r"(Folha\s+\w+)", texto)
    sal = re.search(r"Sal[áa]rio\s+([\d.]+,\d{2})", texto)

    itens = []
    for top in sorted(linhas):
        if top <= topo or top >= limite:
            continue
        ws = sorted(linhas[top], key=lambda w: w["x0"])
        if not ws or not ws[0]["text"].isdigit() or ws[0]["x0"] > 40:
            continue
        valores = [w for w in ws[1:] if _RX_VALOR.match(w["text"])]
        desc = " ".join(w["text"] for w in ws[1:] if w not in valores).strip()
        if not desc:
            continue
        for v in valores:
            dist = {k: abs(v["x1"] - x) for k, (x, _) in col.items()}
            onde = min(dist, key=dist.get)
            if onde == "qtd":
                continue
            prov = onde == "prov"
            itens.append({"codigo": ws[0]["text"], "descricao": desc, "valor": _num(v["text"]),
                          "provento": prov, "classe": classificar(desc, prov), "variavel": prov and variavel(desc)})
    if not itens:
        raise ValueError("Não encontrei as verbas do holerite.")

    def _base(rot):
        mm = re.search(rot + r"\s*:?\s*([\d.]+,\d{2})", texto)
        return _num(mm.group(1)) if mm else None

    return {"ano": ano, "mes": mes, "empresa": emp.group(1).strip() if emp else None, "cnpj": cnpj,
            "folha": (folha.group(1).strip() if folha else "Mensal"),
            "salario_base": _num(sal.group(1)) if sal else _rotulo_valor(palavras, ["Salário", "Base"]),
            "base_irrf": _base(r"Base IRRF") or _rotulo_valor(palavras, ["Base", "Cálc.", "IRRF"]),
            "base_inss": _base(r"Base INSS") or _rotulo_valor(palavras, ["Sal.", "Contr.", "INSS"]),
            "fgts": _base(r"Dep\.FGTS") or _rotulo_valor(palavras, ["F.G.T.S", "do", "Mês"]),
            "liquido": _base(r"L[íi]quido(?!\s+de)") or _rotulo_valor(palavras, ["Valor", "Líquido"], abaixo=False),
            "itens": itens, "arquivo": nome, "chave": hashlib.sha1(dados).hexdigest()}


_CAMPOS_IA = {
    "type": "object",
    "properties": {
        "ano": {"type": "integer"}, "mes": {"type": "integer", "description": "mês de referência 1-12"},
        "empresa": {"type": "string"}, "cnpj": {"type": "string"}, "folha": {"type": "string"},
        "salario_base": {"type": ["number", "null"]}, "base_irrf": {"type": ["number", "null"]},
        "base_inss": {"type": ["number", "null"]}, "fgts": {"type": ["number", "null"]},
        "liquido": {"type": "number", "description": "valor líquido a receber"},
        "itens": {"type": "array", "items": {"type": "object", "properties": {
            "codigo": {"type": "string"}, "descricao": {"type": "string"}, "valor": {"type": "number"},
            "provento": {"type": "boolean", "description": "true = vencimento/provento; false = desconto"}},
            "required": ["descricao", "valor", "provento"]}},
    },
    "required": ["ano", "mes", "liquido", "itens"],
}


def _ler_ia(nome: str, dados: bytes) -> dict:
    """Layout que o app não conhece (ou foto): a IA devolve as verbas; a classificação é a mesma do app."""
    from core import ia, leitores
    if not ia.chave():
        raise ValueError("Holerite em formato desconhecido e a IA não está configurada.")
    if nome.lower().endswith(".pdf"):
        txt = leitores.texto_pdf(dados)
        imgs = leitores.imagens_pdf(dados) if len(txt.strip()) < 80 else None
    else:
        txt, imgs = None, [leitores._imagem_jpeg(dados)]
    import base64
    cont = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(i).decode()}} for i in (imgs or [])]
    if txt and not imgs:
        cont.append({"type": "text", "text": txt[:30000]})
    sis = ("Leia este holerite (demonstrativo de pagamento) brasileiro e responda SOMENTE chamando a ferramenta. "
           "Liste cada verba uma vez (recibos em duas vias repetem tudo: não duplique). Valores positivos.")
    d = leitores._tentar({"max_tokens": 4000, "system": sis, "messages": [{"role": "user", "content": cont}]}
                         | leitores._ferramenta("holerite", _CAMPOS_IA, "Verbas do holerite"))
    itens = [{"codigo": str(x.get("codigo") or ""), "descricao": x["descricao"], "valor": float(x["valor"]),
              "provento": bool(x["provento"]), "classe": classificar(x["descricao"], bool(x["provento"])),
              "variavel": bool(x["provento"]) and variavel(x["descricao"])} for x in d.get("itens") or []]
    return {"ano": int(d["ano"]), "mes": int(d["mes"]), "empresa": d.get("empresa"), "cnpj": d.get("cnpj"),
            "folha": d.get("folha") or "Mensal", "salario_base": d.get("salario_base"),
            "base_irrf": d.get("base_irrf"), "base_inss": d.get("base_inss"), "fgts": d.get("fgts"),
            "liquido": d.get("liquido"), "itens": itens, "arquivo": nome,
            "chave": hashlib.sha1(dados).hexdigest(), "lido_pela_ia": True}


def ler_holerite(nome: str, dados: bytes) -> dict:
    """Layouts conhecidos pela posição das colunas; o resto (ou foto), pela IA."""
    if nome.lower().endswith(".pdf"):
        try:
            return _ler_layout(nome, dados)
        except ValueError:
            pass
    return _ler_ia(nome, dados)


# ---------------------------------------------------------------------------
# fixo × variável (comissão) — para o fluxo de caixa usar só o que é certo
# ---------------------------------------------------------------------------
INSS_2026 = [(1621.00, .075), (2902.84, .09), (4354.27, .12), (8475.55, .14)]
NOMES_SALARIO = ("Salário · adiantamento", "Salário · 2ª parte")
NOME_COMISSAO = "Comissão (previsão)"


def inss_mensal(base: float) -> float:
    total, ant = 0.0, 0.0
    for teto, aliq in INSS_2026:
        if base <= ant:
            break
        total += (min(base, teto) - ant) * aliq
        ant = teto
    return round(total, 2)


def irrf_mensal(rend_tributavel: float, base: float) -> float:
    """Tabela mensal 2026 + redução da Lei 15.270/2025 (zera até R$ 5.000; cai linearmente até R$ 7.350)."""
    lim, aliq, ded = next(f for f in TABELA_MENSAL if base <= f[0])
    imposto = max(0.0, base * aliq - ded)
    if rend_tributavel <= 5000:
        reducao = imposto
    elif rend_tributavel <= 7350:
        reducao = max(0.0, 978.62 - 0.133145 * rend_tributavel)
    else:
        reducao = 0.0
    return round(max(0.0, imposto - reducao), 2)


def fixo_variavel(itens, liquido: float) -> dict:
    """Separa o que entra na conta (adiantamento + líquido) em parte fixa e parte variável (comissão).
    Fixo líquido = verbas fixas − INSS/IR que incidiriam só sobre elas − outros descontos do mês."""
    if isinstance(itens, str):
        itens = json.loads(itens)
    prov = [i for i in itens if i["provento"] and i["classe"] != "ignorar"]
    var_bruto = sum(float(i["valor"]) for i in prov if i.get("variavel") or variavel(i["descricao"]))
    fixo = [i for i in prov if not (i.get("variavel") or variavel(i["descricao"]))]
    fixo_bruto = sum(float(i["valor"]) for i in fixo)
    fixo_trib = sum(float(i["valor"]) for i in fixo if i["classe"] == "tributavel")
    inss_f = inss_mensal(fixo_trib)
    irrf_f = irrf_mensal(fixo_trib, fixo_trib - inss_f)
    outros = sum(float(i["valor"]) for i in itens if not i["provento"]
                 and i["classe"] in ("saude", "outros", "pensao", "pgbl"))
    adto = sum(float(i["valor"]) for i in itens if not i["provento"] and i["classe"] == "pagamento"
               and "adiant" in _sa(i["descricao"]))
    recebido = round(adto + float(liquido or 0), 2)
    fixo_liq = round(fixo_bruto - inss_f - irrf_f - outros, 2)
    if not var_bruto:
        fixo_liq = recebido                       # sem comissão: tudo é fixo, sem estimativa
    return {"fixo_bruto": round(fixo_bruto, 2), "inss_fixo": inss_f, "irrf_fixo": irrf_f, "outros": round(outros, 2),
            "fixo_liquido": min(fixo_liq, recebido), "variavel_bruto": round(var_bruto, 2),
            "variavel_liquido": round(max(0.0, recebido - fixo_liq), 2), "adiantamento": round(adto, 2),
            "liquido": float(liquido or 0), "recebido": recebido}


def efetivar(u, h: dict) -> list[str]:
    """Holerite chegou: os previstos do salário daquele mês (Contas fixas) viram recebidos com o valor real, e a
    previsão de comissão vira a comissão efetiva. Só mexe no que existir; devolve o que fez.
    A 2ª parte/comissão de um mês é a 1ª prevista DEPOIS do adiantamento daquele mês (cai no dia 25 do mesmo
    mês para uns, no dia 5 do seguinte para outros)."""
    from datetime import date
    from sqlalchemy import text
    d = fixo_variavel(h["itens"], h.get("liquido"))
    m = h["ano"] * 100 + h["mes"]
    feito = []

    def _br(v):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    with db.transacao() as s:
        adto = s.execute(text("""select id, data_vencimento, status::text as st from lancamentos
                                  where dono_id = :u and mes_ref = :m and tipo = 'receita' and lower(descricao) = lower(:d)
                                  order by data_vencimento limit 1"""),
                         {"u": u["id"], "m": m, "d": NOMES_SALARIO[0]}).first()
        desde = adto.data_vencimento if adto else date(h["ano"], h["mes"], 1)
        if adto and adto.st == "previsto" and d["adiantamento"] > 0:
            s.execute(text("""update lancamentos set valor = :v, status = 'pago', atualizado_em = now(),
                                     data_pagamento = least(data_vencimento, current_date) where id = :i"""),
                      {"v": d["adiantamento"], "i": adto.id})
            feito.append(f"{NOMES_SALARIO[0]} {adto.data_vencimento:%d/%m}: {_br(d['adiantamento'])}")
        for nome, valor in ((NOMES_SALARIO[1], round(d["fixo_liquido"] - d["adiantamento"], 2)),
                            (NOME_COMISSAO, d["variavel_liquido"])):
            if valor <= 0:
                continue
            r = s.execute(text("""update lancamentos set valor = :v, status = 'pago', atualizado_em = now(),
                                         data_pagamento = least(data_vencimento, current_date)
                                   where id = (select id from lancamentos where dono_id = :u and tipo = 'receita'
                                                 and status = 'previsto' and lower(descricao) = lower(:d)
                                                 and data_vencimento > :desde
                                                 and data_vencimento <= cast(:desde as date) + 45
                                               order by data_vencimento limit 1)
                                   returning descricao, data_vencimento"""),
                          {"v": valor, "u": u["id"], "d": nome, "desde": desde}).first()
            if r:
                feito.append(f"{r.descricao} {r.data_vencimento:%d/%m}: {_br(valor)}")
    return feito


# ---------------------------------------------------------------------------
# banco
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _tabela() -> bool:
    db.executar("""create table if not exists holerites (
        id uuid primary key default gen_random_uuid(),
        dono_id uuid not null references usuarios(id) on delete cascade,
        ano int not null, mes int not null, folha text not null default 'Mensal',
        empresa text, cnpj text, salario_base numeric(14,2), base_irrf numeric(14,2), base_inss numeric(14,2),
        fgts numeric(14,2), liquido numeric(14,2), itens jsonb not null, arquivo text, chave text,
        criado_em timestamptz not null default now(),
        unique (dono_id, ano, mes, folha))""")
    return True


def salvar(u, h: dict):
    _tabela()
    db.executar("""insert into holerites (dono_id, ano, mes, folha, empresa, cnpj, salario_base, base_irrf, base_inss,
                       fgts, liquido, itens, arquivo, chave)
                   values (:u, :ano, :mes, :folha, :empresa, :cnpj, :salario_base, :base_irrf, :base_inss, :fgts,
                       :liquido, cast(:itens as jsonb), :arquivo, :chave)
                   on conflict (dono_id, ano, mes, folha) do update set empresa = excluded.empresa,
                       cnpj = excluded.cnpj, salario_base = excluded.salario_base, base_irrf = excluded.base_irrf,
                       base_inss = excluded.base_inss, fgts = excluded.fgts, liquido = excluded.liquido,
                       itens = excluded.itens, arquivo = excluded.arquivo, chave = excluded.chave""",
                u=u["id"], **{k: h.get(k) for k in ["ano", "mes", "folha", "empresa", "cnpj", "salario_base",
                                                    "base_irrf", "base_inss", "fgts", "liquido", "arquivo",
                                                    "chave"]},
                itens=json.dumps(h["itens"], ensure_ascii=False))


def excluir(u, hid):
    _tabela()
    db.executar("delete from holerites where id = :i and dono_id = :u", i=hid, u=u["id"])


def holerites(u, ano: int) -> pd.DataFrame:
    _tabela()
    return db.consultar("""select id, ano, mes, folha, empresa, cnpj, salario_base, base_irrf, fgts, liquido,
                                  itens, arquivo
                             from holerites where dono_id = :u and ano = :a order by mes, folha""",
                        u=u["id"], a=ano)


def anos(u) -> list[int]:
    _tabela()
    df = db.consultar("select distinct ano from holerites where dono_id = :u order by ano desc", u=u["id"])
    return [int(a) for a in df["ano"]] if not df.empty else []


# ---------------------------------------------------------------------------
# cálculo
# ---------------------------------------------------------------------------
def _somas(itens) -> dict:
    if isinstance(itens, str):
        itens = json.loads(itens)
    s = {k: 0.0 for k in CLASSES}
    for i in itens:
        s[i["classe"]] = s.get(i["classe"], 0.0) + float(i["valor"])
    s["decimo"] -= s.pop("decimo_adto", 0.0)   # adiantamento do 13º descontado em dezembro já entrou em novembro
    return s


def imposto_tabela(base: float, tabela=TABELA_ANUAL) -> float:
    for teto, aliq, ded in tabela:
        if base <= teto:
            return max(0.0, round(base * aliq - ded, 2))
    return 0.0


def por_mes(df: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for r in df.itertuples():
        s = _somas(r.itens)
        linhas.append({"mes": int(r.mes), "folha": r.folha, **s, "liquido": float(r.liquido or 0),
                       "fgts": float(r.fgts or 0), "salario_base": float(r.salario_base or 0), "id": r.id,
                       "empresa": r.empresa, "cnpj": r.cnpj})
    return pd.DataFrame(linhas)


def resumo(df_mes: pd.DataFrame, projetar=True, dependentes=0, outras_deducoes=0.0) -> dict:
    """Totais do ano (com projeção dos meses que faltam, se pedir) e as duas formas de declarar."""
    if df_mes.empty:
        return {}
    real = df_mes.groupby("mes").sum(numeric_only=True)
    tot = real.sum()
    meses_com = sorted(set(df_mes["mes"]))
    proj = {k: 0.0 for k in ["tributavel", "inss", "irrf", "saude"]}
    decimo_proj = 0.0
    if projetar and meses_com and max(meses_com) < 12:
        # mês "normal" mais recente (sem férias/PLR): repete até dezembro
        base = df_mes[(df_mes["isento"] == 0) & (df_mes["plr"] == 0)].sort_values("mes").tail(1)
        if not base.empty:
            b = base.iloc[0]
            faltam = 12 - max(meses_com)
            for k in proj:
                proj[k] = float(b[k]) * faltam
    if projetar and tot.get("decimo", 0) == 0:
        sal = float(df_mes.sort_values("mes")["salario_base"].iloc[-1] or 0)
        decimo_proj = sal
    trib = float(tot["tributavel"]) + proj["tributavel"]
    inss = float(tot["inss"]) + proj["inss"]
    irrf = float(tot["irrf"]) + proj["irrf"]
    saude = float(tot["saude"]) + proj["saude"]
    pgbl = min(float(tot["pgbl"]), trib * .12)
    ded_completa = inss + saude + pgbl + float(tot["pensao"]) + dependentes * DEDUCAO_DEPENDENTE + outras_deducoes
    base_c = max(0.0, trib - ded_completa)
    desc_s = min(trib * .20, LIMITE_SIMPLIFICADO)
    base_s = max(0.0, trib - desc_s)
    dev_c, dev_s = imposto_tabela(base_c), imposto_tabela(base_s)
    decimo = float(tot["decimo"]) + decimo_proj
    inss13 = float(tot["inss_13"]) or (min(decimo * .14, float(tot["inss"]) / max(len(meses_com), 1))
                                        if decimo_proj else 0.0)
    ir13 = float(tot["irrf_13"]) or (imposto_tabela(decimo - inss13, TABELA_MENSAL) if decimo_proj else 0.0)
    return {
        "meses": meses_com, "projetado": any(v for v in proj.values()) or bool(decimo_proj),
        "tributavel": trib, "isento": float(tot["isento"]), "nao_tributavel": float(tot["nao_tributavel"]),
        "plr": float(tot["plr"]), "irrf_plr": float(tot["irrf_plr"]), "decimo": decimo, "inss_13": inss13,
        "irrf_13": ir13, "decimo_projetado": bool(decimo_proj), "inss": inss, "irrf": irrf, "saude": saude,
        "pgbl": pgbl, "fgts": float(tot["fgts"]), "liquido": float(tot["liquido"]),
        "completa": {"deducoes": ded_completa, "base": base_c, "devido": dev_c, "saldo": round(dev_c - irrf, 2)},
        "simplificada": {"deducoes": desc_s, "base": base_s, "devido": dev_s, "saldo": round(dev_s - irrf, 2)},
        "melhor": "simplificada" if dev_s <= dev_c else "completa",
        "reducao_possivel": trib <= TETO_REDUCAO_ANUAL,
    }


def estimar_13(salario: float, inss_mensal: float) -> dict:
    """1ª parcela (nov, sem desconto) e 2ª parcela (dez, com INSS e IR do 13º)."""
    p1 = round(salario / 2, 2)
    inss = round(min(salario * .14, inss_mensal or salario * .14), 2)
    ir = imposto_tabela(salario - inss, TABELA_MENSAL)
    return {"bruto": salario, "p1": p1, "inss": inss, "ir": ir, "p2": round(salario - p1 - inss - ir, 2)}

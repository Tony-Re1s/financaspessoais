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


def classificar(desc: str, provento: bool) -> str:
    d = _sa(desc)
    treze = bool(re.search(r"\b13|decimo", d))
    if provento:
        if re.search(r"devolucao provis|contrapartida", d):
            return "ignorar"
        if re.search(r"reembolso|ajuda de custo|indeniza|diaria", d):
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
    if re.search(r"adiantamento|liquido de|liquido", d):
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


def ler_holerite(nome: str, dados: bytes) -> dict:
    """Demonstrativo de pagamento (layout 'Verba / Descrição / Qtde / Vencimento / Descontos')."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        palavras = [w for p in pdf.pages for w in p.extract_words()]
        texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    linhas: dict[int, list] = {}
    for w in palavras:
        linhas.setdefault(round(w["top"]), []).append(w)
    col = {}
    for w in palavras:
        if w["text"] in ("Qtde", "Vencimento", "Descontos") and w["text"] not in col:
            col[w["text"]] = w["x1"]
    if "Vencimento" not in col or "Descontos" not in col:
        raise ValueError("Não reconheci o layout do holerite (colunas Vencimento/Descontos).")

    m = re.search(r"Refer[êe]ncia\s+(\d{1,2})/(\d{4})", texto)
    if not m:
        raise ValueError("Não achei o mês de referência no holerite.")
    mes, ano = int(m.group(1)), int(m.group(2))
    cnpj = (re.search(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto) or [None, None])[1]
    emp = re.search(r"Empresa\s+\d+\s+(.+?)\s+C\.N\.P\.J", texto)
    folha = re.search(r"Folha\s+\d+\s+(.+?)\s+Refer", texto)
    sal = re.search(r"Sal[áa]rio\s+([\d.]+,\d{2})", texto)

    itens = []
    for top in sorted(linhas):
        ws = sorted(linhas[top], key=lambda w: w["x0"])
        if not ws or not ws[0]["text"].isdigit() or ws[0]["x0"] > 40:
            continue
        valores = [w for w in ws[1:] if _RX_VALOR.match(w["text"])]
        desc = " ".join(w["text"] for w in ws[1:] if w not in valores).strip()
        for v in valores:
            dist = {k: abs(v["x1"] - x) for k, x in col.items()}
            onde = min(dist, key=dist.get)
            if onde == "Qtde":
                continue
            prov = onde == "Vencimento"
            itens.append({"codigo": ws[0]["text"], "descricao": desc, "valor": _num(v["text"]),
                          "provento": prov, "classe": classificar(desc, prov)})
    if not itens:
        raise ValueError("Não encontrei as verbas do holerite.")

    def _base(rot):
        mm = re.search(rot + r"\s*:?\s*([\d.]+,\d{2})", texto)
        return _num(mm.group(1)) if mm else None

    return {"ano": ano, "mes": mes, "empresa": emp.group(1).strip() if emp else None, "cnpj": cnpj,
            "folha": folha.group(1).strip() if folha else "Mensal", "salario_base": _num(sal.group(1)) if sal else None,
            "base_irrf": _base(r"Base IRRF"), "base_inss": _base(r"Base INSS"), "fgts": _base(r"Dep\.FGTS"),
            "liquido": _base(r"L[íi]quido(?!\s+de)"), "itens": itens, "arquivo": nome,
            "chave": hashlib.sha1(dados).hexdigest()}


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

"""Importação de faturas de cartão.

Cada banco tem um leitor (LEITORES). Todos devolvem a mesma estrutura (Fatura),
e daí para frente o fluxo é um só: conferir com o que já está lançado, gerar as
parcelas futuras e gravar. Para um banco novo, basta escrever um leitor.

Conferência (para não duplicar):
  1. linha já importada antes (mesma chave)            -> "já importada"
  2. mesmo cartão, mesmo mês de vencimento, mesmo valor
     (planilha, Apple Pay, lançamento manual)          -> "já lançada"
     empate de valor: ganha quem tem parcela igual e nome/data mais parecidos.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import io
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

import openpyxl
import pandas as pd
from sqlalchemy import text

from core import db
from core.fmt import add_meses, mes_ref


# ---------------------------------------------------------------------------
# Estrutura comum
# ---------------------------------------------------------------------------
@dataclass
class Linha:
    data: date
    descricao: str
    valor: float                      # positivo = compra; negativo = estorno/crédito
    parcela_num: int | None = None
    parcela_total: int | None = None
    titular: bool = True
    portador: str | None = None
    final: str | None = None          # últimos 4 dígitos do cartão usado
    tipo_cartao: str | None = None    # Físico, Wallet, Virtual…
    extra: str | None = None          # ex.: valor em dólar


@dataclass
class Fatura:
    banco: str
    formato: str
    linhas: list[Linha]
    vencimento: date | None = None
    final: str | None = None          # final do cartão principal (do cabeçalho)
    total_banco: float | None = None
    nome_cartao: str | None = None
    avisos: list[str] = field(default_factory=list)


PAGAMENTO = re.compile(r"^(pagamento|pagto|pgto)\b", re.I)


def _num_br(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("R$", "").replace("\xa0", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parcela(txt: str | None) -> tuple[int | None, int | None]:
    """'Parcela 4 de 6' / 'Parcela 4/6' / '- 2/2' -> (4, 6)."""
    if not txt:
        return None, None
    m = re.search(r"(\d{1,2})\s*(?:de|/)\s*(\d{1,2})\s*$", str(txt).strip(), re.I)
    if not m:
        return None, None
    n, t = int(m.group(1)), int(m.group(2))
    return (n, t) if 1 <= n <= t <= 99 else (None, None)


def _limpa(desc: str) -> str:
    return re.sub(r"\s{2,}", " ", str(desc or "")).strip()


# ---------------------------------------------------------------------------
# Leitores
# ---------------------------------------------------------------------------
def _ler_itau_xlsx(nome: str, dados: bytes) -> Fatura:
    """'fatura-aberta-final_XXXX-mes.xlsx' do app/site do Itaú (Latam, Uniclass, Personnalité…)."""
    ws = openpyxl.load_workbook(io.BytesIO(dados), data_only=True).worksheets[0]
    linhas, cab, venc, final, total, nome_cartao = [], None, None, None, None, None
    rows = list(ws.iter_rows(values_only=True))
    for i, r in enumerate(rows):
        vals = [v for v in r]
        txt = [str(v).strip() if v is not None else "" for v in vals]
        if "Cartão" in txt and "Vencimento" in txt and i + 1 < len(rows):
            prox = rows[i + 1]
            nome_cartao = str(prox[txt.index("Cartão")] or "")
            m = re.search(r"final\s*(\d{4})", nome_cartao, re.I)
            final = m.group(1) if m else None
            v = prox[txt.index("Vencimento")]
            venc = v.date() if isinstance(v, datetime) else v
            if "Valor (parcial)" in txt or "Valor" in txt:
                k = txt.index("Valor (parcial)") if "Valor (parcial)" in txt else txt.index("Valor")
                total = _num_br(prox[k])
        if "Data" in txt and "Lançamento" in txt and "Valor" in txt:
            cab = {n: txt.index(n) for n in txt if n}
            continue
        if cab is None:
            continue
        d = vals[cab["Data"]]
        if not isinstance(d, (datetime, date)):
            continue
        valor = _num_br(vals[cab["Valor"]])
        if valor is None:
            continue
        pn, pt = _parcela(vals[cab["Parcelamento"]] if "Parcelamento" in cab else None)
        tit = str(vals[cab["Titularidade"]] or "Titular") if "Titularidade" in cab else "Titular"
        num = str(vals[cab["Número do cartão"]] or "") if "Número do cartão" in cab else ""
        extra_i = cab["Valor"] + 1
        extra = vals[extra_i] if extra_i < len(vals) and vals[extra_i] and extra_i not in cab.values() else None
        linhas.append(Linha(
            data=d.date() if isinstance(d, datetime) else d, descricao=_limpa(vals[cab["Lançamento"]]),
            valor=valor, parcela_num=pn, parcela_total=pt, titular=tit.lower().startswith("titular"),
            portador=vals[cab["Nome"]] if "Nome" in cab else None, final=num[-4:] or None,
            tipo_cartao=vals[cab["Tipo do cartão"]] if "Tipo do cartão" in cab else None,
            extra=re.sub(r"\s+", " ", str(extra)).strip() if extra else None))
    if cab is None:
        raise ValueError("Não achei a tabela de lançamentos (Data / Lançamento / Valor) na fatura do Itaú.")
    return Fatura("Itaú", "itau_xlsx", linhas, venc, final, total, nome_cartao)


def _ler_nubank_csv(nome: str, dados: bytes) -> Fatura:
    """CSV exportado do app Nubank: date,title,amount (Nubank_AAAA-MM-DD.csv = vencimento)."""
    texto = dados.decode("utf-8-sig", errors="replace")
    linhas = []
    for r in csv.DictReader(io.StringIO(texto)):
        valor = _num_br((r.get("amount") or "").replace(" ", ""))
        if valor is None or not r.get("date"):
            continue
        titulo = _limpa(r.get("title"))
        pn, pt = _parcela(titulo)
        desc = re.sub(r"\s*-\s*(Parcela\s*)?\d{1,2}/\d{1,2}\s*$", "", titulo, flags=re.I).strip()
        linhas.append(Linha(data=date.fromisoformat(r["date"][:10]), descricao=desc,
                            valor=valor, parcela_num=pn, parcela_total=pt))
    m = re.search(r"(\d{4}-\d{2}-\d{2})", nome or "")
    venc = date.fromisoformat(m.group(1)) if m else None
    fat = Fatura("Nubank", "nubank_csv", linhas, venc)
    if venc is None:
        fat.avisos.append("O nome do arquivo não traz a data de vencimento; confira abaixo.")
    return fat


def _ofx_tags(bloco: str) -> dict:
    return {m.group(1).upper(): m.group(2).strip() for m in re.finditer(r"<(\w+)>([^<\r\n]*)", bloco)}


def _ofx_data(v: str | None) -> date | None:
    return date(int(v[:4]), int(v[4:6]), int(v[6:8])) if v and len(v) >= 8 and v[:8].isdigit() else None


def _ler_ofx(nome: str, dados: bytes) -> Fatura:
    """OFX de cartão (Nubank e outros): STMTTRN com DTPOSTED / TRNAMT / MEMO. DEBIT negativo = compra."""
    texto = dados.decode("cp1252", errors="replace")
    org = (re.search(r"<ORG>([^<\r\n]+)", texto) or [None, ""])[1].strip()
    banco = "Nubank" if re.search(r"\bnu\b|nubank", org, re.I) else (org.title() or "Cartão")
    linhas = []
    for bloco in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", texto, re.S | re.I):
        t = _ofx_tags(bloco)
        valor, d = _num_br(t.get("TRNAMT")), _ofx_data(t.get("DTPOSTED"))
        if valor is None or d is None:
            continue
        memo = _limpa(t.get("MEMO") or t.get("NAME"))
        pn, pt = _parcela(memo)
        desc = re.sub(r"\s*-\s*(NuPay\s*-\s*)?(Parcela\s*)?\d{1,2}/\d{1,2}\s*$", "", memo, flags=re.I)
        desc = re.sub(r"\s*-\s*NuPay\s*$", "", desc, flags=re.I).strip()
        linhas.append(Linha(data=d, descricao=desc or memo, valor=-valor, parcela_num=pn, parcela_total=pt))
    bal = re.search(r"<LEDGERBAL>.*?<BALAMT>([^<\r\n]+)", texto, re.S | re.I)
    total = -_num_br(bal.group(1)) if bal and _num_br(bal.group(1)) is not None else None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", nome or "")
    venc = date.fromisoformat(m.group(1)) if m else None
    fat = Fatura(banco, "ofx", linhas, venc, total_banco=total)
    if venc is None:
        fat.avisos.append("O arquivo não traz a data de vencimento; confira abaixo.")
    return fat


def _e_ofx(nome, dados):
    return nome.lower().endswith(".ofx") or b"<OFX>" in dados[:3000].upper()


def _e_itau(nome, dados):
    return nome.lower().endswith(".xlsx") and b"xl/" in dados[:4000] and "fatura" in nome.lower()


def _e_nubank(nome, dados):
    cab = dados[:200].decode("utf-8-sig", errors="ignore").lower()
    return nome.lower().endswith(".csv") and cab.startswith("date,title,amount")


# (nome do banco, detecta(nome, bytes), ler(nome, bytes))
LEITORES = [
    ("Itaú (.xlsx)", _e_itau, _ler_itau_xlsx),
    ("Nubank (.csv)", _e_nubank, _ler_nubank_csv),
    ("OFX de cartão — Nubank e outros (.ofx)", _e_ofx, _ler_ofx),
]


def ler(nome: str, dados: bytes) -> Fatura:
    for _, detecta, leitor in LEITORES:
        try:
            if detecta(nome, dados):
                return leitor(nome, dados)
        except ValueError:
            raise
    # Itaú com nome de arquivo diferente: tenta pelo conteúdo
    if nome.lower().endswith(".xlsx"):
        try:
            return _ler_itau_xlsx(nome, dados)
        except Exception:  # noqa: BLE001
            pass
    raise FormatoDesconhecido(nome)


class FormatoDesconhecido(Exception):
    pass


# ---------------------------------------------------------------------------
# Conferência com o que já existe
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"(ifd|mp|pg|dl|htm|ec|pp)\s*\*", " ", s)
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def _parecido(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    if ta & tb:
        r = max(r, 0.6 + 0.4 * len(ta & tb) / max(len(ta), len(tb)))
    return r


def chave(conta_id, ln: Linha) -> str:
    base = f"fat|{conta_id}|{ln.data}|{_norm(ln.descricao)}|{ln.valor:.2f}|{ln.parcela_num}/{ln.parcela_total}|{ln.final}"
    return hashlib.sha1(base.encode()).hexdigest()


def preparar(u, conta_id, fat: Fatura, vencimento: date, incluir_adicionais=False) -> pd.DataFrame:
    """Uma linha por lançamento da fatura, com a situação de cada uma e o que fazer."""
    mes = mes_ref(vencimento)
    existentes = db.consultar("""
        select id, descricao, valor, data_compra, parcela_num, parcela_total, chave_importacao,
               origem::text as origem, categoria_id
          from lancamentos
         where dono_id = :u and conta_id = :c and mes_ref = :m and status <> 'cancelado'""",
        u=u["id"], c=conta_id, m=mes)
    ja_chaves = set(existentes["chave_importacao"].dropna()) if not existentes.empty else set()

    # estornos que anulam uma compra da mesma fatura
    negativos = {(_norm(l.descricao), round(-l.valor, 2)) for l in fat.linhas if l.valor < 0}
    estornadas = set()

    regs = []
    for i, ln in enumerate(fat.linhas):
        k = chave(conta_id, ln)
        r = dict(i=i, data=ln.data, descricao=ln.descricao, valor=ln.valor,
                 parcela=f"{ln.parcela_num}/{ln.parcela_total}" if ln.parcela_num else "",
                 portador=ln.portador or "", titular=ln.titular, final=ln.final, extra=ln.extra or "",
                 chave=k, existente_id=None, existente_desc=None, categoria_id=None)
        if PAGAMENTO.match(ln.descricao) and ln.valor < 0:
            r["situacao"] = "pagamento"
        elif ln.valor < 0:
            r["situacao"] = "estorno"
        elif (_norm(ln.descricao), round(ln.valor, 2)) in negativos and (_norm(ln.descricao), ln.valor) not in estornadas:
            estornadas.add((_norm(ln.descricao), ln.valor))
            r["situacao"] = "estornada"
        elif not ln.titular and not incluir_adicionais:
            r["situacao"] = "adicional"
        elif k in ja_chaves:
            r["situacao"] = "ja_importada"
        else:
            r["situacao"] = "nova"
        regs.append(r)

    # casa as "novas" com lançamentos já existentes no mesmo mês (parceladas primeiro)
    pool = existentes[~existentes["chave_importacao"].isin(
        [r["chave"] for r in regs])] if not existentes.empty else existentes
    livres = {row.id: row for row in pool.itertuples()}
    candidatas = sorted([r for r in regs if r["situacao"] == "nova"],
                        key=lambda r: (r["parcela"] == "", -r["valor"]))
    for r in candidatas:
        ln = fat.linhas[r["i"]]
        melhor, nota = None, -1.0
        for eid, e in livres.items():
            if abs(float(e.valor) - ln.valor) > 0.011:
                continue
            s = _parecido(ln.descricao, e.descricao)
            if ln.parcela_num and e.parcela_num == ln.parcela_num and e.parcela_total == ln.parcela_total:
                s += 1.0
            if e.data_compra is not None and pd.notna(e.data_compra):
                dias = abs((pd.Timestamp(e.data_compra).date() - ln.data).days)
                s += 0.8 if dias <= 3 else 0.0
            if s > nota:
                melhor, nota = eid, s
        if melhor is not None:
            e = livres.pop(melhor)
            r.update(situacao="ja_lancada", existente_id=melhor, existente_desc=e.descricao,
                     origem_existente=e.origem)

    # sugestão de categoria (pelo histórico do mesmo nome)
    hist = db.consultar("""select distinct on (lower(descricao)) lower(descricao) as d, categoria_id
                             from lancamentos where dono_id = :u and categoria_id is not null
                            order by lower(descricao), criado_em desc""", u=u["id"])
    mapa = dict(zip(hist["d"], hist["categoria_id"])) if not hist.empty else {}
    norm_mapa = {_norm(d): c for d, c in mapa.items()}
    for r in regs:
        if r["situacao"] == "nova":
            r["categoria_id"] = mapa.get(r["descricao"].lower()) or norm_mapa.get(_norm(r["descricao"]))
    return pd.DataFrame(regs)


def plano_futuras(u, conta_id, fat: Fatura, regs: pd.DataFrame, vencimento: date) -> list[dict]:
    """Parcelas que ainda vão vencer (n+1..N) e não existem no app."""
    out = []
    for r in regs.itertuples():
        ln = fat.linhas[r.i]
        if r.situacao not in ("nova", "ja_lancada") or not ln.parcela_num or ln.parcela_num >= ln.parcela_total:
            continue
        nomes = [ln.descricao] + ([r.existente_desc] if r.existente_desc else [])
        for k in range(1, ln.parcela_total - ln.parcela_num + 1):
            venc_k = add_meses(vencimento, k)
            ja = db.um("""select 1 from lancamentos
                           where dono_id = :u and conta_id = :c and mes_ref = :m and status <> 'cancelado'
                             and abs(valor - :v) < 0.011
                             and (lower(descricao) = any(:nomes) or parcela_num = :pn)""",
                       u=u["id"], c=conta_id, m=mes_ref(venc_k), v=ln.valor,
                       nomes=[n.lower() for n in nomes], pn=ln.parcela_num + k)
            if ja:
                continue
            futura = Linha(**{**ln.__dict__, "parcela_num": ln.parcela_num + k})
            out.append(dict(i=r.i, descricao=ln.descricao, valor=ln.valor, data_compra=ln.data,
                            data_vencimento=venc_k, parcela_num=ln.parcela_num + k,
                            parcela_total=ln.parcela_total, chave=chave(conta_id, futura)))
    return out


def gravar(u, conta_id, fat: Fatura, vencimento: date, novas: pd.DataFrame, futuras: list[dict],
           nome_arquivo: str, vincular: pd.DataFrame | None = None) -> dict:
    """novas: linhas escolhidas (com categoria_id). futuras: de plano_futuras().
    vincular: linhas 'ja_lancada' — o lançamento que já estava no app (planilha, Apple Pay…) ganha a data da
    compra, a parcela e a chave da fatura; as parcelas seguintes que vieram da planilha são numeradas."""
    grupos: dict[int, uuid.UUID] = {}
    n = nv = 0
    with db.transacao() as s:
        for r in (vincular.itertuples() if vincular is not None and not vincular.empty else []):
            ln = fat.linhas[r.i]
            g = None
            if ln.parcela_num:
                atual = s.execute(text("select grupo_parcela from lancamentos where id = :i"),
                                  dict(i=r.existente_id)).scalar()
                g = grupos.setdefault(r.i, atual or uuid.uuid4())
            nv += s.execute(text("""
                update lancamentos set data_compra = coalesce(data_compra, :dc),
                       parcela_num = coalesce(parcela_num, :pn), parcela_total = coalesce(parcela_total, :pt),
                       grupo_parcela = coalesce(grupo_parcela, :g), chave_importacao = coalesce(chave_importacao, :k),
                       atualizado_em = now()
                 where id = :i and dono_id = :u"""),
                dict(dc=ln.data, pn=ln.parcela_num, pt=ln.parcela_total, g=g, k=r.chave, i=r.existente_id,
                     u=u["id"])).rowcount
            if ln.parcela_num and ln.parcela_num < ln.parcela_total:
                seguintes = s.execute(text("""
                    select id from lancamentos
                     where dono_id = :u and conta_id = :c and mes_ref > :m and status <> 'cancelado'
                       and parcela_num is null and abs(valor - :v) < 0.011 and lower(descricao) = lower(:d)
                     order by mes_ref limit :q"""),
                    dict(u=u["id"], c=conta_id, m=mes_ref(vencimento), v=ln.valor, d=r.existente_desc,
                         q=ln.parcela_total - ln.parcela_num)).scalars().all()
                for k, lid in enumerate(seguintes, start=1):
                    s.execute(text("""update lancamentos set parcela_num = :pn, parcela_total = :pt,
                                             grupo_parcela = :g, data_compra = coalesce(data_compra, :dc)
                                       where id = :i"""),
                              dict(pn=ln.parcela_num + k, pt=ln.parcela_total, g=g, dc=ln.data, i=lid))
        def ins(desc, valor, compra, venc, cat, pn, pt, grupo, k):
            r = s.execute(text("""
                insert into lancamentos (dono_id, conta_id, categoria_id, tipo, descricao, valor, data_compra,
                    data_vencimento, forma_pagamento, status, parcela_num, parcela_total, grupo_parcela,
                    origem, chave_importacao)
                values (:u, :c, :cat, 'despesa', :d, :v, :dc, :dv, 'Cartao de Credito', 'previsto',
                    :pn, :pt, :g, 'importacao', :k)
                on conflict do nothing returning id"""),
                dict(u=u["id"], c=conta_id, cat=cat, d=desc, v=valor, dc=compra, dv=venc,
                     pn=pn, pt=pt, g=grupo, k=k)).first()
            return 1 if r else 0

        cat_por_i = {}
        for r in novas.itertuples():
            ln = fat.linhas[r.i]
            g = None
            if ln.parcela_num:
                g = grupos.setdefault(r.i, uuid.uuid4())
            cat = None if r.categoria_id is None or pd.isna(r.categoria_id) else r.categoria_id
            cat_por_i[r.i] = cat
            n += ins(ln.descricao, ln.valor, ln.data, vencimento, cat, ln.parcela_num, ln.parcela_total, g, r.chave)
        nf = 0
        for f in futuras:
            g = grupos.setdefault(f["i"], uuid.uuid4())
            nf += ins(f["descricao"], f["valor"], f["data_compra"], f["data_vencimento"], cat_por_i.get(f["i"]),
                      f["parcela_num"], f["parcela_total"], g, f["chave"])
        s.execute(text("""insert into importacoes (dono_id, conta_id, arquivo, formato, linhas_lidas, linhas_importadas)
                          values (:u, :c, :a, :f, :l, :n)"""),
                  dict(u=u["id"], c=conta_id, a=nome_arquivo, f=fat.formato, l=len(fat.linhas), n=n + nf))
        if fat.final:
            s.execute(text("""update contas set finais_cartao =
                                 trim(both ',' from concat_ws(',', nullif(finais_cartao, ''), :f))
                               where id = :c and dono_id = :u
                                 and coalesce(finais_cartao, '') not like '%' || :f || '%'"""),
                      dict(f=fat.final, c=conta_id, u=u["id"]))
    return {"novas": n, "futuras": nf, "vinculadas": nv}


def conta_sugerida(u, fat: Fatura, contas: pd.DataFrame):
    """Pelo final do cartão (gravado na 1ª importação) ou pelo nome do banco/cartão."""
    cartoes = contas[contas["tipo"] == "cartao_credito"]
    if fat.final and "finais_cartao" in cartoes:
        hit = cartoes[cartoes["finais_cartao"].fillna("").str.contains(fat.final)]
        if not hit.empty:
            return hit.iloc[0]["id"]
    alvo = _norm(f"{fat.nome_cartao or ''} {fat.banco}")
    melhor, nota = None, 0.0
    for r in cartoes.itertuples():
        s = _parecido(alvo, f"{r.nome} {r.instituicao or ''}")
        if s > nota:
            melhor, nota = r.id, s
    return melhor if nota >= 0.6 else None

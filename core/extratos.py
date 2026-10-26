"""Importação de extratos de conta corrente (Itaú .xls, Nubank .csv; outros bancos = novo leitor).

Cada linha do extrato vira uma AÇÃO:
  lancar       -> receita/despesa paga na conta
  transf_saida -> transferência para outra conta sua / aplicação
  transf_entra -> transferência de outra conta sua / resgate de investimento
  fatura       -> pagamento de fatura de cartão: NÃO é gasto (as compras já estão no cartão);
                  só marca a fatura correspondente como paga
  pix_credito  -> 'Pix no crédito' (crédito liberado + pix enviado): se anulam; o gasto está no cartão
Saldos diários do extrato (Itaú) viram saldo informado da conta.

Conciliação (não duplicar):
  - mesma chave de importação                         -> já importada
  - lançamento já existente na conta ou sem conta, mesmo tipo, valor igual (ou ±3% com nome
    parecido), data até 7 dias de diferença (ex.: aluguel da planilha) -> vira PAGO com o valor real
  - transferência própria já criada pelo extrato da outra conta (mesmo valor, até 3 dias)
    -> só liga as duas pontas
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text

from core import db
from core.faturas import _parecido


@dataclass
class Linha:
    data: date
    descricao: str
    valor: float
    ident: str | None = None          # identificador do banco (Nubank)


@dataclass
class Extrato:
    banco: str
    formato: str
    linhas: list[Linha]
    saldos: list[tuple[date, float]] = field(default_factory=list)
    conta_banco: str | None = None    # nº da conta no banco (para reconhecer a conta no app)
    titular: str | None = None        # nome do titular (reconhece transferências entre contas próprias)
    avisos: list[str] = field(default_factory=list)


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()


def _conserta(s: str) -> str:
    """'DISPONÃ\\x8dVEL' -> 'DISPONÍVEL' (UTF-8 lido como latin-1 no .xls do Itaú)."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


# ---------------------------------------------------------------------------
# Leitores
# ---------------------------------------------------------------------------
def _ler_itau_xls(nome: str, dados: bytes) -> Extrato:
    import xlrd
    sh = xlrd.open_workbook(file_contents=dados).sheet_by_index(0)
    linhas, saldos, conta, cab, titular = [], [], None, False, None
    for i in range(sh.nrows):
        r = sh.row_values(i)
        if str(r[0]).strip().lower().startswith("conta"):
            conta = str(r[1]).strip()
        if str(r[0]).strip().lower().startswith("nome"):
            titular = _conserta(str(r[1])).strip()
        if str(r[0]).strip().lower() == "data" and "lan" in str(r[1]).lower():
            cab = True
            continue
        if not cab or not re.match(r"\d{2}/\d{2}/\d{4}", str(r[0])):
            continue
        d = datetime.strptime(r[0], "%d/%m/%Y").date()
        desc = _conserta(str(r[1])).strip()
        if desc.upper().startswith("SALDO"):
            if r[4] not in ("", None):
                saldos.append((d, float(r[4])))
            continue
        if r[3] in ("", None):
            continue
        linhas.append(Linha(d, re.sub(r"\s{2,}", " ", desc), float(r[3])))
    if not cab:
        raise ValueError("Não achei a tabela de lançamentos no extrato do Itaú.")
    return Extrato("Itaú", "itau_xls", linhas, saldos, conta, titular=titular)


def _ler_nubank_conta_csv(nome: str, dados: bytes) -> Extrato:
    txt = dados.decode("utf-8-sig", errors="replace")
    linhas = []
    for r in csv.DictReader(io.StringIO(txt)):
        try:
            d = datetime.strptime(r["Data"].strip(), "%d/%m/%Y").date()
            v = float(r["Valor"].replace(",", "."))
        except (KeyError, ValueError):
            continue
        linhas.append(Linha(d, r.get("Descrição", r.get("Descricao", "")).strip(), v, r.get("Identificador")))
    m = re.search(r"NU_(\d+)", nome or "")
    ex = Extrato("Nubank", "nubank_conta_csv", linhas, [], conta_banco=m.group(1) if m else None)
    ex.avisos.append("O extrato do Nubank não traz saldo — informe o saldo de hoje em Contas correntes "
                     "depois de importar.")
    return ex


def _e_itau_xls(nome, dados):
    return nome.lower().endswith(".xls") and dados[:4] == b"\xd0\xcf\x11\xe0"


def _e_nubank_conta(nome, dados):
    return dados[:120].decode("utf-8-sig", errors="ignore").lower().startswith("data,valor,identificador")


LEITORES = [("Itaú — extrato .xls", _e_itau_xls, _ler_itau_xls),
            ("Nubank — extrato da conta .csv", _e_nubank_conta, _ler_nubank_conta_csv)]


class FormatoDesconhecido(Exception):
    pass


def ler(arquivos: list[tuple[str, bytes]]) -> Extrato:
    """Um ou mais arquivos do MESMO banco/conta (ex.: Nubank set + out)."""
    exs = []
    for nome, dados in arquivos:
        for _, detecta, leitor in LEITORES:
            if detecta(nome, dados):
                exs.append(leitor(nome, dados))
                break
        else:
            raise FormatoDesconhecido(nome)
    if len({e.formato for e in exs}) > 1:
        raise ValueError("Suba um banco por vez.")
    base = exs[0]
    vistos, linhas = set(), []
    for e in exs:
        for ln in e.linhas:
            k = (ln.ident, ln.data, ln.descricao, ln.valor) if ln.ident else None
            if k and k in vistos:
                continue
            vistos.add(k)
            linhas.append(ln)
    saldos = sorted({d: v for e in exs for d, v in e.saldos}.items())
    return Extrato(base.banco, base.formato, sorted(linhas, key=lambda x: x.data), saldos,
                   conta_banco=base.conta_banco, titular=base.titular, avisos=base.avisos)


# ---------------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------------
REGRAS_CATEGORIA = [   # (regex no texto sem acento, caminho da categoria)
    (r"\bIOF\b", "Servicos Financeiros > IOF"),
    (r"NOVA BLUMENAU|VIBRA", "Imovel > Parcela Incorporadora"),
    (r"CAIXA.*HABITA|GCI CAIXA", "Imovel > Evolucao de Obra"),
    (r"F I A P|\bFIAP\b", "Educacao > Pos-graduacao"),
    (r"\bCLARO\b|\bVIVO\b|\bTIM\b", "Moradia > Telecom"),
    (r"LIGUE IMOVEIS|ALUGUEL", "Moradia > Aluguel"),
    (r"PORTOSEG|PORTO SEGURO", "Transporte > Seguro Veicular"),
    (r"IFOOD|IFD|99 ?FOOD|RAPPI", "Alimentacao > Delivery"),
    (r"CARRE|MERCADO|SUPERMERC|SMART BOX|HORTI|ATACAD|ASSAI", "Alimentacao > Supermercado"),
    (r"PADARIA|PAES|PANIFIC|CAFE", "Alimentacao > Padaria e Cafe"),
    (r"MCDONALD|BURGER|CHURRASC|RESTAUR|LANCH|PIZZ", "Alimentacao > Restaurante"),
    (r"FARMA|DROGA|RAIA", "Saude e Bem-estar > Farmacia"),
    (r"ALLPARK|ESTACION|ZONA AZUL|PEDAGIO|SEM PARAR", "Transporte > Estacionamento e Pedagio"),
    (r"POSTO|COMBUST|SHELL|IPIRANGA", "Transporte > Combustivel"),
    (r"UBER|99 ?APP|99POP", "Transporte > App de Transporte"),
    (r"CAP PIC|CAPITALIZ", "Investimentos e Previdencia > Aplicacao"),
    (r"EMPRESTIMO", "Servicos Financeiros > Juros e Multas"),
    (r"TARIFA|CESTA", "Servicos Financeiros > Tarifas Bancarias"),
    (r"LAVANDERIA", "Moradia > Manutencao da Casa"),
    (r"LOTER", "Viagem e Lazer > Entretenimento"),
]
REGRAS_RECEITA = [(r"SALARIO", "Receitas > Salario"), (r"REND PAGO|RENDIMENTO", "Receitas > Rendimentos"),
                  (r"ESTORNO|REEMBOLSO", "Receitas > Reembolso")]


def _padrao_dono(nomes: list[str | None]) -> re.Pattern | None:
    """'José Anthony Reis Lopes' -> casa 'JOSE AN…' (o Itaú corta o nome)."""
    pads = set()
    for nome in nomes:
        t = _sem_acento(nome or "").upper().split()
        if len(t) >= 2:
            pads.add(rf"\b{re.escape(t[0])}\s+{re.escape(t[1][:2])}")
    return re.compile("|".join(sorted(pads)), re.I) if pads else None


def nomes_titular(u, ex: Extrato) -> list[str]:
    r = db.um("select nome, preferencias->>'nome_titular' as t from usuarios where id = :u", u=u["id"])
    return [n for n in [u.get("nome"), r and r["nome"], r and r["t"], ex.titular] if n]


def classificar(ex: Extrato, nomes_dono: list[str]) -> list[dict]:
    dono = _padrao_dono(nomes_dono)
    out = []
    # pix no crédito do Nubank: mesmo identificador com + e −
    ids_credito = {ln.ident for ln in ex.linhas if ln.ident and "adicionado na conta por cartao" in
                   _sem_acento(ln.descricao).lower()}
    for i, ln in enumerate(ex.linhas):
        t = _sem_acento(ln.descricao).upper()
        r = {"i": i, "data": ln.data, "descricao": ln.descricao, "valor": ln.valor, "acao": "lancar",
             "tipo": "receita" if ln.valor > 0 else "despesa", "categoria_path": None}
        if re.match(r"^(FATURA PAGA|PAGAMENTO DE FATURA|PAGTO FATURA|PAG FATURA)", t):
            r["acao"] = "fatura"
        elif ("CREDITO LIBERAD" in t and "PIX" in t) or t.startswith("PIX CARTAO") or \
                (ln.ident and ln.ident in ids_credito):
            r["acao"] = "pix_credito"
        elif re.search(r"RESGATE (COFRINHO|RDB|CDB|CAIXINHA|POUPANCA|APLIC)", t) or t.startswith("RESGATE RDB"):
            r["acao"], r["descricao"] = "transf_entra", f"Resgate de investimento ({ln.descricao})"
        elif re.search(r"^APLICACAO|APLIC(ACAO)? (RDB|CDB|COFRINHO)|GUARDADO NA CAIXINHA", t):
            r["acao"], r["descricao"] = "transf_saida", f"Aplicação ({ln.descricao})"
        elif dono and dono.search(t) and re.search(r"PIX|TRANSF|TED|DOC", t):
            r["acao"] = "transf_entra" if ln.valor > 0 else "transf_saida"
            r["descricao"] = "Transferência entre contas próprias"
        if r["acao"] == "lancar":
            regras = REGRAS_RECEITA if ln.valor > 0 else REGRAS_CATEGORIA
            for pad, cat in regras:
                if re.search(pad, t):
                    r["categoria_path"] = cat
                    break
            if ln.valor > 0 and not r["categoria_path"]:
                r["categoria_path"] = "Receitas > Outras Receitas"
        out.append(r)
    return out


def _limpa_desc(desc: str) -> str:
    """'PIX QRS PAGALEVE FU01/09' -> 'PAGALEVE FU'; 'Compra no débito - MERCADO VIOLETA' -> 'MERCADO VIOLETA'."""
    d = re.sub(r"\d{2}/\d{2}$", "", desc).strip()
    d = re.sub(r"^(PIX (QRS|TRANSF|CARTAO)|PAY|PAG BOLETO|DA)\s+", "", d, flags=re.I)
    d = re.sub(r"^(Compra no débito( via NuPay)?|Pagamento de boleto efetuado|Transferência (enviada|recebida) "
               r"pelo Pix)\s*-\s*", "", d, flags=re.I)
    d = re.split(r"\s+-\s+•", d)[0]
    return d.strip() or desc


def forma(desc: str) -> str:
    t = _sem_acento(desc).upper()
    if "BOLETO" in t:
        return "Boleto"
    if "PIX" in t:
        return "Pix"
    if t.startswith("DA ") or "DEBITO AUT" in t:
        return "Debito em Conta"
    return "Debito em Conta"


# ---------------------------------------------------------------------------
# Preparar (classificar + conciliar)
# ---------------------------------------------------------------------------
def chave(conta_id, ln: Linha, n: int) -> str:
    base = f"ext|{conta_id}|{ln.data}|{ln.ident or _sem_acento(ln.descricao).lower()}|{ln.valor:.2f}|{n}"
    return hashlib.sha1(base.encode()).hexdigest()


def preparar(u, conta_id, ex: Extrato) -> pd.DataFrame:
    regs = classificar(ex, nomes_titular(u, ex))
    # chave: ocorrência n de linhas idênticas no mesmo dia
    cont = {}
    for r in regs:
        ln = ex.linhas[r["i"]]
        k0 = (ln.data, ln.descricao, ln.valor, ln.ident)
        cont[k0] = cont.get(k0, 0) + 1
        r["chave"] = chave(conta_id, ln, cont[k0])
        r["nome_curto"] = _limpa_desc(r["descricao"]) if r["acao"] == "lancar" else r["descricao"]

    ini = min((ln.data for ln in ex.linhas), default=date.today()) - timedelta(days=8)
    fim = max((ln.data for ln in ex.linhas), default=date.today()) + timedelta(days=8)
    ja = set(db.consultar("select chave_importacao from lancamentos where dono_id = :u and chave_importacao = any(:k)",
                          u=u["id"], k=[r["chave"] for r in regs])["chave_importacao"])
    cand = db.consultar("""
        select l.id, l.descricao, l.valor, l.tipo::text as tipo, l.data_vencimento, l.status::text as status,
               l.conta_id, l.conta_destino_id
          from lancamentos l left join contas c on c.id = l.conta_id
         where l.dono_id = :u and l.status <> 'cancelado' and l.data_vencimento between :a and :b
           and (l.conta_id = :c or l.conta_id is null or (l.tipo = 'transferencia' and l.conta_destino_id is null)
                or (l.tipo = 'transferencia' and l.conta_destino_id = :c))
           and coalesce(c.tipo::text, '') <> 'cartao_credito'
           and coalesce(l.chave_importacao, '') <> all(:k)""",
        u=u["id"], c=conta_id, a=ini, b=fim, k=[r["chave"] for r in regs])
    livres = {row.id: row for row in cand.itertuples()}

    for r in regs:
        r.update(situacao="nova", existente_id=None, existente_desc=None, existente_valor=None, liga=None)
        if r["acao"] in ("fatura", "pix_credito"):
            r["situacao"] = r["acao"]
            continue
        if r["chave"] in ja:
            r["situacao"] = "ja_importada"
            continue
        v, d = abs(r["valor"]), r["data"]
        melhor, nota = None, -1.0
        for eid, e in livres.items():
            dias = abs((pd.Timestamp(e.data_vencimento).date() - d).days)
            ev = float(e.valor)
            if r["acao"] in ("transf_entra", "transf_saida"):
                if e.tipo != "transferencia" or abs(ev - v) > 0.011 or dias > 3:
                    continue
                if r["acao"] == "transf_entra":      # a outra ponta saiu de outra conta e ainda não tem destino
                    ok = e.conta_id != conta_id and (e.conta_destino_id is None or e.conta_destino_id == conta_id)
                else:                                # a outra ponta entrou em outra conta e ainda não tem origem
                    ok = e.conta_destino_id != conta_id and (e.conta_id is None or e.conta_id == conta_id)
                if not ok:
                    continue
                s = 2 - dias / 3
            else:
                if e.tipo != r["tipo"] or dias > 7:
                    continue
                sim = _parecido(r["nome_curto"], e.descricao)
                if abs(ev - v) <= 0.011:
                    s = 2 + sim - dias / 10
                elif abs(ev - v) <= 0.03 * v and sim >= 0.5:
                    s = 1 + sim - dias / 10
                else:
                    continue
            if s > nota:
                melhor, nota = eid, s
        if melhor is not None:
            e = livres.pop(melhor)
            if r["acao"] == "transf_entra":
                pronto = e.conta_destino_id == conta_id
            elif r["acao"] == "transf_saida":
                pronto = e.conta_id == conta_id
            else:
                pronto = e.conta_id == conta_id and e.status == "pago" and abs(float(e.valor) - v) <= 0.011
            r.update(situacao="ja_importada" if pronto else "ja_no_app", existente_id=melhor,
                     existente_desc=e.descricao, existente_valor=float(e.valor))
    return pd.DataFrame(regs)


def categorias_por_caminho(u) -> dict:
    df = db.consultar("""select c.id, coalesce(p.nome || ' > ', '') || c.nome as caminho
                           from categorias c left join categorias p on p.id = c.pai_id
                          where c.dono_id = :u""", u=u["id"])
    return {_sem_acento(k).lower(): v for k, v in zip(df["caminho"], df["id"])}


def sugerir_por_historico(u, nomes: list[str]) -> dict:
    hist = db.consultar("""select distinct on (lower(descricao)) lower(descricao) as d, categoria_id
                             from lancamentos where dono_id = :u and categoria_id is not null
                            order by lower(descricao), criado_em desc""", u=u["id"])
    mapa = dict(zip(hist["d"], hist["categoria_id"])) if not hist.empty else {}
    return {n: mapa.get(n.lower()) for n in nomes}


# ---------------------------------------------------------------------------
# Gravar
# ---------------------------------------------------------------------------
def gravar(u, conta_id, ex: Extrato, regs: pd.DataFrame, nome_arquivo: str) -> dict:
    n = {"novos": 0, "pagos": 0, "transf": 0, "faturas": 0, "saldos": 0}
    with db.transacao() as s:
        for r in regs.itertuples():
            if not getattr(r, "importar", True):
                continue
            ln = ex.linhas[r.i]
            v = abs(ln.valor)
            if r.situacao == "ja_no_app":
                if r.acao in ("transf_entra", "transf_saida"):
                    campo = "conta_destino_id" if r.acao == "transf_entra" else "conta_id"
                    s.execute(text(f"""update lancamentos set {campo} = :c, status = 'pago',
                                         data_pagamento = coalesce(data_pagamento, :d), atualizado_em = now()
                                       where id = :id and dono_id = :u"""),
                              {"c": conta_id, "d": ln.data, "id": r.existente_id, "u": u["id"]})
                    n["transf"] += 1
                else:
                    s.execute(text("""update lancamentos set status = 'pago', data_pagamento = :d, valor = :v,
                                         conta_id = :c, categoria_id = coalesce(categoria_id, :cat),
                                         atualizado_em = now()
                                       where id = :id and dono_id = :u"""),
                              {"d": ln.data, "v": v, "c": conta_id, "cat": _cat(r), "id": r.existente_id,
                               "u": u["id"]})
                    n["pagos"] += 1
            elif r.situacao == "nova":
                if r.acao in ("transf_entra", "transf_saida"):
                    origem, destino = (None, conta_id) if r.acao == "transf_entra" else (conta_id, None)
                    tipo, cat = "transferencia", None
                    n["transf"] += 1
                else:
                    origem, destino, tipo, cat = conta_id, None, r.tipo, _cat(r)
                    n["novos"] += 1
                s.execute(text("""
                    insert into lancamentos (dono_id, conta_id, conta_destino_id, categoria_id, tipo, descricao,
                        valor, data_compra, data_vencimento, data_pagamento, forma_pagamento, status, origem,
                        chave_importacao, observacao)
                    values (:u, :o, :dst, :cat, cast(:t as tipo_lancamento), :desc, :v, :d, :d, :d, :f, 'pago',
                        'importacao', :k, :obs)
                    on conflict do nothing"""),
                    {"u": u["id"], "o": origem, "dst": destino, "cat": cat, "t": tipo,
                     "desc": r.nome_curto if tipo != "transferencia" else r.descricao, "v": v, "d": ln.data,
                     "f": "Transferencia" if tipo == "transferencia" else forma(ln.descricao), "k": r.chave,
                     "obs": ln.descricao})
            elif r.situacao == "fatura":
                baixou = _baixar_fatura(s, u, ln.data, v)
                n["faturas"] += baixou
                if not baixou:
                    # fatura que não está no app: o dinheiro sai da conta (transferência para o cartão),
                    # sem virar gasto — as compras são do cartão
                    s.execute(text("""
                        insert into lancamentos (dono_id, conta_id, conta_destino_id, tipo, descricao, valor,
                            data_compra, data_vencimento, data_pagamento, forma_pagamento, status, origem,
                            chave_importacao, observacao)
                        values (:u, :o, :dst, 'transferencia', :desc, :v, :d, :d, :d, 'Transferencia', 'pago',
                            'importacao', :k, :obs)
                        on conflict do nothing"""),
                        {"u": u["id"], "o": conta_id, "dst": _cartao_da_fatura(s, u, ex.banco, ln.descricao),
                         "desc": ("Pagamento de fatura " + (re.sub(r"^(FATURA PAGA|Pagamento de fatura)\s*", "",
                                                                   ln.descricao, flags=re.I).strip() or ex.banco)),
                         "v": v, "d": ln.data,
                         "k": r.chave, "obs": ln.descricao})
        for d, val in ex.saldos:
            s.execute(text("""insert into saldos (conta_id, data, valor, origem) values (:c, :d, :v, 'importacao')
                              on conflict (conta_id, data) do update set valor = excluded.valor"""),
                      {"c": conta_id, "d": d, "v": val})
            n["saldos"] += 1
        if ex.conta_banco:
            s.execute(text("""update contas set finais_cartao =
                                 trim(both ',' from concat_ws(',', nullif(finais_cartao, ''), :f))
                               where id = :c and dono_id = :u
                                 and coalesce(finais_cartao, '') not like '%' || :f || '%'"""),
                      {"f": ex.conta_banco, "c": conta_id, "u": u["id"]})
        if ex.titular:
            s.execute(text("""update usuarios set preferencias = coalesce(preferencias, '{}'::jsonb)
                                 || jsonb_build_object('nome_titular', cast(:t as text)) where id = :u"""),
                      {"t": ex.titular, "u": u["id"]})
        s.execute(text("""insert into importacoes (dono_id, conta_id, arquivo, formato, linhas_lidas, linhas_importadas)
                          values (:u, :c, :a, :f, :l, :n)"""),
                  {"u": u["id"], "c": conta_id, "a": nome_arquivo, "f": ex.formato, "l": len(ex.linhas),
                   "n": n["novos"] + n["pagos"] + n["transf"]})
    return n


def _cat(r):
    c = getattr(r, "categoria_id", None)
    return None if c is None or (not isinstance(c, str) and pd.isna(c)) else c


def _baixar_fatura(s, u, data_pag: date, valor: float) -> int:
    """Marca como paga a fatura (cartão × mês) com total igual (±1%) e vencimento até 12 dias da data."""
    f = s.execute(text("""
        select l.conta_id, l.mes_ref, sum(case when l.tipo = 'receita' then -l.valor else l.valor end) as total,
               max(l.data_vencimento) as venc
          from lancamentos l join contas c on c.id = l.conta_id and c.tipo = 'cartao_credito'
         where l.dono_id = :u and l.status = 'previsto' and l.data_vencimento between :a and :b
         group by 1, 2"""), {"u": u["id"], "a": data_pag - timedelta(days=12), "b": data_pag + timedelta(days=12)}
    ).mappings().all()
    alvo = [x for x in f if abs(float(x["total"]) - valor) <= max(0.02, 0.01 * valor)]
    if not alvo:
        return 0
    x = min(alvo, key=lambda x: abs((x["venc"] - data_pag).days))
    s.execute(text("""update lancamentos set status = 'pago', data_pagamento = :d, atualizado_em = now()
                       where dono_id = :u and conta_id = :c and mes_ref = :m and status = 'previsto'"""),
              {"d": data_pag, "u": u["id"], "c": x["conta_id"], "m": x["mes_ref"]})
    return 1


def _cartao_da_fatura(s, u, banco: str, desc: str):
    """'FATURA PAGA LATAM PASS I' -> cartão com 'Latam' no nome; 'Pagamento de fatura' no Nubank -> cartão Nubank.
    Só liga com uma palavra que distingue o cartão (nome do banco sozinho não basta: o Itaú tem vários)."""
    cards = s.execute(text("""select id, nome, coalesce(instituicao, '') as inst from contas
                              where dono_id = :u and tipo = 'cartao_credito'"""), {"u": u["id"]}).mappings().all()
    resto = re.sub(r"^(FATURA PAGA|Pagamento de fatura)\s*", "", desc, flags=re.I).strip()
    genericas = {"itau", "fatura", "paga", "cartao", "credito", "pagamento", "de", "do", "da"}
    tokens = [t for t in re.findall(r"[a-z]{4,}", _sem_acento(resto).lower()) if t not in genericas]
    if not tokens:                                   # 'Pagamento de fatura' (Nubank): o próprio banco
        tokens = [_sem_acento(banco).lower()]
    hits = [c["id"] for c in cards
            if any(t[:5] in _sem_acento(f"{c['nome']} {c['inst'] if not resto else ''}").lower() for t in tokens)]
    return hits[0] if len(hits) == 1 else None


def conta_sugerida(u, ex: Extrato, contas: pd.DataFrame):
    cc = contas[contas["tipo"].isin(["conta_corrente", "poupanca"])]
    if ex.conta_banco:
        hit = cc[cc["finais_cartao"].fillna("").str.contains(re.escape(ex.conta_banco))]
        if not hit.empty:
            return hit.iloc[0]["id"]
    alvo = _sem_acento(ex.banco).lower()
    for r in cc.itertuples():
        if alvo in _sem_acento(f"{r.nome} {r.instituicao or ''}").lower():
            return r.id
    return None

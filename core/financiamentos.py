"""Financiamento imobiliário na fase de obra: encargo = saldo devedor × (juros fixos + TR) + seguros/tarifa.

A taxa de juros é fixa (do contrato); a TR é variável — vem do Banco Central, do último boleto ou é digitada.
A projeção vira lançamentos previstos (mesma descrição) até o fim da obra."""
import json
from datetime import date

import httpx
import pandas as pd
import streamlit as st
from sqlalchemy import text

from core import db
from core.fmt import dia_no_mes, mes_ref, somar_meses

# SGS 226: TR (% a.m.) do período que começa em cada dia — o último valor é a TR do mês corrente
_SGS_TR = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.226/dados/ultimos/40?formato=json"
MODOS_TR = {"bcb": "Banco Central (TR atual)", "boleto": "Calculada pelo último boleto", "manual": "Digitada"}


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def tr_bcb() -> tuple[float, str] | None:
    """(TR % a.m., data) mais recente publicada pelo BCB; None se o site não responder."""
    try:
        r = httpx.get(_SGS_TR, timeout=15)
        r.raise_for_status()
        ult = r.json()[-1]
        return float(str(ult["valor"]).replace(",", ".")), ult["data"]
    except Exception:  # noqa: BLE001 — sem internet/BCB fora: a tela cai para a TR do boleto ou digitada
        return None


def listar(u) -> pd.DataFrame:
    df = db.consultar("select * from financiamentos where dono_id = :u order by nome", u=u["id"])
    return df.astype(object).where(df.notna(), None)


def salvar(u, d: dict, fin_id=None) -> None:
    p = d | {"u": u["id"], "cron": json.dumps(d.get("cronograma") or {})}
    campos = ("nome, descricao_lanc, conta_id, categoria_id, forma_pagamento, dia_venc, taxa_am, fixos, saldo, "
              "data_saldo, tr_modo, tr_manual, ultimo_boleto, fim_obra")
    if fin_id:
        sets = ", ".join(f"{c.strip()} = :{c.strip()}" for c in campos.split(","))
        db.executar(f"update financiamentos set {sets}, cronograma = cast(:cron as jsonb) "
                    "where id = :id and dono_id = :u", id=fin_id, **p)
    else:
        vals = ", ".join(f":{c.strip()}" for c in campos.split(","))
        db.executar(f"insert into financiamentos (dono_id, {campos}, cronograma) "
                    f"values (:u, {vals}, cast(:cron as jsonb))", **p)


def tr_do_boleto(f) -> float | None:
    """TR implícita (% a.m.) no último boleto: (boleto − fixos) / saldo − juros."""
    if not f.get("ultimo_boleto") or not f.get("saldo"):
        return None
    return round(((float(f["ultimo_boleto"]) - float(f["fixos"])) / float(f["saldo"])) * 100 - float(f["taxa_am"]), 4)


def tr_usada(f) -> tuple[float, str]:
    """(TR % a.m., de onde veio) conforme o modo escolhido, com recuo para o que existir."""
    modo = f.get("tr_modo") or "bcb"
    if modo == "bcb" and (b := tr_bcb()):
        return b[0], f"Banco Central, {b[1]}"
    if modo in ("bcb", "boleto") and (t := tr_do_boleto(f)) is not None:
        return t, "último boleto" + (" (BCB fora do ar)" if modo == "bcb" else "")
    return float(f.get("tr_manual") or 0), "digitada"


def projetar(f, tr: float, liberacoes=True) -> pd.DataFrame:
    """Encargo de cada vencimento depois da data do saldo até o fim da obra.
    Com liberações: o saldo segue o cronograma (planilha) quando ele passa do saldo real; sem: fica no saldo real."""
    cron = f.get("cronograma") or {}
    if isinstance(cron, str):
        cron = json.loads(cron)
    saldo_real, dia = float(f["saldo"]), int(f["dia_venc"])
    ds = pd.to_datetime(f["data_saldo"]).date()
    ref = mes_ref(ds) if ds.day < dia else somar_meses(mes_ref(ds), 1)
    fim = mes_ref(pd.to_datetime(f["fim_obra"]).date()) if f.get("fim_obra") else somar_meses(ref, 11)
    taxa = (float(f["taxa_am"]) + tr) / 100
    linhas = []
    while ref <= fim:
        chave = f"{ref // 100}-{ref % 100:02d}"
        # o 1º vencimento depois do saldo é cobrado sobre ele mesmo; dali em diante seguem as liberações
        s = max(saldo_real, float(cron.get(chave, 0))) if liberacoes and linhas else saldo_real
        linhas.append({"vencimento": dia_no_mes(ref // 100, ref % 100, dia), "saldo": round(s, 2),
                       "juros_tr": round(s * taxa, 2), "fixos": float(f["fixos"]),
                       "encargo": round(s * taxa + float(f["fixos"]), 2)})
        ref = somar_meses(ref, 1)
    return pd.DataFrame(linhas)


def aplicar(u, f, proj: pd.DataFrame) -> tuple[int, int]:
    """Atualiza os previstos com a descrição do financiamento e cria os meses que faltam.
    Lançamentos pagos não mudam; previstos dessa descrição depois do fim da obra não são tocados."""
    alt = novos = 0
    with db.transacao() as s:
        for r in proj.itertuples():
            n = s.execute(text("""update lancamentos set valor = :v, atualizado_em = now(),
                                         observacao = 'Projeção do financiamento (saldo × juros + TR + fixos)'
                                   where dono_id = :u and descricao = :d and status = 'previsto'
                                     and data_vencimento = :dt"""),
                          {"v": r.encargo, "u": u["id"], "d": f["descricao_lanc"], "dt": r.vencimento}).rowcount
            if n:
                alt += n
                continue
            pago = s.execute(text("""select 1 from lancamentos where dono_id = :u and descricao = :d
                                        and status <> 'previsto' and date_trunc('month', data_vencimento)
                                            = date_trunc('month', cast(:dt as date))"""),
                             {"u": u["id"], "d": f["descricao_lanc"], "dt": r.vencimento}).first()
            if pago:
                continue
            s.execute(text("""insert into lancamentos (dono_id, conta_id, categoria_id, tipo, descricao, valor,
                                  data_compra, data_vencimento, forma_pagamento, status, origem, chave_importacao,
                                  observacao)
                              values (:u, :c, :cat, 'despesa', :d, :v, :dt, :dt, :fp, 'previsto', 'manual', :k,
                                      'Projeção do financiamento (saldo × juros + TR + fixos)')
                              on conflict do nothing"""),
                      {"u": u["id"], "c": f.get("conta_id"), "cat": f.get("categoria_id"), "d": f["descricao_lanc"],
                       "v": r.encargo, "dt": r.vencimento, "fp": f.get("forma_pagamento") or "Boleto",
                       "k": f"fin-{f['id']}-{r.vencimento:%Y-%m}"})
            novos += 1
    return alt, novos

"""Números do Início (formato "Hoje"): saldo de hoje, placar do mês e o que precisa de atenção.

Só leitura. Cada item de atenção: {"nivel": "alto"|"medio"|"info", "titulo", "sub", "pagina"}.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from core import cartoes, db, orcamentos, repo, saldos
from core.fmt import brl, dia_no_mes, hoje, mes_label, mes_ref


def _contas_caixa(u) -> pd.DataFrame:
    c = repo.contas(u)
    return c[c["tipo"].isin(saldos.TIPOS_CAIXA)]


def placar(u) -> dict:
    """Saldo de hoje (contas correntes) e entradas/saídas do mês (real + previsto), sem transferências internas."""
    hj = hoje()
    caixa = _contas_caixa(u)
    ids = list(caixa["id"])
    if not ids:
        return {"saldo": 0.0, "entra": 0.0, "sai": 0.0, "sobra": 0.0, "fim": 0.0, "contas": 0}
    ini, fim = date(hj.year, hj.month, 1), dia_no_mes(hj.year, hj.month, 31)
    s0, ext = saldos.extrato(u, ids, ini, fim)
    ent = sai = 0.0
    saldo_hoje = fim_mes = s0
    if not ext.empty:
        entram = set(ext.loc[ext["fonte"] == "entrada_transf", "id"].dropna())
        interna = ext["id"].isin(entram) & ((ext["fonte"] == "entrada_transf")
                                            | ((ext["valor"] < 0) & (ext["fonte"] != "fatura")))
        real = ext[(ext["fonte"] != "ajuste") & ~interna]
        ent = float(real.loc[real["valor"] > 0, "valor"].sum())
        sai = float(-real.loc[real["valor"] < 0, "valor"].sum())
        saldo_hoje = s0 + float(ext.loc[ext["data"] <= hj, "valor"].sum())
        fim_mes = s0 + float(ext["valor"].sum())
    return {"saldo": saldo_hoje, "entra": ent, "sai": sai, "sobra": ent - sai, "fim": fim_mes, "contas": len(ids)}


def atencao(u, n_caixa: int = 0) -> list[dict]:
    hj = hoje()
    itens: list[dict] = []
    caixa = _contas_caixa(u)
    ids = list(caixa["id"])

    # previstos que já venceram e não foram confirmados
    try:
        venc = saldos.vencidos_sem_confirmar(u, ids) if ids else pd.DataFrame()
        venc = venc[venc["fonte"] != "fatura"] if not venc.empty else venc
        if not venc.empty:
            n = len(venc)
            itens.append({"nivel": "alto", "pagina": "telas/lancamentos.py",
                          "titulo": f"{n} previsto{'s' if n > 1 else ''} vencido{'s' if n > 1 else ''} sem confirmar",
                          "sub": f"{brl(float(-venc['valor'].sum()))} · marque como pago ou ajuste a data"})
    except Exception:  # noqa: BLE001
        pass

    # faturas que vencem nos próximos 7 dias
    try:
        res = cartoes.resumo(u)
        if not res.empty:
            for r in res.itertuples():
                if r.n_atrasadas:
                    itens.append({"nivel": "alto", "pagina": "telas/cartoes.py",
                                  "titulo": f"Fatura {r.cartao} atrasada", "sub": brl(r.atrasadas)})
                elif r.venc_atual and r.fatura_atual > 0.004 and (r.venc_atual - hj).days <= 7:
                    d = (r.venc_atual - hj).days
                    quando = "hoje" if d == 0 else ("amanhã" if d == 1 else f"dia {r.venc_atual:%d}")
                    itens.append({"nivel": "medio", "pagina": "telas/cartoes.py",
                                  "titulo": f"Fatura {r.cartao} vence {quando}", "sub": brl(r.fatura_atual)})
    except Exception:  # noqa: BLE001
        pass

    # saldo das contas fica negativo nos próximos 90 dias
    try:
        if ids:
            proj = saldos.projecao_diaria(u, ids, hj, 90)
            neg = proj[(proj["data"] > hj) & (proj["saldo"] < 0)]
            if not neg.empty:
                p = neg.iloc[0]
                pior = proj.loc[proj["saldo"].idxmin()]
                itens.append({"nivel": "alto", "pagina": "telas/painel.py",
                              "titulo": f"Saldo fica negativo em {p['data']:%d/%m}",
                              "sub": f"chega a {brl(pior['saldo'])} em {pior['data']:%d/%m}"})
    except Exception:  # noqa: BLE001
        pass

    # categorias que passaram do orçamento neste mês
    try:
        q = orcamentos.quadro(u, mes_ref(hj))
        est = q[q["orcado"].notna() & (q["gasto"] > q["orcado"])]
        for r in est.sort_values("gasto", ascending=False).head(2).itertuples():
            itens.append({"nivel": "medio", "pagina": "telas/orcamentos.py",
                          "titulo": f"{r.categoria} passou do orçamento",
                          "sub": f"{brl(r.gasto)} de {brl(r.orcado)} em {mes_label(mes_ref(hj))}"})
    except Exception:  # noqa: BLE001
        pass

    # compras esperando na Caixa de entrada
    if n_caixa:
        itens.append({"nivel": "medio", "pagina": "telas/caixa_entrada.py",
                      "titulo": f"{n_caixa} compra{'s' if n_caixa > 1 else ''} na Caixa de entrada",
                      "sub": "confira e lance"})

    # contas correntes com saldo sem atualizar há mais de 15 dias
    try:
        if ids:
            ult = db.consultar("""select c.nome, max(s.data) as ult from contas c left join saldos s on s.conta_id = c.id
                                   where c.id = any(:ids) group by c.nome""", ids=ids)
            velhas = [r.nome for r in ult.itertuples()
                      if r.ult is not None and not pd.isna(r.ult) and (hj - pd.Timestamp(r.ult).date()).days > 15]
            if velhas:
                itens.append({"nivel": "info", "pagina": "telas/contas_correntes.py",
                              "titulo": "Saldo sem atualizar há mais de 15 dias",
                              "sub": ", ".join(velhas[:4]) + ("…" if len(velhas) > 4 else "")})
    except Exception:  # noqa: BLE001
        pass

    # cadastros salvos para completar depois: cartão sem vencimento ou sem conta que paga a fatura
    try:
        c = repo.contas(u)
        inc = c[(c["tipo"] == "cartao_credito") & (c["dia_vencimento"].isna() | c["conta_pagamento_id"].isna())]
        if not inc.empty:
            n = len(inc)
            itens.append({"nivel": "info", "pagina": "telas/contas.py",
                          "titulo": f"{n} cart{'ões' if n > 1 else 'ão'} para completar o cadastro",
                          "sub": ", ".join(inc["nome"].head(3)) + " · vencimento ou conta que paga a fatura"})
    except Exception:  # noqa: BLE001
        pass

    # deduções do IR sem comprovante
    try:
        from core import deducoes
        r = db.um("""select count(*) as n from ir_deducoes where dono_id = :u and ano = :a and arquivo is null""",
                  u=u["id"], a=hj.year)
        if r and r["n"]:
            itens.append({"nivel": "info", "pagina": "telas/imposto_renda.py",
                          "titulo": f"{r['n']} dedução{'ões' if r['n'] > 1 else ''} do IR sem comprovante",
                          "sub": "anexe o recibo ou a nota"})
        _ = deducoes
    except Exception:  # noqa: BLE001
        pass

    ordem = {"alto": 0, "medio": 1, "info": 2}
    return sorted(itens, key=lambda x: ordem.get(x["nivel"], 3))

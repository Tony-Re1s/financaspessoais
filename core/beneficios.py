"""Cartões de benefício (VR / VA): saldo, crédito mensal e uso.

- VR (e qualquer benefício "nos meus gastos"): compras viram despesa na conta do benefício (contam nas
  categorias); o crédito mensal entra como receita "Benefício".
- VA "fora dos meus gastos" (usado por outra pessoa): o crédito e o uso entram como transferência — mexem só no
  saldo do cartão, não aparecem em gastos nem em receitas.
Nenhum dos dois entra no fluxo das contas correntes nem em fatura.
Configuração em usuarios.preferencias -> 'beneficios': {conta_id: {"credito": 0, "dia": 1, "fora": false}}.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from core import db, saldos
from core.fmt import dia_no_mes, hoje, mes_ref, somar_meses

HORIZONTE = 12


def contas(u) -> pd.DataFrame:
    return db.consultar("""select id, nome, instituicao, apelido_wallet, cor from contas
                            where dono_id = :u and ativa and tipo::text = 'beneficio' order by nome""", u=u["id"])


def config(u) -> dict:
    r = db.um("select preferencias->'beneficios' as b from usuarios where id = :u", u=u["id"])
    b = r["b"] if r else None
    if isinstance(b, str):
        b = json.loads(b)
    return b or {}


def _salvar_config(u, cfg: dict):
    db.executar("""update usuarios set preferencias = coalesce(preferencias, '{}'::jsonb)
                          || jsonb_build_object('beneficios', cast(:b as jsonb)) where id = :u""",
                b=json.dumps(cfg), u=u["id"])


def fora_dos_gastos(u, conta_id) -> bool:
    return bool(config(u).get(str(conta_id), {}).get("fora"))


def criar_padrao(u):
    """VR (nos gastos) e VA (fora dos gastos), se ainda não existirem."""
    existentes = set(contas(u)["nome"].str.upper()) if not contas(u).empty else set()
    cfg = config(u)
    for nome, fora in [("VR", False), ("VA", True)]:
        if nome in existentes:
            continue
        r = db.gravar_retornando("""insert into contas (dono_id, nome, tipo, instituicao, visibilidade, ativa)
                                    values (:u, :n, cast('beneficio' as tipo_conta), 'Benefício', 'privado', true)
                                    on conflict (dono_id, nome) do nothing returning id""", u=u["id"], n=nome)
        if r:
            cfg[str(r["id"])] = {"credito": 0.0, "dia": 1, "fora": fora}
    _salvar_config(u, cfg)


def configurar(u, conta_id, credito: float, dia: int, fora: bool):
    cfg = config(u)
    cfg[str(conta_id)] = {"credito": float(credito or 0), "dia": int(dia or 1), "fora": bool(fora)}
    _salvar_config(u, cfg)
    # refaz os créditos futuros
    db.executar("""delete from lancamentos where dono_id = :u and status = 'previsto' and data_vencimento >= :h
                     and chave_importacao like :k""", u=u["id"], h=hoje(), k=f"benef:{conta_id}:%")
    gerar_creditos(u)


def gerar_creditos(u) -> int:
    """Lança os créditos mensais previstos dos próximos meses (idempotente)."""
    cfg, n = config(u), 0
    ok = set(contas(u)["id"].astype(str)) if not contas(u).empty else set()
    m0 = mes_ref(hoje())
    for cid, c in cfg.items():
        if cid not in ok or not c.get("credito"):
            continue
        for k in range(0, HORIZONTE + 1):
            m = somar_meses(m0, k)
            d = dia_no_mes(m // 100, m % 100, int(c.get("dia") or 1))
            if d < hoje():
                continue
            chave = f"benef:{cid}:{m}"
            fora = bool(c.get("fora"))
            r = db.gravar_retornando(f"""
                insert into lancamentos (dono_id, conta_id, conta_destino_id, tipo, descricao, valor, data_compra,
                    data_vencimento, forma_pagamento, status, origem, chave_importacao)
                select :u, {'null' if fora else ':c'}, {':c' if fora else 'null'},
                       cast(:t as tipo_lancamento), :d, :v, :dt, :dt, 'Beneficio (VR/VA)', 'previsto', 'recorrencia', :k
                 where not exists (select 1 from lancamentos where chave_importacao = :k)
                returning id""", u=u["id"], c=cid, t="transferencia" if fora else "receita",
                d="Crédito do benefício", v=float(c["credito"]), dt=d, k=chave)
            n += 1 if r else 0
    return n


def registrar_uso(u, conta_id, descricao, valor, data, categoria_id=None, fora=False) -> str | None:
    """Compra no benefício. Fora dos gastos = transferência (só baixa o saldo)."""
    r = db.gravar_retornando("""
        insert into lancamentos (dono_id, conta_id, categoria_id, tipo, descricao, valor, data_compra, data_vencimento,
            data_pagamento, forma_pagamento, status, origem)
        values (:u, :c, :cat, cast(:t as tipo_lancamento), :d, :v, :dt, :dt, :dt, 'Beneficio (VR/VA)', 'pago',
            'applepay')
        returning id""", u=u["id"], c=conta_id, cat=None if fora else categoria_id,
        t="transferencia" if fora else "despesa", d=descricao, v=valor, dt=data)
    return r["id"] if r else None


def resumo(u, conta_id, mes: int) -> dict:
    ini, fim = date(mes // 100, mes % 100, 1), dia_no_mes(mes // 100, mes % 100, 31)
    s_ini, ext = saldos.extrato(u, [conta_id], ini, fim)
    hj = hoje()
    ate_hoje = ext[ext["data"] <= hj] if not ext.empty else ext
    cred = float(ext.loc[ext["valor"] > 0, "valor"].sum()) if not ext.empty else 0.0
    uso = float(-ext.loc[(ext["valor"] < 0) & (ext["fonte"] != "ajuste"), "valor"].sum()) if not ext.empty else 0.0
    aj = float(ext.loc[ext["fonte"] == "ajuste", "valor"].sum()) if not ext.empty else 0.0
    saldo_hoje = s_ini + (float(ate_hoje["valor"].sum()) if not ate_hoje.empty else 0.0) if ini <= hj <= fim \
        else s_ini + (float(ext["valor"].sum()) if not ext.empty else 0.0)
    return {"saldo_inicial": s_ini, "creditos": cred, "uso": uso, "ajustes": aj, "saldo": saldo_hoje,
            "saldo_fim": s_ini + (float(ext["valor"].sum()) if not ext.empty else 0.0), "extrato": ext}

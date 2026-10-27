"""Deduções do IR (declaração completa): despesas médicas e de educação.

Regras (Receita Federal, regime de caixa — conta o ano em que foi PAGO):
- Saúde: sem limite. Médicos, dentistas, psicólogos, fisioterapeutas, fonoaudiólogos, terapeutas
  ocupacionais, hospitais, exames, aparelhos/próteses e plano de saúde. NÃO: farmácia, academia,
  estética, cartão de desconto, óculos/lentes, nutricionista.
- Educação: limite de R$ 3.561,50 por pessoa no ano. Escola, graduação, pós-graduação (especialização,
  MBA, mestrado, doutorado) e ensino técnico. NÃO: idiomas, cursos livres/online, cursinho, material.
- Precisa de recibo/nota com nome e CPF/CNPJ do prestador; guarde por 5 anos.

Tabelas: ir_deducoes (o que vai para a declaração) e ir_ded_ignorados (sugestões descartadas).
"""
from __future__ import annotations

import unicodedata

import pandas as pd
import streamlit as st

from core import db

LIMITE_EDUCACAO = 3561.50
TIPOS = {"saude": "Saúde", "educacao": "Educação"}


def _sa(s) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


# ---------------------------------------------------------------------------
# o que é dedutível
# ---------------------------------------------------------------------------
# (padrões, veredito, motivo) — a primeira regra que bater vale
_SAUDE_NAO = [
    (["farmac", "drogaria", "drogasil", "droga raia", "raia ", "ultrafarma", "pacheco", "pague menos",
      "panvel", "sao joao farm"], "Farmácia não é dedutível (só se estiver na conta do hospital)."),
    (["academia", "totalpass", "gympass", "wellhub", "smart fit", "smartfit", "bluefit", "crossfit"],
     "Academia não é despesa médica."),
    (["cartao de saude", "cartao yalo", "yalo", "cartao de desconto", "cartao todos", "cartao saude"],
     "Cartão de desconto não é plano de saúde — só a consulta paga com recibo do médico/clínica conta."),
    (["otica", "oculos", "lente de contato", "lentes de contato"], "Óculos e lentes não são dedutíveis."),
    (["suplement", "whey", "vitamina"], "Suplementos não são dedutíveis."),
    (["nutricion"], "Nutricionista não está na lista da Receita."),
    (["veterin", "pet ", "petz", "cobasi"], "Despesa com animal não é dedutível."),
]
_SAUDE_TALVEZ = [
    (["estetic", "capelli", "capilar", "harmoniza", "botox", "depila", "laser"],
     "Estética não é dedutível — só se for tratamento feito por médico/dentista com nota de serviço médico."),
    (["pilates", "rpg"], "Só conta se for sessão de fisioterapia com recibo de fisioterapeuta."),
    (["terapia", "terapeuta", "coach"], "Só psicólogo, terapeuta ocupacional e afins com registro contam."),
    (["saude e bem", "saude"], "Confira se o prestador é médico, dentista, psicólogo, clínica ou hospital."),
]
_SAUDE_SIM = [
    (["plano de saude", "convenio medic", "unimed", "amil", "bradesco saude", "sulamerica saude",
      "sul america saude", "hapvida", "notredame", "notre dame", "porto saude", "prevent senior", "odontoprev",
      "golden cross", "care plus", "omint", "alice saude", "sami saude", "seguros unimed"],
     "Plano de saúde — dedutível (sem limite). Desconte reembolsos."),
    (["hospital", "pronto socorro", "pronto-socorro", "maternidade"], "Hospital — dedutível (sem limite)."),
    (["laborat", "exame", "fleury", "delboni", "lavoisier", "a+ medicina", "dasa", "hermes pardini",
      "sabin", "raio x", "radiolog", "ultrassom", "tomograf", "ressonan", "imagem"],
     "Exames — dedutível (sem limite)."),
    (["dentist", "odonto", "ortodont", "implante dent"], "Dentista — dedutível (sem limite)."),
    (["psicolog", "psiquiatr", "fisioterap", "fonoaud", "terapia ocupacional", "terapeuta ocupacional"],
     "Profissional de saúde da lista da Receita — dedutível."),
    (["medic", "consulta", "clinica", "dr consulta", "dr. consulta", "dermatolog", "cardiolog", "ortoped",
      "oftalmo", "ginecolog", "urolog", "pediatr", "otorrino", "endocrin", "cirurg", "protese", "aparelho auditivo"],
     "Médico / clínica — dedutível (sem limite)."),
]
_EDU_NAO = [
    (["idioma", "ingles", "english", "espanhol", "frances", "alemao", "italiano", "personnalite ingl",
      "eac ", "eac prime", "wizard", "cna ", "fisk", "ccaa", "cultura inglesa", "open english", "duolingo",
      "berlitz", "yazigi", "wise up"], "Curso de idiomas não é dedutível."),
    (["curso online", "hotmart", "udemy", "alura", "coursera", "domestika", "eduzz", "kiwify", "plataforma",
      "masterclass", "curso livre", "workshop"], "Curso livre/online não é dedutível."),
    (["livro", "material escolar", "apostila", "papelaria", "uniforme"], "Material e livros não são dedutíveis."),
    (["cursinho", "pre-vestibular", "pre vestibular", "concurso"], "Cursinho preparatório não é dedutível."),
    (["musica", "danca", "natacao", "futebol", "esporte", "reforco", "transporte escolar"],
     "Atividade extracurricular não é dedutível."),
]
_EDU_SIM = [
    (["pos-gradua", "pos gradua", "posgradua", "mba", "mestrado", "doutorado", "especializacao", "fiap", "f i a p"],
     f"Pós-graduação — dedutível até R$ 3.561,50 por pessoa no ano."),
    (["graduac", "faculdade", "universidade", "unip", "uninove", "mackenzie", "anhembi", "estacio", "puc",
      "insper", "fgv", "senac", "fatec", "etec", "tecnologo", "curso tecnico", "ensino tecnico"],
     "Ensino superior/técnico — dedutível até R$ 3.561,50 por pessoa no ano."),
    (["escola", "colegio", "creche", "educacao infantil", "ensino fundamental", "ensino medio", "mensalidade escolar"],
     "Escola — dedutível até R$ 3.561,50 por pessoa no ano."),
]


def _bate(texto: str, regras):
    for padroes, motivo in regras:
        if any(p in texto for p in padroes):
            return motivo
    return None


def avaliar(descricao, categoria=None, subcategoria=None) -> dict | None:
    """{'tipo': 'saude'|'educacao', 'veredito': 'sim'|'talvez'|'nao', 'motivo': str} ou None (não é do assunto)."""
    desc = f" {_sa(descricao)} "
    cats = f" {_sa(categoria)} {_sa(subcategoria)} "
    tudo = desc + cats
    eh_edu = "educa" in cats or _bate(desc, _EDU_SIM) or _bate(desc, _EDU_NAO)
    eh_saude = any(k in cats for k in ("saude", "medic", "odonto", "farmac", "estetic")) \
        or _bate(desc, _SAUDE_SIM) or _bate(desc, _SAUDE_NAO) or _bate(desc, _SAUDE_TALVEZ[:3])
    if eh_edu and not (eh_saude and "educa" not in cats):
        if m := _bate(tudo, _EDU_NAO):
            return {"tipo": "educacao", "veredito": "nao", "motivo": m}
        if m := _bate(tudo, _EDU_SIM):
            return {"tipo": "educacao", "veredito": "sim", "motivo": m}
        return {"tipo": "educacao", "veredito": "talvez",
                "motivo": "Só conta escola, graduação, pós-graduação ou curso técnico (até R$ 3.561,50/pessoa)."}
    if eh_saude:
        if m := _bate(tudo, _SAUDE_NAO):
            return {"tipo": "saude", "veredito": "nao", "motivo": m}
        if m := _bate(desc, _SAUDE_SIM):
            return {"tipo": "saude", "veredito": "sim", "motivo": m}
        if m := _bate(tudo, _SAUDE_TALVEZ):
            return {"tipo": "saude", "veredito": "talvez", "motivo": m}
        if m := _bate(tudo, _SAUDE_SIM):
            return {"tipo": "saude", "veredito": "sim", "motivo": m}
        return {"tipo": "saude", "veredito": "talvez",
                "motivo": "Confira se o prestador é médico, dentista, psicólogo, clínica ou hospital."}
    return None


def frase_aviso(descricao, categoria=None, subcategoria=None) -> str | None:
    """Frase curta para mostrar depois de lançar algo (None se não tiver a ver com IR)."""
    a = avaliar(descricao, categoria, subcategoria)
    if not a or a["veredito"] == "nao":
        return None
    t = "despesa médica" if a["tipo"] == "saude" else "educação"
    return (f"🦁 Pode entrar no IR como {t}" if a["veredito"] == "sim" else f"🦁 Talvez entre no IR como {t}") \
        + f" — {a['motivo']} Confira em Imposto de Renda › Deduções."


# ---------------------------------------------------------------------------
# banco
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _tabela() -> bool:
    db.executar("""create table if not exists ir_deducoes (
        id uuid primary key default gen_random_uuid(),
        dono_id uuid not null references usuarios(id) on delete cascade,
        ano int not null, tipo text not null check (tipo in ('saude','educacao')),
        beneficiario text not null default 'Titular',
        prestador text, documento text, descricao text,
        valor_pago numeric(14,2) not null default 0, valor numeric(14,2) not null default 0,
        data date, lancamento_id uuid references lancamentos(id) on delete set null,
        arquivo_nome text, arquivo_tipo text, arquivo bytea, observacao text,
        criado_em timestamptz not null default now())""")
    db.executar("create index if not exists ir_deducoes_dono_ano on ir_deducoes (dono_id, ano)")
    db.executar("""create table if not exists ir_ded_ignorados (
        dono_id uuid not null references usuarios(id) on delete cascade,
        lancamento_id uuid not null references lancamentos(id) on delete cascade,
        primary key (dono_id, lancamento_id))""")
    return True


def lista(u, ano: int) -> pd.DataFrame:
    _tabela()
    df = db.consultar("""select id, ano, tipo, beneficiario, prestador, documento, descricao, valor_pago, valor, data,
                                lancamento_id, arquivo_nome, observacao, (arquivo is not null) as tem_arquivo
                           from ir_deducoes where dono_id = :u and ano = :a order by tipo, data, prestador""",
                      u=u["id"], a=ano)
    for c in ("valor_pago", "valor"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def arquivo(u, ded_id) -> tuple[str, str, bytes] | None:
    _tabela()
    r = db.um("select arquivo_nome, arquivo_tipo, arquivo from ir_deducoes where id = :i and dono_id = :u",
              i=ded_id, u=u["id"])
    return (r["arquivo_nome"], r["arquivo_tipo"], bytes(r["arquivo"])) if r and r["arquivo"] is not None else None


def salvar(u, d: dict, ded_id=None):
    _tabela()
    p = {k: d.get(k) for k in ["ano", "tipo", "beneficiario", "prestador", "documento", "descricao", "valor_pago",
                               "valor", "data", "lancamento_id", "observacao"]}
    p["beneficiario"] = (p["beneficiario"] or "Titular").strip() or "Titular"
    p["valor_pago"] = float(p["valor_pago"] or 0)
    p["valor"] = float(p["valor"] if p["valor"] is not None else p["valor_pago"])
    if ded_id:
        db.executar("""update ir_deducoes set ano=:ano, tipo=:tipo, beneficiario=:beneficiario, prestador=:prestador,
                         documento=:documento, descricao=:descricao, valor_pago=:valor_pago, valor=:valor,
                         data=:data, observacao=:observacao where id=:id and dono_id=:u""", id=ded_id, u=u["id"], **p)
        return ded_id
    r = db.gravar_retornando("""insert into ir_deducoes (dono_id, ano, tipo, beneficiario, prestador, documento,
                                   descricao, valor_pago, valor, data, lancamento_id, observacao)
                                values (:u, :ano, :tipo, :beneficiario, :prestador, :documento, :descricao,
                                   :valor_pago, :valor, :data, :lancamento_id, :observacao) returning id""",
                             u=u["id"], **p)
    return r["id"] if r else None


def anexar(u, ded_id, nome: str, tipo_mime: str, dados: bytes):
    _tabela()
    db.executar("""update ir_deducoes set arquivo_nome = :n, arquivo_tipo = :t, arquivo = :b
                    where id = :i and dono_id = :u""", n=nome, t=tipo_mime, b=dados, i=ded_id, u=u["id"])


def excluir(u, ids: list):
    _tabela()
    db.executar("delete from ir_deducoes where dono_id = :u and id = any(cast(:ids as uuid[]))",
                u=u["id"], ids=[str(i) for i in ids])


def ignorar(u, lanc_ids: list):
    _tabela()
    for i in lanc_ids:
        db.executar("""insert into ir_ded_ignorados (dono_id, lancamento_id) values (:u, :l)
                       on conflict do nothing""", u=u["id"], l=i)


def desfazer_ignorados(u):
    _tabela()
    db.executar("delete from ir_ded_ignorados where dono_id = :u", u=u["id"])


# ---------------------------------------------------------------------------
# sugestões a partir dos lançamentos
# ---------------------------------------------------------------------------
def candidatos(u, ano: int) -> pd.DataFrame:
    """Despesas do ano (pagas ou previstas) que têm a ver com saúde/educação, ainda não na declaração."""
    _tabela()
    df = db.consultar("""
        select l.id, l.data_vencimento as data, l.descricao, l.valor, l.status::text as status, l.categoria,
               l.subcategoria, l.conta, l.parcela_num, l.parcela_total,
               exists (select 1 from ir_ded_ignorados g where g.dono_id = :u and g.lancamento_id = l.id) as ignorado
          from v_lancamentos l
         where l.dono_id = :u and l.tipo = 'despesa' and l.status <> 'cancelado'
           and extract(year from l.data_vencimento) = :a
           and not exists (select 1 from ir_deducoes d where d.lancamento_id = l.id)
         order by l.data_vencimento""", u=u["id"], a=ano)
    if df.empty:
        return df.assign(tipo=None, veredito=None, motivo=None)
    av = [avaliar(r.descricao, r.categoria, r.subcategoria) for r in df.itertuples()]
    df["tipo"] = [a["tipo"] if a else None for a in av]
    df["veredito"] = [a["veredito"] if a else None for a in av]
    df["motivo"] = [a["motivo"] if a else None for a in av]
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    return df[df["tipo"].notna()].reset_index(drop=True)


def resumo(u, ano: int, incluir_sugestoes=True) -> dict:
    """Totais dedutíveis: saúde (sem limite) e educação (limite por pessoa)."""
    ded = lista(u, ano)
    cand = candidatos(u, ano)
    sug = cand[(cand["veredito"] == "sim") & ~cand["ignorado"]] if not cand.empty else cand
    linhas = [(r.tipo, r.beneficiario, float(r.valor)) for r in ded.itertuples()]
    if incluir_sugestoes and not sug.empty:
        linhas += [(r.tipo, "Titular", float(r.valor)) for r in sug.itertuples()]
    saude = sum(v for t, _, v in linhas if t == "saude")
    edu_pessoa: dict[str, float] = {}
    for t, b, v in linhas:
        if t == "educacao":
            edu_pessoa[b] = edu_pessoa.get(b, 0.0) + v
    edu_pago = sum(edu_pessoa.values())
    edu_ded = sum(min(v, LIMITE_EDUCACAO) for v in edu_pessoa.values())
    return {"saude": saude, "educacao_pago": edu_pago, "educacao": edu_ded, "educacao_pessoa": edu_pessoa,
            "total": saude + edu_ded, "confirmadas": ded, "candidatos": cand, "sugestoes": sug,
            "sem_comprovante": int((~ded["tem_arquivo"].astype(bool)).sum()) if not ded.empty else 0}


def aviso_lancamento(descricao, categoria_id) -> str:
    """'' ou ' — 🦁 Pode entrar no IR…' para somar à mensagem de 'lançado'."""
    try:
        cat = sub = None
        if categoria_id:
            r = db.um("""select c.nome as sub, p.nome as cat from categorias c
                          left join categorias p on p.id = c.pai_id where c.id = :i""", i=categoria_id)
            if r:
                cat, sub = (r["cat"], r["sub"]) if r["cat"] else (r["sub"], None)
        f = frase_aviso(descricao, cat, sub)
        return f"\n\n{f}" if f else ""
    except Exception:  # noqa: BLE001 — aviso nunca atrapalha o lançamento
        return ""

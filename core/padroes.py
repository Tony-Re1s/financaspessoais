"""Valores padrão do app: categorias iniciais e listas fixas.

As categorias de despesa seguem a mesma nomenclatura da planilha
Compromissos_Financeiros (sem acento) para a migração casar 1 para 1.
"""

# (subcategoria, natureza_ir) — natureza_ir só onde a despesa é dedutível no IRPF
CATEGORIAS_DESPESA: dict[str, list[tuple[str, str | None]]] = {
    "Moradia": [("Aluguel", None), ("Telecom", None), ("Condominio", None),
                ("Energia", None), ("Agua e Gas", None), ("Manutencao da Casa", None)],
    "Imovel": [("Parcela Incorporadora", None), ("Evolucao de Obra", None),
               ("Cartorio e ITBI", None), ("Financiamento", None)],
    "Transporte": [("Seguro Veicular", None), ("Habilitacao (CNH)", None),
                   ("Manutencao Veicular", None), ("Combustivel", None),
                   ("App de Transporte", None), ("Estacionamento e Pedagio", None)],
    "Alimentacao": [("Supermercado", None), ("Restaurante", None),
                    ("Delivery", None), ("Padaria e Cafe", None)],
    "Educacao": [("Pos-graduacao", "educacao"), ("Curso de Idiomas", None),
                 ("Plataforma de Estudo", None), ("Curso Online", None)],
    "Saude e Bem-estar": [("Plano de Saude", "saude"), ("Consultas e Exames", "saude"),
                          ("Dentista", "saude"), ("Farmacia", None),
                          ("Cartao de Saude", None), ("Academia", None)],
    "Cuidados Pessoais": [("Estetica", None), ("Higiene e Beleza", None)],
    "Assinaturas": [("Software e IA", None), ("Apple", None), ("Streaming", None),
                    ("Clube de Beneficios", None), ("Software e Nuvem", None)],
    "Viagem e Lazer": [("Hospedagem", None), ("Passagens", None), ("Locacao de Veiculo", None),
                       ("Programa de Pontos", None), ("Entretenimento", None)],
    "Compras": [("Vestuario", None), ("Marketplace", None), ("Casa e Decoracao", None)],
    "Servicos Financeiros": [("Anuidade de Cartao", None), ("IOF", None), ("Pix no Cartao", None),
                             ("Plataforma de Investimentos", None), ("Juros e Multas", None),
                             ("Tarifas Bancarias", None)],
    "Investimentos e Previdencia": [("Aplicacao", None), ("Previdencia PGBL", "previdencia_pgbl"),
                                    ("Previdencia VGBL", None)],
}

CATEGORIAS_RECEITA: dict[str, list[tuple[str, str | None]]] = {
    "Receitas": [("Salario", None), ("13o e Ferias", None), ("PLR e Bonus", None),
                 ("Rendimentos", None), ("Reembolso", None), ("Outras Receitas", None)],
}

TIPOS_CONTA = {
    "conta_corrente": "Conta corrente",
    "cartao_credito": "Cartão de crédito",
    "investimento": "Investimentos",
    "poupanca": "Poupança",
    "fgts": "FGTS",
    "previdencia": "Previdência",
    "financiamento": "Financiamento",
    "carteira": "Dinheiro / carteira",
    "outro": "Outro",
}

FORMAS_PAGAMENTO = ["Cartao de Credito", "Boleto", "Debito em Conta", "Pix", "Dinheiro", "Transferencia"]

VISIBILIDADES = {
    "privado": "🔒 Privado — só eu vejo",
    "compartilhado": "👥 Compartilhado — o outro vê o detalhe",
    "so_total": "Σ Só o total — o outro vê apenas somas",
}

NATUREZAS_IR = {
    None: "—",
    "saude": "Saúde (dedutível)",
    "educacao": "Educação (dedutível, com limite)",
    "previdencia_pgbl": "Previdência PGBL (até 12% da renda tributável)",
    "pensao_alimenticia": "Pensão alimentícia",
    "dependente": "Dependente",
    "doacao": "Doação incentivada",
    "livro_caixa": "Livro-caixa",
}

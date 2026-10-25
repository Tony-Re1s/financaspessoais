"""Importa a planilha Compromissos_Financeiros.xlsx pelo terminal.
(O mesmo dá para fazer pela tela "Importar" do app.)

Uso, na pasta do projeto:
    python scripts/migrar_planilha.py Compromissos_Financeiros.xlsx --email seu@gmail.com

A URL do banco vem de .streamlit/secrets.toml ([connections.neon] url) ou de --db-url.
Pode rodar de novo sem duplicar.
"""
import argparse
import sys
import tomllib
from pathlib import Path

from sqlalchemy import create_engine

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from core.importar import importar_planilha_compromissos  # noqa: E402
from core.semente import garantir_usuario  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("planilha")
    ap.add_argument("--email", required=True, help="e-mail Google do dono dos lançamentos")
    ap.add_argument("--nome", default=None)
    ap.add_argument("--db-url", default=None)
    a = ap.parse_args()
    url = a.db_url or tomllib.loads((RAIZ / ".streamlit/secrets.toml").read_text())["connections"]["neon"]["url"]

    with create_engine(url).begin() as cx:
        u = garantir_usuario(cx, a.email, a.nome)
        r = importar_planilha_compromissos(cx, u["id"], a.planilha)
    print(f"{r['lidas']} linhas lidas · {r['novas']} lançamentos novos · {r['contas']} contas · "
          f"{r['categorias']} categorias · total da planilha R$ {r['total']:,.2f}")


if __name__ == "__main__":
    main()

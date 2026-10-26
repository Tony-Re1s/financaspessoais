"""Formatação pt-BR e utilidades de datas."""
import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def hoje() -> date:
    """Data de hoje em São Paulo (o servidor do Streamlit Cloud roda em UTC)."""
    return datetime.now(FUSO).date()


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def brl(v, mostrar=False) -> str:
    """R$ 1.234,56 (o olho de esconder valores mascara na tela, pelo navegador)."""
    if v is None:
        return "—"
    s = f"{abs(float(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {s}" if float(v) < 0 else f"R$ {s}"


def mes_ref(d: date) -> int:
    return d.year * 100 + d.month


def mes_label(ref: int) -> str:
    return f"{MESES[ref % 100 - 1]}/{str(ref // 100)[2:]}"


def somar_meses(ref: int, n: int) -> int:
    y, m = divmod(ref, 100)
    m0 = y * 12 + (m - 1) + n
    return (m0 // 12) * 100 + (m0 % 12) + 1


def dia_no_mes(ano: int, mes: int, dia: int) -> date:
    """Data com o dia limitado ao último dia do mês (31 -> 28/29/30)."""
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def add_meses(d: date, n: int, dia: int | None = None) -> date:
    ref = somar_meses(mes_ref(d), n)
    return dia_no_mes(ref // 100, ref % 100, dia or d.day)


def vencimento_fatura(data_compra: date, dia_fechamento: int | None, dia_vencimento: int) -> date:
    """Em qual vencimento de fatura cai uma compra no cartão.

    Compra no dia do fechamento ou depois vai para a fatura seguinte.
    Se o vencimento é num dia menor/igual ao fechamento, a fatura vence no mês
    seguinte ao fechamento. Sem dia de fechamento cadastrado, assume 7 dias antes
    do vencimento (padrão da maioria dos bancos).
    """
    fech = dia_fechamento or max(1, dia_vencimento - 7)
    ref = mes_ref(data_compra)
    if data_compra.day >= fech:
        ref = somar_meses(ref, 1)                 # mês em que a fatura fecha
    if dia_vencimento <= fech:
        ref = somar_meses(ref, 1)                 # vence no mês seguinte ao fechamento
    return dia_no_mes(ref // 100, ref % 100, dia_vencimento)

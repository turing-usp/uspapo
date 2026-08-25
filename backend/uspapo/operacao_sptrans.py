"""Correções operacionais auditáveis para limitações conhecidas do GTFS.

O feed da SPTrans associa algumas viagens a um serviço diário, mas publica no
``frequencies.txt`` apenas a grade de dia útil e um único itinerário. Isso não
representa corretamente linhas cujo horário ou percurso muda no fim de semana.

As exceções abaixo são pequenas, explícitas e apontam para comunicados oficiais;
elas não substituem o GTFS como catálogo geral.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable


FONTE_ATENDIMENTO_USP = (
    "https://www.sptrans.com.br/informativos/oeste/"
    "sistema-de-transporte-por-onibus-linhas-que-atendem-a-usp/60359/"
)
FONTE_8086_FIM_DE_SEMANA = (
    "https://www.sptrans.com.br/informativos/oeste/"
    "novo-itinerario-da-linha-8086-10-jaguare-pinheiros/64647/"
)
FONTE_IMPLANTACAO_8086 = (
    "https://www.sptrans.com.br/noticias/"
    "sptrans-implementa-linha-8086-10-no-jaguare-a-partir-de-sabado-28/"
)
INICIO_ATENDIMENTO_FIM_DE_SEMANA = date(2024, 9, 2)
INICIO_DESVIO_8086_FIM_DE_SEMANA = date(2024, 12, 28)
INICIO_ITINERARIO_ATUAL_8086 = date(2025, 8, 2)

# A página operacional informa 8012/8022 durante todo o fim de semana, enquanto
# o GTFS atual traz para essas viagens somente faixas da madrugada.
HORARIO_GTFS_INCOMPLETO_FIM_DE_SEMANA = frozenset({"8012", "8022"})

# A 8086 opera todos os dias, mas aos sábados e domingos contorna a USP devido
# ao fechamento dos portões. O GTFS atual reutiliza o itinerário de dia útil e,
# por isso, associa indevidamente a linha a paradas internas como o Biênio.
DESVIO_EXTERNO_FIM_DE_SEMANA = frozenset({"8086"})

# O recorte GTFS é um retângulo maior que o campus e inclui o Jaguaré. Usá-lo
# como fronteira apagaria justamente as paradas da Av. Bolonha/Kenkiti que o
# itinerário de fim de semana mantém. Estes são os stop_ids do trecho interno
# da viagem útil publicada no snapshot; a variante oficial contorna esse trecho.
PARADAS_INTERNAS_8086 = frozenset({
    "400015886",  # Av. Escola Politécnica (entrada do trecho útil)
    "120015887",
    "1211423",
    "120010360",
    "120010358",
    "120010351",
    "120010352",
    "120010353",
    "1207032",
    "120010330",
    "120010331",
    "120010376",
    "120010328",
    "120010354",
    "120010355",
    "120010356",
    "120010357",
    "120010361",
    "1211424",
    "4011405",
})


def numero_base(linha: str) -> str:
    return str(linha or "").strip().upper().split("-", 1)[0]


def eh_fim_de_semana(dia: date) -> bool:
    return dia.weekday() >= 5


def parada_atendida_na_data(
    linha: str,
    parada: dict[str, Any],
    dia: date,
) -> bool:
    """Aplica somente mudanças de itinerário que o GTFS não consegue expressar."""
    if (
        eh_fim_de_semana(dia)
        and dia >= INICIO_DESVIO_8086_FIM_DE_SEMANA
        and numero_base(linha) in DESVIO_EXTERNO_FIM_DE_SEMANA
        and str(parada.get("id", "")) in PARADAS_INTERNAS_8086
    ):
        return False
    return True


def horario_gtfs_confiavel(linha: str, dia: date) -> bool:
    return not (
        eh_fim_de_semana(dia)
        and dia >= INICIO_ATENDIMENTO_FIM_DE_SEMANA
        and numero_base(linha) in HORARIO_GTFS_INCOMPLETO_FIM_DE_SEMANA
    )


def fontes_operacionais(linhas: Iterable[str], datas: Iterable[date]) -> list[str]:
    numeros = {numero_base(linha) for linha in linhas}
    datas_lista = tuple(datas)
    fim_de_semana_usp = any(
        eh_fim_de_semana(dia) and dia >= INICIO_ATENDIMENTO_FIM_DE_SEMANA
        for dia in datas_lista
    )
    fim_de_semana_8086 = any(
        eh_fim_de_semana(dia) and dia >= INICIO_DESVIO_8086_FIM_DE_SEMANA
        for dia in datas_lista
    )
    fontes: list[str] = []
    if fim_de_semana_usp and numeros & HORARIO_GTFS_INCOMPLETO_FIM_DE_SEMANA:
        fontes.append(FONTE_ATENDIMENTO_USP)
    if fim_de_semana_8086 and numeros & DESVIO_EXTERNO_FIM_DE_SEMANA:
        if any(dia >= INICIO_ITINERARIO_ATUAL_8086 for dia in datas_lista):
            fontes.append(FONTE_8086_FIM_DE_SEMANA)
        else:
            fontes.append(FONTE_IMPLANTACAO_8086)
    return fontes


def aviso_programacao_incompleta(linha: str, dia: date) -> str:
    if not horario_gtfs_confiavel(linha, dia):
        return (
            "A SPTrans confirma a operação dessa linha no fim de semana, mas o "
            "GTFS publicado não contém a grade diurna completa; por isso não é "
            "seguro calcular a espera somente por esse arquivo."
        )
    return ""


__all__ = [
    "FONTE_8086_FIM_DE_SEMANA",
    "FONTE_IMPLANTACAO_8086",
    "FONTE_ATENDIMENTO_USP",
    "aviso_programacao_incompleta",
    "fontes_operacionais",
    "horario_gtfs_confiavel",
    "parada_atendida_na_data",
]

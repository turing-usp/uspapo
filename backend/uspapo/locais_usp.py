"""Catálogo canônico de locais da Cidade Universitária Armando de Salles Oliveira.

Este módulo é a fonte compartilhada para nomes, aliases e coordenadas usados
no roteamento. Os aliases são deliberadamente explícitos: uma sigla só casa
como palavra inteira. Assim, por exemplo, ``Poli`` não casa com ``Polícia`` e
``FAU`` não casa com ``Faustolo``.

Contrato público:

* ``resolver_local(texto)`` devolve a chave canônica quando há um único local;
* ``coordenada_local(texto)`` devolve ``(latitude, longitude)``;
* ``mencoes_locais(texto)`` devolve as chaves em ordem de aparição;
* ``CATALOGO_LOCAIS[chave]`` expõe nome, aliases, coordenadas e fonte.

Os nomes foram conferidos no mapa da Prefeitura do Campus e no GTFS oficial
da SPTrans. As coordenadas de edifícios são do OpenStreetMap auditado contra o
mapa do campus; coordenadas marcadas como GTFS representam a parada ou o ponto
de interesse registrado no recorte oficial da SPTrans.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


FONTE_MAPA_USP = "https://puspc.usp.br/mobilidade/mapas/"
FONTE_GTFS_SPTRANS = "https://www.sptrans.com.br/desenvolvedores/"

__all__ = [
    "CATALOGO_LOCAIS",
    "coordenada_local",
    "dados_local",
    "mencoes_locais",
    "resolver_local",
]


def _local(
    nome: str,
    aliases: tuple[str, ...],
    latitude: float,
    longitude: float,
    *,
    fonte: str = FONTE_MAPA_USP,
    nomes_parada: tuple[str, ...] = (),
    nome_curto: str | None = None,
    localizacao: str = "na Cidade Universitária",
) -> dict[str, Any]:
    return {
        "nome": nome,
        "aliases": aliases,
        "latitude": latitude,
        "longitude": longitude,
        "fonte": fonte,
        "nomes_parada": nomes_parada,
        "nome_curto": nome_curto or aliases[0],
        "localizacao": localizacao,
    }


# ``Central`` pertence somente ao restaurante. Administração Central e
# Reitoria são três destinos diferentes e têm entradas próprias.
CATALOGO_LOCAIS: dict[str, dict[str, Any]] = {
    "restaurante_central": _local(
        "Restaurante Universitário Central",
        (
            "Central",
            "Restaurante Central",
            "Restaurante Universitário Central",
            "RU Central",
            "Bandejão Central",
            "Bandeco Central",
        ),
        -23.5598279,
        -46.7211485,
    ),
    "administracao_central": _local(
        "Administração Central da USP",
        (
            "Administração Central",
            "Administração Central da USP",
            "Prédio da Administração Central",
        ),
        -23.5612529,
        -46.7223728,
    ),
    "reitoria": _local(
        "Reitoria da USP",
        ("Reitoria", "Reitoria da USP", "Prédio da Reitoria"),
        -23.5587573,
        -46.7257853,
        nomes_parada=("Reitoria",),
    ),
    "metro_butanta": _local(
        "Terminal Metrô Butantã",
        (
            "Metrô Butantã",
            "Metro Butanta",
            "Metrô",
            "Metro",
            "Estação Butantã",
            "Estacao Butanta",
            "Terminal Metrô Butantã",
            "Terminal Metro Butanta",
        ),
        -23.5718,
        -46.7082,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Terminal Metrô Butantã",),
        nome_curto="Metrô Butantã",
        localizacao="junto à estação Butantã do metrô",
    ),
    "p1": _local(
        "Portaria 1 da Cidade Universitária",
        (
            "P1",
            "Portaria 1",
            "Portaria Um",
            "Portão 1",
            "Portao 1",
            "Portão Um",
            "Entrada de pedestres da Cidade Universitária",
        ),
        -23.5661,
        -46.7104,
    ),
    "terminal_usp": _local(
        "Terminal USP (Cidade Universitária)",
        (
            "Terminal USP",
            "Terminal da USP",
            "Terminal Cidade Universitária",
            "Terminal da Cidade Universitária",
        ),
        -23.552416,
        -46.732118,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Terminal USP (Cidade Universitária)",),
    ),
    "poli": _local(
        "Escola Politécnica da USP",
        (
            "Poli",
            "Poli USP",
            "Politécnica",
            "Escola Politécnica",
            "Escola Politécnica da USP",
            "EPUSP",
        ),
        -23.5549831,
        -46.7297362,
    ),
    "bienio": _local(
        "Prédio do Biênio da Escola Politécnica",
        ("Biênio", "Bienio", "Biênio da Poli", "Prédio do Biênio", "Prédio do Biênio da Poli"),
        -23.557818,
        -46.732322,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Biênio",),
        nome_curto="Biênio",
        localizacao="na Escola Politécnica, dentro da Cidade Universitária",
    ),
    "civil": _local(
        "Engenharia Civil da Escola Politécnica",
        ("Civil", "Engenharia Civil", "Civil da Poli", "Prédio da Civil"),
        -23.555743,
        -46.733507,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Parada Civil",),
    ),
    "mecanica": _local(
        "Engenharia Mecânica da Escola Politécnica",
        (
            "Mecânica",
            "Mecanica",
            "Engenharia Mecânica",
            "Engenharia Mecanica",
            "Mecânica da Poli",
            "Prédio da Mecânica",
        ),
        -23.5528,
        -46.7284,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Mecânica I", "Mecânica II"),
        nome_curto="Engenharia Mecânica",
        localizacao="na Escola Politécnica, dentro da Cidade Universitária",
    ),
    "metalurgia": _local(
        "Engenharia Metalúrgica e de Materiais da Escola Politécnica",
        (
            "Metalurgia",
            "Engenharia Metalúrgica",
            "Engenharia Metalurgica",
            "Materiais da Poli",
            "PMT",
        ),
        -23.552224,
        -46.731491,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Metalurgia",),
    ),
    "hidraulica": _local(
        "Engenharia Hidráulica e Ambiental da Escola Politécnica",
        (
            "Hidráulica",
            "Hidraulica",
            "Engenharia Hidráulica",
            "Engenharia Ambiental da Poli",
            "PHA",
        ),
        -23.556162,
        -46.726306,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Hidráulica",),
    ),
    "fea": _local(
        "Faculdade de Economia, Administração, Contabilidade e Atuária da USP",
        (
            "FEA",
            "FEA USP",
            "Faculdade de Economia",
            "Faculdade de Economia e Administração",
            "Economia e Administração",
        ),
        -23.5584928,
        -46.7294998,
        nomes_parada=("Economia e Administração",),
    ),
    "ime": _local(
        "Instituto de Matemática e Estatística da USP",
        (
            "IME",
            "IME USP",
            "Instituto de Matemática",
            "Instituto de Matemática e Estatística",
            "Matemática e Estatística",
        ),
        -23.5591370,
        -46.7316847,
        nomes_parada=("Matemática e Estatística",),
    ),
    "if": _local(
        "Instituto de Física da USP",
        ("IF", "IFUSP", "IF USP", "Instituto de Física", "Instituto de Física da USP", "Física"),
        -23.5610906,
        -46.7344949,
        nomes_parada=("Física",),
    ),
    "quimica": _local(
        "Instituto de Química da USP",
        (
            "IQ",
            "IQUSP",
            "IQ USP",
            "Química",
            "Instituto de Química",
            "Instituto de Química da USP",
        ),
        -23.5645595,
        -46.7259003,
        nomes_parada=("Farmácia e Química I", "Farmácia e Química II"),
    ),
    "fflch": _local(
        "Faculdade de Filosofia, Letras e Ciências Humanas da USP",
        (
            "FFLCH",
            "FFLCH USP",
            "Faculdade de Filosofia Letras e Ciências Humanas",
            "Faculdade de Filosofia Letras e Ciencias Humanas",
            "Faculdade de Filosofia e Letras",
        ),
        -23.5627318,
        -46.7242016,
    ),
    "letras": _local(
        "Prédio de Letras da FFLCH",
        ("Letras", "Prédio de Letras", "Letras da FFLCH"),
        -23.562058,
        -46.724361,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Letras",),
    ),
    "historia_geografia": _local(
        "Prédios de História e Geografia da FFLCH",
        (
            "História e Geografia",
            "Historia e Geografia",
            "História da FFLCH",
            "Geografia da FFLCH",
        ),
        -23.56414,
        -46.72239,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("História e Geografia I", "História e Geografia II"),
    ),
    "educacao": _local(
        "Faculdade de Educação da USP",
        ("FEUSP", "FE USP", "Educação", "Faculdade de Educação", "Faculdade de Educação da USP"),
        -23.5625761,
        -46.7157326,
        nomes_parada=("Educação",),
    ),
    "psicologia": _local(
        "Instituto de Psicologia da USP",
        ("IP", "IPUSP", "IP USP", "Psicologia", "Instituto de Psicologia", "Instituto de Psicologia da USP"),
        -23.5559012,
        -46.7248320,
        nomes_parada=("Psicologia I", "Psicologia II"),
    ),
    "geociencias": _local(
        "Instituto de Geociências da USP",
        ("IGc", "IGc USP", "Geociências", "Geociencias", "Instituto de Geociências"),
        -23.5618247,
        -46.7271758,
        nomes_parada=("Geociências",),
    ),
    "fau": _local(
        "Faculdade de Arquitetura e Urbanismo e de Design da USP",
        (
            "FAU",
            "FAU USP",
            "FAUUSP",
            "Faculdade de Arquitetura",
            "Faculdade de Arquitetura e Urbanismo",
            "Arquitetura Urbanismo e Design",
        ),
        -23.5599965,
        -46.730408,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Arquitetura Urbanismo Design I", "Arquitetura Urbanismo Design II"),
    ),
    "eca": _local(
        "Escola de Comunicações e Artes da USP",
        ("ECA", "ECA USP", "ECAUSP", "Escola de Comunicações e Artes", "Comunicações e Artes"),
        -23.557807,
        -46.726901,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Comunicações e Artes",),
    ),
    "inova": _local(
        "InovaUSP",
        ("Inova", "Inova USP", "InovaUSP"),
        -23.557821,
        -46.727255,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Inova USP",),
    ),
    "brasiliana": _local(
        "Biblioteca Brasiliana Guita e José Mindlin",
        (
            "Brasiliana",
            "Biblioteca Brasiliana",
            "Biblioteca Brasiliana Guita e José Mindlin",
            "BBM",
        ),
        -23.562368,
        -46.723045,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Biblioteca Brasiliana",),
    ),
    "praca_relogio": _local(
        "Praça do Relógio",
        ("Praça do Relógio", "Praca do Relogio", "Relógio da USP"),
        -23.555317,
        -46.724043,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Praça do Relógio",),
    ),
    "crusp": _local(
        "Conjunto Residencial da Universidade de São Paulo",
        ("CRUSP", "Conjunto Residencial da USP", "Moradia do CRUSP"),
        -23.5573292,
        -46.7199603,
        nomes_parada=("CRUSP I", "CRUSP II"),
    ),
    "hu": _local(
        "Hospital Universitário da USP",
        ("HU", "HU USP", "HU-USP", "Hospital Universitário", "Hospital Universitário da USP"),
        -23.56384,
        -46.74107,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Hospital Universitário I", "Hospital Universitário II"),
    ),
    "odontologia": _local(
        "Faculdade de Odontologia da USP",
        ("FO", "FOUSP", "FO USP", "Odontologia", "Faculdade de Odontologia"),
        -23.566677,
        -46.73838,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Odontologia",),
    ),
    "ib": _local(
        "Instituto de Biociências da USP",
        ("IB", "IBUSP", "IB USP", "Biociências", "Instituto de Biociências"),
        -23.56641,
        -46.73032,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Biociências I", "Biociências II"),
    ),
    "prefeitura_campus": _local(
        "Prefeitura do Campus USP Capital-Butantã",
        (
            "Prefeitura do Campus",
            "Prefeitura do Campus da USP",
            "Prefeitura do Campus Capital-Butantã",
            "Prefeitura da USP",
            "PUSP-C",
            "PUSP C",
        ),
        -23.55939,
        -46.73856,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Prefeitura do Campus I", "Prefeitura do Campus II"),
    ),
    "raia": _local(
        "Raia Olímpica da USP",
        ("Raia", "Raia Olímpica", "Raia Olímpica da USP"),
        -23.556683,
        -46.720517,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Raia Olímpica",),
    ),
    "cptm_cidade_universitaria": _local(
        "Estação Cidade Universitária da CPTM",
        (
            "CPTM Cidade Universitária",
            "Estação Cidade Universitária",
            "Estação da CPTM Cidade Universitária",
            "Trem Cidade Universitária",
        ),
        -23.5615305,
        -46.7130435,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("CPTM Cidade Universitária I", "CPTM Cidade Universitária II"),
    ),
    "iag": _local(
        "Instituto de Astronomia, Geofísica e Ciências Atmosféricas da USP",
        (
            "IAG",
            "IAG USP",
            "IAGUSP",
            "Instituto de Astronomia e Geofísica",
            "Astronomia e Geofísica",
        ),
        -23.559661,
        -46.734486,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Astronomia e Geofísica",),
    ),
    "io": _local(
        "Instituto Oceanográfico da USP",
        ("IO", "IOUSP", "IO USP", "Instituto Oceanográfico", "Oceanográfico"),
        -23.560829,
        -46.730869,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Oceanográfico",),
    ),
    "eefe": _local(
        "Escola de Educação Física e Esporte da USP",
        (
            "EEFE",
            "EEFE USP",
            "Educação Física",
            "Escola de Educação Física e Esporte",
        ),
        -23.5639835,
        -46.7129075,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Educação Física I", "Educação Física II"),
    ),
    "mae": _local(
        "Museu de Arqueologia e Etnologia da USP",
        ("MAE", "MAE USP", "Museu de Arqueologia", "Museu de Arqueologia e Etnologia"),
        -23.559711,
        -46.742161,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Museu de Arqueologia",),
    ),
    "ipen": _local(
        "Instituto de Pesquisas Energéticas e Nucleares",
        ("IPEN", "Pesquisas Nucleares", "Instituto de Pesquisas Energéticas e Nucleares"),
        -23.566057,
        -46.738512,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Pesquisas Nucleares",),
    ),
    "ipt": _local(
        "Instituto de Pesquisas Tecnológicas",
        ("IPT", "Pesquisas Tecnológicas", "Instituto de Pesquisas Tecnológicas"),
        -23.556039,
        -46.73379,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Pesquisas Tecnológicas",),
    ),
    "icb": _local(
        "Instituto de Ciências Biomédicas da USP",
        ("ICB", "ICB USP", "Biomédicas", "Instituto de Ciências Biomédicas"),
        -23.568607,
        -46.731683,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Biomédicas I e II", "Biomédicas III"),
    ),
    "farmacia": _local(
        "Faculdade de Ciências Farmacêuticas da USP",
        ("FCF", "FCF USP", "Farmácia", "Faculdade de Farmácia", "Faculdade de Ciências Farmacêuticas"),
        -23.565626,
        -46.7250865,
        fonte=FONTE_GTFS_SPTRANS,
        nomes_parada=("Farmácia e Química I", "Farmácia e Química II"),
    ),
}


def _normalizar_palavra(texto: str) -> str:
    bruto = unicodedata.normalize("NFKD", str(texto).casefold())
    return "".join(c for c in bruto if not unicodedata.combining(c))


def _tokens(texto: str) -> list[tuple[str, int, int]]:
    """Tokeniza preservando posições; nunca aceita prefixos como equivalência."""
    return [
        (_normalizar_palavra(match.group(0)), match.start(), match.end())
        for match in re.finditer(r"[^\W_]+", str(texto), flags=re.UNICODE)
    ]


def _tokens_alias(texto: str) -> tuple[str, ...]:
    return tuple(item[0] for item in _tokens(texto))


def _construir_indice() -> dict[tuple[str, ...], str]:
    candidatos: dict[tuple[str, ...], set[str]] = {}
    for chave, local in CATALOGO_LOCAIS.items():
        nomes = (local["nome"], *local["aliases"], *local["nomes_parada"])
        for nome in nomes:
            tokens = _tokens_alias(nome)
            candidatos.setdefault(tokens, set()).add(chave)

    # Uma placa de parada pode atender dois prédios vizinhos (por exemplo,
    # "Farmácia e Química"). Nesse caso o nome da parada não deve escolher um
    # deles silenciosamente; os aliases inequívocos continuam disponíveis.
    return {
        tokens: next(iter(chaves))
        for tokens, chaves in candidatos.items()
        if len(chaves) == 1
    }


_INDICE_ALIASES = _construir_indice()
_ALIASES_ORDENADOS = sorted(
    _INDICE_ALIASES.items(), key=lambda item: (-len(item[0]), item[0])
)


def _mencoes_com_posicao(texto: str) -> list[tuple[int, int, str]]:
    """Retorna ``(início, fim, chave)`` sem aliases sobrepostos."""
    tokens = _tokens(texto)
    if not tokens:
        return []

    candidatos: list[tuple[int, int, int, str]] = []
    valores = [token[0] for token in tokens]
    for alias, chave in _ALIASES_ORDENADOS:
        tamanho = len(alias)
        for inicio in range(0, len(tokens) - tamanho + 1):
            fim = inicio + tamanho
            if tuple(valores[inicio:fim]) == alias:
                # No contexto do campus, "o metrô" costuma significar Butantã.
                # Mas a palavra dentro de "Metrô Santana" ou "Metrô Vila
                # Madalena" não pode transformar silenciosamente outra estação
                # em Butantã. O alias genérico só vale isolado ou seguido de um
                # conector de trajeto; o nome completo "Metrô Butantã" continua
                # vencendo pelo critério de alias mais longo.
                if (
                    chave == "metro_butanta"
                    and alias == ("metro",)
                    and fim < len(tokens)
                    and valores[fim] not in {
                        "a", "ao", "ate", "da", "de", "do", "e", "em",
                        "na", "no", "ou", "para", "pra", "pro",
                    }
                ):
                    continue
                candidatos.append((inicio, fim, tamanho, chave))

    # O alias mais longo vence no mesmo trecho. Isso faz "Administração
    # Central" ser Administração Central, sem criar uma segunda ocorrência do
    # restaurante por causa da palavra "Central".
    selecionados: list[tuple[int, int, int, str]] = []
    ocupados: set[int] = set()
    for candidato in sorted(candidatos, key=lambda item: (-item[2], item[0], item[3])):
        inicio, fim, _, _ = candidato
        if not any(posicao in ocupados for posicao in range(inicio, fim)):
            selecionados.append(candidato)
            ocupados.update(range(inicio, fim))

    return [
        (tokens[inicio][1], tokens[fim - 1][2], chave)
        for inicio, fim, _, chave in sorted(selecionados, key=lambda item: item[0])
    ]


def mencoes_locais(texto: str) -> list[str]:
    """Lista chaves canônicas em ordem, uma por ocorrência não sobreposta."""
    return [chave for _, _, chave in _mencoes_com_posicao(texto)]


def resolver_local(texto: str) -> str | None:
    """Resolve um texto que menciona exatamente um local sem fazer suposições."""
    if texto in CATALOGO_LOCAIS:
        return texto
    mencoes = mencoes_locais(texto)
    unicas = list(dict.fromkeys(mencoes))
    return unicas[0] if len(unicas) == 1 else None


def dados_local(texto: str) -> dict[str, Any] | None:
    """Devolve os dados canônicos de um local reconhecido."""
    chave = texto if texto in CATALOGO_LOCAIS else resolver_local(texto)
    return CATALOGO_LOCAIS.get(chave) if chave else None


def coordenada_local(texto: str) -> tuple[float, float] | None:
    """Devolve a coordenada auditada de um nome, alias ou chave canônica."""
    local = dados_local(texto)
    if not local:
        return None
    return float(local["latitude"]), float(local["longitude"])

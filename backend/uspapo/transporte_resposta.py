"""Contrato público e apresentação das respostas de transporte.

O planejador decide fatos; este módulo decide o que vale a pena dizer ao aluno.
As durações permanecem em segundos até a última etapa para que arredondamento,
ranking e texto nunca tenham verdades diferentes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
import unicodedata


def _normalizar(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto).lower())
    return "".join(c for c in base if not unicodedata.combining(c))


def _minutos(segundos: float) -> int:
    """Arredondamento convencional para medidas não negativas (0,5 sobe)."""
    return max(0, math.floor(float(segundos) / 60 + 0.5))


def _minutos_decimal(segundos: float) -> str:
    valor = round(float(segundos) / 60, 1)
    if valor.is_integer():
        return str(int(valor))
    return str(valor).replace(".", ",")


@dataclass(frozen=True)
class FacetasResposta:
    localizacao: bool = False
    duracao: bool = False
    tempo_real: bool = False
    alternativas: bool = False
    explicacao: bool = False


def facetas_da_pergunta(pergunta: str | None) -> FacetasResposta:
    texto = _normalizar(pergunta or "")
    palavras = set(re.findall(r"[a-z0-9]+", texto))
    return FacetasResposta(
        localizacao=bool(
            palavras & {"onde", "aonde", "fica", "localizacao", "localizado"}
            or "onde e" in texto
        ),
        duracao=bool(
            palavras & {"tempo", "demora", "demorar", "leva", "levar", "quanto"}
        ),
        tempo_real=bool(
            palavras
            & {
                "agora", "quando", "proximo", "proxima", "chega", "chegada",
                "passa", "passar", "previsao",
            }
            or "tempo real" in texto
            or "vai passar" in texto
        ),
        alternativas=bool(
            palavras & {"alternativa", "alternativas", "opcoes", "outras"}
        ),
        explicacao=bool(
            palavras & {"calculo", "calculado", "calculada", "fonte", "dados"}
            or "por que" in texto
            or "de onde vem" in texto
        ),
    )


@dataclass(frozen=True)
class LocalPublico:
    chave: str
    nome: str
    nome_curto: str
    localizacao: str


@dataclass(frozen=True)
class EstimativaEspera:
    base: str
    esperada_s: float
    minima_s: float
    maxima_s: float
    intervalo_s: float | None = None
    eta: str | None = None
    observado_em: str | None = None

    def __post_init__(self) -> None:
        if min(self.minima_s, self.esperada_s, self.maxima_s) < 0:
            raise ValueError("duração de espera negativa")
        if not self.minima_s <= self.esperada_s <= self.maxima_s:
            raise ValueError("espera esperada fora de seus limites")


@dataclass(frozen=True)
class AlternativaPublica:
    linha: str
    sentido: str
    total_s: float


@dataclass(frozen=True)
class ResultadoTrajeto:
    origem: LocalPublico
    destino: LocalPublico
    linha: str
    sentido: str
    embarque: str
    desembarque: str
    caminhada_origem_m: float
    caminhada_destino_m: float
    caminhada_origem_s: float
    caminhada_destino_s: float
    viagem_s: float
    espera: EstimativaEspera
    previsao_consultada: bool = False
    veiculos_ativos: int | None = None
    alternativas: tuple[AlternativaPublica, ...] = ()
    aviso: str = ""

    @property
    def total_esperado_s(self) -> float:
        return (
            self.caminhada_origem_s
            + self.espera.esperada_s
            + self.viagem_s
            + self.caminhada_destino_s
        )

    @property
    def total_minimo_s(self) -> float:
        return (
            self.caminhada_origem_s
            + self.espera.minima_s
            + self.viagem_s
            + self.caminhada_destino_s
        )

    @property
    def total_maximo_s(self) -> float:
        return (
            self.caminhada_origem_s
            + self.espera.maxima_s
            + self.viagem_s
            + self.caminhada_destino_s
        )

    def public_view(self, facetas: FacetasResposta) -> dict[str, object]:
        """Fatos públicos já formatados para a verbalização final."""
        if self.espera.base == "eta_ao_vivo":
            status_api = "eta_disponivel"
        elif self.previsao_consultada:
            status_api = "consultada_sem_eta"
        else:
            status_api = "nao_consultada"
        espera: dict[str, object] = {
            "base": self.espera.base,
            "esperada_min": _minutos_decimal(self.espera.esperada_s),
            "minima_min": _minutos_decimal(self.espera.minima_s),
            "maxima_min": _minutos_decimal(self.espera.maxima_s),
        }
        if self.espera.intervalo_s is not None:
            espera["intervalo_programado_min"] = _minutos_decimal(
                self.espera.intervalo_s
            )
        if self.espera.eta:
            espera["hora_prevista"] = self.espera.eta
        if self.espera.observado_em:
            espera["observado_em"] = self.espera.observado_em

        vista: dict[str, object] = {
            "tipo": "trajeto_onibus",
            "facetas": {
                "localizacao": facetas.localizacao,
                "duracao": facetas.duracao,
                "tempo_real": facetas.tempo_real,
                "alternativas": facetas.alternativas,
                "explicacao": facetas.explicacao,
            },
            "origem": {
                "nome": self.origem.nome_curto,
                "localizacao": self.origem.localizacao,
            },
            "destino": {
                "nome": self.destino.nome_curto,
                "localizacao": self.destino.localizacao,
            },
            "melhor_opcao": {
                "linha": self.linha,
                "sentido": self.sentido,
                "embarque": self.embarque,
                "desembarque": self.desembarque,
                "caminhada_origem_m": round(self.caminhada_origem_m),
                "caminhada_destino_m": round(self.caminhada_destino_m),
            },
            "tempo": {
                "total_esperado_min": _minutos(self.total_esperado_s),
                "total_minimo_min": _minutos(self.total_minimo_s),
                "total_maximo_min": _minutos(self.total_maximo_s),
                "viagem_onibus_min": _minutos_decimal(self.viagem_s),
                "caminhada_total_min": _minutos_decimal(
                    self.caminhada_origem_s + self.caminhada_destino_s
                ),
                "espera": espera,
            },
            "status_api": status_api,
            "fatos_obrigatorios": [self.linha, self.desembarque],
        }
        if facetas.localizacao:
            vista["fatos_obrigatorios"].append(self.destino.nome_curto)
        if facetas.duracao:
            vista["numeros_obrigatorios"] = [_minutos(self.total_esperado_s)]
        if self.previsao_consultada and self.veiculos_ativos is not None:
            vista["veiculos_ativos"] = self.veiculos_ativos
        if facetas.alternativas:
            vista["alternativas"] = [
                {
                    "linha": item.linha,
                    "sentido": item.sentido,
                    "tempo_total_min": _minutos(item.total_s),
                    "base_tempo": "programacao",
                }
                for item in self.alternativas
            ]
        if self.aviso:
            vista["aviso"] = self.aviso
        return vista


def _frase_localizacao(resultado: ResultadoTrajeto) -> str:
    if resultado.caminhada_destino_m <= 80:
        proximidade = (
            f", e a parada **{resultado.desembarque}** fica praticamente em frente"
        )
    else:
        proximidade = (
            f", a cerca de {round(resultado.caminhada_destino_m)} m da parada "
            f"**{resultado.desembarque}**"
        )
    return (
        f"A **{resultado.destino.nome_curto}** fica "
        f"{resultado.destino.localizacao}{proximidade}."
    )


def _frase_rota(
    resultado: ResultadoTrajeto, *, incluir_proximidade: bool = True
) -> str:
    if resultado.caminhada_origem_m <= 120:
        marcador = "no" if "terminal" in _normalizar(resultado.embarque) else "no ponto"
        embarque = f"{marcador} **{resultado.embarque}**"
    else:
        embarque = (
            f"depois de caminhar cerca de {round(resultado.caminhada_origem_m)} m "
            f"até **{resultado.embarque}**"
        )
    frase = (
        f"Saindo do **{resultado.origem.nome_curto}**, pegue o "
        f"**{resultado.linha}, sentido {resultado.sentido}**, {embarque}, e desça "
        f"em **{resultado.desembarque}**."
    )
    if incluir_proximidade and resultado.caminhada_destino_m <= 80:
        frase += " O destino fica praticamente em frente."
    elif incluir_proximidade and resultado.caminhada_destino_m <= 250:
        frase += (
            f" De lá, são cerca de {round(resultado.caminhada_destino_m)} m a pé."
        )
    return frase


def _frase_tempo(resultado: ResultadoTrajeto) -> str:
    total = _minutos(resultado.total_esperado_s)
    if resultado.espera.base == "eta_ao_vivo":
        return (
            f"Com a chegada prevista para **{resultado.espera.eta}**, conte com "
            f"**cerca de {total} minutos no total** se você sair agora."
        )
    if resultado.espera.base == "frequencia_media":
        return (
            f"Em média, reserve **cerca de {total} minutos no total**, já contando "
            "a espera habitual e as caminhadas curtas."
        )
    return (
        f"Pela programação, reserve **cerca de {total} minutos no total**, "
        "incluindo a espera e as caminhadas."
    )


def _frase_explicacao(resultado: ResultadoTrajeto) -> str:
    caminhada_s = resultado.caminhada_origem_s + resultado.caminhada_destino_s
    return (
        "Esse total reúne "
        f"{_minutos_decimal(resultado.viagem_s)} min dentro do ônibus, "
        f"{_minutos_decimal(resultado.espera.esperada_s)} min de espera "
        f"e {_minutos_decimal(caminhada_s)} min de caminhada. A rota e os "
        "tempos programados vêm dos dados oficiais da SPTrans."
    )


def _lista_alternativas(alternativas: tuple[AlternativaPublica, ...]) -> str:
    itens = [
        f"**{item.linha}** (cerca de {_minutos(item.total_s)} min)"
        for item in alternativas
    ]
    if len(itens) <= 1:
        return itens[0] if itens else ""
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _frase_alternativas(resultado: ResultadoTrajeto) -> str:
    lista = _lista_alternativas(resultado.alternativas)
    if not lista:
        return "Não encontrei outra opção direta competitiva para esse trajeto."
    sufixo = (
        " pela programação"
        if resultado.espera.base == "eta_ao_vivo"
        else ""
    )
    return f"Se preferir, há outras opções diretas{sufixo}: {lista}."


def renderizar_trajeto(
    resultado: ResultadoTrajeto,
    facetas: FacetasResposta,
) -> str:
    """Realiza o plano em poucos atos de fala, sem expor implementação."""
    partes: list[str] = []
    if facetas.localizacao:
        partes.append(_frase_localizacao(resultado))

    # Em perguntas apenas de duração, responder o número primeiro. Nas demais,
    # a instrução vem antes e o total fecha a resposta com seu contexto.
    if facetas.duracao and not facetas.localizacao:
        partes.append(_frase_tempo(resultado))
        partes.append(
            _frase_rota(resultado, incluir_proximidade=not facetas.localizacao)
        )
    else:
        partes.append(
            _frase_rota(resultado, incluir_proximidade=not facetas.localizacao)
        )
        partes.append(_frase_tempo(resultado))

    if facetas.tempo_real and resultado.espera.base != "eta_ao_vivo":
        partes.append(
            "Não há previsão exata de chegada para esse ponto neste momento."
        )
    if facetas.explicacao:
        partes.append(_frase_explicacao(resultado))
    if facetas.alternativas:
        partes.append(_frase_alternativas(resultado))
    if resultado.aviso:
        partes.append(resultado.aviso)
    return "\n\n".join(partes)


@dataclass(frozen=True)
class ResultadoCaminhada:
    """Contrato público do trajeto que se faz melhor a pé.

    Ir a pé é uma resposta de primeira classe num campus onde quase tudo está a
    quinze minutos de caminhada. Ela passa pelo mesmo contrato do trajeto de
    ônibus para que a camada de linguagem receba os mesmos fatos obrigatórios —
    antes esse ramo montava a prosa por fora e o naturalizador podia devolver
    uma resposta simpática que não dizia quantos minutos eram.
    """

    origem: LocalPublico
    destino: LocalPublico
    distancia_m: float
    duracao_s: float
    alternativas: tuple[AlternativaPublica, ...] = ()
    aviso: str = ""

    def __post_init__(self) -> None:
        if self.distancia_m < 0 or self.duracao_s < 0:
            raise ValueError("caminhada com distância ou duração negativa")

    @property
    def duracao_min(self) -> int:
        return max(1, _minutos(self.duracao_s))

    def public_view(self, facetas: FacetasResposta) -> dict[str, object]:
        """Fatos públicos já formatados para a verbalização final."""
        vista: dict[str, object] = {
            "tipo": "trajeto_a_pe",
            "facetas": {
                "localizacao": facetas.localizacao,
                "duracao": facetas.duracao,
                "tempo_real": facetas.tempo_real,
                "alternativas": facetas.alternativas,
                "explicacao": facetas.explicacao,
            },
            "origem": {
                "nome": self.origem.nome_curto,
                "localizacao": self.origem.localizacao,
            },
            "destino": {
                "nome": self.destino.nome_curto,
                "localizacao": self.destino.localizacao,
            },
            "melhor_opcao": {
                "modo": "a_pe",
                "distancia_m": round(self.distancia_m),
                "tempo_total_min": self.duracao_min,
            },
            "fatos_obrigatorios": [self.destino.nome_curto],
            # O tempo da caminhada é a resposta inteira aqui, não um detalhe
            # que só aparece quando o aluno pergunta "quanto demora".
            "numeros_obrigatorios": [self.duracao_min],
        }
        if facetas.alternativas and self.alternativas:
            vista["alternativas"] = [
                {
                    "modo": "onibus",
                    "linha": item.linha,
                    "sentido": item.sentido,
                    "tempo_total_min": _minutos(item.total_s),
                    "base_tempo": "programacao",
                }
                for item in self.alternativas
            ]
        if self.aviso:
            vista["aviso"] = self.aviso
        return vista


def renderizar_caminhada(
    resultado: ResultadoCaminhada,
    facetas: FacetasResposta,
) -> str:
    """Fallback determinístico do trajeto a pé."""
    partes: list[str] = []
    if facetas.localizacao:
        partes.append(
            f"A **{resultado.destino.nome_curto}** fica "
            f"{resultado.destino.localizacao}."
        )
    partes.append(
        f"De **{resultado.origem.nome_curto}** até "
        f"**{resultado.destino.nome_curto}**, a melhor opção é ir a pé: são "
        f"cerca de **{resultado.duracao_min} minutos** "
        f"({round(resultado.distancia_m)} m)."
    )
    if resultado.aviso:
        partes.append(resultado.aviso)
    if facetas.alternativas:
        lista = _lista_alternativas(resultado.alternativas)
        partes.append(
            f"Se preferir ônibus, as opções diretas são: {lista}."
            if lista
            else "Não há linha direta competitiva para esse trajeto agora."
        )
    return "\n\n".join(partes)


@dataclass(frozen=True)
class PrevisaoChegada:
    """Uma chegada publicada pela API Olho Vivo."""

    horario: str
    acessivel: bool | None = None

    def __post_init__(self) -> None:
        if not self.horario.strip():
            raise ValueError("previsão de chegada sem horário")


@dataclass(frozen=True)
class FaixaPassagemProgramada:
    """Janela derivada de uma frequência GTFS, nunca um ETA exato."""

    referencia: str
    referencia_instante: str
    inicio: str
    fim: str
    inicio_texto: str
    fim_texto: str
    intervalo_min: int
    espera_tipica_min: int
    espera_maxima_min: int
    ativa_agora: bool

    def __post_init__(self) -> None:
        if self.intervalo_min <= 0:
            raise ValueError("intervalo programado deve ser positivo")
        if min(self.espera_tipica_min, self.espera_maxima_min) < 0:
            raise ValueError("espera programada negativa")


@dataclass(frozen=True)
class PassagensPorSentido:
    """Fatos de chegada de uma linha, parada e sentido inequívocos."""

    linha: str
    parada: str
    sentido: str = ""
    previsoes_ao_vivo: tuple[PrevisaoChegada, ...] = ()
    horarios_programados: tuple[str, ...] = ()
    instantes_programados: tuple[str, ...] = ()
    faixas_programadas: tuple[FaixaPassagemProgramada, ...] = ()


@dataclass(frozen=True)
class ResultadoChegada:
    """Contrato público para perguntas como "quando chega o 8084?".

    O contrato guarda todos os fatos operacionais para uma futura camada de
    linguagem, enquanto ``renderizar_chegada`` oferece uma resposta curta e
    determinística como fallback.
    """

    linha: str
    parada: str
    sentidos: tuple[PassagensPorSentido, ...]
    api_consultada: bool
    observado_em: str | None = None
    veiculos_ativos: int | None = None
    aviso_api: str = ""
    aviso: str = ""

    def __post_init__(self) -> None:
        if not self.sentidos:
            raise ValueError("resultado de chegada sem nenhum sentido")
        if any(item.previsoes_ao_vivo for item in self.sentidos) and not self.api_consultada:
            raise ValueError("ETA ao vivo sem consulta à API")
        if self.veiculos_ativos is not None and self.veiculos_ativos < 0:
            raise ValueError("quantidade negativa de veículos")

    def como_payload(self) -> dict[str, object]:
        """Serializa o contrato sem transformar fatos em prosa."""
        return {
            "tipo": "chegada_onibus",
            "linha": self.linha,
            "parada": self.parada,
            "api_olho_vivo": {
                "consultada": self.api_consultada,
                "observado_em": self.observado_em,
                "veiculos_ativos": self.veiculos_ativos,
                "aviso": self.aviso_api or None,
            },
            "sentidos": [
                {
                    "linha": item.linha,
                    "parada": item.parada,
                    "sentido": item.sentido or None,
                    "previsoes_ao_vivo": [
                        {
                            "horario": previsao.horario,
                            "acessivel": previsao.acessivel,
                        }
                        for previsao in item.previsoes_ao_vivo
                    ],
                    "programacao": {
                        "horarios": list(item.horarios_programados),
                        "instantes": list(item.instantes_programados),
                        "faixas": [
                            {
                                "referencia": faixa.referencia,
                                "referencia_instante": faixa.referencia_instante,
                                "inicio": faixa.inicio,
                                "fim": faixa.fim,
                                "inicio_texto": faixa.inicio_texto,
                                "fim_texto": faixa.fim_texto,
                                "intervalo_min": faixa.intervalo_min,
                                "espera_tipica_min": faixa.espera_tipica_min,
                                "espera_maxima_min": faixa.espera_maxima_min,
                                "ativa_agora": faixa.ativa_agora,
                            }
                            for faixa in item.faixas_programadas
                        ],
                    },
                }
                for item in self.sentidos
            ],
            "aviso": self.aviso or None,
        }

    def public_view(
        self,
        pergunta: str | None = None,
        *,
        detalhes: bool = False,
    ) -> dict[str, object]:
        """Visão segura e já formatada para uma camada final de linguagem.

        IDs internos, instantes auxiliares e nomes de algoritmos ficam fora.
        Assim, um modelo pode naturalizar a resposta sem recalcular horários ou
        precisar interpretar o payload operacional completo.
        """
        facetas = facetas_da_pergunta(pergunta)
        itens: list[dict[str, object]] = []
        tem_eta = False
        for item in self.sentidos:
            if item.previsoes_ao_vivo:
                tem_eta = True
                publico: dict[str, object] = {
                    "linha": item.linha,
                    "sentido": item.sentido or None,
                    "parada": item.parada,
                    "base_previsao": "eta_ao_vivo",
                    "horarios": [p.horario for p in item.previsoes_ao_vivo],
                    "acessibilidade": [
                        p.acessivel for p in item.previsoes_ao_vivo
                    ],
                }
            else:
                referencia = _proxima_referencia_programada(item)
                publico = {
                    "linha": item.linha,
                    "sentido": item.sentido or None,
                    "parada": item.parada,
                    "base_previsao": "indisponivel",
                    "horarios": [],
                }
                if referencia and referencia[0] == "horario":
                    publico.update({
                        "base_previsao": "horario_programado",
                        "horarios": list(item.horarios_programados[:3]),
                    })
                elif referencia:
                    faixa = referencia[1]
                    assert isinstance(faixa, FaixaPassagemProgramada)
                    publico.update({
                        "base_previsao": "frequencia_programada",
                        "horario_referencia": faixa.referencia,
                        "espera_tipica_min": faixa.espera_tipica_min,
                        "intervalo_programado_min": faixa.intervalo_min,
                    })
                    if not faixa.ativa_agora:
                        publico["janela"] = {
                            "inicio": faixa.inicio_texto,
                            "fim": faixa.fim_texto,
                        }
            itens.append(publico)

        if tem_eta:
            status_api = "eta_disponivel"
        elif self.api_consultada:
            status_api = "consultada_sem_eta"
        else:
            status_api = "nao_consultada"
        vista: dict[str, object] = {
            "tipo": "chegada_onibus",
            "facetas": {
                "tempo_real": facetas.tempo_real,
                "explicacao": facetas.explicacao or detalhes,
            },
            "linha": self.linha,
            "parada": self.parada,
            "status_api": status_api,
            "sentidos": itens,
            "fatos_obrigatorios": [self.linha, self.parada],
        }
        horarios_obrigatorios: list[str] = []
        for item in itens:
            horarios = item.get("horarios")
            if isinstance(horarios, list) and horarios:
                horarios_obrigatorios.append(str(horarios[0]))
            elif item.get("horario_referencia"):
                horarios_obrigatorios.append(str(item["horario_referencia"]))
        if horarios_obrigatorios:
            vista["horarios_obrigatorios"] = list(
                dict.fromkeys(horarios_obrigatorios)
            )
        if self.api_consultada and self.observado_em:
            vista["observado_em"] = self.observado_em
        if self.api_consultada and self.veiculos_ativos is not None:
            vista["veiculos_ativos"] = self.veiculos_ativos
        if detalhes and self.aviso_api:
            vista["observacao_api"] = self.aviso_api
        if self.aviso:
            vista["aviso"] = self.aviso
        return vista


def _instante_ordenavel(valor: str | None) -> float:
    try:
        return datetime.fromisoformat(str(valor)).timestamp()
    except (TypeError, ValueError, OverflowError):
        return math.inf


def _proxima_referencia_programada(
    passagens: PassagensPorSentido,
) -> tuple[str, str | FaixaPassagemProgramada] | None:
    """Escolhe a referência cronologicamente mais próxima sem perder o tipo."""
    candidatos: list[tuple[float, str, str | FaixaPassagemProgramada]] = []
    if passagens.horarios_programados:
        instante = (
            passagens.instantes_programados[0]
            if passagens.instantes_programados
            else None
        )
        candidatos.append((
            _instante_ordenavel(instante),
            "horario",
            passagens.horarios_programados[0],
        ))
    if passagens.faixas_programadas:
        faixa = passagens.faixas_programadas[0]
        candidatos.append((
            _instante_ordenavel(faixa.referencia_instante),
            "frequencia",
            faixa,
        ))
    if not candidatos:
        return None
    _instante, tipo, referencia = min(candidatos, key=lambda item: item[0])
    return tipo, referencia


def _descricao_linha(passagens: PassagensPorSentido) -> str:
    if passagens.sentido:
        return f"**{passagens.linha}, sentido {passagens.sentido}**"
    return f"**{passagens.linha}**"


def _juntar_horarios(horarios: tuple[str, ...]) -> str:
    if len(horarios) <= 1:
        return horarios[0] if horarios else ""
    if len(horarios) == 2:
        return f"{horarios[0]} e {horarios[1]}"
    return ", ".join(horarios[:-1]) + f" e {horarios[-1]}"


def _frases_chegada_ao_vivo(passagens: PassagensPorSentido) -> list[str]:
    previsoes = passagens.previsoes_ao_vivo
    primeira = previsoes[0]
    proximas = tuple(item.horario for item in previsoes[:3])
    if len(proximas) == 1:
        frases = [
            f"O próximo {_descricao_linha(passagens)} deve chegar à parada "
            f"**{passagens.parada}** às **{primeira.horario}**."
        ]
    else:
        frases = [
            f"As próximas chegadas previstas do {_descricao_linha(passagens)} "
            f"na parada **{passagens.parada}** são **"
            + ", ".join(proximas)
            + "**."
        ]
    acessiveis = sum(item.acessivel is True for item in previsoes[:3])
    if acessiveis:
        verbo = "aparece como acessível" if acessiveis == 1 else "aparecem como acessíveis"
        frases.append(
            f"{acessiveis} dos próximos {min(3, len(previsoes))} ônibus {verbo}."
        )
    return frases


def _frases_referencia_programada(
    passagens: PassagensPorSentido,
    *,
    api_consultada: bool,
    prefixo_sentido: bool = False,
    veiculos_ativos: int | None = None,
) -> list[str]:
    referencia = _proxima_referencia_programada(passagens)
    descricao = _descricao_linha(passagens)
    inicio = f"Para {descricao}, o próximo ônibus" if prefixo_sentido else f"O próximo {descricao}"
    if api_consultada and not prefixo_sentido:
        if veiculos_ativos:
            prefixo_api = (
                f"A SPTrans mostra {veiculos_ativos} ônibus da linha em "
                "circulação, mas não publicou uma previsão ao vivo para essa "
                "parada agora. "
            )
        else:
            prefixo_api = (
                "A SPTrans não publicou uma previsão ao vivo para essa parada "
                "agora. "
            )
    else:
        prefixo_api = ""
    if referencia is None:
        if api_consultada:
            return [
                f"A SPTrans não informou a chegada do {descricao} na parada "
                f"**{passagens.parada}** agora."
            ]
        return [
            f"Não encontrei uma referência programada do {descricao} na parada "
            f"**{passagens.parada}**."
        ]

    tipo, valor = referencia
    if tipo == "horario":
        horarios = passagens.horarios_programados[:3]
        if len(horarios) > 1:
            corpo = (
                f"Pela programação, as próximas passagens do {descricao} na "
                f"parada **{passagens.parada}** são **"
                + ", ".join(horarios)
                + "**."
            )
        else:
            corpo = (
                f"{inicio} está programado para **{valor}** na parada "
                f"**{passagens.parada}**."
            )
        if prefixo_sentido:
            return [prefixo_api + corpo]
        return [
            prefixo_api + corpo,
            "É uma estimativa baseada na programação da linha, não uma "
            "confirmação em tempo real.",
        ]

    faixa = valor
    assert isinstance(faixa, FaixaPassagemProgramada)
    if faixa.ativa_agora:
        corpo = (
            f"{inicio} deve passar em **{passagens.parada}** por volta de "
            f"**{faixa.referencia}**."
        )
        espera = (
            "Essa é uma estimativa baseada na programação por frequência: a espera "
            f"típica é de cerca de **{faixa.espera_tipica_min} minutos**, "
            f"com intervalo programado de **{faixa.intervalo_min} minutos**; "
            "não é uma confirmação em tempo real."
        )
    else:
        corpo = (
            f"{inicio} é esperado por volta de **{faixa.referencia}** na parada "
            f"**{passagens.parada}**; essa faixa começa às "
            f"**{faixa.inicio_texto}** e vai até **{faixa.fim_texto}**."
        )
        espera = (
            "Essa é uma estimativa baseada na programação; nessa faixa, a "
            f"espera típica é de cerca de "
            f"**{faixa.espera_tipica_min} minutos**, com intervalo máximo de "
            f"**{faixa.intervalo_min} minutos**."
        )
    if prefixo_sentido:
        return [prefixo_api + corpo[:-1] + "; " + espera[0].lower() + espera[1:]]
    return [prefixo_api + corpo, espera]


def _detalhes_chegada(resultado: ResultadoChegada) -> str:
    blocos: list[str] = []
    for item in resultado.sentidos:
        referencia = _proxima_referencia_programada(item)
        if referencia and referencia[0] == "frequencia":
            faixa = referencia[1]
            assert isinstance(faixa, FaixaPassagemProgramada)
            sentido = f" no sentido {item.sentido}" if item.sentido else ""
            blocos.append(
                f"A referência{sentido} vem de uma faixa oficial com ônibus "
                f"a cada {faixa.intervalo_min} minutos; por isso ela indica uma "
                "janela, não uma partida exata."
            )
        elif referencia and referencia[0] == "horario":
            blocos.append(
                "Os horários exibidos são partidas programadas e podem variar "
                "com o trânsito e a operação."
            )
    if resultado.aviso_api:
        blocos.append(resultado.aviso_api)
    if not blocos:
        blocos.append(
            "A previsão ao vivo vem da API Olho Vivo da SPTrans e pode mudar "
            "conforme o ônibus avança."
        )
    return " ".join(dict.fromkeys(blocos))


def renderizar_chegada(
    resultado: ResultadoChegada,
    *,
    detalhes: bool = False,
) -> str:
    """Fallback curto; a camada de linguagem deve consumir ``public_view``."""
    sentidos_com_eta = [
        item for item in resultado.sentidos if item.previsoes_ao_vivo
    ]
    partes: list[str] = []

    # ETA real sempre vence a programação. Não mostramos os dois relógios na
    # mesma resposta padrão porque isso induz o aluno a compará-los como iguais.
    if sentidos_com_eta:
        if len(sentidos_com_eta) == 1:
            partes.extend(_frases_chegada_ao_vivo(sentidos_com_eta[0]))
        else:
            partes.append(
                f"A **{resultado.linha}** tem previsão ao vivo em mais de um "
                f"sentido na parada **{resultado.parada}**:"
            )
            partes.extend(
                "- " + _frases_chegada_ao_vivo(item)[0]
                for item in sentidos_com_eta
            )
    elif len(resultado.sentidos) == 1:
        partes.extend(_frases_referencia_programada(
            resultado.sentidos[0],
            api_consultada=resultado.api_consultada,
            veiculos_ativos=resultado.veiculos_ativos,
        ))
    else:
        if resultado.api_consultada and resultado.veiculos_ativos:
            estado_api = (
                f"A SPTrans mostra {resultado.veiculos_ativos} ônibus da linha "
                "em circulação, mas não publicou uma previsão ao vivo agora; "
            )
        elif resultado.api_consultada:
            estado_api = "A SPTrans não publicou uma previsão ao vivo agora; "
        else:
            estado_api = "Pela programação, "
        partes.append(
            f"{estado_api}a **{resultado.linha}** atende a parada "
            f"**{resultado.parada}** em mais de um sentido:"
        )
        for item in resultado.sentidos:
            frases = _frases_referencia_programada(
                item, api_consultada=False, prefixo_sentido=True
            )
            partes.append("- " + " ".join(frases))

    if detalhes:
        partes.append(_detalhes_chegada(resultado))
    if resultado.aviso:
        partes.append(resultado.aviso)
    return "\n\n".join(partes)


__all__ = [
    "AlternativaPublica",
    "EstimativaEspera",
    "FaixaPassagemProgramada",
    "FacetasResposta",
    "LocalPublico",
    "PassagensPorSentido",
    "PrevisaoChegada",
    "ResultadoCaminhada",
    "ResultadoChegada",
    "ResultadoTrajeto",
    "facetas_da_pergunta",
    "renderizar_caminhada",
    "renderizar_chegada",
    "renderizar_trajeto",
]

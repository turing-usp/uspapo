"""Contrato público e apresentação das respostas de transporte.

O planejador decide fatos; este módulo decide o que vale a pena dizer ao aluno.
As durações permanecem em segundos até a última etapa para que arredondamento,
ranking e texto nunca tenham verdades diferentes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
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
                "passa", "passar", "passando", "circulando", "hoje", "previsao",
                "previsoes", "horario", "horarios",
            }
            or "tempo real" in texto
            or "vai passar" in texto
            or "neste momento" in texto
            or "nesse momento" in texto
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
        if min(
            self.minima_s,
            self.esperada_s,
            self.maxima_s,
        ) < 0:
            raise ValueError(
                "duração de espera negativa"
            )

        if not (
            self.minima_s
            <= self.esperada_s
            <= self.maxima_s
        ):
            raise ValueError(
                "espera esperada fora de seus limites"
            )

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
    # Identificadores fazem parte do fato calculado e ficam fora da vista
    # normal entregue ao naturalizador; servem para auditoria/reuso interno.
    embarque_id: str | None = None
    desembarque_id: str | None = None
    espera_source: str = "scheduled"
    espera_confidence: str = "scheduled"
    tempo_bordo_source: str = "gtfs_scheduled"

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
            "source": self.espera_source,
            "confidence": self.espera_confidence,
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
    source: str = "live"
    confidence: str = "low"
    minutos_ate_chegada: int | None = None
    intervalo_programado_min: int | None = None
    # Instante técnico usado apenas para ordenar fontes diferentes (inclusive
    # em 24:xx/meia-noite). Não é exposto ao naturalizador.
    instante: str | None = None

    def __post_init__(self) -> None:
        if not self.horario.strip():
            raise ValueError(
                "previsão de chegada sem horário"
            )

        if self.source not in {
            "live",
            "live_gps_estimate",
            "scheduled",
            "scheduled_estimate",
        }:
            raise ValueError(
                f"origem de chegada inválida: {self.source!r}"
            )

        niveis = {
            "high",
            "medium",
            "low",
            "scheduled",
            "scheduled_uncertain",
        }

        if self.confidence not in niveis:
            raise ValueError(
                "confiança de chegada inválida"
            )

        if (
            self.source == "scheduled"
            and self.confidence != "scheduled"
        ):
            raise ValueError(
                "horário programado não pode ter confiança ao vivo"
            )

        if (
            self.source == "scheduled_estimate"
            and self.confidence not in {
                "scheduled",
                "scheduled_uncertain",
            }
        ):
            raise ValueError(
                "estimativa programada com confiança inválida"
            )

        if (
            self.source in {
                "live",
                "live_gps_estimate",
            }
            and self.confidence in {
                "scheduled",
                "scheduled_uncertain",
            }
        ):
            raise ValueError(
                "ETA baseado em dados ao vivo não pode ser programado"
            )

        if (
            self.source == "live_gps_estimate"
            and self.confidence == "high"
        ):
            raise ValueError(
                "ETA derivado de GPS não pode ter confiança alta"
            )

        if (
            self.minutos_ate_chegada is not None
            and self.minutos_ate_chegada < 0
        ):
            raise ValueError(
                "minutos até chegada negativos"
            )

        if (
            self.intervalo_programado_min is not None
            and self.intervalo_programado_min <= 0
        ):
            raise ValueError(
                "intervalo programado inválido"
            )


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
    estimativas_programadas: tuple[PrevisaoChegada, ...] = ()
    faixas_programadas: tuple[FaixaPassagemProgramada, ...] = ()
    programacao_confidence: str = "scheduled"
    # Evidência técnica do Olho Vivo, intencionalmente fora de como_payload e
    # public_view. Serve à próxima fase de classificação de confiança sem fazer
    # a LLM interpretar IDs, coordenadas ou clocks brutos.
    dados_operacionais: tuple[dict[str, object], ...] = ()


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
    api_falhou: bool = False
    observado_em: str | None = None
    veiculos_ativos: int | None = None
    aviso_api: str = ""
    aviso: str = ""
    sem_servico: bool = False
    sem_passagem: bool = False
    horario_indisponivel: bool = False
    periodo: str = ""

    def __post_init__(self) -> None:
        if not self.sentidos:
            raise ValueError("resultado de chegada sem nenhum sentido")
        if any(item.previsoes_ao_vivo for item in self.sentidos) and not self.api_consultada:
            raise ValueError("ETA ao vivo sem consulta à API")
        if self.api_falhou and not self.api_consultada:
            raise ValueError("falha de API sem tentativa de consulta")
        if self.veiculos_ativos is not None and self.veiculos_ativos < 0:
            raise ValueError("quantidade negativa de veículos")

    def como_payload(self) -> dict[str, object]:
        """Serializa o contrato sem transformar fatos em prosa."""
        tem_eta = any(item.previsoes_ao_vivo for item in self.sentidos)
        return {
            "tipo": "chegada_onibus",
            "linha": self.linha,
            "parada": self.parada,
            "api_olho_vivo": {
                "consultada": self.api_consultada,
                "status": (
                    "eta_disponivel"
                    if tem_eta
                    else "indisponivel"
                    if self.api_falhou
                    else "consultada_sem_eta"
                    if self.api_consultada
                    else "nao_consultada"
                ),
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
                            "source": previsao.source,
                            "confidence": previsao.confidence,
                            "minutos_ate_chegada": previsao.minutos_ate_chegada,
                        }
                        for previsao in item.previsoes_ao_vivo
                    ],
                    "programacao": {
                        "horarios": list(item.horarios_programados),
                        "instantes": list(item.instantes_programados),
                        "chegadas": [
                            {
                                "horario": horario,
                                "source": "scheduled",
                                "confidence": item.programacao_confidence,
                            }
                            for horario in item.horarios_programados[:3]
                        ],
                        "estimativas": [
                            {
                                "horario": previsao.horario,
                                "source": previsao.source,
                                "confidence": previsao.confidence,
                                "intervalo_programado_min": previsao.intervalo_programado_min,
                            }
                            for previsao in item.estimativas_programadas[:3]
                        ],
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

        def minutos_relogio(valor: object) -> int | None:
            encontrados = re.findall(r"(\d{1,2}):(\d{2})", str(valor or ""))
            if not encontrados:
                return None
            hora, minuto = (int(parte) for parte in encontrados[-1])
            if hora > 23 or minuto > 59:
                return None
            return hora * 60 + minuto

        referencia_min = minutos_relogio(self.observado_em)

        def instante_iso(valor: str | None) -> datetime | None:
            try:
                instante = datetime.fromisoformat(str(valor))
            except (TypeError, ValueError):
                return None
            # Instantes internos são aware. Um ISO legado sem offset não pode
            # ser comparado diretamente com eles; ele cai no mesmo caminho
            # seguro de relógio HH:MM abaixo.
            return instante if instante.tzinfo is not None else None

        def ordem_temporal(
            horario: str,
            instante: str | None,
            ancora_iso: datetime | None,
        ) -> float:
            instante_valido = instante_iso(instante)
            if instante_valido is not None:
                return instante_valido.timestamp()
            minutos = minutos_relogio(horario)
            if minutos is None:
                return math.inf
            # Nunca misture minutos-do-dia com timestamps Unix. Se qualquer
            # fonte trouxe um instante ISO, ancore os relógios legados na data
            # mais próxima dele, inclusive na virada da meia-noite.
            if ancora_iso is not None:
                candidato = datetime.combine(
                    ancora_iso.date(),
                    time(minutos // 60, minutos % 60),
                    tzinfo=ancora_iso.tzinfo,
                )
                if candidato - ancora_iso > timedelta(hours=12):
                    candidato -= timedelta(days=1)
                elif ancora_iso - candidato > timedelta(hours=12):
                    candidato += timedelta(days=1)
                return candidato.timestamp()

            # Sem nenhum ISO (integrações antigas), ``observado_em`` ainda
            # resolve a virada do dia sem expor essa conta à LLM.
            if referencia_min is not None:
                if minutos < referencia_min - 12 * 60:
                    minutos += 24 * 60
                elif minutos > referencia_min + 12 * 60:
                    minutos -= 24 * 60
            return float(minutos)

        def chegadas_mescladas(
            item: PassagensPorSentido,
        ) -> list[dict[str, object]]:
            instantes_conhecidos = [
                instante_iso(previsao.instante)
                for previsao in item.previsoes_ao_vivo
            ] + [
                instante_iso(instante)
                for instante in item.instantes_programados
            ] + [
                instante_iso(previsao.instante)
                for previsao in item.estimativas_programadas
            ]
            ancora_iso = min(
                (
                    instante
                    for instante in instantes_conhecidos
                    if instante is not None
                ),
                default=None,
            )
            candidatos: list[
                tuple[float, int, int, dict[str, object], bool]
            ] = []
            indice = 0

            for previsao in item.previsoes_ao_vivo:
                publico: dict[str, object] = {
                    "horario": previsao.horario,
                    "minutos_ate_chegada": previsao.minutos_ate_chegada,
                    "source": previsao.source,
                    "confidence": previsao.confidence,
                }
                candidatos.append((
                    ordem_temporal(
                        previsao.horario, previsao.instante, ancora_iso
                    ),
                    3,
                    indice,
                    publico,
                    True,
                ))
                indice += 1

            for posicao, horario in enumerate(item.horarios_programados):
                instante = (
                    item.instantes_programados[posicao]
                    if posicao < len(item.instantes_programados)
                    else None
                )
                publico = {
                    "horario": horario,
                    "source": "scheduled",
                    "confidence": item.programacao_confidence,
                }
                candidatos.append((
                    ordem_temporal(horario, instante, ancora_iso),
                    2,
                    indice,
                    publico,
                    False,
                ))
                indice += 1

            for previsao in item.estimativas_programadas:
                publico = {
                    "horario": previsao.horario,
                    "source": previsao.source,
                    "confidence": previsao.confidence,
                    "intervalo_programado_min":
                        previsao.intervalo_programado_min,
                }
                candidatos.append((
                    ordem_temporal(
                        previsao.horario, previsao.instante, ancora_iso
                    ),
                    1,
                    indice,
                    publico,
                    False,
                ))
                indice += 1

            # Um ETA ao vivo substitui o baseline até o último veículo
            # observado. Só usamos a programação para completar passagens
            # posteriores, nunca para inserir um suposto ônibus antes dele.
            ordens_live = [
                ordem for ordem, _prioridade, _i, _item, ao_vivo in candidatos
                if ao_vivo
            ]
            limite_live = max(ordens_live) if ordens_live else None
            if limite_live is not None:
                candidatos = [
                    candidato
                    for candidato in candidatos
                    if candidato[4] or candidato[0] > limite_live
                ]

            candidatos.sort(
                key=lambda candidato: (
                    candidato[0], -candidato[1], candidato[2]
                )
            )
            resultado: list[dict[str, object]] = []
            fontes_por_horario: dict[str, str] = {}
            for _ordem, _prioridade, _i, chegada, ao_vivo in candidatos:
                horario = str(chegada["horario"])
                fonte_existente = fontes_por_horario.get(horario)
                if fonte_existente is not None and not (
                    ao_vivo and fonte_existente in {"live", "live_gps_estimate"}
                ):
                    continue
                fontes_por_horario.setdefault(
                    horario, str(chegada["source"])
                )
                resultado.append(chegada)
                if len(resultado) == 3:
                    break
            return resultado

        for item in self.sentidos:
            chegadas = chegadas_mescladas(item)
            if item.previsoes_ao_vivo:
                tem_eta = True

                fontes_previsao = {
                    previsao.source
                    for previsao in item.previsoes_ao_vivo
                }

                somente_gps_estimado = (
                    fontes_previsao
                    == {"live_gps_estimate"}
                )

                publico: dict[str, object] = {
                    "linha": item.linha,
                    "sentido": item.sentido or None,
                    "parada": item.parada,
                    "base_previsao": (
                        "eta_gps_estimado"
                        if somente_gps_estimado
                        else "eta_ao_vivo"
                    ),
                    "horarios": [str(chegada["horario"]) for chegada in chegadas],
                    "chegadas": chegadas,
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
                if chegadas and chegadas[0].get("source") == "scheduled":
                    publico.update({
                        "base_previsao": "horario_programado",
                        "horarios": [
                            str(chegada["horario"]) for chegada in chegadas
                        ],
                        "chegadas": chegadas,
                    })
                elif chegadas:
                    intervalos = {
                        int(chegada["intervalo_programado_min"])
                        for chegada in chegadas
                        if chegada.get("intervalo_programado_min") is not None
                    }

                    if not intervalos:
                        publico.update({
                            "base_previsao": "horario_programado_estimado",
                            "horarios": [
                                str(chegada["horario"])
                                for chegada in chegadas
                            ],
                            "chegadas": chegadas,
                        })
                    else:
                        publico.update({
                            "base_previsao": "frequencia_programada_estimada",
                            "horarios": [
                                str(chegada["horario"])
                                for chegada in chegadas
                            ],
                            "chegadas": chegadas,
                        })
                        if len(intervalos) == 1:
                            publico["intervalo_programado_min"] = next(
                                iter(intervalos)
                            )
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
        elif self.api_falhou:
            status_api = "indisponivel"
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
        if self.sem_servico:
            vista["status_operacao"] = "sem_servico"
            vista["periodo"] = self.periodo or None
            vista["frases_obrigatorias"] = ["não tem serviço programado"]
        elif self.sem_passagem:
            vista["status_operacao"] = "sem_passagem_restante"
            vista["periodo"] = self.periodo or None
            vista["frases_obrigatorias"] = [
                "não há outra passagem programada"
            ]
        elif self.horario_indisponivel:
            vista["status_operacao"] = "horario_indisponivel"
            vista["periodo"] = self.periodo or None
            vista["frases_obrigatorias"] = [
                "não é seguro informar a próxima chegada"
            ]
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
) -> tuple[str, str | PrevisaoChegada | FaixaPassagemProgramada] | None:
    """Escolhe a referência cronologicamente mais próxima sem perder o tipo."""
    candidatos: list[
        tuple[float, str, str | PrevisaoChegada | FaixaPassagemProgramada]
    ] = []
    if passagens.horarios_programados:
        instante = (
            passagens.instantes_programados[0]
            if passagens.instantes_programados
            else None
        )
        instante_ordenavel = _instante_ordenavel(instante)
        if math.isinf(instante_ordenavel):
            minutos = re.findall(
                r"(\d{1,2}):(\d{2})", passagens.horarios_programados[0]
            )
            instante_ordenavel = (
                float(int(minutos[-1][0]) * 60 + int(minutos[-1][1]))
                if minutos
                else math.inf
            )
        candidatos.append((
            instante_ordenavel,
            "horario",
            passagens.horarios_programados[0],
        ))
    if passagens.estimativas_programadas:
        estimativa = passagens.estimativas_programadas[0]
        instante_estimado = _instante_ordenavel(estimativa.instante)
        if math.isinf(instante_estimado):
            minutos = re.findall(
                r"(\d{1,2}):(\d{2})", estimativa.horario
            )
            instante_estimado = (
                float(int(minutos[-1][0]) * 60 + int(minutos[-1][1]))
                if minutos
                else math.inf
            )
        candidatos.append((
            instante_estimado,
            "estimativa",
            estimativa,
        ))
    if not passagens.estimativas_programadas and passagens.faixas_programadas:
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


def _frases_chegada_ao_vivo(
    passagens: PassagensPorSentido,
) -> list[str]:
    previsoes = passagens.previsoes_ao_vivo
    primeira = previsoes[0]

    proximas = tuple(
        item.horario
        for item in previsoes[:3]
    )

    somente_gps_estimado = all(
        item.source == "live_gps_estimate"
        for item in previsoes[:3]
    )

    if len(proximas) == 1:
        if somente_gps_estimado:
            frases = [
                f"Pela posição GPS em tempo real, o próximo "
                f"{_descricao_linha(passagens)} tem chegada estimada "
                f"à parada **{passagens.parada}** por volta de "
                f"**{primeira.horario}**."
            ]
        else:
            frases = [
                f"O próximo {_descricao_linha(passagens)} deve chegar "
                f"à parada **{passagens.parada}** às "
                f"**{primeira.horario}**."
            ]
    else:
        if somente_gps_estimado:
            frases = [
                f"Pelas posições GPS em tempo real, as próximas "
                f"chegadas estimadas do {_descricao_linha(passagens)} "
                f"na parada **{passagens.parada}** são **"
                + ", ".join(proximas)
                + "**."
            ]
        else:
            frases = [
                f"As próximas chegadas previstas do "
                f"{_descricao_linha(passagens)} na parada "
                f"**{passagens.parada}** são **"
                + ", ".join(proximas)
                + "**."
            ]

    acessiveis = sum(
        item.acessivel is True
        for item in previsoes[:3]
    )

    if acessiveis:
        verbo = (
            "aparece como acessível"
            if acessiveis == 1
            else "aparecem como acessíveis"
        )

        frases.append(
            f"{acessiveis} dos próximos "
            f"{min(3, len(previsoes))} ônibus {verbo}."
        )

    return frases


def _frases_referencia_programada(
    passagens: PassagensPorSentido,
    *,
    api_consultada: bool,
    prefixo_sentido: bool = False,
    veiculos_ativos: int | None = None,
    api_falhou: bool = False,
) -> list[str]:
    referencia = _proxima_referencia_programada(passagens)
    descricao = _descricao_linha(passagens)
    inicio = f"Para {descricao}, o próximo ônibus" if prefixo_sentido else f"O próximo {descricao}"
    if api_falhou and not prefixo_sentido:
        prefixo_api = (
            "A consulta em tempo real à SPTrans não respondeu agora. "
        )
    elif api_consultada and not prefixo_sentido:
        if veiculos_ativos:
            prefixo_api = (
                f"A SPTrans reportou posições de {veiculos_ativos} ônibus "
                "nesse sentido, mas nenhuma produziu uma previsão segura para "
                "essa parada agora. "
            )
        else:
            prefixo_api = (
                "A SPTrans não publicou uma previsão ao vivo para essa parada "
                "agora. "
            )
    else:
        prefixo_api = ""
    if referencia is None:
        if api_falhou and not prefixo_sentido:
            return [
                "A consulta em tempo real à SPTrans não respondeu agora e "
                f"não encontrei uma referência programada do {descricao} na "
                f"parada **{passagens.parada}**."
            ]
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

    if tipo == "estimativa":
        estimativas = passagens.estimativas_programadas[:3]
        horarios = tuple(
            f"~{item.horario}"
            for item in estimativas
        )

        intervalos = tuple(dict.fromkeys(
            item.intervalo_programado_min
            for item in estimativas
            if item.intervalo_programado_min is not None
        ))

        if not intervalos:
            corpo = (
                f"Pela programação oficial, as próximas passagens estimadas "
                f"do {descricao} na parada **{passagens.parada}** são **"
                + ", ".join(horarios)
                + "**."
            )

            cautela = (
                "Os horários são estimados a partir das partidas programadas "
                "e do perfil do trajeto; não são confirmações em tempo real."
            )
        else:
            corpo = (
                f"Pela frequência programada, as próximas passagens estimadas "
                f"do {descricao} na parada **{passagens.parada}** são **"
                + ", ".join(horarios)
                + "**."
            )

            if len(intervalos) == 1:
                cautela = (
                    f"São slots estimados a partir do intervalo programado de "
                    f"**{intervalos[0]} minutos**, não confirmações em tempo real."
                )
            else:
                intervalos_texto = _juntar_horarios(tuple(
                    f"{intervalo} minutos" for intervalo in intervalos
                ))
                cautela = (
                    "São slots estimados em faixas cuja frequência muda entre "
                    f"**{intervalos_texto}**; não são confirmações em tempo real."
                )

        if prefixo_sentido:
            return [
                prefixo_api
                + corpo[:-1]
                + "; "
                + cautela[0].lower()
                + cautela[1:]
            ]

        return [
            prefixo_api + corpo,
            cautela,
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
        elif referencia and referencia[0] == "estimativa":
            estimativa = referencia[1]
            assert isinstance(
                estimativa,
                PrevisaoChegada,
            )

            if estimativa.intervalo_programado_min is None:
                blocos.append(
                    "Os horários com ~ são estimados a partir das "
                    "partidas programadas pela SPTrans e do perfil "
                    "do trajeto; não são chegadas confirmadas."
                )
            else:
                blocos.append(
                    "Os horários com ~ são estimados pela frequência "
                    "GTFS, não chegadas confirmadas."
                )
    if resultado.aviso_api:
        blocos.append(resultado.aviso_api)
    if not blocos:
        tem_eta_gps = any(
            previsao.source
            == "live_gps_estimate"
            for sentido in resultado.sentidos
            for previsao
            in sentido.previsoes_ao_vivo
        )

        if tem_eta_gps:
            blocos.append(
                "Essa chegada é uma estimativa calculada a partir "
                "da posição GPS em tempo real fornecida pela API "
                "Olho Vivo e do percurso da linha no GTFS. "
                "Ela não é um ETA oficial publicado pela SPTrans."
            )
        else:
            blocos.append(
                "A previsão ao vivo vem da API Olho Vivo da SPTrans "
                "e pode mudar conforme o ônibus avança."
            )
    return " ".join(dict.fromkeys(blocos))


def renderizar_chegada(
    resultado: ResultadoChegada,
    *,
    detalhes: bool = False,
) -> str:
    """Fallback curto; a camada de linguagem deve consumir ``public_view``."""
    if resultado.horario_indisponivel:
        periodo = f" {resultado.periodo}" if resultado.periodo else " no período pedido"
        partes = [
            f"A linha **{resultado.linha}** opera na parada "
            f"**{resultado.parada}**{periodo}, mas a grade publicada pela "
            "SPTrans está incompleta; não é seguro informar a próxima chegada."
        ]
        if resultado.aviso:
            partes.append(resultado.aviso)
        return "\n\n".join(dict.fromkeys(partes))
    if resultado.sem_passagem:
        periodo = f" {resultado.periodo}" if resultado.periodo else " no período pedido"
        partes = [
            f"Não há outra passagem programada da linha **{resultado.linha}** "
            f"na parada **{resultado.parada}**{periodo}."
        ]
        if resultado.aviso:
            partes.append(resultado.aviso)
        return "\n\n".join(partes)
    if resultado.sem_servico:
        periodo = f" {resultado.periodo}" if resultado.periodo else " no período pedido"
        partes = [
            f"A linha **{resultado.linha}** não tem serviço programado na parada "
            f"**{resultado.parada}**{periodo}."
        ]
        if resultado.aviso:
            partes.append(resultado.aviso)
        return "\n\n".join(partes)

    sentidos_com_eta = [
        item for item in resultado.sentidos if item.previsoes_ao_vivo
    ]
    sentidos_sem_eta = [
        item for item in resultado.sentidos if not item.previsoes_ao_vivo
    ]
    partes: list[str] = []
    vistas_sentidos = resultado.public_view().get("sentidos", [])

    def complemento_programado(indice: int) -> str:
        if indice >= len(vistas_sentidos):
            return ""
        vista = vistas_sentidos[indice]
        if not isinstance(vista, dict):
            return ""
        chegadas = vista.get("chegadas", [])
        if not isinstance(chegadas, list):
            return ""
        programadas = [
            chegada for chegada in chegadas
            if isinstance(chegada, dict)
            and chegada.get("source") in {"scheduled", "scheduled_estimate"}
        ]
        if not programadas:
            return ""
        horarios = tuple(
            (
                "~" if chegada.get("source") == "scheduled_estimate" else ""
            ) + str(chegada.get("horario") or "")
            for chegada in programadas
            if chegada.get("horario")
        )
        if not horarios:
            return ""
        return (
            "Depois dela, a programação indica "
            f"**{_juntar_horarios(horarios)}**; "
            "esses horários não são previsões ao vivo."
        )

    # ETA real sempre vence a programação. Referências programadas só completam
    # passagens posteriores e aparecem explicitamente como não-live.
    if sentidos_com_eta:
        if len(sentidos_com_eta) == 1:
            sentido = sentidos_com_eta[0]
            partes.extend(_frases_chegada_ao_vivo(sentido))
            indice = resultado.sentidos.index(sentido)
            complemento = complemento_programado(indice)
            if complemento:
                partes.append(complemento)
        else:
            partes.append(
                f"A **{resultado.linha}** tem previsão ao vivo em mais de um "
                f"sentido na parada **{resultado.parada}**:"
            )
            for item in sentidos_com_eta:
                indice = resultado.sentidos.index(item)
                complemento = complemento_programado(indice)
                frase = _frases_chegada_ao_vivo(item)[0]
                partes.append(
                    "- " + " ".join(filter(None, (frase, complemento)))
                )
        if sentidos_sem_eta:
            partes.append(
                "Nos demais sentidos, não há ETA ao vivo:"
            )
            for item in sentidos_sem_eta:
                frases = _frases_referencia_programada(
                    item,
                    api_consultada=False,
                    prefixo_sentido=True,
                )
                partes.append("- " + " ".join(frases))
    elif len(resultado.sentidos) == 1:
        partes.extend(_frases_referencia_programada(
            resultado.sentidos[0],
            api_consultada=resultado.api_consultada,
            veiculos_ativos=resultado.veiculos_ativos,
            api_falhou=resultado.api_falhou,
        ))
    else:
        if resultado.api_falhou:
            estado_api = (
                "A consulta em tempo real à SPTrans não respondeu agora; "
            )
        elif resultado.api_consultada and resultado.veiculos_ativos:
            estado_api = (
                f"A SPTrans reportou posições de {resultado.veiculos_ativos} "
                "ônibus nesse sentido, mas nenhuma produziu uma previsão "
                "segura agora; "
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

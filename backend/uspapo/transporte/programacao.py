"""Programação, horários e atendimento das linhas e paradas."""

from datetime import date, datetime, time, timedelta, timezone
import math
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from uspapo import gtfs_sptrans
from uspapo.ferramentas import normalizar
from uspapo.intencao_transporte import RestricaoTemporal
from uspapo.locais_usp import CATALOGO_LOCAIS, coordenada_local, resolver_local
from uspapo.operacao_sptrans import (
    aviso_programacao_incompleta,
    fontes_operacionais,
    horario_gtfs_confiavel,
    parada_atendida_na_data,
)
from uspapo.transporte import planoper as _planoper

try:
    FUSO_SP = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:  # pragma: no cover - imagens Windows sem tzdata
    FUSO_SP = timezone(timedelta(hours=-3))

# Uma correspondência por coordenada só é válida quando há de fato uma parada
# caminhável perto do local pedido. Antes, o ponto globalmente mais próximo era
# aceito sem teto: uma linha que não atende o Metrô Butantã podia ser anunciada
# usando uma parada a mais de meio quilômetro dali.
RAIO_ACESSO_M = 450
# O pipeline atualiza o recorte diariamente. Depois de uma semana sem uma
# geração bem-sucedida, a resposta continua útil, mas passa a avisar claramente
# que o dado está vencido em vez de aparentar atualidade.
MAX_IDADE_GTFS_DIAS = 7

_catalogo_gtfs = gtfs_sptrans.catalogo
_mesmo_nome = gtfs_sptrans.mesmo_nome
_servico_ativo = gtfs_sptrans.servico_ativo
_distancia_parada_gtfs = gtfs_sptrans.distancia_m


def _normalizar_sentido_operacional(valor: object) -> str:
    """Normaliza apenas variações seguras de grafia entre os dois feeds."""
    palavras = [
        {"cid": "cidade", "univ": "universitaria"}.get(palavra, palavra)
        for palavra in normalizar(valor).replace(".", " ").split()
    ]
    return " ".join(palavras)


def _sentido_explicito_da_pergunta(
    numero: str,
    pergunta: str | None,
) -> str | None:
    """Resolve um headsign GTFS somente quando o usuário o informou.

    O trecho após ``sentido`` não vira um fato por si só: ele precisa casar de
    maneira inequívoca com um destino já existente para a linha no GTFS.
    """
    achado = re.search(r"\bsentido\s+(.+?)(?:[?!.,;]|$)", normalizar(pergunta or ""))
    if not achado:
        return None
    pedido = _normalizar_sentido_operacional(achado.group(1))
    if not pedido:
        return None
    rotas = _catalogo_gtfs().get("linhas", {}).get(normalizar(numero).upper(), [])
    destinos = sorted({
        str(viagem.get("destino") or "").strip()
        for rota in rotas
        for viagem in rota.get("viagens", [])
        if str(viagem.get("destino") or "").strip()
    }, key=normalizar)
    compativeis = [
        destino for destino in destinos
        if (
            _normalizar_sentido_operacional(destino) == pedido
            or _normalizar_sentido_operacional(destino) in pedido
            or pedido in _normalizar_sentido_operacional(destino)
        )
    ]
    return compativeis[0] if len(compativeis) == 1 else pedido


def _coordenada_ponto(ponto: str) -> tuple[float, float] | None:
    coordenada = coordenada_local(ponto)
    if coordenada:
        return coordenada
    # Nomes de parada que não estão no catálogo manual continuam roteáveis. A
    # média entre plataformas/lados da via representa o local, não o embarque;
    # o planejador escolhe depois o lado e o sentido corretos.
    paradas: dict[str, dict[str, Any]] = {}
    for rotas in _catalogo_gtfs().get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                for parada in viagem.get("paradas", []):
                    if _mesmo_nome(ponto, parada.get("nome", "")):
                        paradas[str(parada.get("id"))] = parada
    if paradas:
        return (
            sum(float(p["latitude"]) for p in paradas.values()) / len(paradas),
            sum(float(p["longitude"]) for p in paradas.values()) / len(paradas),
        )
    return None


def _nota_atualizacao_gtfs(agora: datetime | None = None) -> str:
    """Expõe a idade do snapshot; dado estático nunca deve parecer "ao vivo"."""
    texto_gerado = str(_catalogo_gtfs().get("gerado_em") or "").strip()
    if not texto_gerado:
        return "A data de atualização do recorte GTFS não está disponível."
    try:
        gerado = datetime.fromisoformat(texto_gerado.replace("Z", "+00:00"))
        if gerado.tzinfo is None:
            gerado = gerado.replace(tzinfo=timezone.utc)
        referencia = agora or datetime.now(timezone.utc)
        if referencia.tzinfo is None:
            referencia = referencia.replace(tzinfo=timezone.utc)
        idade_dias = max(0, (referencia - gerado).days)
        local = gerado.astimezone(FUSO_SP)
    except (TypeError, ValueError, OverflowError):
        return "A data de atualização do recorte GTFS é inválida."

    nota = (
        "Recorte GTFS oficial gerado em "
        f"{local.strftime('%d/%m/%Y às %H:%M')} (horário de São Paulo)."
    )
    if idade_dias > MAX_IDADE_GTFS_DIAS:
        nota += (
            f" **Atenção:** ele está há {idade_dias} dias sem atualização; "
            "confirme o itinerário na SPTrans."
        )
    return nota


def _aviso_gtfs_se_necessario(agora: datetime | None = None) -> str:
    """Só leva a idade do feed à UX quando ela realmente exige atenção."""
    nota = _nota_atualizacao_gtfs(agora)
    problemas = (
        "**Atenção:**",
        "não está disponível",
        "é inválida",
    )
    return nota if any(problema in nota for problema in problemas) else ""


def _slots_estimados_frequencia(
    inicio: datetime,
    fim: datetime,
    intervalo_s: int,
    depois_de: datetime,
    *,
    limite: int = 3,
) -> list[datetime]:
    """Próximos slots estimados de uma faixa GTFS ``exact_times=0``.

    A âncora é o início publicado da faixa; os slots são aproximações
    reproduzíveis, não partidas confirmadas. ``datetime`` preserva naturalmente
    serviços 24:xx, que já carregam o dia de serviço correto.
    """
    if intervalo_s <= 0 or fim <= inicio or limite <= 0 or depois_de >= fim:
        return []
    if depois_de < inicio:
        proximo = inicio
    else:
        decorrido_s = (depois_de - inicio).total_seconds()
        passos = math.floor(decorrido_s / intervalo_s) + 1
        proximo = inicio + timedelta(seconds=passos * intervalo_s)
    slots: list[datetime] = []
    while proximo < fim and len(slots) < limite:
        slots.append(proximo)
        proximo += timedelta(seconds=intervalo_s)
    return slots


def _partidas_planoper_da_viagem(
    rota: dict[str, Any],
    viagem: dict[str, Any],
    dia_servico: date,
) -> list[tuple[int, bool | None]]:
    """Partidas PlanOper em segundos desde o início do dia de serviço.

    Horários após a meia-noite continuam pertencendo ao mesmo dia de serviço:
    23:55, 00:11 vira 23:55, 24:11.
    """
    return _planoper.partidas_da_viagem(
        rota, viagem, dia_servico, _normalizar_sentido_operacional,
    )


def _programacao_gtfs(
    numero: str,
    ponto: str,
    agora: datetime | None = None,
    sentido_esperado: str | None = None,
    datas_permitidas: tuple[date, ...] = (),
    restricao_temporal: RestricaoTemporal | None = None,
) -> dict[str, Any]:
    """Calcula as proximas passagens programadas no GTFS, sem chama de LLM."""
    catalogo = _catalogo_gtfs()
    rotas = catalogo.get("linhas", {}).get(normalizar(numero).upper(), [])
    if not rotas:
        return {"erro": f"O GTFS atual da SPTrans nao contem a linha {numero}."}

    candidatos: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    todas: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for rota in rotas:
        for viagem in rota.get("viagens", []):
            for parada in viagem.get("paradas", []):
                item = (rota, viagem, parada)
                todas.append(item)
                if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                    candidatos.append(item)

    if sentido_esperado:
        def atende_sentido(
            item: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
        ) -> bool:
            destino_viagem = str(item[1].get("destino", ""))
            return (
                _normalizar_sentido_operacional(destino_viagem)
                == _normalizar_sentido_operacional(sentido_esperado)
            )

        todas_no_sentido = [item for item in todas if atende_sentido(item)]
        havia_candidato_na_parada = bool(candidatos)
        candidatos_no_sentido = [
            item for item in candidatos if atende_sentido(item)
        ]
        # Depois de reconhecer um sentido explícito, nunca voltamos ao conjunto
        # completo por proximidade. Isso impediria uma resposta no sentido
        # oposto quando a parada não pertence ao headsign solicitado.
        if not todas_no_sentido or (
            havia_candidato_na_parada and not candidatos_no_sentido
        ):
            return {
                "tipo": "sentido_incompativel",
                "linha": str(rotas[0].get("linha") or numero),
                "parada": ponto,
                "sentido_solicitado": sentido_esperado,
                "sentidos_disponiveis": sorted({
                    str(item[1].get("destino") or "")
                    for item in candidatos
                    if str(item[1].get("destino") or "")
                }, key=normalizar),
            }
        todas = todas_no_sentido
        candidatos = candidatos_no_sentido

    coordenada = _coordenada_ponto(ponto)
    if not candidatos:
        if coordenada and todas:
            # Inclui a mesma parada em diferentes viagens/sentidos, mas nao uma
            # parada distante apenas porque é a mais próxima que a linha tem.
            # O teto é o que impede, por exemplo, anunciar a 7725 no Metrô
            # Butantã usando uma parada da Av. Afrânio Peixoto.
            menor = min(
                _distancia_parada_gtfs(item[2], coordenada) for item in todas
            )
            if menor <= RAIO_ACESSO_M:
                candidatos = sorted(
                    (
                        item for item in todas
                        if _distancia_parada_gtfs(item[2], coordenada)
                        <= min(menor + 40, RAIO_ACESSO_M)
                    ),
                    key=lambda item: _distancia_parada_gtfs(item[2], coordenada),
                )
    elif coordenada:
        candidatos.sort(
            key=lambda item: _distancia_parada_gtfs(item[2], coordenada)
        )
    if not candidatos:
        return {
            "erro": (
                f"Nao localizei no GTFS uma parada da linha {numero} "
                f"correspondente a '{ponto}'."
            )
        }

    # Sem sentido explícito, preserve todos os headsigns plausíveis antes de
    # escolher um stop_id. Plataformas opostas costumam ter IDs diferentes;
    # selecionar primeiro a mais próxima publicava silenciosamente a grade de
    # apenas um lado da via. Cada recursão abaixo fixa o sentido e, só então,
    # escolhe sua plataforma canônica.
    destinos = sorted({
        str(item[1].get("destino", "")).strip()
        for item in candidatos
        if str(item[1].get("destino", "")).strip()
    }, key=normalizar)
    if not sentido_esperado and len(destinos) > 1:
        programacoes: list[dict[str, Any]] = []
        for destino in destinos:
            programacao = _programacao_gtfs(
                numero,
                ponto,
                agora,
                sentido_esperado=destino,
                datas_permitidas=datas_permitidas,
                restricao_temporal=restricao_temporal,
            )
            if not programacao.get("erro"):
                programacoes.append(programacao)
        if programacoes:
            tipos = {str(item.get("tipo")) for item in programacoes}
            if "programacao" in tipos:
                tipo_agregado = "programacao"
            elif "sem_passagem" in tipos:
                tipo_agregado = "sem_passagem"
            else:
                tipo_agregado = "sem_servico"
            avisos = list(dict.fromkeys(
                str(item.get("aviso") or "")
                for item in programacoes
                if item.get("aviso")
            ))
            return {
                "tipo": tipo_agregado,
                "linha": programacoes[0].get("linha", numero),
                "parada": programacoes[0].get("parada", ponto),
                "horarios": [],
                "instantes": [],
                "sentidos": programacoes,
                "programacao_incompleta": any(
                    bool(item.get("programacao_incompleta"))
                    for item in programacoes
                ),
                "servico_cadastrado": any(
                    bool(item.get("servico_cadastrado"))
                    for item in programacoes
                ),
                "aviso": " ".join(avisos),
            }

    # A busca geográfica pode encontrar vários pontos próximos. Misturar as
    # faixas de todos eles e rotular o resultado com apenas o primeiro nome
    # produzia uma tabela impossível de auditar. A programação abaixo pertence
    # sempre a um único stop_id (a plataforma mais próxima); repetições desse
    # mesmo ID em viagens/serviços continuam sendo combinadas.
    if coordenada:
        candidatos.sort(
            key=lambda item: (
                _distancia_parada_gtfs(item[2], coordenada),
                str(item[2].get("id", "")),
            )
        )
    else:
        candidatos.sort(
            key=lambda item: (
                normalizar(str(item[2].get("nome", ""))),
                str(item[2].get("id", "")),
            )
        )
    parada_escolhida_id = str(candidatos[0][2].get("id", ""))
    candidatos = [
        item
        for item in candidatos
        if str(item[2].get("id", "")) == parada_escolhida_id
    ]

    instante = agora or datetime.now(FUSO_SP)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=FUSO_SP)
    datas_ordenadas = tuple(sorted(set(datas_permitidas)))
    limite_inicio = (
        datetime.combine(datas_ordenadas[0], time.min, tzinfo=FUSO_SP)
        if datas_ordenadas
        else None
    )
    limite_fim = (
        datetime.combine(
            datas_ordenadas[-1] + timedelta(days=1), time.min, tzinfo=FUSO_SP
        )
        if datas_ordenadas
        else None
    )
    # Uma consulta de próxima chegada feita no fim do dia não termina
    # artificialmente à meia-noite civil. Mantemos um horizonte curto de três
    # horas (o mesmo máximo aceito para ETA Olho Vivo), sem abrir datas futuras
    # em consultas explícitas para outro dia.
    estendeu_horizonte_atual = False
    if (
        datas_ordenadas
        and restricao_temporal is None
        and datas_ordenadas[-1] == instante.date()
        and limite_fim is not None
        and instante + timedelta(hours=3) > limite_fim
    ):
        limite_fim = instante + timedelta(hours=3)
        estendeu_horizonte_atual = True
    if restricao_temporal is not None:
        # A consulta e calculada a partir do limite pedido, mesmo quando a
        # janela esta no passado/futuro em relacao ao relogio da requisicao.
        # ``datas_permitidas`` continua definindo os dias de servico a testar.
        instante = restricao_temporal.inicio
        limite_inicio = restricao_temporal.inicio
        limite_fim = restricao_temporal.fim
    dias_servico = (
        sorted({
            *(dia - timedelta(days=1) for dia in datas_ordenadas),
            *datas_ordenadas,
            *(
                (datas_ordenadas[-1] + timedelta(days=1),)
                if estendeu_horizonte_atual
                else ()
            ),
        })
        if datas_ordenadas
        else [instante.date() + timedelta(days=dias) for dias in range(-1, 8)]
    )
    chegadas: set[datetime] = set()
    estimativas_frequencia: set[tuple[datetime, int]] = set()
    faixas_frequencia: set[tuple[datetime, datetime, int]] = set()
    estimativas_planoper: dict[
        datetime,
        bool | None,
    ] = {}

    programacao_incompleta = False
    houve_servico_no_ponto = False
    dias_gtfs_incompletos: set[date] = set()
    dias_cobertos_planoper: set[date] = set()
    for rota, viagem, parada in candidatos:
        deslocamento = int(parada.get("deslocamento", 0))
        # Horários GTFS podem ultrapassar 24:00 e pertencem ao dia de serviço
        # anterior. À 00:30, por exemplo, uma viagem 24:45 de sexta ainda é uma
        # chegada futura válida no sábado civil.
        for dia_servico in dias_servico:
            if not _servico_ativo(catalogo, str(viagem.get("servico", "")), dia_servico):
                continue
            if not parada_atendida_na_data(
                str(rota.get("linha", numero)), parada, dia_servico
            ):
                continue
            dia_civil_pedido = (
                not datas_ordenadas or dia_servico in datas_ordenadas
            )
            if dia_civil_pedido:
                houve_servico_no_ponto = True
            linha_atual = str(
                rota.get("linha", numero)
            )

            gtfs_confiavel = horario_gtfs_confiavel(
                linha_atual,
                dia_servico,
            )

            if not gtfs_confiavel:
                if dia_civil_pedido:
                    dias_gtfs_incompletos.add(
                        dia_servico
                    )

            meia_noite = datetime.combine(
                dia_servico,
                time.min,
                tzinfo=FUSO_SP,
            )

            # Quando a grade GTFS não é confiável, usamos as partidas oficiais
            # da PlanOper como âncora e o deslocamento relativo GTFS para
            # estimar a passagem nesta parada.
            partidas_planoper: list[
                tuple[int, bool | None]
            ] = []

            if not gtfs_confiavel:
                partidas_planoper = (
                    _partidas_planoper_da_viagem(
                        rota,
                        viagem,
                        dia_servico,
                    )
                )

                if (
                    partidas_planoper
                    and dia_civil_pedido
                ):
                    dias_cobertos_planoper.add(
                        dia_servico
                    )

                for (
                    partida_planoper_s,
                    acessivel,
                ) in partidas_planoper:
                    chegada_planoper = (
                        meia_noite
                        + timedelta(
                            seconds=(
                                partida_planoper_s
                                + deslocamento
                            )
                        )
                    )

                    if (
                        chegada_planoper
                        >= instante - timedelta(seconds=30)
                        and (
                            limite_inicio is None
                            or chegada_planoper >= limite_inicio
                        )
                        and (
                            limite_fim is None
                            or chegada_planoper < limite_fim
                        )
                    ):
                        estimativas_planoper.setdefault(
                            chegada_planoper,
                            acessivel,
                        )

                # A PlanOper preencheu a grade que o GTFS marcou como
                # não confiável. Não misture as duas programações.
                if partidas_planoper:
                    continue

            frequencias = viagem.get("frequencias", [])
            if frequencias:
                for frequencia in frequencias:
                    inicio = int(frequencia["inicio"])
                    fim = int(frequencia["fim"])
                    intervalo = int(frequencia["intervalo"])
                    if int(frequencia.get("exact_times", 0)) == 1:
                        for partida in range(inicio, fim, intervalo):
                            chegada = meia_noite + timedelta(
                                seconds=partida + deslocamento
                            )
                            if (
                                chegada >= instante - timedelta(seconds=30)
                                and (limite_inicio is None or chegada >= limite_inicio)
                                and (limite_fim is None or chegada < limite_fim)
                            ):
                                chegadas.add(chegada)
                    else:
                        inicio_ponto = meia_noite + timedelta(
                            seconds=inicio + deslocamento
                        )
                        fim_ponto = meia_noite + timedelta(
                            seconds=fim + deslocamento
                        )
                        inicio_util = max(
                            inicio_ponto,
                            instante,
                            limite_inicio or inicio_ponto,
                        )
                        fim_util = min(fim_ponto, limite_fim or fim_ponto)
                        if fim_util > inicio_util:
                            faixas_frequencia.add(
                                (inicio_util, fim_util, intervalo)
                            )
                            # Uma faixa/janela ainda futura deve incluir seu
                            # primeiro slot. Já em uma faixa ativa, a consulta
                            # continua pedindo o slot estritamente posterior ao
                            # instante atual. Aproximar o corte futuro em um
                            # microssegundo também evita que o limite de três do
                            # helper seja consumido por slots anteriores à
                            # janela civil solicitada.
                            corte_slots = (
                                inicio_util - timedelta(microseconds=1)
                                if inicio_util > instante
                                else instante
                            )
                            slots_validos = [
                                slot
                                for slot in _slots_estimados_frequencia(
                                    inicio_ponto,
                                    fim_ponto,
                                    intervalo,
                                    corte_slots,
                                )
                                if inicio_util <= slot < fim_util
                            ]
                            for slot in slots_validos:
                                estimativas_frequencia.add((slot, intervalo))

                            # No fim de uma faixa ativa pode já não restar um
                            # múltiplo ancorado, embora a própria faixa ainda
                            # indique serviço esperado. Preserve a referência
                            # central da janela restante como estimativa, em
                            # vez de escondê-la atrás da faixa seguinte.
                            if (
                                not slots_validos
                                and inicio_ponto <= instante < fim_util
                            ):
                                janela_fim = min(
                                    instante + timedelta(seconds=intervalo),
                                    fim_util,
                                )
                                referencia = instante + (
                                    janela_fim - instante
                                ) / 2
                                estimativas_frequencia.add(
                                    (referencia, intervalo)
                                )
            else:
                chegada = meia_noite + timedelta(seconds=int(parada["horario"]))
                if (
                    chegada >= instante - timedelta(seconds=30)
                    and (limite_inicio is None or chegada >= limite_inicio)
                    and (limite_fim is None or chegada < limite_fim)
                ):
                    chegadas.add(chegada)

    programacao_incompleta = bool(
        dias_gtfs_incompletos
        - dias_cobertos_planoper
    )

    proximas = sorted(chegadas)[:3]
    faixas = sorted(faixas_frequencia)[:3]
    estimativas = sorted(estimativas_frequencia)[:3]

    estimativas_planoper_ordenadas = sorted(
        estimativas_planoper.items(),
        key=lambda item: item[0],
    )[:3]

    rota, viagem_escolhida, parada = candidatos[0]
    if not proximas and not faixas and not estimativas and not estimativas_planoper_ordenadas and datas_ordenadas:
        aviso = ""
        if programacao_incompleta:
            aviso = aviso_programacao_incompleta(
                str(rota.get("linha", numero)), datas_ordenadas[0]
            )
        return {
            "tipo": (
                "programacao"
                if programacao_incompleta
                else "sem_passagem"
                if houve_servico_no_ponto
                else "sem_servico"
            ),
            "linha": rota.get("linha", numero),
            "parada": parada.get("nome", ponto),
            "parada_id": parada_escolhida_id,
            "destino": viagem_escolhida.get("destino", ""),
            "sentido_gtfs": viagem_escolhida.get("sentido"),
            "horarios": [],
            "instantes": [],
            "faixas": [],
            "programacao_incompleta": programacao_incompleta,
            "servico_cadastrado": houve_servico_no_ponto,
            "aviso": aviso,
        }
    if not proximas and not faixas and not estimativas and not estimativas_planoper_ordenadas:
        return {"erro": "Nao ha horario programado no periodo coberto pelo GTFS."}

    horarios = [
        chegada.strftime("%H:%M")
        if chegada.date() == instante.date()
        else chegada.strftime("%d/%m as %H:%M")
        for chegada in proximas
    ]

    estimativas_formatadas = [
        {
            "horario": (
                chegada.strftime("%H:%M")
                if chegada.date() == instante.date()
                else chegada.strftime("%d/%m as %H:%M")
            ),
            "instante": chegada.isoformat(),
            "intervalo_min": round(intervalo / 60),
            "source": "scheduled_estimate",
            "confidence": (
                "scheduled_uncertain"
                if programacao_incompleta
                else "scheduled"
            ),
            "origem_programacao": "gtfs_frequencia",
        }
        for chegada, intervalo in estimativas
    ]

    estimativas_formatadas.extend(
        {
            "horario": (
                chegada.strftime("%H:%M")
                if chegada.date() == instante.date()
                else chegada.strftime("%d/%m as %H:%M")
            ),
            "instante": chegada.isoformat(),
            "source": "scheduled_estimate",
            "confidence": "scheduled",
            "origem_programacao": "planoper",
            "acessivel": acessivel,
        }
        for chegada, acessivel
        in estimativas_planoper_ordenadas
    )

    # Ordem cronológica e deduplicação.
    estimativas_por_instante: dict[
        str,
        dict[str, Any],
    ] = {}

    for item in estimativas_formatadas:
        chave = str(item["instante"])

        # Em colisão, PlanOper é preferido à extrapolação de frequência GTFS.
        if (
            chave not in estimativas_por_instante
            or item.get("origem_programacao") == "planoper"
        ):
            estimativas_por_instante[chave] = item

    estimativas_formatadas = sorted(
        estimativas_por_instante.values(),
        key=lambda item: str(item["instante"]),
    )[:3]

    resultado = {
        "tipo": "programacao",
        "linha": rota.get("linha", numero),
        "parada": parada.get("nome", ponto),
        "parada_id": parada_escolhida_id,
        "destino": viagem_escolhida.get("destino", ""),
        "sentido_gtfs": viagem_escolhida.get("sentido"),
        "horarios": horarios,
        "instantes": [chegada.isoformat() for chegada in proximas],
        "estimativas": estimativas_formatadas,
        "programacao_incompleta": programacao_incompleta,
        "servico_cadastrado": houve_servico_no_ponto,
        "programacao_planoper": bool(
            estimativas_planoper_ordenadas
        ),
    }
    if faixas:
        faixas_formatadas = []
        for inicio, fim, intervalo in faixas:
            # exact_times=0 não autoriza cravar os múltiplos do headway como
            # partidas. Ainda assim, o headway permite responder de maneira
            # útil: se a faixa está ativa, a próxima passagem é esperada em
            # até um intervalo; se ela ainda vai começar, a janela parte do
            # início publicado. A referência central é uma estimativa, nunca
            # um horário garantido.
            janela_inicio = max(instante, inicio)
            janela_fim = min(
                janela_inicio + timedelta(seconds=intervalo),
                fim,
            )
            referencia = janela_inicio + (janela_fim - janela_inicio) / 2

            def texto_horario(valor: datetime) -> str:
                if valor.date() == instante.date():
                    return valor.strftime("%H:%M")
                return valor.strftime("%d/%m às %H:%M")

            faixas_formatadas.append({
                "inicio": inicio.isoformat(),
                "fim": fim.isoformat(),
                "inicio_texto": texto_horario(inicio),
                "fim_texto": texto_horario(fim),
                "intervalo_min": round(intervalo / 60),
                "ativa_agora": inicio <= instante < fim,
                "proxima_janela_inicio": janela_inicio.isoformat(),
                "proxima_janela_fim": janela_fim.isoformat(),
                "proxima_janela_inicio_texto": texto_horario(janela_inicio),
                "proxima_janela_fim_texto": texto_horario(janela_fim),
                "proxima_referencia": referencia.isoformat(),
                "proxima_referencia_texto": texto_horario(referencia),
                # Metade do headway é a espera típica dentro de uma faixa. O
                # tempo desde agora até a referência é outro fato, sobretudo
                # quando a próxima faixa ainda não começou.
                "espera_tipica_min": max(1, round(intervalo / 120)),
                "espera_ate_referencia_min": max(
                    0,
                    round((referencia - instante).total_seconds() / 60),
                ),
                "espera_maxima_min": max(
                    0,
                    math.ceil((janela_fim - instante).total_seconds() / 60),
                ),
            })
        resultado["faixas"] = faixas_formatadas
    return resultado


def _resumo_gtfs(numero: str) -> list[dict[str, Any]]:
    catalogo = _catalogo_gtfs()
    rotas = catalogo.get("linhas", {}).get(normalizar(numero).upper(), [])
    resumos = []
    for rota in rotas:
        nomes_paradas: list[str] = []
        vistas: set[str] = set()
        for viagem in rota.get("viagens", []):
            for parada in viagem.get("paradas", []):
                nome = str(parada.get("nome", "")).strip()
                chave = normalizar(nome)
                if nome and chave not in vistas:
                    vistas.add(chave)
                    nomes_paradas.append(nome)
        resumos.append({
            "linha": rota.get("linha", numero),
            "nome": rota.get("nome", ""),
            "paradas": nomes_paradas,
        })
    return resumos


def _atendimento_linha_na_parada_gtfs(
    numero: str,
    ponto: str,
    datas: tuple[date, ...],
) -> dict[str, Any]:
    """Verifica atendimento por stop+viagem na data, sem inferir por resumo.

    A presença da parada em uma viagem prova apenas itinerário. A resposta
    positiva exige também serviço ativo (calendário/calendar_dates) e a
    regra operacional da parada para a data consultada.
    """
    catalogo = _catalogo_gtfs()
    rotas = catalogo.get("linhas", {}).get(normalizar(numero).upper(), [])
    if not rotas:
        return {"estado": "dados_insuficientes", "linhas": []}

    ocorrencias: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for rota in rotas:
        for viagem in rota.get("viagens", []):
            for parada in viagem.get("paradas", []):
                if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                    ocorrencias.append((rota, viagem, parada))
    if not ocorrencias:
        return {"estado": "nao_atende", "linhas": []}
    if not datas:
        return {
            "estado": "dados_insuficientes",
            "linhas": sorted({str(rota.get("linha", numero)) for rota, _, _ in ocorrencias}),
            "paradas": sorted({str(parada.get("nome", ponto)) for _, _, parada in ocorrencias}),
        }

    ativos: list[dict[str, Any]] = []
    for rota, viagem, parada in ocorrencias:
        linha = str(rota.get("linha", numero))
        dias = [
            dia for dia in datas
            if (
                _servico_ativo(catalogo, str(viagem.get("servico", "")), dia)
                and parada_atendida_na_data(linha, parada, dia)
            )
        ]
        if dias:
            ativos.append({
                "linha": linha,
                "parada": str(parada.get("nome", ponto)),
                "stop_id": str(parada.get("id", "")),
                "sentido": str(viagem.get("destino", "")),
                "viagem_id": str(viagem.get("id", "")),
                "datas": [dia.isoformat() for dia in dias],
            })
    paradas = sorted({str(parada.get("nome", ponto)) for _, _, parada in ocorrencias})
    linhas = sorted({str(rota.get("linha", numero)) for rota, _, _ in ocorrencias})
    return {
        "estado": "atende" if ativos else "sem_servico",
        "linhas": linhas,
        "paradas": paradas,
        "ocorrencias_ativas": ativos,
    }


def _linhas_por_ponto_gtfs(
    ponto: str,
    datas: tuple[date, ...] = (),
) -> dict[str, Any]:
    """Inverte o GTFS e, quando pedido, filtra serviço e itinerário por data."""
    catalogo = _catalogo_gtfs()
    ocorrencias: list[
        tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    ] = []
    textuais: list[
        tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    ] = []
    for rotas in catalogo.get("linhas", {}).values():
        for rota in rotas:
            for viagem in rota.get("viagens", []):
                for parada in viagem.get("paradas", []):
                    item = (rota, viagem, parada)
                    ocorrencias.append(item)
                    if _mesmo_nome(ponto, str(parada.get("nome", ""))):
                        textuais.append(item)

    candidatas = textuais
    coordenada = _coordenada_ponto(ponto)
    if not candidatas:
        if coordenada and ocorrencias:
            menor = min(
                _distancia_parada_gtfs(parada, coordenada)
                for _rota, _viagem, parada in ocorrencias
            )
            if menor <= RAIO_ACESSO_M:
                candidatas = sorted(
                    (
                        item for item in ocorrencias
                        if _distancia_parada_gtfs(item[2], coordenada)
                        <= min(menor + 40, RAIO_ACESSO_M)
                    ),
                    key=lambda item: _distancia_parada_gtfs(item[2], coordenada),
                )
    elif coordenada:
        candidatas.sort(
            key=lambda item: _distancia_parada_gtfs(item[2], coordenada)
        )
    if not candidatas:
        return {"erro": f"Não localizei a parada '{ponto}' no GTFS da SPTrans."}

    linhas_candidatas = [str(rota.get("linha", "")) for rota, _, _ in candidatas]
    linhas: dict[str, dict[str, Any]] = {}
    paradas: dict[str, str] = {}
    for rota, viagem, parada in candidatas:
        dias_ativos = [
            dia
            for dia in datas
            if (
                _servico_ativo(catalogo, str(viagem.get("servico", "")), dia)
                and parada_atendida_na_data(str(rota.get("linha", "")), parada, dia)
            )
        ]
        if datas and not dias_ativos:
            continue
        id_rota = str(rota.get("id") or rota.get("linha"))
        item_linha = linhas.setdefault(id_rota, {
            "linha": str(rota.get("linha", "")),
            "nome": str(rota.get("nome", "")),
            "datas": [],
        })
        item_linha["datas"] = sorted({
            *item_linha.get("datas", []),
            *(dia.isoformat() for dia in dias_ativos),
        })
        paradas[str(parada.get("id"))] = str(parada.get("nome", ponto))

    # Mesmo quando nenhuma linha opera no período, a parada foi localizada e a
    # resposta deve dizer "nenhuma", não fingir que ela inexiste no catálogo.
    if not paradas:
        for _rota, _viagem, parada in candidatas:
            paradas[str(parada.get("id"))] = str(parada.get("nome", ponto))
    return {
        "parada": sorted(paradas.values(), key=normalizar)[0],
        "linhas": sorted(linhas.values(), key=lambda item: normalizar(item["linha"])),
        "fontes_operacionais": fontes_operacionais(linhas_candidatas, datas),
    }


def _chave_local(ponto: str) -> str | None:
    return ponto if ponto in CATALOGO_LOCAIS else resolver_local(ponto)


def _proxima_passagem_gtfs(
    catalogo: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    depois_de: datetime,
    ate: datetime | None = None,
) -> datetime | None:
    deslocamento = int(parada.get("deslocamento", 0))
    melhor: datetime | None = None
    for dias_a_frente in range(-1, 8):
        dia_servico = depois_de.date() + timedelta(days=dias_a_frente)
        if not _servico_ativo(catalogo, str(viagem.get("servico", "")), dia_servico):
            continue
        meia_noite = datetime.combine(dia_servico, time.min, tzinfo=FUSO_SP)
        frequencias = viagem.get("frequencias", [])
        if frequencias:
            for frequencia in frequencias:
                inicio = int(frequencia["inicio"])
                fim = int(frequencia["fim"])
                if int(frequencia.get("exact_times", 0)) == 1:
                    partidas = range(
                        inicio,
                        fim,
                        int(frequencia["intervalo"]),
                    )
                    for partida in partidas:
                        passagem = meia_noite + timedelta(
                            seconds=partida + deslocamento
                        )
                        if passagem >= depois_de and (
                            (ate is None or passagem < ate)
                            and (melhor is None or passagem < melhor)
                        ):
                            melhor = passagem
                else:
                    # exact_times=0 não confirma partidas, mas a ancoragem da
                    # faixa permite calcular slots programados estimados.
                    inicio_ponto = meia_noite + timedelta(
                        seconds=inicio + deslocamento
                    )
                    fim_ponto = meia_noite + timedelta(
                        seconds=fim + deslocamento
                    )
                    for passagem in _slots_estimados_frequencia(
                        inicio_ponto,
                        fim_ponto,
                        int(frequencia["intervalo"]),
                        depois_de,
                        limite=1,
                    ):
                        if (ate is None or passagem < ate) and (
                            melhor is None or passagem < melhor
                        ):
                            melhor = passagem
        else:
            passagem = meia_noite + timedelta(seconds=int(parada["horario"]))
            if (
                passagem >= depois_de
                and (ate is None or passagem < ate)
                and (melhor is None or passagem < melhor)
            ):
                melhor = passagem
    return melhor


def _espera_media_gtfs(
    catalogo: dict[str, Any],
    viagem: dict[str, Any],
    parada: dict[str, Any],
    pronto_para_embarcar: datetime,
    ate: datetime | None = None,
) -> tuple[float, float | None]:
    """Espera GTFS; frequências produzem slots explicitamente estimados."""
    servico = str(viagem.get("servico", ""))
    deslocamento = int(parada.get("deslocamento", 0))
    estimativas: list[tuple[datetime, int]] = []
    for dias_a_frente in range(-1, 8):
        dia_servico = pronto_para_embarcar.date() + timedelta(days=dias_a_frente)
        if not _servico_ativo(catalogo, servico, dia_servico):
            continue
        meia_noite_servico = datetime.combine(
            dia_servico, time.min, tzinfo=FUSO_SP
        )
        for frequencia in viagem.get("frequencias", []):
            if int(frequencia.get("exact_times", 0)) == 1:
                continue
            inicio_no_ponto = meia_noite_servico + timedelta(
                seconds=int(frequencia["inicio"]) + deslocamento
            )
            fim_no_ponto = meia_noite_servico + timedelta(
                seconds=int(frequencia["fim"]) + deslocamento
            )
            for slot in _slots_estimados_frequencia(
                inicio_no_ponto,
                fim_no_ponto,
                int(frequencia["intervalo"]),
                pronto_para_embarcar,
                limite=1,
            ):
                if ate is None or slot < ate:
                    estimativas.append((slot, int(frequencia["intervalo"])))
    if estimativas:
        proxima, intervalo_s = min(estimativas, key=lambda item: item[0])
        return (
            max(0, (proxima - pronto_para_embarcar).total_seconds() / 60),
            intervalo_s / 60,
        )

    proxima = _proxima_passagem_gtfs(
        catalogo, viagem, parada, pronto_para_embarcar, ate=ate
    )
    if proxima is None:
        return float("inf"), None
    return (
        (proxima - pronto_para_embarcar).total_seconds() / 60,
        None,
    )

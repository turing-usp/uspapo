# Transporte no USPapo

## De onde vêm os nomes

Há duas camadas separadas, para que o modelo não invente pontos:

1. **Paradas e linhas:** `stop_id`, `stop_name`, `route_short_name`,
   `route_long_name` e `trip_headsign` vêm do GTFS oficial da SPTrans. Quando a
   API Olho Vivo responde, `np` (nome da parada) e `ed` (endereço) são mantidos
   como publicados pela SPTrans.
2. **Prédios e apelidos da comunidade:** ficam no catálogo explícito
   `backend/uspapo/locais_usp.py`. Ele liga aliases como `Poli`, `FEA` e `HU` a
   uma coordenada auditada. O casamento usa palavras inteiras; `Poli` não pode
   casar com `Academia de Polícia`, por exemplo.

`Central` significa **Restaurante Universitário Central**. `Administração
Central` e `Reitoria` são locais distintos e precisam ser escritos com esses
nomes. Toda resposta de trajeto mostra a interpretação feita antes das
instruções.

## Horário programado não é previsão

- Uma chegada só recebe o rótulo **previsão ao vivo** se vier da API Olho Vivo.
- No GTFS, `exact_times=0` representa uma faixa de operação e um intervalo. O
  USPapo mostra a faixa, o headway e uma janela para a próxima passagem. Também
  mostra o centro dessa janela como referência aproximada, sem apresentá-lo
  como partida exata ou previsão GPS.
- A espera esperada numa faixa é **meio intervalo**, nunca zero. A SPTrans
  publica as faixas como `[inicio, inicio+3540]`, deixando 60 segundos de lacuna
  entre uma e a seguinte; tratar essa lacuna como "sem faixa" fazia o instante
  que caísse nela valer uma espera de segundos, e essa linha vencia o ranking do
  planejador. Fora da faixa, soma-se o tempo até ela abrir.
- `calendar_dates.txt` tem precedência sobre o calendário semanal quando a
  SPTrans o publicar.
- A resposta informa quando o recorte GTFS foi gerado e alerta após sete dias
  sem atualização.

O cálculo de caminhada é uma aproximação geográfica, não uma navegação por
calçadas. O planejador cobre caminhada e viagens diretas de ônibus; ele ainda
não modela baldeações. A API do Google Maps não está integrada e não é tratada
como fonte implícita.

Duas regras de produto decidem o que é oferecido:

- **A caminhada ganha o empate.** O ônibus só é recomendado quando chega antes
  de quem foi a pé. O fator conservador de 15% sobre a distância em linha reta
  já é a margem de erro do cálculo.
- **Espera acima de hora e meia não é opção.** Sem esse teto, um domingo
  devolvia "8084-10, cerca de 618 minutos" como alternativa, porque a próxima
  partida programada era na segunda de manhã. Quando as linhas existem mas não
  circulam agora, a resposta diz isso em vez de recomendar uma caminhada longa
  sem explicação.

## Resposta para o aluno

A resposta é montada em quatro camadas: o planejador preserva os componentes em
segundos, `transporte_resposta.py` cria uma visão pública tipada, uma chamada
curta à LLM verbaliza somente esses fatos e um validador confere a resposta
inteira antes de exibi-la. Assim, “onde fica e como chegar” responde às duas
partes, enquanto uma pergunta simples não recebe uma explicação de engenharia.

Os módulos seguem a mesma separação das outras ferramentas do projeto: o motor
de horários é `backend/uspapo/gtfs_sptrans.py`, a API ao vivo é
`backend/uspapo/olhovivo.py`, e `backend/uspapo/ferramentas/circulares.py` só
faz o despacho entre os quatro modos de consulta, escreve a prosa de falha e
declara o schema — ele não faz aritmética de horário nem de distância. O trajeto
a pé passa pelo mesmo contrato tipado do trajeto de ônibus, com os mesmos fatos
obrigatórios, para que a naturalização não possa omitir a duração.

O modo normal mostra uma única duração: o total, já incluindo espera e
caminhada. O tempo dentro do ônibus só aparece quando o aluno pede o cálculo;
nesse caso, todos os componentes aparecem juntos. Quando existe ETA ao vivo,
ele substitui a espera programada e o total é recalculado.

Termos internos como GTFS, `stop_id`, recorte, ranking e `exact_times` não
aparecem na resposta normal; as fontes continuam sendo exibidas separadamente
pelo site. A LLM não recebe IDs internos e não decide linha, sentido, parada ou
duração. Sua saída não é transmitida em streaming: primeiro ela é validada
contra a visão pública. Número, horário, linha ou local novo fazem o backend
descartar a paráfrase e usar imediatamente o renderer determinístico de fallback.

## Atualização e validação

O workflow diário baixa o GTFS, valida o tamanho mínimo do recorte, publica o
JSON de forma atômica e só então executa os testes. Para repetir localmente no
PowerShell:

```powershell
.\venv\Scripts\python.exe scripts\atualizar_gtfs_sptrans.py
$env:PYTHONPATH='backend'
$env:SPTRANS_TOKEN=''
.\venv\Scripts\python.exe -m unittest `
  backend.uspapo.test_roteamento `
  backend.uspapo.test_gtfs_sptrans `
  backend.uspapo.test_olhovivo `
  backend.uspapo.test_naturalizador_transporte `
  backend.uspapo.test_transporte_resposta `
  backend.uspapo.test_provedores `
  backend.uspapo.ferramentas.test_circulares `
  backend.uspapo.test_preconsulta_conversa `
  scripts.test_atualizar_gtfs_sptrans -v
```

A matriz de regressão testa todos os pares dirigidos do catálogo. Para incluir
um prédio novo, adicione nome, aliases, coordenada e fonte a
`CATALOGO_LOCAIS`; se declarar um `nomes_parada`, o teste exige que esse nome
exista no GTFS oficial atual.

Fontes primárias:

- [Dados GTFS da SPTrans](https://www.sptrans.com.br/desenvolvedores/)
- [Documentação da API Olho Vivo](https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/)
- [Mapas da Prefeitura do Campus](https://puspc.usp.br/mobilidade/mapas/)

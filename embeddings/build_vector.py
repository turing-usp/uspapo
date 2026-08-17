"""Sincronização do banco vetorial: `data/processed/` -> Pinecone.

O desenho central continua o mesmo, porque ele estava certo: o ledger guarda o
hash de cada parágrafo, o rechunking ancorado reconhece o que não mudou, e só o
que sobra vira requisição. Numa semana em que nada mudou, o custo é zero.

O que mudou é tudo que acontece em volta disso, porque foi em volta que o
pipeline quebrou:

**Orçamento antes de qualquer requisição.** O plano inteiro é montado em memória
e conferido contra três travas antes de a primeira chamada sair. A trava
proporcional é a que importa: mexer em mais de um quarto do banco de uma vez não
é manutenção, é migração, e migração pede `--forcar-migracao` na mão de alguém,
não o cron das 5h.

**Ordem à prova de queda.** Antes era deletar, depois inserir, e salvar o ledger
só no fim. Uma queda no meio deixava o ledger apontando para vetores já apagados
e nunca reescritos: um buraco permanente e silencioso na busca. Agora insere
primeiro, salva o ledger com o que foi confirmado, e só então apaga, e o que
está para apagar fica registrado em `pendencias.json` para o caso de a queda ser
bem no meio disso. A invariante é `ledger ⊆ Pinecone`: sobra de vetor custa
dinheiro, falta de vetor custa resposta errada.

**Repetição com teto.** O `while not sucesso:` sem saída rodava até o GitHub
Actions matar o job seis horas depois. Agora é backoff exponencial com número
máximo de tentativas.

Roda como `python -m embeddings.build_vector` a partir da raiz do projeto.
"""

import argparse
import glob
import json
import os
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from tqdm import tqdm

from embeddings import config_vetor as cfg
from embeddings import cota as C
from embeddings import ledger as L
from embeddings.chunking import agrupar_paragrafos, gerar_hash, rechunking_ancorado, texto_para_embedding
from embeddings.qualidade import filtrar_chunks
from embeddings.texto import segmentar_paragrafos

# Um arquivo que perde mais da metade das páginas de uma vez quase nunca é um
# site que encolheu: é um scraper que quebrou. Melhor não sincronizar nada dele.
LIMIAR_SUMICO_ARQUIVO = 0.5


class OrcamentoEstourado(RuntimeError):
    pass


class CotaMensalEstourada(RuntimeError):
    """A cota de tokens de embedding do mês acabou; backoff não resolve."""


@dataclass
class Plano:
    upserts: list[dict] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    total_no_ledger: int = 0
    nascidos: Counter = field(default_factory=Counter)
    mortos: Counter = field(default_factory=Counter)
    reaproveitados: int = 0
    descartes: Counter = field(default_factory=Counter)
    realocados: list[dict] = field(default_factory=list)
    arquivos_pulados: list[str] = field(default_factory=list)

    @property
    def toca(self) -> int:
        return len(self.upserts) + len(self.deletes)


# ─────────────────────────────────────────────
# Disjuntor
# ─────────────────────────────────────────────
def custo_em_tokens(plano: Plano) -> int:
    """Quanto esta remessa deve custar de tokens de embedding."""
    return C.estimar_tokens(registro.get("text", "") for registro in plano.upserts)


def verificar_cota_mensal(plano: Plano) -> None:
    """Trava acumulativa: as outras são por execução, esta é do mês inteiro.

    Vale inclusive na migração forçada. `--forcar-migracao` autoriza mexer em
    muito vetor de uma vez; ele não cria tokens que o plano não tem, e um
    rebuild completo do corpus (~25 mil chunks) custa mais que a cota mensal
    sozinho — foi assim que o 429 apareceu.
    """
    cabe, motivo = C.cabe(custo_em_tokens(plano))
    if not cabe:
        raise CotaMensalEstourada(motivo)


def verificar_orcamento(plano: Plano, permitir_migracao: bool) -> None:
    """Três travas independentes. Qualquer uma aborta antes de tocar na nuvem."""
    if permitir_migracao:
        return

    if len(plano.upserts) > cfg.ORCAMENTO_UPSERTS:
        raise OrcamentoEstourado(
            f"{len(plano.upserts)} upserts pedidos, teto é {cfg.ORCAMENTO_UPSERTS}. "
            f"Maiores responsáveis: {plano.nascidos.most_common(3)}"
        )
    if len(plano.deletes) > cfg.ORCAMENTO_DELETES:
        raise OrcamentoEstourado(
            f"{len(plano.deletes)} deletes pedidos, teto é {cfg.ORCAMENTO_DELETES}. "
            f"Maiores responsáveis: {plano.mortos.most_common(3)}"
        )

    base = plano.total_no_ledger
    if base and plano.toca / base > cfg.LIMIAR_ABORTO_PCT:
        raise OrcamentoEstourado(
            f"a operação mexeria em {plano.toca} de {base} vetores "
            f"({100 * plano.toca / base:.0f}%), acima do limite de "
            f"{100 * cfg.LIMIAR_ABORTO_PCT:.0f}%. Isso é uma migração, não uma "
            "atualização de rotina. Se for mesmo o que você quer, rode com "
            "--forcar-migracao."
        )


# Um 429 de cota mensal não é o mesmo que um 429 de excesso de requisições. O
# primeiro só passa na virada do mês; insistir seis vezes com backoff apenas
# atrasa a falha em minutos e polui o log com "tentativa 5/6".
MARCAS_DE_COTA = ("embedding token limit", "for the current month", "upgrade your plan")


def _e_cota_mensal(texto: str) -> bool:
    minusculo = texto.lower()
    return any(marca in minusculo for marca in MARCAS_DE_COTA)


def executar_com_backoff(operacao, descricao: str):
    """Repete com espera exponencial e desistência explícita."""
    for tentativa in range(1, cfg.MAX_TENTATIVAS + 1):
        try:
            return operacao()
        except Exception as erro:
            texto = str(erro)
            if _e_cota_mensal(texto):
                raise CotaMensalEstourada(
                    "a cota mensal de tokens de embedding do plano acabou. "
                    "Ela só volta na virada do mês; nenhuma tentativa extra "
                    f"adianta. {C.resumo()}"
                ) from erro
            recuperavel = any(
                marca in texto
                for marca in ("429", "RESOURCE_EXHAUSTED", "503", "502", "504", "timeout", "Timeout")
            )
            if not recuperavel or tentativa == cfg.MAX_TENTATIVAS:
                raise
            espera = min(cfg.BACKOFF_BASE * (2 ** (tentativa - 1)), cfg.BACKOFF_TETO)
            espera += random.uniform(0, espera * 0.1)  # jitter, para não sincronizar retentativas
            print(
                f"\n[!] {descricao} falhou ({texto[:80]}). "
                f"Tentativa {tentativa}/{cfg.MAX_TENTATIVAS}, aguardando {espera:.0f}s..."
            )
            time.sleep(espera)


# ─────────────────────────────────────────────
# Montagem do plano
# ─────────────────────────────────────────────
def _registro(chunk_id: str, texto: str, url: str, titulo: str, arquivo: str) -> dict:
    return {
        "_id": chunk_id,
        "text": texto_para_embedding(titulo, texto),
        "url": url,
        "titulo": titulo or "Sem título",
        "arquivo_origem": arquivo,
    }


def sincronizar_pagina(
    ledger: dict, plano: Plano, arquivo: str, pagina: dict, estado: dict, contexto: dict
) -> None:
    url = pagina.get("url", "")
    titulo = pagina.get("titulo", "")
    contexto["titulos"][(arquivo, url)] = titulo
    paragrafos = segmentar_paragrafos(pagina.get("texto_limpo", ""))
    if not paragrafos:
        return

    antigos = estado.get(url, {}).get("chunks", [])
    finais = (
        rechunking_ancorado(antigos, paragrafos) if antigos else agrupar_paragrafos(paragrafos)
    )

    finais, descartes = filtrar_chunks(finais)
    for motivo, quantos in descartes.items():
        plano.descartes[motivo] += quantos
    if not finais:
        return

    # Chunk reaproveitado vem do ledger sem texto, mas o texto está aqui: os
    # `hashes_p` dele apontam para parágrafos DESTA página. Reconstruir custa
    # nada e é o que permite reenviar o metadado de um chunk que trocou de dono.
    mapa_paragrafos = {gerar_hash(p): p for p in paragrafos}
    for chunk in finais:
        if chunk.get("texto") is None:
            partes = [mapa_paragrafos.get(h) for h in chunk.get("hashes_p", [])]
            if partes and all(p is not None for p in partes):
                chunk["texto"] = "\n\n".join(partes)

    hash_url = gerar_hash(url)[:8]

    # Adquirir ANTES de liberar. Se fosse ao contrário, um chunk que continua na
    # página chegaria a zero referências no meio do caminho, seria agendado para
    # deleção, e renasceria com outro id — churn puro.
    for indice, chunk in enumerate(finais):
        # O mapa de textos serve para reenviar metadado de chunk que trocou de
        # dono; alimentá-lo com todo chunk cujo texto conhecemos, reaproveitado
        # ou não, é o que faz essa reconciliação fechar na mesma execução.
        if chunk.get("texto") is not None:
            contexto["textos"][chunk["hash_chunk"]] = chunk["texto"]
        chunk_id, nasceu = L.adquirir(
            ledger,
            chunk["hash_chunk"],
            arquivo,
            url,
            lambda i=indice, h=chunk["hash_chunk"]: f"{arquivo}_{hash_url}_ch{i}_{h}",
        )
        chunk["chunk_id"] = chunk_id
        if nasceu:
            plano.upserts.append(_registro(chunk_id, chunk["texto"], url, titulo, arquivo))
            plano.nascidos[arquivo] += 1
        else:
            plano.reaproveitados += 1

    for antigo in antigos:
        resultado = L.liberar(ledger, antigo["hash_chunk"], arquivo, url)
        if resultado is None:
            continue
        if resultado["acao"] == "morto":
            plano.deletes.append(resultado["chunk_id"])
            plano.mortos[arquivo] += 1
        else:
            plano.realocados.append(resultado)

    estado[url] = {"titulo": titulo, "chunks": [L.enxugar_chunk(c) for c in finais]}


def soltar_pagina(ledger: dict, plano: Plano, arquivo: str, url: str, dados: dict) -> None:
    for chunk in dados.get("chunks", []):
        resultado = L.liberar(ledger, chunk["hash_chunk"], arquivo, url)
        if resultado is None:
            continue
        if resultado["acao"] == "morto":
            plano.deletes.append(resultado["chunk_id"])
            plano.mortos[arquivo] += 1
        else:
            plano.realocados.append(resultado)


def montar_plano(ledger: dict, arquivos: list[str], somente: list[str] | None) -> Plano:
    plano = Plano(total_no_ledger=L.total_de_chunks(ledger))
    contexto: dict = {"textos": {}, "titulos": {}}
    locais = {os.path.basename(caminho) for caminho in arquivos}

    # Arquivos que sumiram do disco: soltam tudo que tinham.
    if not somente:
        for nome in sorted(set(ledger["arquivos"]) - locais):
            print(f"   [Lixeira] {nome} não existe mais localmente. Soltando referências...")
            for url, dados in ledger["arquivos"][nome].get("paginas", {}).items():
                soltar_pagina(ledger, plano, nome, url, dados)
            del ledger["arquivos"][nome]

    for caminho in arquivos:
        nome = os.path.basename(caminho)
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                paginas = json.load(f)
        except (OSError, json.JSONDecodeError) as erro:
            print(f"   [ERRO] Falha ao ler {nome}: {erro}")
            plano.arquivos_pulados.append(nome)
            continue

        estado = L.paginas_do_arquivo(ledger, nome)
        urls_atuais = {p.get("url", "") for p in paginas}
        sumidas = set(estado) - urls_atuais

        # Trava de sanidade: scraper quebrado não vira deleção em massa.
        if estado and len(sumidas) > len(estado) * LIMIAR_SUMICO_ARQUIVO:
            print(
                f"   [PULADO] {nome}: {len(sumidas)} de {len(estado)} páginas sumiram de uma vez. "
                "Parece scraper quebrado, não site encolhendo. Nada foi sincronizado."
            )
            plano.arquivos_pulados.append(nome)
            continue

        for url in sumidas:
            soltar_pagina(ledger, plano, nome, url, estado[url])
            del estado[url]

        for pagina in paginas:
            sincronizar_pagina(ledger, plano, nome, pagina, estado, contexto)

        if plano.nascidos[nome] or plano.mortos[nome]:
            print(
                f"   [{nome:26s}] +{plano.nascidos[nome]:5d} novos  "
                f"-{plano.mortos[nome]:5d} removidos"
            )

    _resolver_realocados(plano, contexto)
    return plano


def _resolver_realocados(plano: Plano, contexto: dict) -> None:
    """Reenvia o metadado dos chunks cujo dono mudou.

    Acontece quando a página que criou um chunk compartilhado some e outra
    continua usando o texto. O vetor segue válido, mas o `url` gravado nele
    apontaria para uma página que não existe mais — e é essa URL que a busca
    devolve como fonte.
    """
    if not plano.realocados:
        return

    pendentes = 0
    for item in plano.realocados:
        # `chunk_id` termina com o hash do texto: é dele que recuperamos o conteúdo.
        hash_chunk = item["chunk_id"].rsplit("_", 1)[-1]
        texto = contexto["textos"].get(hash_chunk)
        if texto is None:
            pendentes += 1
            continue
        titulo = contexto["titulos"].get((item["arquivo"], item["url"]), "")
        plano.upserts.append(
            _registro(item["chunk_id"], texto, item["url"], titulo, item["arquivo"])
        )

    if pendentes:
        print(
            f"   [aviso] {pendentes} chunk(s) mudaram de dono mas o novo dono não foi "
            "processado nesta execução; o metadado deles continua apontando para a "
            "página antiga até a próxima execução completa."
        )


# ─────────────────────────────────────────────
# Aplicação
# ─────────────────────────────────────────────
def aplicar_plano(plano: Plano, ledger: dict, index) -> None:
    # Nunca apagar o que estamos reescrevendo nesta mesma execução.
    ids_upsert = {registro["_id"] for registro in plano.upserts}
    deletes = [i for i in plano.deletes if i not in ids_upsert]

    if plano.upserts:
        print(f"\n-> Enviando {len(plano.upserts)} vetores...")
        for i in tqdm(range(0, len(plano.upserts), cfg.LOTE_UPSERT), desc="Sincronizando"):
            lote = plano.upserts[i : i + cfg.LOTE_UPSERT]
            executar_com_backoff(
                lambda l=lote: index.upsert_records(namespace=cfg.PINECONE_NAMESPACE, records=l),
                "upsert",
            )
            # Contabiliza lote a lote, e não no fim: uma queda no meio da
            # remessa já gastou os tokens dos lotes que passaram, e o mês
            # precisa saber disso na próxima execução.
            C.registrar(C.estimar_tokens(r.get("text", "") for r in lote))
            time.sleep(cfg.PAUSA_ENTRE_LOTES)
        print(f"\n-> {C.resumo()}")

    # O ledger é salvo AQUI: tudo que ele afirma existir já foi confirmado.
    if deletes:
        L.salvar_pendencias(deletes)
    L.salvar_ledger(ledger)

    if deletes:
        print(f"\n-> Removendo {len(deletes)} vetores obsoletos...")
        for i in range(0, len(deletes), cfg.LOTE_DELETE):
            lote = deletes[i : i + cfg.LOTE_DELETE]
            executar_com_backoff(
                lambda l=lote: index.delete(ids=l, namespace=cfg.PINECONE_NAMESPACE), "delete"
            )
    L.limpar_pendencias()


def _resgatar_pendencias(index) -> None:
    """Termina as deleções que uma execução anterior deixou pela metade."""
    pendentes = L.carregar_pendencias()
    if not pendentes:
        return
    print(f"-> {len(pendentes)} deleção(ões) pendente(s) de uma execução anterior. Concluindo...")
    for i in range(0, len(pendentes), cfg.LOTE_DELETE):
        lote = pendentes[i : i + cfg.LOTE_DELETE]
        executar_com_backoff(
            lambda l=lote: index.delete(ids=l, namespace=cfg.PINECONE_NAMESPACE), "delete pendente"
        )
    L.limpar_pendencias()


# ─────────────────────────────────────────────
# Entrada
# ─────────────────────────────────────────────
def construir_banco(
    somente: list[str] | None = None,
    dry_run: bool | None = None,
    forcar_migracao: bool = False,
) -> dict:
    dry_run = cfg.DRY_RUN if dry_run is None else dry_run

    arquivos = sorted(glob.glob(os.path.join(cfg.PASTA_PROCESSED, "**", "*.json"), recursive=True))
    if somente:
        alvos = {os.path.basename(a) for a in somente}
        arquivos = [a for a in arquivos if os.path.basename(a) in alvos]
    if not arquivos:
        print(f"[AVISO] Nenhum JSON encontrado em {cfg.PASTA_PROCESSED}.")
        return {}

    index = None
    if not dry_run:
        from pinecone import Pinecone

        print("-> Conectando ao Pinecone...")
        pc = Pinecone(api_key=cfg.exigir_api_key())
        index = pc.Index(cfg.PINECONE_INDEX)
        _resgatar_pendencias(index)

    ledger = L.carregar_ledger()
    plano = montar_plano(ledger, arquivos, somente)

    print("\n" + "=" * 56)
    print("RESUMO DA OPERAÇÃO")
    print("=" * 56)
    print(f" Vetores hoje no ledger : {plano.total_no_ledger}")
    print(f" Upserts agendados      : {len(plano.upserts)}")
    print(f" Deletes agendados      : {len(plano.deletes)}")
    print(f" Chunks reaproveitados  : {plano.reaproveitados}")
    if plano.descartes:
        print(f" Descartados na qualidade: {dict(plano.descartes)}")
    if plano.arquivos_pulados:
        print(f" Arquivos pulados       : {plano.arquivos_pulados}")
    tokens_previstos = custo_em_tokens(plano)
    print(f" Tokens de embedding    : ~{tokens_previstos} (restam ~{C.disponivel()} no mês)")
    print("=" * 56)

    relatorio = {
        "data": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "total_no_ledger": plano.total_no_ledger,
        "upserts": len(plano.upserts),
        "deletes": len(plano.deletes),
        "reaproveitados": plano.reaproveitados,
        "descartes": dict(plano.descartes),
        "nascidos_por_arquivo": dict(plano.nascidos),
        "mortos_por_arquivo": dict(plano.mortos),
        "arquivos_pulados": plano.arquivos_pulados,
        "tokens_embedding_previstos": tokens_previstos,
        "cota_mensal": C.carregar(),
    }
    os.makedirs(cfg.PASTA_RELATORIOS, exist_ok=True)
    with open(os.path.join(cfg.PASTA_RELATORIOS, "ultima_execucao.json"), "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    if not plano.toca:
        print("\n-> Banco vetorial já sincronizado. Nada a enviar.")
        if not dry_run:
            L.salvar_ledger(ledger)  # persiste a migração de formato, se houve
        return relatorio

    verificar_orcamento(plano, forcar_migracao or cfg.PERMITIR_MIGRACAO_TOTAL)
    # A cota do mês vale mesmo na migração forçada: ela não é uma trava de
    # segurança do banco, é o teto do plano contratado.
    if not dry_run:
        verificar_cota_mensal(plano)

    if dry_run:
        # O ledger simulado vai para OUTRO arquivo, de propósito. Se um ensaio
        # sobrescrevesse o ledger de verdade, a execução seguinte veria "nada a
        # fazer" e o Pinecone nunca receberia os vetores — uma perda silenciosa,
        # e o comportamento antigo era exatamente esse.
        simulado = cfg.ARQUIVO_LEDGER.replace(".json", ".simulado.json")
        L.salvar_ledger(ledger, simulado)
        print(
            f"\n[DRY RUN] Nada foi enviado. Estado simulado em "
            f"{os.path.relpath(simulado, cfg.RAIZ_PROJETO)} (o ledger real ficou intacto)."
        )
        return relatorio

    aplicar_plano(plano, ledger, index)
    print("\n[SUCESSO] Sincronização concluída.")
    try:
        print(f"Total de vetores no índice: {index.describe_index_stats().total_vector_count}")
    except Exception:
        pass
    return relatorio


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza data/processed com o Pinecone.")
    parser.add_argument("--dry-run", action="store_true", help="Calcula o plano sem escrever na nuvem.")
    parser.add_argument("--somente", nargs="*", default=None, help="Só estes arquivos de data/processed.")
    parser.add_argument(
        "--forcar-migracao",
        action="store_true",
        help="Desliga o disjuntor de orçamento. Use para o rebuild, nunca no cron.",
    )
    argumentos = parser.parse_args()

    try:
        construir_banco(
            somente=argumentos.somente,
            dry_run=True if argumentos.dry_run else None,
            forcar_migracao=argumentos.forcar_migracao,
        )
    except CotaMensalEstourada as erro:
        # Código próprio: a ronda de scraping precisa distinguir "o banco não
        # aceitou esta remessa" de "o mês acabou e nenhuma remessa vai passar".
        print(f"\n[ABORTADO PELA COTA MENSAL] {erro}")
        raise SystemExit(3)
    except OrcamentoEstourado as erro:
        print(f"\n[ABORTADO PELO ORÇAMENTO] {erro}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()

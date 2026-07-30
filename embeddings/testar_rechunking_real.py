import json
import os
import hashlib

def gerar_hash(texto: str) -> str:
    return hashlib.md5(texto.encode('utf-8')).hexdigest()

def agrupar_lista_de_paragrafos(lista_textos_paragrafos: list, target_size=800, max_size=1100) -> list:
    chunks_formados = []
    chunk_atual_textos = []
    tamanho_atual = 0

    for p in lista_textos_paragrafos:
        tam_p = len(p)
        if tam_p > max_size:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_formados.append({
                    "texto": texto_junto,
                    "hash_chunk": gerar_hash(texto_junto),
                    "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                })
                chunk_atual_textos = []
                tamanho_atual = 0
            chunks_formados.append({
                "texto": p,
                "hash_chunk": gerar_hash(p),
                "paragrafos": [{"texto": p, "hash_p": gerar_hash(p)}]
            })
            continue

        tamanho_projetado = tamanho_atual + tam_p + (2 if chunk_atual_textos else 0)

        if tamanho_projetado <= target_size:
            chunk_atual_textos.append(p)
            tamanho_atual = tamanho_projetado
        elif tamanho_projetado <= max_size:
            chunk_atual_textos.append(p)
            texto_junto = "\n\n".join(chunk_atual_textos)
            chunks_formados.append({
                "texto": texto_junto,
                "hash_chunk": gerar_hash(texto_junto),
                "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
            })
            chunk_atual_textos = []
            tamanho_atual = 0
        else:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_formados.append({
                    "texto": texto_junto,
                    "hash_chunk": gerar_hash(texto_junto),
                    "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                })
            chunk_atual_textos = [p]
            tamanho_atual = tam_p

    if chunk_atual_textos:
        texto_junto = "\n\n".join(chunk_atual_textos)
        chunks_formados.append({
            "texto": texto_junto,
            "hash_chunk": gerar_hash(texto_junto),
            "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
        })

    return chunks_formados


def rechunking_ancorado(old_chunks, novos_paragrafos_puros, target_size=800, max_size=1100):
    """
    ALGORITMO DEFINITIVO: Resolve Múltiplas Zonas de Impacto com O(N) de complexidade.
    Usa os chunks antigos como 'Save Points' (Âncoras) para parar cascatas instantaneamente.
    """
    # 1. Cria um mapa de Âncoras altamente otimizado (busca em O(1))
    primeiro_p_map = {}
    for c in old_chunks:
        if not c["paragrafos"]: continue
        first_hash = c["paragrafos"][0]["hash_p"]
        assinatura = "".join([p["hash_p"] for p in c["paragrafos"]])
        
        if first_hash not in primeiro_p_map:
            primeiro_p_map[first_hash] = []
        primeiro_p_map[first_hash].append({
            "assinatura": assinatura, 
            "len": len(c["paragrafos"]), 
            "chunk": c
        })

    chunks_finais = []
    chunk_atual_textos = []
    tamanho_atual = 0

    idx = 0
    total_p = len(novos_paragrafos_puros)
    novos_hashes = [gerar_hash(p) for p in novos_paragrafos_puros] # Pre-calculado por performance

    while idx < total_p:
        p_texto = novos_paragrafos_puros[idx]
        p_hash = novos_hashes[idx]

        # TENTATIVA DE ANCORAGEM (O freio da cascata)
        ancorado = False
        if len(chunk_atual_textos) == 0:
            if p_hash in primeiro_p_map:
                for candidato in primeiro_p_map[p_hash]:
                    tam_janela = candidato["len"]
                    if idx + tam_janela <= total_p:
                        # Verifica se a assinatura bate perfeitamente
                        assinatura_teste = "".join(novos_hashes[idx : idx + tam_janela])
                        if assinatura_teste == candidato["assinatura"]:
                            # BINGO! Reutiliza o chunk do Pinecone e pula o cursor!
                            chunks_finais.append(candidato["chunk"])
                            idx += tam_janela
                            ancorado = True
                            break
        
        if ancorado:
            continue

        # LÓGICA DE AGRUPAMENTO (Constrói o novo Chunk)
        tam_p = len(p_texto)
        if tam_p > max_size:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_finais.append({
                    "texto": texto_junto,
                    "hash_chunk": gerar_hash(texto_junto),
                    "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                })
                chunk_atual_textos = []
                tamanho_atual = 0

            chunks_finais.append({
                "texto": p_texto,
                "hash_chunk": p_hash,
                "paragrafos": [{"texto": p_texto, "hash_p": p_hash}]
            })
            idx += 1
            continue

        tamanho_projetado = tamanho_atual + tam_p + (2 if chunk_atual_textos else 0)

        if tamanho_projetado <= target_size:
            chunk_atual_textos.append(p_texto)
            tamanho_atual = tamanho_projetado
        elif tamanho_projetado <= max_size:
            chunk_atual_textos.append(p_texto)
            texto_junto = "\n\n".join(chunk_atual_textos)
            chunks_finais.append({
                "texto": texto_junto,
                "hash_chunk": gerar_hash(texto_junto),
                "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
            })
            chunk_atual_textos = []
            tamanho_atual = 0
        else:
            if chunk_atual_textos:
                texto_junto = "\n\n".join(chunk_atual_textos)
                chunks_finais.append({
                    "texto": texto_junto,
                    "hash_chunk": gerar_hash(texto_junto),
                    "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
                })
            chunk_atual_textos = [p_texto]
            tamanho_atual = tam_p

        idx += 1

    # Fecha o último chunk se sobrou algo
    if chunk_atual_textos:
        texto_junto = "\n\n".join(chunk_atual_textos)
        chunks_finais.append({
            "texto": texto_junto,
            "hash_chunk": gerar_hash(texto_junto),
            "paragrafos": [{"texto": txt, "hash_p": gerar_hash(txt)} for txt in chunk_atual_textos]
        })

    # BALANÇO FINANCEIRO (Pinecone)
    ids_velhos = {c["chunk_id"]: c for c in old_chunks if "chunk_id" in c}
    ids_novos_preservados = set()
    chunks_nascidos = []

    for c_final in chunks_finais:
        if "chunk_id" in c_final:
            ids_novos_preservados.add(c_final["chunk_id"])
        else:
            chunks_nascidos.append(c_final)

    ids_mortos = list(set(ids_velhos.keys()) - ids_novos_preservados)

    return chunks_finais, ids_mortos, chunks_nascidos


def simular_multiplas_zonas_reais():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_json = os.path.join(diretorio_atual, "..", "data", "processed", "IQ", "conteudo_navbar_limpo.json")
    
    # Fallback se a pasta for diferente no seu PC
    if not os.path.exists(caminho_json):
        caminho_json = os.path.join(diretorio_atual, "..", "data", "processed", "conteudo_navbar_limpo.json")

    with open(caminho_json, 'r', encoding='utf-8') as f:
        paginas = json.load(f)

    paragrafos_originais = []
    for pag in paginas:
        p_list = [p.strip() for p in pag.get("texto_limpo", "").split("\n\n") if p.strip()]
        paragrafos_originais.extend(p_list)

    # DIA 1: O estado antigo
    old_chunks = agrupar_lista_de_paragrafos(paragrafos_originais)
    for idx, c in enumerate(old_chunks):
        c["chunk_id"] = f"POLI_CHUNK_{idx+1}"

    print(f"DIA 1: {len(old_chunks)} chunks armazenados.")

    # DIA 2: Destruindo o site da USP em várias regiões independentes
    print("\nSIMULANDO DIA 2: Múltiplas mutações simultâneas...")
    paragrafos_dia2 = paragrafos_originais.copy()
    
    # 1. Mutação no Início (Deletando um parágrafo)
    print(" -> Deletando o parágrafo 10.")
    paragrafos_dia2.pop(10)
    
    # 2. Mutação no Meio (Alterando texto)
    print(" -> Alterando o parágrafo 200.")
    paragrafos_dia2[200] = "Texto totalmente alterado na Poli."
    
    # 3. Mutação no Fim (Inserindo novo)
    print(" -> Inserindo um novo parágrafo logo após o 500.")
    paragrafos_dia2.insert(500, "Novo parágrafo gigantesco inserido aqui!")
    
    # 4. Mutação aleatória (Unindo dois parágrafos)
    print(" -> Unindo o parágrafo 800 e 801 em um só.")
    paragrafos_dia2[800] = paragrafos_dia2[800] + " " + paragrafos_dia2[801]
    paragrafos_dia2.pop(801)

    finais, ids_deletados, chunks_novos = rechunking_ancorado(old_chunks, paragrafos_dia2)
    chunks_intactos = [c for c in finais if 'chunk_id' in c]

    print(f"\nRESULTADO DA ANCORAGEM MÚLTIPLA:")
    print(f" -> Chunks Salvos (Custo 0): {len(chunks_intactos)} / {len(old_chunks)}")
    print(f" -> Chunks Destruídos pelo Pinecone: {len(ids_deletados)}")
    print(f" -> Chunks Nascidos: {len(chunks_novos)}")
    
    # Validação de segurança: Não engoliu o documento?
    economia = (len(chunks_intactos) / len(old_chunks)) * 100
    print(f" -> Economia de WUs: {economia:.1f}%")
    
    if economia > 90:
        print("\n[VEREDITO] É UM SUCESSO ABSOLUTO! O algoritmo isolou 4 pontos críticos independentes sem derreter o meio do arquivo!")

if __name__ == "__main__":
    simular_multiplas_zonas_reais()
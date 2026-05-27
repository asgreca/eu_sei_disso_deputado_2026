#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
10_H_saneador_mencoes_fuzz.py
Usa a biblioteca RapidFuzz para limpar as extrações enganosas do modelo de linguagem (LLM).
Compara o nome que a IA extraiu contra o banco oficial TBD (nome de urna / nome civil).
Registros que não atingirem 85% de similaridade (ex: 'Projeto de Lei', 'Segurança', 'Jair Bolsonaro') serão EXCLUÍDOS.
Os registros corretos terão o nome padronizado para o Nome de Urna oficial.
"""

import sqlite3
import os
from rapidfuzz import process, fuzz
from tqdm import tqdm

DB_NOTICIAS = "/Users/aislangreca/TCC/noticias_parlamentares.db"
DB_TABELAO = "/Users/aislangreca/Library/Mobile Documents/com~apple~CloudDocs/Projetos_dados/acompanhamento_camara/dash2/tabelao.db"

def buscar_nomes_oficiais():
    """Busca o nome de urna e nome civil de todos os parlamentares no banco mestre."""
    print("📥 Carregando listagem oficial de Parlamentares da Câmara...")
    try:
        conn = sqlite3.connect(DB_TABELAO)
    except sqlite3.OperationalError:
        print("❌ Erro ao conectar no tabelao.db. Verifique o caminho.")
        return [], {}

    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, nomeCivil FROM tabelao")
    linhas = cursor.fetchall()
    conn.close()

    nomes_oficiais_para_fuzz = []
    mapa_nome_para_urna = {} # Mapeia civil ou nome de urna para o nome de Urna definitivo

    for _, pug, civil in linhas:
        if pug: # nome de urna
            nomes_oficiais_para_fuzz.append(pug.strip())
            mapa_nome_para_urna[pug.strip().lower()] = pug.strip()
        if civil:
            nomes_oficiais_para_fuzz.append(civil.strip())
            mapa_nome_para_urna[civil.strip().lower()] = pug.strip() # Se bater no civil, padroniza pro Urna
            
    return list(set(nomes_oficiais_para_fuzz)), mapa_nome_para_urna

def normalizar_mencoes_do_grafo(lista_fuzz, mapa_padrao):
    """Varre todas as menções que a IA fez e exclui as falsas ou padroniza as verdadeiras."""
    print("🔍 Conectando no banco de Notícias e Menções...")
    conn = sqlite3.connect(DB_NOTICIAS)
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, parlamentar_nome FROM noticias_mencoes")
    mencoes_cruas = cursor.fetchall()
    
    if not mencoes_cruas:
        print("✅ Nenhuma menção encontrada para padronizar.")
        return
        
    print(f"🧹 Analisando {len(mencoes_cruas)} entidades extraídas pelo LLM usando Fuzzy Matching...")
    
    registros_excluidos = 0
    registros_padronizados = 0
    
    # Threshold (Nota de corte): A IA tem que ter chegado em pelo menos 80% do nome correto
    # Senão, excluímos como falso positivo (ex: 'Governo Federal', 'Projeto de Lei').
    CORTE_SIMILARIDADE = 80.0
    
    for row_id, nome_extraido in tqdm(mencoes_cruas):
        if not nome_extraido:
            cursor.execute("DELETE FROM noticias_mencoes WHERE id = ?", (row_id,))
            registros_excluidos += 1
            continue

        # Evitar bugs se o nome extraído for um bloco muito grande de texto
        if len(nome_extraido) > 100:
            cursor.execute("DELETE FROM noticias_mencoes WHERE id = ?", (row_id,))
            registros_excluidos += 1
            continue
            
        # O process.extractOne retorna (melhor_string_achada, pontuacao_0_a_100, indice)
        resultado = process.extractOne(
            nome_extraido.strip(), 
            lista_fuzz, 
            scorer=fuzz.WRatio # O WRatio é ótimo para misturar maiusculas, sobrenomes omitidos, etc.
        )
        
        if resultado is None:
            continue
            
        melhor_match, pontuacao, _ = resultado
        
        if pontuacao >= CORTE_SIMILARIDADE:
            # Encontrou! A IA se referia a este deputado. Vamos padronizar o nome no banco para cruzar os dados fácil
            nome_oficial = mapa_padrao.get(melhor_match.lower(), melhor_match)
            
            # Só faz o update se o nome oficial for diferente da forma como a IA escreveu
            if nome_extraido != nome_oficial:
                cursor.execute("UPDATE noticias_mencoes SET parlamentar_nome = ? WHERE id = ?", (nome_oficial, row_id))
                registros_padronizados += 1
        else:
            # O nome extraído pela IA não atinge os 80% mínimos de semelhança com a lista de 513 deputados
            # Ou seja, é lixo (Jair Bolsonaro, Projeto de Lei, Ministro, Assessor, etc).
            cursor.execute("DELETE FROM noticias_mencoes WHERE id = ?", (row_id,))
            registros_excluidos += 1

    conn.commit()
    conn.close()
    
    print("\n=======================================================")
    print(" 🏁 RESULTADO DA PADRONIZAÇÃO RAPIDFUZZ")
    print("=======================================================")
    print(f"🗑️ Deletados (Falsos Positivos): {registros_excluidos} registros ('Projeto de lei', não-deputados, etc)")
    print(f"✨ Padronizados c/ Sucesso: {registros_padronizados} nomes alinhados ao Nome de Urna")
    print("=======================================================")
    print("O seu banco de dados de Grafos está purificado!")

if __name__ == "__main__":
    lista, mapa = buscar_nomes_oficiais()
    if lista:
        normalizar_mencoes_do_grafo(lista, mapa)

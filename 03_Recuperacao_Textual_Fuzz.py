#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
10_I_recuperacao_fuzz_textos.py
Lê a reportagem na íntegra de TODOS os milhares de textos do banco de notícias.
Cruza com o Tabelão de Parlamentares batendo Nome de Urna e Nome Civil usando Match Exato e Fuzzing de Alta Velocidade.
Isso serve para descobrirmos a VERDADEIRA quantidade de notícias que citam os deputados da base oficial.
"""

import sqlite3
import os
import re
from tqdm import tqdm

DB_NOTICIAS = "/Users/aislangreca/TCC/noticias_parlamentares.db"
DB_TABELAO = "/Users/aislangreca/Library/Mobile Documents/com~apple~CloudDocs/Projetos_dados/acompanhamento_camara/dash2/tabelao.db"

def buscar_nomes_oficiais():
    print("📥 Carregando listagem oficial de Parlamentares da Câmara...")
    try:
        conn = sqlite3.connect(DB_TABELAO)
    except sqlite3.OperationalError:
        return []

    cursor = conn.cursor()
    cursor.execute("SELECT nome, nomeCivil FROM tabelao")
    linhas = cursor.fetchall()
    conn.close()

    nomes = set()
    for pug, civil in linhas:
        if pug: nomes.add(pug.strip())
        # Para Nome Civil, como costuma ser muito longo e a mídia abrevia, 
        # pegamos também o Primeiro + Último sobrenome (Ex: Aislan Greca)
        if civil:
            civil = civil.strip()
            nomes.add(civil)
            partes = civil.split()
            if len(partes) > 2:
                nomes.add(f"{partes[0]} {partes[-1]}")
                
    # Remover palavras muito curtas ou comuns para evitar falsos positivos
    nomes_limpos = {n for n in nomes if len(n) > 5}
    return list(nomes_limpos)

def minerar_textos(lista_deputados):
    print("🔍 Conectando no banco de Notícias e lendo TODOS os textos completos...")
    conn = sqlite3.connect(DB_NOTICIAS)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, titulo, resumo, texto_completo FROM noticias")
    noticias = cursor.fetchall()
    
    print(f"📖 Foram carregadas {len(noticias)} reportagens brutas (incluindo apenas títulos/resumos).")
    
    noticias_com_citacao = 0
    total_citacoes = 0
    
    # Pre-compilar Regex para velocidade máxima (Whole word match ignorando case)
    # Evita que "Aislan" dê match dentro de "Aislandia"
    print("⚙️ Compilando Dicionário Léxico de Nomes...")
    padroes = []
    for nome in lista_deputados:
        # Escapando regex e criando whole-word bounds sensível
        padroes.append((nome, re.compile(rf'\b{re.escape(nome)}\b', re.IGNORECASE)))
        
    print("🚀 Iniciando Varredura Textual Absoluta...")
    
    # Criar uma tabela temporária ou provisória nova para guardar essas menções seguras
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mencoes_textuais_seguras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_id INTEGER,
        parlamentar_nome TEXT
    )""")
    # Limpa caso já exista
    cursor.execute("DELETE FROM mencoes_textuais_seguras")
    
    for news_id, titulo, resumo, texto in tqdm(noticias):
        # Une o título, resumo e o texto completo para não deixar NENHUMA menção escapar
        # Usamos or "" para tratar os campos vazios (None)
        texto_unido = f"{titulo or ''} {resumo or ''} {texto or ''}"
        
        achou_na_noticia = False
        para_inserir = []
        
        for nome_original, regex in padroes:
            if regex.search(texto_unido):
                para_inserir.append((news_id, nome_original))
                total_citacoes += 1
                achou_na_noticia = True
                
        if achou_na_noticia:
            noticias_com_citacao += 1
            cursor.executemany("INSERT INTO mencoes_textuais_seguras (news_id, parlamentar_nome) VALUES (?, ?)", para_inserir)
            
    conn.commit()
    conn.close()
    
    print("\n=======================================================")
    print(" 🏁 RESULTADO DA VARREDURA NO TEXTO BRUTO")
    print("=======================================================")
    print(f"📰 Notícias que REALMENTE citam deputados: {noticias_com_citacao} de {len(noticias)}")
    print(f"🗣️ Total de citações encontradas: {total_citacoes}")
    print("=======================================================")
    print("Os resultados garantidos foram salvos na tabela 'mencoes_textuais_seguras'.")

if __name__ == "__main__":
    lista = buscar_nomes_oficiais()
    if lista:
        minerar_textos(lista)

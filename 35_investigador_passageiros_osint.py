#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
35_investigador_passageiros_osint.py
Motor de processamento em lote para investigação de passageiros frequentes.
Cruza dados internos, busca OSINT na web, identifica outros parlamentares e gera dossiês via GPT-4o-mini.
"""

import os
import json
import sqlite3
import pandas as pd
from datetime import datetime
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm
import time

# Carregar variáveis do arquivo .env
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

DB_PATH = "tabelao.db"

def conectar_bd():
    return sqlite3.connect(DB_PATH)

def identificar_passageiros_frequentes(limite=50):
    """Identifica passageiros com mais de 2 viagens para processamento."""
    conn = conectar_bd()
    query = """
    SELECT txtPassageiro, COUNT(*) as qtd, SUM(vlrLiquido) as total 
    FROM tabelao 
    WHERE UPPER(txtDescricao) LIKE '%PASSAGEM AÉREA%'
    AND txtPassageiro IS NOT NULL AND txtPassageiro != 'N/A'
    GROUP BY txtPassageiro 
    HAVING qtd > 2 
    ORDER BY total DESC 
    LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=[limite])
    conn.close()
    return df

def obter_outros_parlamentares(nome_passageiro):
    """Descobre quais outros deputados pagaram passagens para este nome."""
    conn = conectar_bd()
    query = """
    SELECT DISTINCT nome 
    FROM tabelao 
    WHERE txtPassageiro = ? 
    AND UPPER(txtDescricao) LIKE '%PASSAGEM AÉREA%'
    """
    df = pd.read_sql_query(query, conn, params=[nome_passageiro])
    conn.close()
    return df['nome'].tolist()

def investigar_nome(nome_passageiro):
    """Realiza a coleta de dados sobre um nome específico."""
    nome = nome_passageiro.strip().upper()
    conn = conectar_bd()
    
    # 1. Sociedades (CNPJ)
    query_socio = "SELECT Nome, Qualificação_Socio FROM lista_cnpj_geral WHERE Nome_Socio LIKE ?"
    df_socios = pd.read_sql_query(query_socio, conn, params=[f"%{nome}%"])
    socios_info = df_socios.to_dict('records')
    
    # 2. Doações de Campanha
    query_doacao = "SELECT parlamentar, valor_doado_campanha, data_doacao FROM cruzamento_doacoes WHERE socio LIKE ?"
    df_doacoes = pd.read_sql_query(query_doacao, conn, params=[f"%{nome}%"])
    doacoes_info = df_doacoes.to_dict('records')
    
    # 3. Gabinete/Assessores
    query_assessor = "SELECT nome_deputado_referencia FROM gabinetes_assessores WHERE nome_assessor LIKE ?"
    df_assessores = pd.read_sql_query(query_assessor, conn, params=[f"%{nome}%"])
    assessores_info = df_assessores.to_dict('records')
    
    conn.close()
    
    # 4. Outros Parlamentares (Rastreio de Cota)
    outros_parls = obter_outros_parlamentares(nome_passageiro)
    
    # 5. Busca Web (OSINT)
    buscas = []
    try:
        with DDGS(timeout=10) as ddgs:
            pesquisa = f'"{nome}" assessor OR deputado OR parente OR sócio'
            resultados = list(ddgs.text(pesquisa, max_results=5))
            for r in resultados:
                buscas.append({"titulo": r.get("title"), "link": r.get("href"), "snippet": r.get("body")})
    except Exception as e:
        pass
        
    return {
        "socios": socios_info,
        "doacoes": doacoes_info,
        "assessores": assessores_info,
        "outros_parlamentares": outros_parls,
        "web": buscas
    }

def gerar_dossie_ia(nome, dados):
    """Utiliza GPT-4o-mini para consolidar o dossiê."""
    contexto = f"""
    Passageiro: {nome}
    
    Dados Internos:
    - Sociedades: {json.dumps(dados['socios'], ensure_ascii=False)}
    - Doações: {json.dumps(dados['doacoes'], ensure_ascii=False)}
    - Registros como Assessor Formal: {json.dumps(dados['assessores'], ensure_ascii=False)}
    - Deputados que já pagaram passagens para ele: {", ".join(dados['outros_parlamentares'])}
    
    Buscas Web:
    {json.dumps(dados['web'], ensure_ascii=False)}
    
    Aja como um auditor forense. Identifique o provável vínculo do passageiro com a esfera política.
    Ele parece ser um assessor compartilhado? Um doador frequente? Um familiar?
    Forneça um resumo curto (máximo 500 caracteres) e imparcial.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um auditor de inteligência parlamentar especializado em OSINT."},
                {"role": "user", "content": contexto}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Erro ao gerar dossiê."

def salvar_investigacao(nome, dossie, dados):
    """Salva ou atualiza a investigação no banco."""
    conn = conectar_bd()
    cursor = conn.cursor()
    
    data_hoje = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO passageiros_osint 
        (nome_passageiro, dossie, vinculos_socios, vinculos_doacoes, fontes_web, data_atualizacao, outros_parlamentares)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(nome_passageiro) DO UPDATE SET 
            dossie = excluded.dossie,
            vinculos_socios = excluded.vinculos_socios,
            vinculos_doacoes = excluded.vinculos_doacoes,
            fontes_web = excluded.fontes_web,
            data_atualizacao = excluded.data_atualizacao,
            outros_parlamentares = excluded.outros_parlamentares
    """, (
        nome, 
        dossie, 
        json.dumps(dados['socios']), 
        json.dumps(dados['doacoes']), 
        json.dumps(dados['web']), 
        data_hoje,
        json.dumps(dados['outros_parlamentares'])
    ))
    
    conn.commit()
    conn.close()

def main():
    print("\n" + "="*60)
    print("🚀 MOTOR DE INVESTIGAÇÃO OSINT - PASSAGEIROS FREQUENTES")
    print("="*60 + "\n")
    
    # Identificar alvos
    passageiros = identificar_passageiros_frequentes(limite=100)
    print(f"📈 Identificados {len(passageiros)} alvos prioritários para investigação.\n")
    
    # tqdm para mostrar o progresso
    for _, row in tqdm(passageiros.iterrows(), total=len(passageiros), desc="🔍 Investigando"):
        nome = row['txtPassageiro']
        
        try:
            # 1. Investigar (Interno + Web + Outros Parls)
            dados = investigar_nome(nome)
            
            # 2. Resumir com IA
            dossie = gerar_dossie_ia(nome, dados)
            
            # 3. Salvar
            salvar_investigacao(nome, dossie, dados)
            
            # Feedback de persistência
            tqdm.write(f"✅ Inteligência salva: {nome}")
            
            # Pequeno delay para fluidez
            time.sleep(0.5)
        except Exception as e:
            tqdm.write(f"\n⚠️ Erro ao processar {nome}: {e}")

    print("\n" + "="*60)
    print("✅ AUDITORIA CONCLUÍDA!")
    print(f"Dossiês salvos na tabela 'passageiros_osint' do tabelao.db.")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()

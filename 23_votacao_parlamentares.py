import sqlite3
import pandas as pd
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

# Configuração
load_dotenv()
DB_PATH = "tabelao.db"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("⚠️  ERRO: OPENAI_API_KEY não encontrada no .env")
    exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabela de Enriquecimento (Análise IA)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS votacoes_analise_enrichment (
        id_votacao TEXT PRIMARY KEY,
        tema_macro TEXT,
        resumo_leigo TEXT,
        pauta_governo TEXT,
        local_votacao TEXT,
        analise_ia_json TEXT,
        atualizado_em TEXT,
        FOREIGN KEY(id_votacao) REFERENCES votacoes_destaque(id_votacao)
    )
    """)
    conn.commit()
    conn.close()

def analyze_voting_with_ai(votacao_data):
    """
    Usa GPT para classificar e resumir a votação.
    """
    prompt = f"""
    Analise a seguinte votação da Câmara dos Deputados:
    
    Proposição: {votacao_data['proposicao']}
    Resumo Oficial: {votacao_data['resumo_camara']}
    Resumo da Mídia: {votacao_data['resumo_midia']}
    Posição da Mídia: {votacao_data['posicao_midia']}
    
    TAREFAS:
    1. Classifique em um TEMA MACRO (Ex: Saúde, Educação, Economia, Segurança, Meio Ambiente, Direitos Humanos, Infraestrutura, Política Externa, Administração Pública).
    2. Escreva um RESUMO LEIGO (máx 200 caracteres) explicando o impacto direto na vida do cidadão.
    3. Avalie se era PAUTA DO GOVERNO (Baseado no contexto, se favorece ou é de autoria do executivo). Opções: "Sim", "Não", "Indefinido".
    
    Retorne APENAS JSON:
    {{
        "tema": "...",
        "resumo_leigo": "...",
        "pauta_governo": "..."
    }}
    """
    
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um especialista legislativo que traduz o 'juridiquês' para o cidadão comum."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        content = json.loads(resp.choices[0].message.content)
        return content
    except Exception as e:
        print(f"   ⚠️  Erro na OpenAI: {e}")
        return None

def process_enrichment():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Buscar votações com mídia (Sim) que ainda não foram processadas (ou todas se for update)
    # Por enquanto, pegar todas com cobertura_midia=1
    print("🔍 Buscando votações com impacto na mídia...")
    
    df_votacoes = pd.read_sql_query("""
        SELECT * FROM votacoes_destaque 
        WHERE cobertura_midia = 1 
        AND id_votacao NOT IN (SELECT id_votacao FROM votacoes_analise_enrichment)
    """, conn)
    
    total = len(df_votacoes)
    print(f"🚀 {total} votações pendentes de análise de IA.")
    
    for idx, row in df_votacoes.iterrows():
        id_votacao = row['id_votacao']
        sigla_orgao = row['sigla_orgao']
        
        print(f"[{idx+1}/{total}] Processando: {id_votacao} - {row['proposicao'][:40]}...")
        
        # Determinar Local
        local = "Plenário" if sigla_orgao == "PLEN" else f"Comissão ({sigla_orgao})"
        
        # Double check se já foi processado (caso de concorrência ou restart rápido)
        cursor.execute("SELECT 1 FROM votacoes_analise_enrichment WHERE id_votacao = ?", (id_votacao,))
        if cursor.fetchone():
            print(f"⏩ Pulando {id_votacao} (já processado).")
            continue

        # Análise IA
        ai_result = analyze_voting_with_ai(row)
        
        if ai_result:
            cursor.execute("""
            INSERT INTO votacoes_analise_enrichment 
            (id_votacao, tema_macro, resumo_leigo, pauta_governo, local_votacao, analise_ia_json, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                id_votacao,
                ai_result.get('tema', 'Outros'),
                ai_result.get('resumo_leigo', 'Sem resumo.'),
                ai_result.get('pauta_governo', 'Indefinido'),
                local,
                json.dumps(ai_result),
                datetime.now().isoformat()
            ))
            conn.commit()
            print(f"   ✅ Salvo: {ai_result.get('tema')} | Gov: {ai_result.get('pauta_governo')}")
        else:
             print("   ❌ Falha na análise IA.")
             
        # Rate limit protection (cheap but safe)
        time.sleep(0.5)

    print("🏁 Enriquecimento concluído!")
    conn.close()

if __name__ == "__main__":
    process_enrichment()

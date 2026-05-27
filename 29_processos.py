import sqlite3
import pandas as pd
from duckduckgo_search import DDGS
import time
from tqdm import tqdm
import json
from openai import OpenAI
import random

# Configurações
DB_NAME = "tabelao.db"
LM_STUDIO_URL = "http://localhost:1234/v1"
client_ia = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")

def setup_db():
    conn = sqlite3.connect(DB_NAME, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS processos_judiciais (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cpf_deputado TEXT,
        nome_parlamentar TEXT,
        numero_processo TEXT,
        tribunal TEXT,
        assunto TEXT,
        status_visto TEXT,
        fonte_url TEXT,
        data_descoberta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(cpf_deputado, numero_processo)
    )
    """)
    try:
        cursor.execute("ALTER TABLE tabelao ADD COLUMN processos_vistos INTEGER DEFAULT 0")
    except:
        pass
    conn.commit()
    return conn

def mascarar_cpf(cpf):
    """Transforma 12345678901 em ***.456.789-** (Formato comum em Diários Oficiais)"""
    if not cpf or len(str(cpf)) < 11: return None
    s = str(cpf).zfill(11)
    return f"***.{s[3:6]}.{s[6:9]}-**"

def buscar_processos_resiliente(nome_civil, cpf_limpo):
    """Busca processos usando CPF e Nome com fallback para evitar erros de biblioteca."""
    cpf_mascarado = mascarar_cpf(cpf_limpo)
    
    # Tentativa 1: Busca via Nome + CPF (Mais preciso)
    queries = [
        f'"{nome_civil}" "{cpf_limpo}" processo judicial',
        f'"{nome_civil}" "{cpf_mascarado}" tribunal',
        f'"{cpf_limpo}" jusbrasil'
    ]
    
    results = []
    
    # Tenta usar DuckDuckGo (API alternativa se a principal falhar)
    try:
        with DDGS() as ddgs:
            for q in queries:
                try:
                    # Usando max_results menor para evitar blocks
                    ddgs_gen = ddgs.text(q, region='br-pt', safesearch='off', max_results=3)
                    for r in ddgs_gen:
                        results.append(f"Título: {r['title']}\nSnippet: {r['body']}\nURL: {r['href']}")
                    if results: break # Se achou algo, já economiza tempo
                except Exception as e:
                    print(f"Erro no DDG para query '{q}': {e}")
                    continue
    except:
        pass

    # Fallback: Se o DDG falhar totalmente, podemos tentar a biblioteca 'google' (se instalada)
    if not results:
        try:
            from googlesearch import search
            for q in queries:
                for url in search(q, num_results=3, lang='pt'):
                    results.append(f"URL encontrada via Google: {url}")
                if results: break
        except:
            pass

    return "\n---\n".join(results)

def extrair_dados_ia(snippets, nome_parlamentar):
    if not snippets or len(snippets) < 20: return []
    
    prompt = f"""Analise os resultados de busca sobre processos judiciais do deputado(a) {nome_parlamentar}.
Extraia apenas processos REAIS e CONCRETOS. 

Retorne uma LISTA JSON:
[
  {{
    "numero": "0000000-00.0000.0.00.0000",
    "tribunal": "Sigla (STF, TJSP, etc)",
    "assunto": "Resumo do crime/causa",
    "status": "Resumo (Arquivado, Ativo, etc)",
    "url": "Link da fonte"
  }}
]
Resultados:
{snippets}
"""
    try:
        response = client_ia.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "system", "content": "Responda APENAS com JSON estruturado. Seja criterioso."},
                {"role": "user", "content": prompt}
            ],
            timeout=180
        )
        content = response.choices[0].message.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        return json.loads(content)
    except:
        return []

def main():
    conn = setup_db()
    # Seleciona todos os deputados únicos que ainda não foram verificados
    query = "SELECT DISTINCT cpf, nomeCivil, nome FROM tabelao WHERE processos_vistos = 0"
    deputados = pd.read_sql_query(query, conn)
    
    if deputados.empty:
        print("✅ Tudo verificado!")
        return

    print(f"🔎 Iniciando varredura jurídica via CPF e Nome ({len(deputados)} parlamentares)...")
    
    for _, dep in tqdm(deputados.iterrows(), total=len(deputados)):
        cpf_limpo = str(dep['cpf']).replace('.', '').replace('-', '').zfill(11)
        nome_civil = dep['nomeCivil']
        
        # 1. Busca Multi-Fonte (CPF + Nome)
        texto_busca = buscar_processos_resiliente(nome_civil, cpf_limpo)
        
        # 2. IA processa
        processos = extrair_dados_ia(texto_busca, dep['nome'])
        
        if processos:
            for p in processos:
                try:
                    conn.execute("""
                    INSERT OR IGNORE INTO processos_judiciais 
                    (cpf_deputado, nome_parlamentar, numero_processo, tribunal, assunto, status_visto, fonte_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (cpf_limpo, dep['nome'], p.get('numero'), p.get('tribunal'), 
                          p.get('assunto'), p.get('status'), p.get('url')))
                except: pass
        
        conn.execute("UPDATE tabelao SET processos_vistos = 1 WHERE cpf = ?", (dep['cpf'],))
        conn.commit()
        
        # Delay mais agressivo e randômico para evitar bloqueio
        time.sleep(random.uniform(5, 12))

    conn.close()

if __name__ == "__main__":
    main()

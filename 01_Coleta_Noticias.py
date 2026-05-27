#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
10_E_COLETOR_BATCH_OPTIMIZED.py
Coletor massivo de notícias parlamentares (2023-2026).
Estratégia: Busca por lotes de 10 parlamentares via Serper.dev para economia de créditos.
Extração: Conteúdo integral via Trafilatura.
"""

import sqlite3
import pandas as pd
import json
import os
import time
import requests
import re
import trafilatura
from datetime import datetime
from tqdm import tqdm
from openai import OpenAI

class ColetorBatchSerper:
    def __init__(self):
        # Configurações
        self.api_key = os.getenv("SERPER_API_KEY", "")
        self.client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

        self.db_tabelao = os.path.join(os.path.dirname(__file__), "tabelao.db")
        self.db_noticias = os.path.join(os.path.dirname(__file__), "noticias_parlamentares.db")
        
        self.meses_nomes = {
            1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
            5: "maio", 6: "junho", 7: "julho", 8: "agosto",
            9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
        }
        
        self.preparar_bancos()

    def preparar_bancos(self):
        conn = sqlite3.connect(self.db_noticias)
        with conn:
            # Tabela de controle de lotes para não repetir buscas pagas
            conn.execute("""
            CREATE TABLE IF NOT EXISTS controle_lotes_serper (
                lote_id TEXT,
                mes_ano TEXT,
                status TEXT DEFAULT 'pendente',
                UNIQUE(lote_id, mes_ano)
            )
            """)
            # Garante que a coluna de texto completo existe na tabela principal
            try:
                conn.execute("ALTER TABLE noticias ADD COLUMN texto_completo TEXT;")
            except:
                pass
        conn.close()

    def obter_parlamentares(self):
        conn = sqlite3.connect(self.db_tabelao)
        # Pega todos os ativos na legislatura 57
        df = pd.read_sql_query("SELECT id, nome, sgPartido, sgUF FROM tabelao WHERE ultimoStatus_idLegislatura = 57 GROUP BY id", conn)
        conn.close()
        return df.to_dict('records')

    def gerar_meses(self):
        meses = []
        # 2023
        for m in range(1, 13): meses.append(f"{m:02d}/2023")
        # 2024
        for m in range(1, 13): meses.append(f"{m:02d}/2024")
        # 2025
        for m in range(1, 13): meses.append(f"{m:02d}/2025")
        # 2026 (Até Abril)
        for m in range(1, 5): meses.append(f"{m:02d}/2026")
        return meses

    def buscar_google_news(self, query):
        url = "https://google.serper.dev/news"
        payload = json.dumps({"q": query, "gl": "br", "hl": "pt-br", "num": 10})
        headers = {'X-API-KEY': self.api_key, 'Content-Type': 'application/json'}
        try:
            response = requests.post(url, headers=headers, data=payload, timeout=30)
            if response.status_code == 200:
                return response.json().get('news', [])
            elif response.status_code == 403:
                print(f"🚨 ERRO SERPER (403): Créditos esgotados ou Chave Inválida!")
                return "API_ERROR"
            elif response.status_code == 429:
                print(f"🚨 ERRO SERPER (429): Limite de velocidade atingido. Aguardando...")
                return "API_ERROR"
            else:
                print(f"⚠️ Erro Inesperado Serper: {response.status_code}")
                return "API_ERROR"
        except Exception as e:
            print(f"⚠️ Erro de Conexão: {e}")
            return "API_ERROR"

    def extrair_texto_completo(self, url):
        try:
            # Timeout explícito para evitar travamentos
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                # Evita que o extrator herde lixo de execuções passadas
                return trafilatura.extract(downloaded, include_comments=False, no_fallback=True)
            return None
        except Exception as e:
            # Silencioso para não poluir, mas evita crash
            return None

    def processar(self):
        parlamentares = self.obter_parlamentares()
        meses = self.gerar_meses()
        
        # Divide parlamentares em grupos de 10
        lotes_deputados = [parlamentares[i:i + 10] for i in range(0, len(parlamentares), 10)]
        
        conn = sqlite3.connect(self.db_noticias)
        
        # Alimenta a fila de lotes se estiver vazia
        cursor = conn.cursor()
        for idx, _ in enumerate(lotes_deputados):
            l_id = f"lote_{idx}"
            for m in meses:
                cursor.execute("INSERT OR IGNORE INTO controle_lotes_serper (lote_id, mes_ano) VALUES (?, ?)", (l_id, m))
        conn.commit()

        # Busca lotes pendentes
        df_fila = pd.read_sql_query("SELECT lote_id, mes_ano FROM controle_lotes_serper WHERE status = 'pendente'", conn)
        
        if df_fila.empty:
            print("✅ Todos os lotes foram processados!")
            return False

        print(f"🚀 Iniciando processamento de {len(df_fila)} lotes (40 meses x grupos de 10)...")
        
        with tqdm(df_fila.iterrows(), total=len(df_fila), desc="Progresso Batches") as pbar:
            for _, row in pbar:
                try:
                    l_idx = int(row['lote_id'].split('_')[1])
                    mes_ano = row['mes_ano']
                    lote = lotes_deputados[l_idx]
                    
                    # Monta query
                    nomes_query = " OR ".join([f'"{p["nome"]}"' for p in lote])
                    mes_num = int(mes_ano.split('/')[0])
                    ano_num = mes_ano.split('/')[1]
                    mes_extenso = self.meses_nomes[mes_num]
                    
                    query_busca = f'({nomes_query}) deputado federal notícias {mes_extenso} {ano_num}'
                    
                    # 💵 Buscando no Serper
                    results = self.buscar_google_news(query_busca)
                    
                    if results == "API_ERROR":
                        pbar.write("🛑 Erro na API do Serper. Interrompendo lote.")
                        break
                    
                    noticias_lote_count = 0
                    for res in results:
                        link = res.get('link')
                        if not link: continue
                        
                        titulo = res.get('title', '')
                        snippet = res.get('snippet', '')
                        veiculo = res.get('source', 'Google News')
                        data_publicacao = res.get('date', f'01/{mes_ano}')

                        texto_corpo = self.extrair_texto_completo(link) or snippet
                        
                        noticias_para_salvar = []
                        for p in lote:
                            if re.search(re.escape(p['nome']), titulo + " " + texto_corpo, re.IGNORECASE):
                                noticias_para_salvar.append((
                                    p['id'], p['nome'], titulo, veiculo + " (Serper Batch)",
                                    data_publicacao, link, snippet, texto_corpo, 
                                    "[]", "Neutro", 0.5, "Geral", "citado", "{}",
                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mes_ano, 1
                                ))
                        
                        if noticias_para_salvar:
                            try:
                                cursor = conn.cursor()
                                cursor.executemany("""
                                INSERT OR IGNORE INTO noticias (
                                    parlamentar_id, parlamentar_nome, titulo, veiculo, data, link, 
                                    resumo, texto_completo, palavras_chave, tom_da_noticia, 
                                    intensidade_sentimento, categoria, relevancia_personagem, 
                                    entidades, data_coleta, mes_ano, validado_llm
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, noticias_para_salvar)
                                conn.commit()
                                noticias_lote_count += len(noticias_para_salvar)
                                pbar.write(f"📰 [SALVO] {noticias_para_salvar[0][1]} - {titulo[:60]}...")
                            except Exception as e:
                                pbar.write(f"⚠️ Erro ao salvar notícia: {e}")

                    # Marca lote como concluído
                    conn.execute("UPDATE controle_lotes_serper SET status = 'concluido' WHERE lote_id = ? AND mes_ano = ?", 
                                (row['lote_id'], mes_ano))
                    conn.commit()
                    
                    time.sleep(0.5)
                except Exception as e:
                    pbar.write(f"❌ Erro crítico no lote {row['lote_id']}: {e}")
                    continue

        conn.close()
        return True

if __name__ == "__main__":
    app = ColetorBatchSerper()
    print("Iniciando Coletor Otimizado 2023-2026...")
    app.processar()

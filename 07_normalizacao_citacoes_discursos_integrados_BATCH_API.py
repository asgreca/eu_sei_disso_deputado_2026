#!/usr/bin/env python3
"""
07_normalizacao_citacoes_discursos_integrados_BATCH_API.py
Refatorado para escalar com a Batch API da OpenAI, garantindo baixo custo
e automatizando todo o processo infinitamente.
"""

import sqlite3
import pandas as pd
import json
import openai
import os
import time
import re
import unicodedata
from typing import List, Dict, Tuple, Optional, Any
from difflib import SequenceMatcher
from tqdm import tqdm
from dotenv import load_dotenv

class BatchNormalizacaoIntegrados:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            print("❌ OPENAI_API_KEY não configurada!")
            exit(1)
        self.client = openai.OpenAI(api_key=self.api_key)
        
        self.db_discursos = "discursos.db"
        self.db_tabelao = "tabelao.db"
        self.db_cache = "cache_normalizacao_citacoes_integrados.db"
        
        self.status_file = "pending_batch_07_status.json"
        self.request_file = "batch_07_requests.jsonl"
        self.dict_file = "batch_07_current_dict.json"
        
        self.parlamentares_oficiais = self.carregar_parlamentares_oficiais()
        self._setup_database()
        
        print("✅ Sistema BATCH de Normalização de Citações (Script 07) inicializado")
        print(f"📊 {len(self.parlamentares_oficiais)} parlamentares carregados do Tabelão")

    def carregar_parlamentares_oficiais(self) -> Dict[str, Dict]:
        conn = sqlite3.connect(self.db_tabelao)
        query = "SELECT DISTINCT nome, id FROM tabelao WHERE nome IS NOT NULL"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        parlamentares = {}
        for _, row in df.iterrows():
            parlamentares[row['nome']] = {'id': row['id'], 'nome_oficial': row['nome']}
        return parlamentares

    def _setup_database(self):
        conn = sqlite3.connect(self.db_cache)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cache_normalizacoes_citacoes (
                nome_citado TEXT UNIQUE,
                nome_normalizado TEXT,
                confianca REAL,
                id_parlamentar TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cache_discursos_processados (
                hash_linha TEXT PRIMARY KEY,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def _normalizar_nome_match(self, texto: str) -> str:
        if not texto:
            return ""
        texto = unicodedata.normalize("NFKD", str(texto))
        texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
        texto = texto.lower()
        texto = re.sub(r"[^a-z0-9\s]", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto

    def _tokens_nome_relevantes(self, texto: str) -> List[str]:
        stopwords = {"de", "da", "do", "das", "dos", "e"}
        tokens = []
        for token in self._normalizar_nome_match(texto).split():
            if len(token) < 3:
                continue
            if token in stopwords:
                continue
            tokens.append(token)
        return tokens

    def _score_coincidencia_nome(self, nome_citado: str, contexto: str) -> float:
        tokens_nome = self._tokens_nome_relevantes(nome_citado)
        tokens_contexto = set(self._tokens_nome_relevantes(contexto))
        if not tokens_nome or not tokens_contexto:
            return 0.0
        encontrados = sum(1 for token in tokens_nome if token in tokens_contexto)
        return encontrados / len(tokens_nome)

    def normalizar_nome_simples(self, nome_citado: str, contexto: str = "") -> Optional[Dict[str, Any]]:
        nome_upper = nome_citado.upper()
        # Busca exata
        for nome_oficial, dados in self.parlamentares_oficiais.items():
            if nome_oficial.upper() == nome_upper:
                return {"nome_normalizado": nome_oficial.upper(), "confianca": 1.0, "id_parlamentar": dados["id"]}

        # Busca por primeiro nome só vale se o contexto bater com pelo menos 80% do nome oficial.
        primeiro_nome = nome_upper.split()[0] if nome_upper.split() else nome_upper
        for nome_oficial, dados in self.parlamentares_oficiais.items():
            if nome_oficial.upper().startswith(primeiro_nome):
                score = self._score_coincidencia_nome(nome_oficial, contexto)
                if score >= 0.8:
                    return {"nome_normalizado": nome_oficial.upper(), "confianca": score, "id_parlamentar": dados["id"]}
        return None

    def encontrar_candidatos_similares(self, nome_citado: str) -> List[Tuple[str, str, float]]:
        candidatos = []
        nome_citado_lower = nome_citado.lower()
        for nome_oficial, dados in self.parlamentares_oficiais.items():
            sim = SequenceMatcher(None, nome_citado_lower, nome_oficial.lower()).ratio()
            if sim > 0.6: candidatos.append((dados['id'], nome_oficial, sim))
        candidatos.sort(key=lambda x: x[2], reverse=True)
        return candidatos[:5]

    def _obter_cache_normalizacao(self, nome_citado: str) -> Optional[Dict]:
        conn = sqlite3.connect(self.db_cache)
        cursor = conn.cursor()
        cursor.execute('SELECT nome_normalizado, confianca, id_parlamentar FROM cache_normalizacoes_citacoes WHERE nome_citado = ?', (nome_citado,))
        resultado = cursor.fetchone()
        conn.close()
        if resultado:
            return {'nome_normalizado': resultado[0], 'confianca': resultado[1], 'id_parlamentar': resultado[2]}
        return None

    def _salvar_cache_normalizacao(self, nome_citado: str, p_id: str, p_nome: str, confianca: float):
        conn = sqlite3.connect(self.db_cache)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO cache_normalizacoes_citacoes 
            (nome_citado, nome_normalizado, confianca, id_parlamentar)
            VALUES (?, ?, ?, ?)
        ''', (nome_citado, p_nome, confianca, p_id))
        conn.commit()
        conn.close()

    def _deve_usar_llm(self, candidatos: List[Tuple]) -> bool:
        if not candidatos: return False
        melhor = candidatos[0]
        if len(candidatos) == 1 and melhor[2] > 0.7: return False
        if len(candidatos) > 1 and melhor[2] > 0.8 and candidatos[1][2] < 0.7: return False
        if (len(candidatos) > 1 and melhor[2] > 0.75 and candidatos[1][2] > 0.7 and (melhor[2] - candidatos[1][2]) < 0.1): return True
        if melhor[2] < 0.6: return True
        return False

    def _extrair_contexto(self, sentenca_exata: str, nome_citado: str) -> str:
        if not sentenca_exata or not nome_citado: return ""
        posicao = sentenca_exata.lower().find(nome_citado.lower())
        if posicao == -1: return sentenca_exata[:200]
        inicio = max(0, posicao - 100)
        fim = min(len(sentenca_exata), posicao + len(nome_citado) + 100)
        return sentenca_exata[inicio:fim]

    # FLUXO PRINCIPAL BACH
    def carregar_tudo_e_montar_lote(self) -> bool:
        print("📥 Lendo discursos pendentes do SQLite (Verificando resoluções locais)...")
        conn_cache = sqlite3.connect(self.db_cache)
        hashes_processados = set(r[0] for r in conn_cache.execute('SELECT hash_linha FROM cache_discursos_processados').fetchall())
        conn_cache.close()

        conn = sqlite3.connect(self.db_discursos)
        # Tabela deve existir (criada pelo script 05)
        df = pd.read_sql_query("SELECT hash_linha, citacoes FROM discursos_integrados", conn)
        df_invalid = df[df['citacoes'] == '[]']
        df_valid = df[df['citacoes'] != '[]']
        
        # Filtra já processados
        df_pendente = df_valid[~df_valid['hash_linha'].isin(hashes_processados)]
        
        # Se os sem-citação não estiverem no cache, vamos marcar localmente só para tirar da frente.
        novos_vazios = df_invalid[~df_invalid['hash_linha'].isin(hashes_processados)]
        if not novos_vazios.empty:
            ccache = sqlite3.connect(self.db_cache)
            ccache.executemany("INSERT OR IGNORE INTO cache_discursos_processados (hash_linha) VALUES (?)", [(h,) for h in novos_vazios['hash_linha']])
            ccache.commit()
            ccache.close()

        if df_pendente.empty:
            print("✅ Todos os discursos já tiveram suas citações processadas (Normalização Completa)!")
            return False

        print(f"📊 {len(df_pendente)} discursos com citações detectadas e pendentes de checagem.")
        
        # Lote de LLM
        linhas_jsonl = []
        candidatos_para_salvar = {} # Salva { custom_id : [candidatos] }
        id_counter = 0
        
        total_atualizados_local = 0
        llm_na_fila = 0
        
        # Iterando
        for _, row in tqdm(df_pendente.iterrows(), total=len(df_pendente), desc="Avaliando Nomes Localmente"):
            hash_linha = row['hash_linha']
            citacoes_json = row['citacoes']
            
            try:
                if not citacoes_json or pd.isna(citacoes_json):
                    citacoes = []
                else:
                    citacoes = json.loads(citacoes_json)
                    if not isinstance(citacoes, list):
                        citacoes = []
            except Exception:
                citacoes = []

            precisa_de_llm = False
            citacoes_atualizadas = []
            mudou = False
            
            for cit in citacoes:
                nome_citado = cit.get('nome_citado', '')
                if not nome_citado:
                    citacoes_atualizadas.append(cit)
                    continue
                
                # Check cache
                cached = self._obter_cache_normalizacao(nome_citado)
                if cached:
                    # Substitui
                    novo_cit = cit.copy()
                    if cached['nome_normalizado'] != nome_citado:
                        mudou = True
                        novo_cit['nome_citado'] = cached['nome_normalizado']
                        novo_cit['nome_original'] = nome_citado
                        novo_cit['id_parlamentar'] = cached['id_parlamentar']
                        novo_cit['confianca_normalizacao'] = cached['confianca']
                    citacoes_atualizadas.append(novo_cit)
                    continue
                
                # Try simple normalization
                contexto = self._extrair_contexto(cit.get('sentenca_exata', ''), nome_citado)
                simples = self.normalizar_nome_simples(nome_citado, contexto)
                if simples:
                    self._salvar_cache_normalizacao(nome_citado, simples['id_parlamentar'], simples['nome_normalizado'], simples['confianca'])
                    novo_cit = cit.copy()
                    if simples['nome_normalizado'] != nome_citado:
                        mudou = True
                        novo_cit['nome_citado'] = simples['nome_normalizado']
                        novo_cit['nome_original'] = nome_citado
                        novo_cit['id_parlamentar'] = simples['id_parlamentar']
                        novo_cit['confianca_normalizacao'] = simples['confianca']
                    citacoes_atualizadas.append(novo_cit)
                    continue

                # Not simple, get candidates
                candidatos = self.encontrar_candidatos_similares(nome_citado)
                if not candidatos:
                    # Nem achou nada parecido, salva com o citado original
                    citacoes_atualizadas.append(cit)
                    continue

                if self._deve_usar_llm(candidatos):
                    # Flag row
                    precisa_de_llm = True
                    citacoes_atualizadas.append(cit) # Preserva momentaneamente

                    # Cria payload p/ Batch (usando nome_citado como chave primária é até melhor!)
                    # O script mandaria dezenas de LLMs iguais. Ao invés disso, chave única pelo NOME_CITADO
                    custom_id = f"LLMCIT_{hash(nome_citado)}"
                    if custom_id not in candidatos_para_salvar:
                        contexto = self._extrair_contexto(cit.get('sentenca_exata', ''), nome_citado)
                        cand_str = "\n".join([f"- {nome} (ID: {id_par}, Sim: {sim:.2f})" for id_par, nome, sim in candidatos])
                        prompt = f"""Você é um especialista em nomes parlamentares do Brasil.
NOME CITADO: "{nome_citado}"
CONTEXTO: {contexto}
CANDIDATOS:
{cand_str}
Retorne exclusivamente o NOME OFICIAL MAIÚSCULO do parlamentar correspondente da lista. Se inconclusivo, responda INCERTO."""

                        req = {
                            "custom_id": custom_id,
                            "method": "POST",
                            "url": "/v1/chat/completions",
                            "body": {
                                "model": "gpt-4o-mini",
                                "temperature": 0.0,
                                "messages": [{"role": "user", "content": prompt}],
                                "max_tokens": 50
                            }
                        }
                        linhas_jsonl.append(json.dumps(req))
                        candidatos_para_salvar[custom_id] = {
                            "nome_citado": nome_citado,
                            "candidatos": candidatos
                        }
                        llm_na_fila += 1
                else:
                    melhor = max(candidatos, key=lambda x: x[2])
                    if melhor[2] > 0.65:
                        self._salvar_cache_normalizacao(nome_citado, melhor[0], melhor[1].upper(), melhor[2])
                        novo_cit = cit.copy()
                        mudou = True
                        novo_cit['nome_citado'] = melhor[1].upper()
                        novo_cit['nome_original'] = nome_citado
                        novo_cit['id_parlamentar'] = melhor[0]
                        novo_cit['confianca_normalizacao'] = melhor[2]
                        citacoes_atualizadas.append(novo_cit)
                    else:
                        citacoes_atualizadas.append(cit)

            # Se TODAS daquela linha resolveram localmente, commit no DB agora
            if not precisa_de_llm:
                cursor_db = conn.cursor()
                if mudou:
                    cursor_db.execute("UPDATE discursos_integrados SET citacoes = ? WHERE hash_linha = ?", (json.dumps(citacoes_atualizadas, ensure_ascii=False), hash_linha))
                conn.commit()
                ccache = sqlite3.connect(self.db_cache)
                ccache.execute("INSERT OR IGNORE INTO cache_discursos_processados (hash_linha) VALUES (?)", (hash_linha,))
                ccache.commit()
                ccache.close()
                total_atualizados_local += 1

        conn.close()
        
        print(f"✔️ {total_atualizados_local} discursos resolvidos com Velocidade Ultra-Rápida via regras LOCAIS.")
        
        if llm_na_fila > 0:
            print(f"⚙️ Preparando submissão p/ OpenAI de {llm_na_fila} nomes ambíguos únicos...")
            with open(self.request_file, "w") as f:
                f.write("\n".join(linhas_jsonl))
            with open(self.dict_file, "w") as f:
                json.dump(candidatos_para_salvar, f)

            # Envios
            with open(self.request_file, "rb") as f:
                file_metadata = self.client.files.create(file=f, purpose="batch")
            input_file_id = file_metadata.id
            
            # Limite de 20.000 para JSONL no batch já seria suficiente
            batch = self.client.batches.create(
                input_file_id=input_file_id,
                endpoint="/v1/chat/completions",
                completion_window="24h"
            )
            print(f"✅ Lote aceito Pela OpenAI! ID: {batch.id}")
            with open(self.status_file, "w") as f:
                json.dump({"batch_id": batch.id}, f)
            return True # Tem monitoramento pela frente
        
        else:
            return True # Retorna "True" pois não gerou LLM, mas como loop atualizou local, se rodar de novo ele escoa a fila para zero

    def verificar_batch_pendente(self) -> bool:
        if not os.path.exists(self.status_file):
            return False
            
        with open(self.status_file, "r") as f:
            bstat = json.load(f)
        batch_id = bstat.get("batch_id")
        
        print(f"👀 Re-conectando ao Batch {batch_id}...")
        pbar = None
        
        while True:
            try:
                batch = self.client.batches.retrieve(batch_id)
                st = batch.status
                counts = batch.request_counts
                done = counts.completed if counts else 0
                failed = counts.failed if counts else 0
                total = counts.total if counts else 1
                
                if not pbar and total > 1 and st not in ['validating', 'failed']:
                    pbar = tqdm(total=total, desc="Processando Nomes GPT-4o-mini")
                    
                if pbar:
                    pbar.n = done
                    pbar.set_postfix_str(f"[Status: {st.upper()}] Falhas: {failed}")
                    pbar.refresh()
                    
                if st in ["completed", "failed", "cancelled", "expired"]:
                    if pbar: pbar.close()
                    break
                    
                time.sleep(30)
            except Exception as e:
                print(f"Erro no monitoramento: {e}")
                time.sleep(60)
        
        if batch.status == "completed":
            print(f"🎉 Resoluções Concluídas! Baixando respostas e embutindo no Cache...")
            out_file_id = batch.output_file_id
            response = self.client.files.content(out_file_id)
            res_linhas = response.text.strip().split('\n')
            
            with open(self.dict_file, "r") as f:
                candidatos_para_salvar = json.load(f)

            num_sucesso = 0
            for linha in res_linhas:
                if not linha: continue
                obj = json.loads(linha)
                cid = obj.get("custom_id")
                
                # Ler erro do runtime
                if obj.get("error"):
                    continue

                res = obj["response"]["body"]["choices"][0]["message"]["content"].strip()
                dic_original = candidatos_para_salvar.get(cid, {})
                nome_citado_original = dic_original.get("nome_citado")
                cands = dic_original.get("candidatos", [])
                
                if res == "INCERTO" or len(res) < 3:
                     self._salvar_cache_normalizacao(nome_citado_original, "0", nome_citado_original, 0.0) # Assume nulo
                     continue
                
                matched = False
                for id_par, nome_of, sim in cands:
                    if nome_of.upper() == res:
                        self._salvar_cache_normalizacao(nome_citado_original, id_par, nome_of.upper(), 0.9)
                        num_sucesso += 1
                        matched = True
                        break
                
                # Se a IA retornou um nome fora da lista, salva como ignorado (INCERTO) para quebrar o loop infinito
                if not matched:
                    self._salvar_cache_normalizacao(nome_citado_original, "0", nome_citado_original, 0.0)
            
            print(f"✅ Adicionados {num_sucesso} nomes complexos ao seu banco local CEREBRAL SQLite.")
            
        else:
            print(f"❌ O Batch parou em Status: {batch.status}")
            
        os.remove(self.status_file)
        if os.path.exists(self.request_file): os.remove(self.request_file)
        if os.path.exists(self.dict_file): os.remove(self.dict_file)
        print("🔄 Limpeza feita, partindo para acerto local...")
        return True

def main():
    print("==========================================================================")
    print(" 🛠 BATCH API | SCRIPT 07: Normalização de Citações Integradas")
    print("==========================================================================")
    app = BatchNormalizacaoIntegrados()
    
    while True:
        # Se tem um batch pendente rodando, monitora.
        if os.path.exists(app.status_file):
            app.verificar_batch_pendente()
            
        # Do contrário tenta construir lendo do banco  
        continua = app.carregar_tudo_e_montar_lote()
        if not continua:
            break
            
if __name__ == "__main__":
    main()

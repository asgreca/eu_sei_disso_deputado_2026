#!/usr/bin/env python3
"""
08_verificacao_contexto_ambiguo_BATCH_API.py
Versão refatorada e unificada usando a OpenAI Batch API (50% desconto).
"""

import sqlite3
import pandas as pd
import json
import openai
import os
import time
import hashlib
from typing import List, Dict, Tuple, Optional, Any
from tqdm import tqdm
from dotenv import load_dotenv

class BatchVerificadorAmbiguo:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            print("❌ OPENAI_API_KEY não configurada!")
            exit(1)
        self.client = openai.OpenAI(api_key=self.api_key)
        
        self.db_discursos = "discursos.db"
        self.db_tabelao = "tabelao.db"
        
        self.status_file = "pending_batch_08_status.json"
        self.request_file = "batch_08_requests.jsonl"
        self.dict_file = "batch_08_current_dict.json"
        
        self.nomes_ambiguos = {
            'EDUARDO BOLSONARO': {
                'parlamentar_id': None,
                'figura_publica': 'BOLSONARO',
            },
            'LULA DA FONTE': {
                'parlamentar_id': None,
                'figura_publica': 'LULA',
            }
        }
        
        self.inicializar_bancos()
        print("✅ Sistema BATCH de Contexto Ambíguo (Script 08) inicializado")

    def inicializar_bancos(self):
        conn_tabelao = sqlite3.connect(self.db_tabelao)
        for nome_par in self.nomes_ambiguos:
            res = conn_tabelao.execute("SELECT id FROM tabelao WHERE nome = ?", (nome_par,)).fetchone()
            if res:
                self.nomes_ambiguos[nome_par]['parlamentar_id'] = res[0]
        conn_tabelao.close()
        
        conn_discursos = sqlite3.connect(self.db_discursos)
        conn_discursos.execute("""
            CREATE TABLE IF NOT EXISTS cache_verificacao_contexto (
                hash_citacao TEXT PRIMARY KEY,
                nome_original TEXT,
                nome_normalizado_original TEXT,
                nome_normalizado_corrigido TEXT,
                contexto_analisado TEXT,
                decisao_llm TEXT,
                confianca_correcao REAL,
                data_verificacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                llm_used INTEGER DEFAULT 1
            )
        """)
        conn_discursos.commit()
        conn_discursos.close()

    def gerar_hash_citacao(self, hash_linha: str, nome_or: str, sentenca: str) -> str:
        texto = f"{hash_linha}_{nome_or}_{sentenca}"
        return hashlib.md5(texto.encode("utf-8")).hexdigest()

    def carregar_tudo_e_montar_lote(self) -> bool:
        print("📥 Lendo discursos pendentes do SQLite...")
        
        conn = sqlite3.connect(self.db_discursos)
        # Carregar hashes processados
        hashes_processados = set(r[0] for r in conn.execute('SELECT hash_citacao FROM cache_verificacao_contexto').fetchall())
        
        query = """
        SELECT hash_linha, citacoes
        FROM discursos_integrados_normalizado
        WHERE citacoes != '[]' AND citacoes IS NOT NULL
        """
        df = pd.read_sql_query(query, conn)
        
        # Filtro de ambiguos
        citacoes_ambiguas = []
        for _, row in tqdm(df.iterrows(), total=len(df), desc="Buscando Nomes Ambiguos"):
            cit_json = row['citacoes']
            try:
                citacoes = json.loads(cit_json)
                if not isinstance(citacoes, list): continue
            except:
                continue
                
            for citacao in citacoes:
                nome_norm = citacao.get('nome_citado', '')
                if nome_norm in self.nomes_ambiguos:
                    nome_or = citacao.get('nome_original', '')
                    sentenca = citacao.get('sentenca_exata', '')
                    h_cit = self.gerar_hash_citacao(row['hash_linha'], nome_or, sentenca)
                    if h_cit not in hashes_processados:
                        citacao['_metadata_hash_cit'] = h_cit
                        citacao['_metadata_hash_linha'] = row['hash_linha']
                        citacoes_ambiguas.append(citacao)
        
        if not citacoes_ambiguas:
            print("✅ Nenhuma citação ambígua pendente! Base 100% perfeita!")
            conn.close()
            return False

        print(f"📊 {len(citacoes_ambiguas)} citações ambíguas pendentes de Batch.")
        
        candidatos_para_salvar = {}
        linhas_jsonl = []
        
        for cit in citacoes_ambiguas:
            h_cit = cit['_metadata_hash_cit']
            nome_norm = cit.get('nome_citado', '')
            figura = self.nomes_ambiguos[nome_norm]['figura_publica']
            contexto = cit.get('contexto', '')
            sentenca = cit.get('sentenca_exata', '')
            
            # Formar request Batch (cada Custom ID é hash exclusivo)
            custom_id = f"LLMAMB_{h_cit}"
            
            prompt = f"""Analise o contexto abaixo e determine se a menção se refere ao PARLAMENTAR ou à FIGURA PÚBLICA.

PARLAMENTAR: {nome_norm} (Deputado Federal)
FIGURA PÚBLICA: {figura}

CONTEXTO COMPLETO:
{contexto}

SENTENÇA ESPECÍFICA:
{sentenca}

INSTRUÇÕES CRÍTICAS:
- REGRA PRINCIPAL: PADRÃO É SEMPRE FIGURA_PUBLICA (Presidente Lula ou Ex-Presidente Bolsonaro)
- SÓ CLASSIFIQUE COMO PARLAMENTAR QUANDO FOR MUITO CLARO QUE É O DEPUTADO ESPECÍFICO:
  * Se menciona explicitamente "Eduardo Bolsonaro" (nome completo) = PARLAMENTAR
  * Se menciona explicitamente "Lula da Fonte" (nome completo) = PARLAMENTAR
  * Se menciona CLARAMENTE "deputado Eduardo Bolsonaro" ou "deputado Lula da Fonte" = PARLAMENTAR
  * Se menciona atividades parlamentares específicas do deputado = PARLAMENTAR
- TODOS OS OUTROS CASOS = FIGURA_PUBLICA

Responda APENAS no formato JSON validavél:
{{"decisao": "PARLAMENTAR" ou "FIGURA_PUBLICA", "confianca": 0.9, "justificativa": "breve", "nome_correto": "NOME OFICIAL"}}
"""
            req = {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": "gpt-4o-mini",
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 150
                }
            }
            linhas_jsonl.append(json.dumps(req))
            candidatos_para_salvar[custom_id] = {
                "hash_cit": h_cit,
                "hash_linha": cit['_metadata_hash_linha'],
                "nome_original": cit.get('nome_original', ''),
                "nome_normalizado_original": nome_norm,
                "contexto": contexto[:500],
                "sentenca": sentenca
            }

        conn.close()

        print(f"⚙️ Preparando submissão p/ OpenAI de {len(linhas_jsonl)} cenários ambíguos...")
        with open(self.request_file, "w") as f:
             f.write("\n".join(linhas_jsonl))
        with open(self.dict_file, "w") as f:
             json.dump(candidatos_para_salvar, f)

        # Upload
        with open(self.request_file, "rb") as f:
             file_metadata = self.client.files.create(file=f, purpose="batch")
             
        batch = self.client.batches.create(
             input_file_id=file_metadata.id,
             endpoint="/v1/chat/completions",
             completion_window="24h"
        )
        print(f"✅ Lote aceito Pela OpenAI! ID: {batch.id}")
        with open(self.status_file, "w") as f:
             json.dump({"batch_id": batch.id}, f)
        return True

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
                    pbar = tqdm(total=total, desc="Processando Contextos GPT-4o-mini")
                    
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
            print(f"🎉 Contextos Analisados! Atualizando bancos locais...")
            out_file_id = batch.output_file_id
            response = self.client.files.content(out_file_id)
            res_linhas = response.text.strip().split('\n')
            
            with open(self.dict_file, "r") as f:
                candidatos_para_salvar = json.load(f)

            conn = sqlite3.connect(self.db_discursos)
            linhas_afetadas = set()
            dados_para_db = []

            for linha in res_linhas:
                if not linha: continue
                obj = json.loads(linha)
                cid = obj.get("custom_id")
                
                if obj.get("error"): continue
                
                # Resposta JSON
                res_str = obj["response"]["body"]["choices"][0]["message"]["content"].strip()
                try:
                    res = json.loads(res_str)
                except:
                    # Falhou json parsing
                     res = {"decisao": "FIGURA_PUBLICA", "confianca": 0.5, "justificativa": "Falha de JSON", "nome_correto": "?"}
                     
                dic_orig = candidatos_para_salvar.get(cid)
                if not dic_orig: continue
                
                # Se decidiu que é figura publica mas n sabe o nome, assume o fallback
                if res.get("nome_correto", "?") == "?":
                    res["nome_correto"] = self.nomes_ambiguos.get(dic_orig["nome_normalizado_original"], {}).get('figura_publica', "DESCONHECIDO")
                    
                # Fixar p/ parlamentar se for
                if res.get("decisao") == "PARLAMENTAR":
                     res["nome_correto"] = res.get("nome_correto").upper()
                     
                # 1. Preparar cache log
                dados_para_db.append((
                   dic_orig["hash_cit"],
                   dic_orig["nome_original"],
                   dic_orig["nome_normalizado_original"],
                   res["nome_correto"],
                   dic_orig["contexto"],
                   res.get("decisao", "ERRO"),
                   float(res.get("confianca", 0.0))
                ))
                
                # 2. Atualizar tabela integrado JSON (apenas se mudou)
                if res["nome_correto"].upper() != dic_orig["nome_normalizado_original"].upper():
                    linhas_afetadas.add((dic_orig["hash_linha"], dic_orig["nome_original"], dic_orig["sentenca"], res["nome_correto"]))
            
            # Executar DB Insercoes
            # 1. Salvar caches
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO cache_verificacao_contexto 
                (hash_citacao, nome_original, nome_normalizado_original, nome_normalizado_corrigido,
                 contexto_analisado, decisao_llm, confianca_correcao)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, dados_para_db)
            
            # 2. Corrigir normalização
            # Agrupuar por linha
            from collections import defaultdict
            upds = defaultdict(list)
            for hl, n_or, sent, nc in linhas_afetadas:
                upds[hl].append((n_or, sent, nc))
                
            num_correcoes = 0
            for hl, correcoes in upds.items():
                cur2 = conn.cursor()
                res = cur2.execute("SELECT citacoes FROM discursos_integrados_normalizado WHERE hash_linha=?", (hl,)).fetchone()
                if not res: continue
                
                try: cit_atual = json.loads(res[0])
                except: continue
                
                mudou = False
                for c in cit_atual:
                    for (n_or, sent, nc) in correcoes:
                         if c.get("nome_original") == n_or and c.get("sentenca_exata") == sent:
                             c["nome_citado"] = nc
                             mudou = True
                
                if mudou:
                    cur2.execute("UPDATE discursos_integrados_normalizado SET citacoes=? WHERE hash_linha=?", (json.dumps(cit_atual, ensure_ascii=False), hl))
                    num_correcoes += 1
                    
            conn.commit()
            conn.close()
            print(f"✅ Feitas {num_correcoes} Correções em {len(dados_para_db)} Discursos Ambiguos no SQLite Principal!")
            
        else:
            print(f"❌ O Batch parou em Status: {batch.status}")
            
        os.remove(self.status_file)
        if os.path.exists(self.request_file): os.remove(self.request_file)
        if os.path.exists(self.dict_file): os.remove(self.dict_file)
        
        print("🔄 Limpeza feita, partindo para acerto final...")
        return True

def main():
    print("==========================================================================")
    print(" 🛠 BATCH API | SCRIPT 08: Verificador Contexto Ambíguo")
    print("==========================================================================")
    app = BatchVerificadorAmbiguo()
    
    while True:
        if os.path.exists(app.status_file):
            app.verificar_batch_pendente()
            
        continua = app.carregar_tudo_e_montar_lote()
        if not continua:
            break
            
if __name__ == "__main__":
    main()

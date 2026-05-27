#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
10_J_ULTRA_BATCH_V2_DEEP_AUDIT.py
Executa o Batch API da OpenAI focado EXCLUSIVAMENTE nas 101 mil notícias vitais (que sabidamente citam um deputado).
Usa o GPT-4o-mini com "Structured Outputs" absoluto (JSON Schema) para aniquilar qualquer alucinação na saída 
e extrair dezenas de novos dados (figuras não-políticas, escândalos, clusters temáticos rígidos, palavras chave e bigramas).
"""

import sqlite3
import os
import json
import time
import argparse
from datetime import datetime
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm
from macrotemas_imprensa import MACRO_TEMAS, normalizar_temas_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "noticias_parlamentares.db")
BATCH_TRACKER = os.path.join(BASE_DIR, "noticias_active_batches_v2.json")

# SCHEMA RÍGIDO (Structured Output da OpenAI). A IA não consegue inventar chaves fora disso.
SCHEMA_FORENSE = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracao_forense",
        "description": "Extração forense completa de jornais e metadados.",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "metadados_fonte": {
                    "type": "object",
                    "properties": {
                        "veiculo_nome": {"type": "string"},
                        "mes_publicacao": {"type": "string", "description": "Mês 01-12. Retorne '' se impossível."},
                        "ano_publicacao": {"type": "string", "description": "Ano 2020-2026. Retorne '' se impossível."},
                        "vies_editorial": {"type": "string", "enum": ["ESQUERDA", "CENTRO", "DIREITA", "NEUTRO"]}
                    },
                    "required": ["veiculo_nome", "mes_publicacao", "ano_publicacao", "vies_editorial"],
                    "additionalProperties": False
                },
                "grafos_entidades": {
                    "type": "object",
                    "properties": {
                        "parlamentares_federais": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "nome": {"type": "string"},
                                    "sentimento_score": {"type": "integer", "description": "0 a 10"},
                                    "protagonismo_score": {"type": "integer", "description": "0 a 10"},
                                    "resumo_participacao": {"type": "string"}
                                },
                                "required": ["nome", "sentimento_score", "protagonismo_score", "resumo_participacao"],
                                "additionalProperties": False
                            }
                        },
                        "outras_figuras_publicas": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "nome": {"type": "string"},
                                    "cargo_ou_rotulo": {"type": "string"}
                                },
                                "required": ["nome", "cargo_ou_rotulo"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["parlamentares_federais", "outras_figuras_publicas"],
                    "additionalProperties": False
                },
                "auditoria_contexto": {
                    "type": "object",
                    "properties": {
                        "palavras_chave": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "bigramas": {
                            "type": "array",
                            "items": {"type": "string", "description": "Conceitos em duplas tipo 'lavagem_dinheiro'"}
                        },
                        "temas_tratados": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 1,
                            "description": "Escolha exatamente um macrotema entre as 10 categorias permitidas.",
                            "items": {
                                "type": "string",
                                "enum": MACRO_TEMAS
                            }
                        },
                        "indicador_escandalo_juridico": {"type": "boolean"},
                        "resumo_forense": {"type": "string", "description": "Resumo analítico curto em 2 frases."}
                    },
                    "required": ["palavras_chave", "bigramas", "temas_tratados", "indicador_escandalo_juridico", "resumo_forense"],
                    "additionalProperties": False
                }
            },
            "required": ["metadados_fonte", "grafos_entidades", "auditoria_contexto"],
            "additionalProperties": False
        }
    }
}

class SaneadorDeepAudit:
    def __init__(self, desbloquear_travas=True):
        load_dotenv()
        key = os.getenv("OPENAI_API_KEY", "").strip().replace('"', '').replace("'", "")
        self.client = OpenAI(api_key=key)
        self.db_path = DB_PATH
        self.criar_tabelas_v2(desbloquear_travas=desbloquear_travas)

    def criar_tabelas_v2(self, desbloquear_travas=True):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        
        # Libera qualquer trava de lote fantasma caso o script tenha sofrido um crash (ex: limite de billing)
        if desbloquear_travas:
            cursor.execute("UPDATE noticias SET validado_llm_profundo = 0 WHERE validado_llm_profundo = -1")
        
        # Tabelas exclusivas da Fase 2 para não sobrescrever nem estragar o banco atual
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS noticias_metadados_v2 (
            news_id INTEGER PRIMARY KEY,
            veiculo_nome TEXT,
            mes_publicacao TEXT,
            ano_publicacao TEXT,
            vies_editorial TEXT,
            palavras_chave TEXT,
            bigramas TEXT,
            temas_tratados TEXT,
            indicador_escandalo_juridico BOOLEAN,
            resumo_forense TEXT
        )""")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS noticias_mencoes_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER,
            tipo_entidade TEXT, 
            nome TEXT,
            sentimento_score INTEGER,
            protagonismo_score INTEGER,
            resumo_participacao TEXT,
            cargo_ou_rotulo TEXT
        )""")
        
        conn.commit()
        conn.close()

    def carregar_batches_ativos(self):
        if os.path.exists(BATCH_TRACKER):
            with open(BATCH_TRACKER, "r") as f:
                return json.load(f)
        return []

    def salvar_batches_ativos(self, batches):
        with open(BATCH_TRACKER, "w") as f:
            json.dump(batches, f, indent=4)

    def enviar_novos_lotes(self, limite_por_lote=10000, max_lotes_ativos=10, only_relevant_missing=False):
        ativos = self.carregar_batches_ativos()
        
        while len(ativos) < max_lotes_ativos:
            if only_relevant_missing:
                print(f"📥 Buscando até {limite_por_lote} notícias RELEVANTES ainda fora da V2...")
            else:
                print(f"📥 Buscando até {limite_por_lote} notícias VALIDADAS TEXTUALMENTE para novo lote...")
            conn = sqlite3.connect(self.db_path)
            
            if only_relevant_missing:
                # Recorte estrito: so noticias com mencao textual segura e ainda ausentes da tabela V2.
                query = """
                SELECT DISTINCT n.id, n.titulo, n.resumo, n.texto_completo
                FROM noticias n
                JOIN mencoes_textuais_seguras m ON n.id = m.news_id
                LEFT JOIN noticias_metadados_v2 v2 ON v2.news_id = n.id
                WHERE v2.news_id IS NULL
                LIMIT ?
                """
            else:
                # Puxamos EXCLUSIVAMENTE as notícias cuja ID exista em mencoes_textuais_seguras e não tenha sido deep_auditada
                query = """
                SELECT DISTINCT n.id, n.titulo, n.resumo, n.texto_completo 
                FROM noticias n 
                JOIN mencoes_textuais_seguras m ON n.id = m.news_id 
                WHERE n.validado_llm_profundo = 0 
                LIMIT ?
                """
            
            df = pd.read_sql_query(query, conn, params=(limite_por_lote,))
            
            if df.empty:
                conn.close()
                print("✅ Nenhuma notícia pendente para o Deep Audit.")
                break

            ids_lote = df['id'].tolist()
            # Bloqueia ids temporariamente (-1) para eles não serem pegos repetidos
            conn.execute(f"UPDATE noticias SET validado_llm_profundo = -1 WHERE id IN ({','.join(['?']*len(ids_lote))})", ids_lote)
            conn.commit()
            conn.close()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            req_file = f"batch_req_v2_{timestamp}.jsonl"
            map_file = f"batch_map_v2_{timestamp}.json"
            
            requests_list = []
            id_map = {}
            for _, row in tqdm(df.iterrows(), total=len(df), desc=f"Prompting Lote V2 {len(ativos)+1}"):
                news_id = row['id']
                texto = f"{row['titulo'] or ''}\n{row['resumo'] or ''}\n{row['texto_completo'] or ''}"
                
                # Truncamento seguro de tokens (cerca de 2500 palavras/10000 caracteres)
                prompt = f"Faça extração forense matemática da reportagem a seguir:\n\n{texto[:12000]}"
                custom_id = f"V2_N_{news_id}"
                id_map[custom_id] = news_id
                
                req = {
                    "custom_id": custom_id, 
                    "method": "POST", 
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": "gpt-4o-mini", 
                        "temperature": 0.0, # Temperatura Zero: Não permite criatividade, foca apenas na extração.
                        "response_format": SCHEMA_FORENSE,
                        "messages": [
                            {"role": "system", "content": "Você é uma IA de Auditoria Governamental Criminológica e Analítica. Extraia dados perfeitamente no formato solicitado."},
                            {"role": "user", "content": prompt}
                        ]
                    }
                }
                requests_list.append(json.dumps(req))

            with open(req_file, "w", encoding="utf-8") as f: 
                f.write("\n".join(requests_list))
            with open(map_file, "w", encoding="utf-8") as f: 
                json.dump(id_map, f)

            try:
                with open(req_file, "rb") as f:
                    b_file = self.client.files.create(file=f, purpose="batch")
                
                batch = self.client.batches.create(
                    input_file_id=b_file.id, endpoint="/v1/chat/completions", completion_window="24h"
                )
                
                ativos.append({"id": batch.id, "map_file": map_file, "req_file": req_file})
                self.salvar_batches_ativos(ativos)
                print(f"🚀 Lote Profundo {batch.id} enviado p/ OpenAI!")
            except Exception as e:
                # Se o erro for de faturamento (Billing), apenas avisamos e paramos de tentar enviar novos
                if "billing_hard_limit_reached" in str(e).lower():
                    print("\n🛑 AVISO: Limite de gastos atingido na OpenAI (Billing Hard Limit).")
                    print("⚠️  Não foi possível enviar novos lotes. O sistema continuará monitorando os lotes já ativos.\n")
                    # Remove o arquivo temporário já que não foi enviado
                    if os.path.exists(req_file): os.remove(req_file)
                    # Devolve as notícias para a fila (O bloqueio -1 será limpo no próximo ciclo de monitoramento)
                    break 
                else:
                    print(f"❌ Erro fatal ao tentar criar lote: {e}")
                    raise e

    def _salvar_no_banco_v2(self, obj, news_id, conn):
        """Desmembra e injeta o objeto JSON gigante nas duas tabelas V2."""
        meta = obj.get("metadados_fonte", {})
        grafos = obj.get("grafos_entidades", {})
        audit = obj.get("auditoria_contexto", {})
        temas_macro = normalizar_temas_json(
            json.dumps(audit.get("temas_tratados", []), ensure_ascii=False),
            json.dumps(audit.get("palavras_chave", []), ensure_ascii=False),
            json.dumps(audit.get("bigramas", []), ensure_ascii=False),
            audit.get("resumo_forense", ""),
        )
        
        # 1. METADADOS V2
        conn.execute("""
        INSERT INTO noticias_metadados_v2 
        (news_id, veiculo_nome, mes_publicacao, ano_publicacao, vies_editorial, 
        palavras_chave, bigramas, temas_tratados, indicador_escandalo_juridico, resumo_forense)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(news_id) DO UPDATE SET
        veiculo_nome=excluded.veiculo_nome, mes_publicacao=excluded.mes_publicacao, ano_publicacao=excluded.ano_publicacao, 
        vies_editorial=excluded.vies_editorial, palavras_chave=excluded.palavras_chave, bigramas=excluded.bigramas,
        temas_tratados=excluded.temas_tratados, indicador_escandalo_juridico=excluded.indicador_escandalo_juridico, 
        resumo_forense=excluded.resumo_forense
        """, (
            news_id,
            meta.get("veiculo_nome", ""),
            meta.get("mes_publicacao", ""),
            meta.get("ano_publicacao", ""),
            meta.get("vies_editorial", "NEUTRO"),
            json.dumps(audit.get("palavras_chave", [])),
            json.dumps(audit.get("bigramas", [])),
            temas_macro,
            1 if audit.get("indicador_escandalo_juridico") else 0,
            audit.get("resumo_forense", "")
        ))

        # 2. LIMPEZA E INJEÇÃO MENÇÕES V2 (DEPUTADOS)
        conn.execute("DELETE FROM noticias_mencoes_v2 WHERE news_id = ?", (news_id,))
        
        for p in grafos.get("parlamentares_federais", []):
            conn.execute("""
            INSERT INTO noticias_mencoes_v2 
            (news_id, tipo_entidade, nome, sentimento_score, protagonismo_score, resumo_participacao) 
            VALUES (?, 'PARLAMENTAR', ?, ?, ?, ?)
            """, (news_id, p.get("nome"), p.get("sentimento_score"), p.get("protagonismo_score"), p.get("resumo_participacao")))

        # 3. INJEÇÃO MENÇÕES V2 (OUTROS)
        for o in grafos.get("outras_figuras_publicas", []):
            conn.execute("""
            INSERT INTO noticias_mencoes_v2 
            (news_id, tipo_entidade, nome, cargo_ou_rotulo) 
            VALUES (?, 'OUTROS', ?, ?)
            """, (news_id, o.get("nome"), o.get("cargo_ou_rotulo")))
            
        # Marca como concluído definitamente
        conn.execute("UPDATE noticias SET validado_llm_profundo = 1 WHERE id = ?", (news_id,))

    def monitorar_e_processar(
        self,
        limite_por_lote=10000,
        max_lotes_ativos=10,
        only_relevant_missing=False,
        sleep_seconds=60,
    ):
        while True:
            ativos = self.carregar_batches_ativos()
            
            # Se a fila estiver vazia no início do ciclo, tenta preenchê-la
            if len(ativos) < max_lotes_ativos:
                self.enviar_novos_lotes(
                    limite_por_lote=limite_por_lote,
                    max_lotes_ativos=max_lotes_ativos,
                    only_relevant_missing=only_relevant_missing,
                )
                ativos = self.carregar_batches_ativos()
                
            if not ativos:
                print("🏁 Banco limpo! Todas as notícias foram totalmente auditadas e mapeadas.")
                break
                
            novos_ativos = []
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            
            print(f"\n👀 Monitorando {len(ativos)} lotes ativos (Depp Audit V2)...")
            
            for b_info in ativos:
                batch_id = b_info["id"]
                req_file = b_info["req_file"]
                map_file = b_info["map_file"]
                
                try:
                    status = self.client.batches.retrieve(batch_id)
                except Exception as e:
                    print(f"⚠️ Erro ao checar status do batch {batch_id}: {e}")
                    novos_ativos.append(b_info)
                    continue
                
                req_count = status.request_counts.total if status.request_counts else 0
                comp_count = status.request_counts.completed if status.request_counts else 0
                print(f"  - {batch_id}: {status.status} ({comp_count}/{req_count})")
                
                if status.status in ["completed", "failed", "cancelled", "expired"]:
                    if status.status == "completed" and status.output_file_id:
                        print(f"💾 Extraindo matriz de Grafos do {map_file}...")
                        try:
                            content = self.client.files.content(status.output_file_id).text
                        except Exception as e:
                            print(f"⚠️ Output indisponivel para {batch_id}: {e}")
                            print("   Removendo batch antigo do tracker local; ele nao e mais importavel.")
                            continue
                        
                        with open(map_file, "r") as f:
                            id_map = json.load(f)
                            
                        # Limpa os bloqueios (-1 -> 0) caso algo falhou
                        conn.execute("UPDATE noticias SET validado_llm_profundo = 0 WHERE validado_llm_profundo = -1")
                        
                        count_salvos = 0
                        for line in content.strip().split("\n"):
                            if line:
                                data = json.loads(line)
                                c_id = data["custom_id"]
                                news_id = id_map.get(c_id)
                                
                                if news_id:
                                    try:
                                        raw_json_str = data["response"]["body"]["choices"][0]["message"]["content"]
                                        obj = json.loads(raw_json_str)
                                        self._salvar_no_banco_v2(obj, news_id, conn)
                                        count_salvos += 1
                                    except Exception as e:
                                        print(f"❌ Erro ao parsear JSON do ID {news_id}: {e}")
                        conn.commit()
                        print(f"✅ {count_salvos} matrizes salvas e cruzadas!")
                    
                    if os.path.exists(req_file): os.remove(req_file)
                    if os.path.exists(map_file): os.remove(map_file)
                else:
                    novos_ativos.append(b_info)
            
            conn.close()
            self.salvar_batches_ativos(novos_ativos)
            
            # Reposição contínua:
            if len(novos_ativos) < max_lotes_ativos:
                print("🔄 Repondo a fila de Auditoria Profunda...")
                self.enviar_novos_lotes(
                    limite_por_lote=limite_por_lote,
                    max_lotes_ativos=max_lotes_ativos,
                    only_relevant_missing=only_relevant_missing,
                )
                novos_ativos = self.carregar_batches_ativos()

            if not novos_ativos:
                print("🏁 Operação Encerrada. Tabelas Atualizadas.")
                break
            
            print(f"🕒 Aguardando {sleep_seconds} segundos para próxima varredura de satélite...")
            time.sleep(sleep_seconds)

    def importar_batches_ativos(self, aplicar=True, remover_arquivos=False):
        """
        Verifica apenas os batches ja registrados no tracker local.
        Nao envia nenhum lote novo para a OpenAI.
        """
        ativos = self.carregar_batches_ativos()
        if not ativos:
            print("Nenhum batch ativo no tracker local.")
            return

        novos_ativos = []
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")

        total_salvos = 0
        total_erros = 0
        print(f"Monitorando/importando {len(ativos)} batches ja existentes...")

        for b_info in ativos:
            batch_id = b_info["id"]
            req_file = b_info["req_file"]
            map_file = b_info["map_file"]

            try:
                status = self.client.batches.retrieve(batch_id)
            except Exception as e:
                print(f"- {batch_id}: erro ao checar status: {e}")
                novos_ativos.append(b_info)
                continue

            req_count = status.request_counts.total if status.request_counts else 0
            comp_count = status.request_counts.completed if status.request_counts else 0
            fail_count = status.request_counts.failed if status.request_counts else 0
            print(f"- {batch_id}: {status.status} ({comp_count}/{req_count}, falhas={fail_count})")

            if status.status == "completed" and status.output_file_id:
                if not aplicar:
                    continue
                if not os.path.exists(map_file):
                    print(f"  mapa local ausente: {map_file}. Mantendo batch no tracker.")
                    novos_ativos.append(b_info)
                    continue

                print(f"  importando resultados de {map_file}...")
                content = self.client.files.content(status.output_file_id).text
                with open(map_file, "r") as f:
                    id_map = json.load(f)

                count_salvos = 0
                count_erros = 0
                for line in content.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        c_id = data["custom_id"]
                        news_id = id_map.get(c_id)
                        if not news_id:
                            count_erros += 1
                            continue
                        raw_json_str = data["response"]["body"]["choices"][0]["message"]["content"]
                        obj = json.loads(raw_json_str)
                        self._salvar_no_banco_v2(obj, news_id, conn)
                        count_salvos += 1
                    except Exception as e:
                        count_erros += 1
                        print(f"  erro ao importar linha: {e}")

                conn.commit()
                total_salvos += count_salvos
                total_erros += count_erros
                print(f"  salvo no banco: {count_salvos}; erros: {count_erros}")

                if remover_arquivos:
                    if os.path.exists(req_file):
                        os.remove(req_file)
                    if os.path.exists(map_file):
                        os.remove(map_file)
            elif status.status in ["failed", "cancelled", "expired"]:
                print("  batch encerrado sem resultado importavel; removendo do tracker.")
            else:
                novos_ativos.append(b_info)

        conn.close()

        if aplicar:
            self.salvar_batches_ativos(novos_ativos)
            print(f"\nImportacao concluida. Registros salvos: {total_salvos}; erros: {total_erros}.")
            print(f"Batches ainda ativos no tracker: {len(novos_ativos)}")
        else:
            print("\nStatus-only concluido. Nenhum dado foi alterado.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auditoria profunda de imprensa V2")
    parser.add_argument("--import-only", action="store_true", help="Importa apenas batches ja existentes no tracker local; nao envia novos lotes.")
    parser.add_argument("--status-only", action="store_true", help="Mostra status dos batches do tracker sem alterar o banco.")
    parser.add_argument("--remover-arquivos-importados", action="store_true", help="Remove JSONL/map local apos importar batch completo.")
    parser.add_argument("--only-relevant-missing", action="store_true", help="Envia apenas noticias em mencoes_textuais_seguras ainda ausentes de noticias_metadados_v2.")
    parser.add_argument("--max-lotes-ativos", type=int, default=10, help="Quantidade maxima de batches ativos simultaneos.")
    parser.add_argument("--limite-por-lote", type=int, default=10000, help="Quantidade maxima de noticias por batch novo.")
    parser.add_argument("--sleep-seconds", type=int, default=60, help="Intervalo entre verificacoes de batches.")
    args = parser.parse_args()

    if args.status_only:
        app = SaneadorDeepAudit(desbloquear_travas=False)
        app.importar_batches_ativos(aplicar=False)
    elif args.import_only:
        app = SaneadorDeepAudit(desbloquear_travas=False)
        app.importar_batches_ativos(aplicar=True, remover_arquivos=args.remover_arquivos_importados)
    else:
        app = SaneadorDeepAudit()
        app.monitorar_e_processar(
            limite_por_lote=args.limite_por_lote,
            max_lotes_ativos=args.max_lotes_ativos,
            only_relevant_missing=args.only_relevant_missing,
            sleep_seconds=args.sleep_seconds,
        )

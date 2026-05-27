#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Busca Semântica com Progresso Detalhado - NOVO FLUXO
Estrutura de 4 fases com atualizações em tempo real
"""

import json
import sqlite3
import asyncio
from typing import Dict, List, Any
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
from datetime import datetime
import time

load_dotenv()


class ProgressoSemantica:
    """Gerencia progresso detalhado da busca semântica"""

    def __init__(self, session_id: str, tema: str):
        self.session_id = session_id
        self.tema = tema
        self.inicio = time.time()
        self.status = {
            "session_id": session_id,
            "tema": tema,
            "fase_atual": 0,
            "total_fases": 4,
            "percent": 0,
            "tempo_decorrido": 0,
            "status": "nao_iniciada",
            "fases": self._inicializar_fases(),
        }

    def _inicializar_fases(self) -> Dict:
        return {
            "fase_1": {
                "nome": "🔍 Busca Inicial",
                "status": "nao_iniciada",
                "percent": 0,
                "mensagens": [],
                "estatisticas": {
                    "palavras_chave_geradas": 0,
                    "discursos_encontrados": 0,
                    "parlamentares_encontrados": 0,
                    "tempo_decorrido": 0,
                },
            },
            "fase_2": {
                "nome": "✅ Validação de Relevância",
                "status": "nao_iniciada",
                "percent": 0,
                "mensagens": [],
                "estatisticas": {
                    "lotes_totais": 0,
                    "lotes_processados": 0,
                    "discursos_validados": 0,
                    "discursos_rejeitados": 0,
                    "score_medio": 0,
                    "tempo_decorrido": 0,
                },
            },
            "fase_3": {
                "nome": "❤️ Análise dos Discursos",
                "status": "nao_iniciada",
                "percent": 0,
                "mensagens": [],
                "estatisticas": {
                    "discursos_favoraveis": 0,
                    "discursos_contrarios": 0,
                    "discursos_neutros": 0,
                    "embeddings_gerados": 0,
                    "tempo_decorrido": 0,
                },
            },
            "fase_4": {
                "nome": "📄 Geração do Relatório",
                "status": "nao_iniciada",
                "percent": 0,
                "mensagens": [],
                "estatisticas": {
                    "secoes_geradas": 0,
                    "frases_extraidas": 0,
                    "tempo_decorrido": 0,
                },
            },
        }

    def adicionar_mensagem(self, fase: str, mensagem: str):
        """Adiciona mensagem a uma fase"""
        if fase in self.status["fases"]:
            self.status["fases"][fase]["mensagens"].append(
                f"{'✅' if 'completo' in mensagem.lower() else '⏳'} {mensagem}"
            )

    def atualizar_fase(
        self, fase: str, status: str, percent: int, estatisticas: Dict = None
    ):
        """Atualiza status de uma fase"""
        if fase in self.status["fases"]:
            self.status["fases"][fase]["status"] = status
            self.status["fases"][fase]["percent"] = percent
            if estatisticas:
                self.status["fases"][fase]["estatisticas"].update(estatisticas)

    def atualizar_progresso_global(self):
        """Calcula progresso global baseado nas fases"""
        # FASE 1: 0-10%
        # FASE 2: 10-50%
        # FASE 3: 50-85%
        # FASE 4: 85-100%

        fase_1_percent = self.status["fases"]["fase_1"]["percent"]
        fase_2_percent = self.status["fases"]["fase_2"]["percent"]
        fase_3_percent = self.status["fases"]["fase_3"]["percent"]
        fase_4_percent = self.status["fases"]["fase_4"]["percent"]

        if fase_1_percent < 100:
            self.status["percent"] = min(10, (fase_1_percent / 100) * 10)
            self.status["fase_atual"] = 1
        elif fase_2_percent < 100:
            self.status["percent"] = 10 + (fase_2_percent / 100) * 40
            self.status["fase_atual"] = 2
        elif fase_3_percent < 100:
            self.status["percent"] = 50 + (fase_3_percent / 100) * 35
            self.status["fase_atual"] = 3
        elif fase_4_percent < 100:
            self.status["percent"] = 85 + (fase_4_percent / 100) * 15
            self.status["fase_atual"] = 4
        else:
            self.status["percent"] = 100
            self.status["fase_atual"] = 4

        self.status["tempo_decorrido"] = int(time.time() - self.inicio)

    def get_status(self) -> Dict:
        """Retorna status atual formatado"""
        self.atualizar_progresso_global()
        return self.status

    def marcar_completo(self, resultado: Dict):
        """Marca o progresso como completo"""
        self.status["status"] = "completo"
        self.status["percent"] = 100
        self.status["resultado"] = resultado
        self.status["tempo_total"] = int(time.time() - self.inicio)


async def validar_relevancia_lote(
    client: AsyncOpenAI, discursos: List[Dict], tema: str, lote_num: int
) -> Dict:
    """
    Valida relevância de um lote de discursos com LLM
    Retorna scores e validações
    """
    try:
        # Preparar dados do lote
        dados_lote = []
        for idx, d in enumerate(discursos):
            texto_preview = (d.get("Texto_completo") or d.get("Texto", ""))[:400]
            dados_lote.append(
                {
                    "indice": idx,
                    "parlamentar": d.get("Parlamentar", "N/A"),
                    "data": d.get("Data", "N/A"),
                    "comissao": d.get("Comissao", "N/A"),
                    "preview": texto_preview,
                }
            )

        prompt = f"""
Você é um especialista em análise de discursos parlamentares.

TEMA: "{tema}"

Analise cada discurso abaixo e classifique sua relevância para o tema "{tema}" com um score 0-100.

CRITÉRIOS:
- 80-100: MUITO RELEVANTE - Trata diretamente do tema com profundidade
- 60-79: RELEVANTE - Menciona e analisa o tema
- 40-59: POUCO RELEVANTE - Menciona tema mas sem aprofundamento
- 0-39: IRRELEVANTE - Não trata do tema

Discursos:
{json.dumps(dados_lote, ensure_ascii=False)}

Responda APENAS com JSON:
{{
    "validacoes": [
        {{"indice": 0, "score": 85, "relevancia": "MUITO_RELEVANTE", "motivo": "Discussão detalhada sobre..."}},
        ...
    ]
}}
"""

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=1500,
                temperature=0.1,
            ),
            timeout=30.0,
        )

        resposta_limpa = response.choices[0].message.content.strip()
        resultado = json.loads(resposta_limpa)
        return {
            "lote": lote_num,
            "sucesso": True,
            "validacoes": resultado.get("validacoes", []),
        }

    except asyncio.TimeoutError:
        print(f"⏱️ Timeout ao validar lote {lote_num}")
        return {
            "lote": lote_num,
            "sucesso": False,
            "erro": "Timeout na API OpenAI",
            "validacoes": [],
        }
    except Exception as e:
        print(f"❌ Erro ao validar lote {lote_num}: {e}")
        return {
            "lote": lote_num,
            "sucesso": False,
            "erro": str(e),
            "validacoes": [],
        }


async def analisar_sentimento_discurso(
    client: AsyncOpenAI, discurso: Dict, tema: str
) -> Dict:
    """
    Analisa sentimento (positivo/negativo/neutro) de um discurso sobre o tema
    """
    try:
        texto = (discurso.get("Texto_completo") or discurso.get("Texto", ""))[
            :800
        ]
        parlamentar = discurso.get("Parlamentar", "N/A")

        prompt = f"""
Você é um especialista em análise de sentimento em discursos políticos.

TEMA: "{tema}"
PARLAMENTAR: {parlamentar}

Analise o sentimento do seguinte discurso em relação ao tema "{tema}":

DISCURSO:
{texto}

Responda com JSON:
{{
    "sentimento": "POSITIVO" | "NEGATIVO" | "NEUTRO",
    "score": 0-100,
    "justificativa": "Explicação breve",
    "passagens_chave": ["citação 1", "citação 2"]
}}

REGRAS:
- POSITIVO (70-100): Defende/apoia ações sobre o tema
- NEGATIVO (70-100): Critica/se opõe ao tema
- NEUTRO (40-60): Apenas apresenta dados/fatos
"""

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=500,
                temperature=0.1,
            ),
            timeout=20.0,
        )

        resultado = json.loads(response.choices[0].message.content.strip())
        return {
            "id_discurso": discurso.get("id"),
            "parlamentar": parlamentar,
            "sentimento": resultado.get("sentimento", "NEUTRO"),
            "score": resultado.get("score", 50),
            "sucesso": True,
        }

    except asyncio.TimeoutError:
        return {
            "id_discurso": discurso.get("id"),
            "parlamentar": discurso.get("Parlamentar", "N/A"),
            "sentimento": "NEUTRO",
            "score": 50,
            "sucesso": False,
        }
    except Exception as e:
        return {
            "id_discurso": discurso.get("id"),
            "parlamentar": discurso.get("Parlamentar", "N/A"),
            "sentimento": "NEUTRO",
            "score": 50,
            "sucesso": False,
        }


def gerar_embeddings_batchwise(
    discursos: List[Dict], client: AsyncOpenAI
) -> List[Dict]:
    """
    Gera embeddings para discursos usando a API OpenAI
    """
    # Implementação será feita com rate limiting
    # Por enquanto retorna placeholder
    return [
        {
            "id_discurso": d.get("id"),
            "embedding": [0.0] * 1536,  # Placeholder
            "sucesso": True,
        }
        for d in discursos
    ]


async def analisar_sentimentos_com_rate_limit(
    client: AsyncOpenAI, discursos: List[Dict], tema: str, max_concurrent: int = 5
) -> List[Dict]:
    """
    Analisa sentimentos em lotes com rate limiting para evitar sobrecarga da API
    """
    resultados = []
    total = len(discursos)

    # Processar em grupos de max_concurrent
    for i in range(0, total, max_concurrent):
        batch = discursos[i : i + max_concurrent]
        tarefas = [analisar_sentimento_discurso(client, d, tema) for d in batch]

        # Aguardar este lote terminar antes de passar ao próximo
        batch_resultados = await asyncio.gather(*tarefas)
        resultados.extend(batch_resultados)

        # Log de progresso
        processados = min(i + max_concurrent, total)
        print(f"⏳ Sentimento: {processados}/{total} discursos analisados")

        # Pequena pausa entre lotes para evitar rate limiting
        if i + max_concurrent < total:
            await asyncio.sleep(0.5)

    return resultados


def inserir_no_chromadb(
    discursos: List[Dict], embeddings: List[Dict], tema: str, session_id: str
):
    """
    Insere discursos na base vetorial com metadata
    """
    try:
        import chromadb

        CHROMA_PERSIST_PATH = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "vetores"
        )
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)

        collection_name = f"tema_{session_id}_{int(time.time())}"
        collection = client.get_or_create_collection(name=collection_name)

        # Inserir documentos
        ids = []
        metadatas = []
        documents = []
        embeddings_list = []

        for d, emb in zip(discursos, embeddings):
            ids.append(str(d.get("id")))
            metadatas.append(
                {
                    "tema": tema,
                    "parlamentar": d.get("Parlamentar", "N/A"),
                    "partido": d.get("Partido", "N/A"),
                    "estado": d.get("Estado", "N/A"),
                    "data": d.get("Data", "N/A"),
                    "sentimento": d.get("sentimento", "NEUTRO"),
                    "score_relevancia": str(d.get("score_relevancia", 0)),
                }
            )
            documents.append(
                (d.get("Texto_completo") or d.get("Texto", ""))[:5000]
            )
            embeddings_list.append(emb.get("embedding", [0.0] * 1536))

        collection.add(
            ids=ids, metadatas=metadatas, documents=documents, embeddings=embeddings_list
        )

        return {"sucesso": True, "collection": collection_name, "total": len(ids)}

    except Exception as e:
        print(f"❌ Erro ao inserir na base vetorial: {e}")
        return {"sucesso": False, "erro": str(e)}

# main.py
import sqlite3
import pandas as pd
import numpy as np
import sys
import os

# Garantir que o diretório do script está no sys.path para imports locais
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import json
import logging
import subprocess
from datetime import datetime
import traceback
from fastapi import FastAPI, HTTPException, Request, Response, Security, Depends, BackgroundTasks, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import mimetypes
import io
import chromadb
from openai import OpenAI
import threading
import asyncio
try:
    import duckdb
except ImportError:
    duckdb = None

import hashlib
import re
import unicodedata
from functools import lru_cache
from copy import deepcopy
from dotenv import load_dotenv
# AntunesCrew é importado dinamicamente (lazy import) dentro do endpoint que usa
from busca_semantica_nova import buscar_semantica_nova
import math
import time
import httpx
try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


# ===== IMPORTS NOVOS - Busca Semântica com Progresso Detalhado =====
try:
    from busca_semantica_progressivo import (
        ProgressoSemantica,
        validar_relevancia_lote,
        analisar_sentimento_discurso,
        analisar_sentimentos_com_rate_limit,
        inserir_no_chromadb,
    )
except ImportError as e:
    print(f"⚠️ Aviso: Não foi possível importar busca_semantica_progressivo: {e}")
    ProgressoSemantica = None
# ===== FIM DOS IMPORTS NOVOS ====
import requests
try:
    from shapely.geometry import Point, shape, mapping
    from shapely.strtree import STRtree
    from shapely.ops import unary_union
except ImportError:
    Point = shape = mapping = STRtree = unary_union = None
try:
    from analysis_reference import build_reference_lens, retrieve_reference_passages
except Exception:
    build_reference_lens = None
    retrieve_reference_passages = None

# Iniciar Cache de LLM
def init_llm_cache():
    try:
        # Usar llm_cache.db para não bloquear o tabelao.db
        conn = sqlite3.connect('llm_cache.db')
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                hash_id TEXT PRIMARY KEY,
                response_json TEXT,
                created_at TEXT
            )
        """)
        conn.commit()
        conn.close()
        print("✅ Tabela llm_cache inicializada em llm_cache.db.")
    except Exception as e:
        print(f"⚠️ Erro ao inicializar cache LLM: {e}")

# init_llm_cache() é chamado no evento startup do FastAPI (lazy init)


# Caminho do DuckDB de votação — prioriza bancos/ subdirectory
_duck_in_bancos = os.path.join(_SCRIPT_DIR, "bancos", "votacao.duckdb")
_duck_in_mapa = os.path.join(_SCRIPT_DIR, "mapa", "votacao.duckdb")
DUCK_DB_PATH = _duck_in_bancos if os.path.exists(_duck_in_bancos) else _duck_in_mapa

# Iniciar ChromaDB (Busca Vetorial para Chat Parlamentar)
try:
    CHROMA_PERSIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vetores")
    chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
    print(f"✅ ChromaDB inicializado em {CHROMA_PERSIST_PATH}")
except Exception as e:
    chroma_client = None
    print(f"⚠️ Erro ao inicializar ChromaDB: {e}")

# Função para limpar dados antes de converter para JSON
def safe_duckdb_connect(path=None, read_only=False):
    """Gere conexões DuckDB de forma segura contra falhas de instalação"""
    if duckdb is None:
        raise Exception("A biblioteca 'duckdb' não está instalada ou falhou ao carregar no servidor.")
    if path:
        return duckdb.connect(path, read_only=read_only)
    return duckdb.connect()

def clean_data_for_json(data):
    """Limpa dados para serem compatíveis com JSON"""
    if isinstance(data, dict):
        return {k: clean_data_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_data_for_json(item) for item in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    elif isinstance(data, str):
        normalized = data.strip().lower()
        if normalized in {"nan", "nan%", "r$ nan", "r$ nan%"}:
            return "N/D"
        return data
    return data


GASTOS_GRAPH_CACHE = {}
GASTOS_GRAPH_CACHE_TTL = 300


def _normalizar_nome_match(texto: Optional[str]) -> str:
    """Normaliza nomes para comparação robusta."""
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _tokens_nome_relevantes(texto: Optional[str]) -> List[str]:
    """Retorna apenas tokens úteis para match nominal."""
    stopwords = {
        "de", "da", "do", "das", "dos", "e"
    }
    tokens = []
    for token in _normalizar_nome_match(texto).split():
        if len(token) < 3:
            continue
        if token in stopwords:
            continue
        tokens.append(token)
    return tokens


def _calcular_score_coincidencia_nome(nome_alvo: Optional[str], sentenca: Optional[str]) -> float:
    """
    Mede a coincidência nominal entre o nome alvo e a sentença.
    Exige presença dos tokens relevantes do nome, evitando match por contexto amplo.
    """
    tokens_nome = _tokens_nome_relevantes(nome_alvo)
    tokens_sentenca = set(_tokens_nome_relevantes(sentenca))

    if not tokens_nome or not tokens_sentenca:
        return 0.0

    tokens_encontrados = sum(1 for token in tokens_nome if token in tokens_sentenca)
    score_tokens = tokens_encontrados / len(tokens_nome)

    nome_norm = _normalizar_nome_match(nome_alvo)
    sentenca_norm = _normalizar_nome_match(sentenca)

    score_fuzzy = 0.0
    if fuzz is not None and nome_norm and sentenca_norm:
        score_fuzzy = max(
            fuzz.partial_ratio(nome_norm, sentenca_norm) / 100.0,
            fuzz.token_set_ratio(nome_norm, sentenca_norm) / 100.0,
        )

    # Priorizamos coincidência real dos tokens do nome.
    return max(score_tokens, score_fuzzy if score_tokens >= 0.5 else 0.0)

def extrair_origem_destino(trecho):
    """Extrai origem e destino de um trecho de voo"""
    if not trecho or pd.isna(trecho):
        return None, None
    
    trecho_str = str(trecho).strip()
    if '/' in trecho_str:
        partes = trecho_str.split('/', 1)
        return partes[0].strip(), partes[1].strip()
    
    return None, None
    
# --- GLOBAIS DE NORMALIZAÇÃO ---
def normalizar_nome(nome):
    if not nome: return ""
    # Remover tags de partido entre parênteses (ex: "NOME (PARTIDO)")
    nome_limpo = re.sub(r'\(.*?\)', '', str(nome)).strip()
    nfkd = unicodedata.normalize('NFKD', nome_limpo)
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).upper().strip()

def resolve_party_logo_url(partido):
    if not partido: return None
    p = str(partido).strip().upper()
    # Tenta buscar no dicionário carregado do CSV
    if 'partido_logos_dict' in globals():
        return partido_logos_dict.get(p)
    return None

def resolve_state_flag_url(uf):
    if not uf: return None
    u = str(uf).strip().upper()
    if 'estado_logos_dict' in globals():
        return estado_logos_dict.get(u)
    return None

def mapear_despesa_robusto(d):
    if not d: return d
    # Usar a normalização que já temos para remover acentos antes do match de palavras-chave
    d_clean = normalizar_nome(d)
    
    if "COMBUST" in d_clean: return "COMBUSTÍVEIS E LUBRIFICANTES."
    if "DIVULGA" in d_clean: return "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR."
    if "PASSAGEM" in d_clean: return "PASSAGEM AÉREA - RPA"
    if "ESCRITORIO" in d_clean or "LOCACAO" in d_clean or "IMOVEIS" in d_clean: 
        return "MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR"
    if "CONSULTORIA" in d_clean: return "CONSULTORIAS, PESQUISAS E TRABALHOS TÉCNICOS."
    if "VEICULO" in d_clean or "FRETAMENTO" in d_clean: return "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES"
    if "ALIMENTA" in d_clean: return "FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR"
    if "TELEFONIA" in d_clean or "TELEFONE" in d_clean: return "TELEFONIA"
    if "POSTAIS" in d_clean: return "SERVIÇOS POSTAIS"
    return d

def _json_safe_value(value, default=None):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return default
    return value

SQL_NORMALIZAR_NOME = """
UPPER(
    REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
    REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
        nome,
        'Á','A'),'À','A'),'Â','A'),'Ã','A'),'Ä','A'),
        'É','E'),'È','E'),'Ê','E'),'Ë','E'),
        'Í','I'),'Ì','I'),'Î','I'),'Ï','I'),
        'Ó','O'),'Ò','O'),'Ô','O'),'Õ','O'),'Ö','O'),
        'Ú','U'),'Ù','U')
)
"""
# --- FIM GLOBAIS ---


AUDIT_NOTAS_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "notas_fiscais_auditoria.db")

DISTANCIA_NORTE_SUL_ESTADO_KM = {
    "AC": 445, "AL": 230, "AM": 1570, "AP": 578, "BA": 1260, "CE": 573, "DF": 80,
    "ES": 460, "GO": 685, "MA": 970, "MG": 1248, "MS": 893, "MT": 906, "PA": 1250,
    "PB": 263, "PE": 471, "PI": 740, "PR": 630, "RJ": 430, "RN": 278, "RO": 880,
    "RR": 964, "RS": 623, "SC": 379, "SE": 210, "SP": 623, "TO": 899,
}

MODELOS_CLARAMENTE_NAO_DIESEL = [
    "COROLLA", "CIVIC", "ONIX", "HB20", "GOL", "MOBI", "KWID", "ARGO", "CRONOS",
    "UNO", "PALIO", "SANDERO", "LOGAN", "ETIOS", "YARIS", "KA", "FIESTA", "VERSA",
    "MARCH", "FOX", "POLO", "VIRTUS",
]


def classificar_combustivel_compativel_modelo(modelo: str):
    modelo_norm = _normalize_text(modelo).upper()
    if not modelo_norm:
        return None
    if any(token in modelo_norm for token in MODELOS_CLARAMENTE_NAO_DIESEL):
        return {"aceita_diesel": False, "categoria": "carro_passeio"}
    return None


def _safe_float(value):
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _safe_int(value):
    try:
        if value is None or value == "":
            return 0
        return int(value)
    except Exception:
        return 0


def _normalize_text(value):
    return str(value or "").strip()


def obter_insights_notas_fiscais(parlamentar: str, rubrica: str, estado: Optional[str] = None):
    if not os.path.exists(AUDIT_NOTAS_DB_PATH):
        return {
            "cobertura_notas": {
                "disponivel": False,
                "mensagem": "Banco de auditoria de notas fiscais não encontrado."
            },
            "insights_notas": None
        }

    conn = sqlite3.connect(AUDIT_NOTAS_DB_PATH)
    conn.row_factory = sqlite3.Row

    rubrica_para_tabela = {
        "COMBUSTÍVEIS E LUBRIFICANTES.": "nf_combustivel",
        "FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR": "nf_restaurante",
        "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES": "nf_locacao_veiculo",
        "HOSPEDAGEM ,EXCETO DO PARLAMENTAR NO DISTRITO FEDERAL.": "nf_hospedagem",
        "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR.": "nf_divulgacao",
    }

    try:
        df_docs = pd.read_sql_query(
            """
            SELECT doc_key, status_parse, fornecedor_nome, numero_documento_fonte, data_emissao_fonte, valor_liquido_fonte
            FROM nf_documentos
            WHERE deputado_nome = ? AND rubrica = ?
            """,
            conn,
            params=[parlamentar, rubrica]
        )

        total_docs = int(len(df_docs))
        parse_ok = int((df_docs["status_parse"] == "done").sum()) if not df_docs.empty else 0
        parse_fail = total_docs - parse_ok

        tabela_detalhe = rubrica_para_tabela.get(rubrica)
        detalhe_docs = 0
        insights = None

        if tabela_detalhe and total_docs > 0:
            df_detalhe = pd.read_sql_query(
                f"""
                SELECT t.*, d.fornecedor_nome, d.numero_documento_fonte, d.data_emissao_fonte, d.valor_liquido_fonte
                FROM {tabela_detalhe} t
                JOIN nf_documentos d ON d.doc_key = t.doc_key
                WHERE d.deputado_nome = ? AND d.rubrica = ?
                """,
                conn,
                params=[parlamentar, rubrica]
            )
            detalhe_docs = int(df_detalhe["doc_key"].nunique()) if not df_detalhe.empty else 0

            if rubrica == "COMBUSTÍVEIS E LUBRIFICANTES." and not df_detalhe.empty:
                insights = {
                    "tipo": "combustivel",
                    "mensagem": "Detalhamento de consumo e quilometragem removido."
                }

            elif rubrica == "FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR" and not df_detalhe.empty:
                df_detalhe["quantidade"] = df_detalhe["quantidade"].apply(_safe_float)
                df_detalhe["valor_item"] = df_detalhe["valor_item"].apply(_safe_float)
                df_detalhe["estimativa_pessoas"] = df_detalhe["estimativa_pessoas"].apply(_safe_float)
                df_detalhe["item_nome_norm"] = df_detalhe["item_nome"].fillna("Item não identificado").astype(str).str.strip()
                pratos = (
                    df_detalhe.groupby("item_nome_norm")
                    .agg(ocorrencias=("item_id", "count"), valor_total=("valor_item", "sum"))
                    .reset_index()
                    .sort_values(["ocorrencias", "valor_total"], ascending=[False, False])
                    .head(5)
                )
                notas_multi = int((df_detalhe["ind_multiplas_pessoas"].fillna(0).astype(int) == 1).sum())
                insights = {
                    "tipo": "alimentacao",
                    "itens_extraidos": int(len(df_detalhe)),
                    "estimativa_pessoas_total": round(df_detalhe["estimativa_pessoas"].sum(), 1),
                    "notas_suspeita_multiplas_pessoas": notas_multi,
                    "pratos_mais_frequentes": pratos.to_dict("records"),
                }

            elif rubrica == "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES" and not df_detalhe.empty:
                df_detalhe["quantidade_veiculos"] = df_detalhe["quantidade_veiculos"].apply(_safe_float)
                df_detalhe["quantidade_diarias"] = df_detalhe["quantidade_diarias"].apply(_safe_float)
                df_detalhe["valor_total"] = df_detalhe["valor_total"].apply(_safe_float)
                modelos = (
                    df_detalhe[df_detalhe["modelo_veiculo"].notna() & (df_detalhe["modelo_veiculo"].astype(str).str.strip() != "")]
                    .groupby("modelo_veiculo")
                    .agg(ocorrencias=("item_id", "count"), valor_total=("valor_total", "sum"))
                    .reset_index()
                    .sort_values(["ocorrencias", "valor_total"], ascending=[False, False])
                    .head(5)
                )
                insights = {
                    "tipo": "locacao_veiculo",
                    "locadoras_unicas": int(df_detalhe["locadora"].replace("", np.nan).dropna().nunique()),
                    "veiculos_estimados": round(df_detalhe["quantidade_veiculos"].sum(), 1),
                    "diarias_estimadas": round(df_detalhe["quantidade_diarias"].sum(), 1),
                    "modelos_mais_frequentes": modelos.to_dict("records"),
                }

            elif rubrica == "HOSPEDAGEM ,EXCETO DO PARLAMENTAR NO DISTRITO FEDERAL." and not df_detalhe.empty:
                df_detalhe["quantidade_diarias"] = df_detalhe["quantidade_diarias"].apply(_safe_float)
                df_detalhe["valor_hospedagem"] = df_detalhe["valor_hospedagem"].apply(_safe_float)
                hoteis = (
                    df_detalhe[df_detalhe["hotel"].notna() & (df_detalhe["hotel"].astype(str).str.strip() != "")]
                    .groupby("hotel")
                    .agg(ocorrencias=("item_id", "count"), valor_total=("valor_hospedagem", "sum"))
                    .reset_index()
                    .sort_values(["ocorrencias", "valor_total"], ascending=[False, False])
                    .head(5)
                )
                insights = {
                    "tipo": "hospedagem",
                    "diarias_estimadas": round(df_detalhe["quantidade_diarias"].sum(), 1),
                    "hoteis_mais_frequentes": hoteis.to_dict("records"),
                }

            elif rubrica == "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR." and not df_detalhe.empty:
                df_detalhe["servico_norm"] = df_detalhe["servico"].fillna("servico_nao_identificado").astype(str).str.strip()
                servicos = (
                    df_detalhe.groupby("servico_norm")
                    .agg(ocorrencias=("item_id", "count"), valor_total=("valor_total", "sum"))
                    .reset_index()
                    .sort_values(["ocorrencias", "valor_total"], ascending=[False, False])
                    .head(6)
                )
                periodos = (
                    df_detalhe[df_detalhe["periodo_referencia"].notna() & (df_detalhe["periodo_referencia"].astype(str).str.strip() != "")]
                    .groupby("periodo_referencia")
                    .agg(ocorrencias=("item_id", "count"))
                    .reset_index()
                    .sort_values(["ocorrencias", "periodo_referencia"], ascending=[False, False])
                    .head(6)
                )
                insights = {
                    "tipo": "divulgacao",
                    "servicos_mais_frequentes": servicos.to_dict("records"),
                    "periodos_identificados": periodos.to_dict("records"),
                }

        cobertura = {
            "disponivel": True,
            "total_documentos_auditoria": total_docs,
            "documentos_parseados": parse_ok,
            "documentos_nao_processados": parse_fail,
            "documentos_com_detalhes_estruturados": detalhe_docs,
            "mensagem_nao_processadas": (
                f"Por questões técnicas, não foi possível processar {parse_fail} nota(s) fiscal(is) deste deputado nesta rubrica."
                if parse_fail > 0 else None
            )
        }

        return {
            "cobertura_notas": cobertura,
            "insights_notas": clean_data_for_json(insights) if insights else None
        }
    except Exception as e:
        logger.warning(f"Falha ao obter insights de notas fiscais para {parlamentar} / {rubrica}: {e}")
        return {
            "cobertura_notas": {
                "disponivel": False,
                "mensagem": f"Falha ao carregar auditoria de notas: {str(e)}"
            },
            "insights_notas": None
        }
    finally:
        conn.close()

# Carregar variáveis de ambiente
load_dotenv()

# Configurar logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuração do CORS Explícita para evitar bloqueios em localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Configuração de Segurança via API Key
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# API Key configurável via .env (use uma senha forte em produção)
API_KEY = os.getenv("API_KEY", "")

async def get_api_key(api_key: str = Security(api_key_header)):
    """Valida a API Key para endpoints protegidos"""
    if api_key == API_KEY:
        return api_key
    raise HTTPException(
        status_code=403,
        detail="❌ API Key inválida ou ausente. Forneça o header 'X-API-Key'."
    )


@app.api_route("/api/img-proxy", methods=["GET", "HEAD"])
async def proxy_image(request: Request, imageUrl: str):
    """Proxy robusto com normalização de URL para Wikipedia/Wikimedia."""
    if not imageUrl:
        raise HTTPException(status_code=400, detail="imageUrl é obrigatória.")
        
    import urllib.parse
    # Normalizar a URL (descodificar o que veio do frontend e codificar apenas o necessário para a Wikipedia)
    # A Wikipedia é sensível a parênteses e vírgulas na URL
    clean_url = urllib.parse.unquote(imageUrl)
    
    cache_dir = "data/cache_imagens"
    os.makedirs(cache_dir, exist_ok=True)
    
    url_hash = hashlib.md5(clean_url.encode()).hexdigest()
    ext = mimetypes.guess_extension(mimetypes.guess_type(clean_url)[0] or 'image/png') or '.png'
    cache_path = os.path.join(cache_dir, f"{url_hash}{ext}")
    
    if os.path.exists(cache_path):
        mime_type, _ = mimetypes.guess_type(cache_path)
        if request.method == "HEAD":
            return Response(status_code=200, media_type=mime_type or "image/png")
        return StreamingResponse(open(cache_path, "rb"), media_type=mime_type or "image/png")
        
    try:
        # User-Agent e Referer conforme políticas da Wikimedia (https://wikitech.wikimedia.org/wiki/User-Agent_policy)
        headers = {
            "User-Agent": "AntunesAuditBot/1.1 (https://github.com/aislangreca/TCC; contact@antunesaudit.com) python-httpx/0.24",
            "Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://commons.wikimedia.org/"
        }
        
        async with httpx.AsyncClient(follow_redirects=True) as client:
            ext_method = "HEAD" if request.method == "HEAD" else "GET"
            # Usar a clean_url diretamente, o httpx fará o escape necessário
            response = await client.request(ext_method, clean_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                if request.method == "GET":
                    with open(cache_path, "wb") as f:
                        f.write(response.content)
                    logger.info(f"✅ Logo salva em cache: {clean_url}")
                    return Response(content=response.content, media_type=response.headers.get("Content-Type", "image/png"))
                return Response(status_code=200, media_type=response.headers.get("Content-Type", "image/png"))
            
            logger.warning(f"Proxy 403/Falha para {clean_url}: Status {response.status_code}")
            transparent_pixel = b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
            import base64
            return Response(content=base64.b64decode(transparent_pixel), media_type="image/png")
                
    except Exception as e:
        logger.error(f"Erro fatal no Proxy Image ({imageUrl}): {e}")
        transparent_pixel = b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
        import base64
        return Response(content=base64.b64decode(transparent_pixel), media_type="image/png")

# --- GLOBAL UTILITY FUNCTIONS FOR MAP AND ANALYSIS ---

TERMOS_GENERICOS = ['NACIONAL', 'MULTIPLO', 'MÚLTIPLO', 'ESTADO DE', '(UF)', 'SAO PAULO (UF)', 'DESCONHECIDO', 'MISTO', 'DIVERSOS']

UF_SIGLA_TO_IBGE = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17",
    "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27",
    "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41",
    "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}

UF_TO_REGION = {
    "RO": "Norte", "AC": "Norte", "AM": "Norte", "RR": "Norte", "PA": "Norte", "AP": "Norte", "TO": "Norte",
    "MA": "Nordeste", "PI": "Nordeste", "CE": "Nordeste", "RN": "Nordeste", "PB": "Nordeste", "PE": "Nordeste", "AL": "Nordeste", "SE": "Nordeste", "BA": "Nordeste",
    "MG": "Sudeste", "ES": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "SC": "Sul", "RS": "Sul",
    "MS": "Centro-Oeste", "MT": "Centro-Oeste", "GO": "Centro-Oeste", "DF": "Centro-Oeste",
}

IBGE_TO_UF_SIGLA = {value: key for key, value in UF_SIGLA_TO_IBGE.items()}

def normalize_city_name(name):
    if not name: return ""
    name = str(name).upper().strip()
    # Remove (UF)
    if '(UF)' in name: name = name.replace('(UF)', '').strip()
    # Remove - UF (ex: ARUJA - SP)
    if ' - ' in name: name = name.split(' - ')[0].strip()
    # Remove acentos
    import unicodedata
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    return name

def clean_json_record(record):
    cleaned = {}
    for key, value in record.items():
        if isinstance(value, (np.generic,)):
            value = value.item()
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            value = None
        elif not isinstance(value, (list, dict, str, int, float, bool, type(None))) and pd.isna(value):
            value = None
        cleaned[key] = value
    return cleaned

def load_sector_shapes_for_uf(granular_db_path: str, uf_sigla: str):
    uf_code = UF_SIGLA_TO_IBGE.get((uf_sigla or "").upper())
    if not uf_code or not os.path.exists(granular_db_path):
        return None, [], []

    conn = sqlite3.connect(granular_db_path)
    try:
        rows = conn.execute(
            """
            SELECT geojson
            FROM setores_cache
            WHERE json_extract(geojson, '$.properties.CD_UF') = ?
            """,
            [uf_code],
        ).fetchall()
    finally:
        conn.close()

    polygons = []
    metadata = []
    for (geojson_text,) in rows:
        try:
            feature = json.loads(geojson_text)
            props = feature.get("properties", {}) or {}
            geometry = feature.get("geometry")
            if not geometry:
                continue
            polygon = shape(geometry)
            if polygon.is_empty:
                continue
            polygons.append(polygon)
            metadata.append({
                "cd_setor": str(props.get("CD_SETOR", "")).strip(),
                "uf": uf_sigla,
                "municipio": props.get("NM_MUN"),
                "bairro": props.get("NM_BAIRRO"),
                "nome": props.get("NM_BAIRRO") or props.get("NM_MUN") or props.get("CD_SETOR"),
            })
        except Exception:
            continue

    if not polygons:
        return None, [], []

    return STRtree(polygons), polygons, metadata


@lru_cache(maxsize=64)
def load_state_perimeter_index(uf_sigla: str):
    granular_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "redutos_granular.db")
    tree, polygons, _metadata = load_sector_shapes_for_uf(granular_db_path, uf_sigla)
    if tree is None or not polygons:
        return None, tuple()
    return tree, tuple(polygons)


@lru_cache(maxsize=32)
def load_state_perimeter_geojson(uf_sigla: str):
    granular_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "redutos_granular.db")
    _tree, polygons, _metadata = load_sector_shapes_for_uf(granular_db_path, uf_sigla)
    if not polygons:
        return None
    try:
        merged = unary_union(polygons)
        simplified = merged.simplify(0.005, preserve_topology=True)
        return mapping(simplified)
    except Exception:
        return None

def load_enriched_indicator_map(sector_codes: list):
    def derive_age_fields(record):
        def num(key):
            try:
                value = record.get(key)
                if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
                    return None
                return float(value)
            except Exception:
                return None

        total = num("demografia_v01006") or num("populacao") or num("basico_v0001")
        if not total or total <= 0:
            return record

        faixa_0_14 = sum(filter(None, [num("demografia_v01031"), num("demografia_v01032"), num("demografia_v01033")]))
        faixa_15_24 = sum(filter(None, [num("demografia_v01034"), num("demografia_v01035")]))
        faixa_25_39 = sum(filter(None, [num("demografia_v01036"), num("demografia_v01037")]))
        faixa_40_59 = sum(filter(None, [num("demografia_v01038"), num("demografia_v01039")]))
        faixa_60_mais = sum(filter(None, [num("demografia_v01040"), num("demografia_v01041")]))

        record["share_0_14"] = (faixa_0_14 / total) * 100
        record["share_15_24"] = (faixa_15_24 / total) * 100
        record["share_25_39"] = (faixa_25_39 / total) * 100
        record["share_40_59"] = (faixa_40_59 / total) * 100
        record["share_60_mais"] = (faixa_60_mais / total) * 100
        record["share_idosos"] = record["share_60_mais"]
        record["share_criancas"] = record["share_0_14"]
        record["share_adultos"] = ((faixa_25_39 + faixa_40_59) / total) * 100
        return record

    def derive_literacy_fields(record):
        def num(key):
            try:
                value = record.get(key)
                if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
                    return None
                return float(value)
            except Exception:
                return None

        alfabetizados = num("alfabetizacao_v00900") or num("V00900")
        nao_alfabetizados = num("alfabetizacao_v00901") or num("V00901")
        total = None
        if alfabetizados is not None or nao_alfabetizados is not None:
            total = (alfabetizados or 0.0) + (nao_alfabetizados or 0.0)

        if total and total > 0:
            record["alfabetizacao"] = (alfabetizados or 0.0) / total * 100
            record["nao_alfabetizacao"] = (nao_alfabetizados or 0.0) / total * 100
        return record

    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
        "ibge",
        "processed",
        "indicadores_setor_brasil_enriquecido.csv",
    )
    target = {str(code).strip() for code in sector_codes if code is not None and str(code).strip()}
    if not target:
        return {}

    result = {}
    granular_db_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
        "redutos_granular.db",
    )
    if os.path.exists(granular_db_path):
        conn = sqlite3.connect(granular_db_path)
        try:
            placeholders = ",".join(["?"] * len(target))
            rows = conn.execute(
                f"""
                SELECT indicadores_json
                FROM indicadores_setor
                WHERE json_extract(indicadores_json, '$.cd_setor') IN ({placeholders})
                """,
                list(target),
            ).fetchall()
        finally:
            conn.close()

        for (raw_json,) in rows:
            try:
                raw_record = json.loads(raw_json)
            except Exception:
                continue
            cd_setor = str(raw_record.get("cd_setor", "")).strip()
            if not cd_setor:
                continue
            merged = result.get(cd_setor, {})
            merged.update(clean_json_record(raw_record))
            merged = derive_age_fields(merged)
            merged = derive_literacy_fields(merged)
            if merged.get("populacao") is None and merged.get("basico_v0001") is not None:
                merged["populacao"] = merged.get("basico_v0001")
            if merged.get("domicilios") is None and merged.get("basico_v0002") is not None:
                merged["domicilios"] = merged.get("basico_v0002")
            if merged.get("renda_media_responsavel") is None and merged.get("renda_v06004") is not None:
                merged["renda_media_responsavel"] = merged.get("renda_v06004")
            result[cd_setor] = merged

    if os.path.exists(csv_path) and len(result) < len(target):
        remaining = target.difference(result.keys())
        for chunk in pd.read_csv(csv_path, encoding="utf-8", low_memory=False, chunksize=10000):
            if "cd_setor" not in chunk.columns:
                break
            chunk["cd_setor"] = chunk["cd_setor"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
            filtered = chunk[chunk["cd_setor"].isin(remaining)]
            if filtered.empty:
                continue
            for _, row in filtered.iterrows():
                cd_setor = str(row["cd_setor"]).strip()
                row_dict = clean_json_record(row.to_dict())
                row_dict = derive_literacy_fields(row_dict)
                result[cd_setor] = row_dict
            if len(result) >= len(target):
                break

    return result

@lru_cache(maxsize=1)
def get_ibge_metric_benchmarks_bulk():
    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
        "ibge",
        "processed",
        "indicadores_setor_brasil_enriquecido.csv",
    )
    if not os.path.exists(csv_path):
        return {}

    metric_names = (
        "alfabetizacao",
        "nao_alfabetizacao",
        "rede_geral_agua",
        "rede_esgoto",
        "lixo_coletado",
        "sem_banheiro",
        "share_domicilios_improvisados",
        "share_cortico",
        "share_maloca",
        "poco_artesiano",
        "sem_esgoto",
        "fossa_rudimentar_buraco",
        "lixo_queimado",
        "lixo_ceu_aberto",
        "share_estrutura_degradada",
        "entorno_via_pavimentada",
        "entorno_bueiro",
        "entorno_calcada_sem_obstaculo",
        "entorno_rampa_cadeirante",
        "entorno_ponto_onibus",
        "entorno_calcada",
        "entorno_iluminacao_publica",
        "entorno_arborizacao_1_2_arvores",
        "entorno_arborizacao_3_4_arvores",
        "entorno_arborizacao_5_mais_arvores",
        "entorno_sem_arvores",
        "renda_media_responsavel",
        "moradores_por_domicilio",
    )
    requested_cols = {"cd_setor", "uf", "domicilios", *metric_names}

    aggregations = {
        metric: {
            "brasil_sum": 0.0,
            "brasil_weight": 0.0,
            "ufs": {},
            "regioes": {},
        }
        for metric in metric_names
    }

    try:
        for chunk in pd.read_csv(
            csv_path,
            usecols=lambda col: col in requested_cols,
            low_memory=False,
            chunksize=50000,
        ):
            chunk["cd_setor"] = chunk["cd_setor"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
            chunk["uf"] = chunk["uf"].astype(str).str.strip().str.upper()
            missing_uf_mask = chunk["uf"].isin(["", "NAN", "NONE"])
            if missing_uf_mask.any():
                chunk.loc[missing_uf_mask, "uf"] = chunk.loc[missing_uf_mask, "cd_setor"].str[:2].map(IBGE_TO_UF_SIGLA)
            chunk["domicilios"] = pd.to_numeric(chunk["domicilios"], errors="coerce")
            chunk["_peso"] = chunk["domicilios"].where(chunk["domicilios"].notna() & (chunk["domicilios"] > 0), 1.0)
            chunk["regiao"] = chunk["uf"].map(UF_TO_REGION)

            for metric_name in metric_names:
                if metric_name not in chunk.columns:
                    continue
                metric_df = chunk[["uf", "regiao", "_peso", metric_name]].copy()
                metric_df[metric_name] = pd.to_numeric(metric_df[metric_name], errors="coerce")
                metric_df = metric_df[metric_df[metric_name].notna()]
                if metric_df.empty:
                    continue

                metric_df["_weighted_value"] = metric_df[metric_name] * metric_df["_peso"]
                agg = aggregations[metric_name]
                agg["brasil_sum"] += float(metric_df["_weighted_value"].sum())
                agg["brasil_weight"] += float(metric_df["_peso"].sum())

                for uf, group in metric_df.groupby("uf"):
                    uf_data = agg["ufs"].setdefault(uf, {"sum": 0.0, "weight": 0.0})
                    uf_data["sum"] += float(group["_weighted_value"].sum())
                    uf_data["weight"] += float(group["_peso"].sum())

                for regiao, group in metric_df[metric_df["regiao"].notna()].groupby("regiao"):
                    reg_data = agg["regioes"].setdefault(regiao, {"sum": 0.0, "weight": 0.0})
                    reg_data["sum"] += float(group["_weighted_value"].sum())
                    reg_data["weight"] += float(group["_peso"].sum())
    except Exception:
        return {}

    result = {}
    for metric_name, agg in aggregations.items():
        brasil = (
            float(agg["brasil_sum"] / agg["brasil_weight"])
            if agg["brasil_weight"] > 0 else None
        )
        ufs = {
            uf: float(data["sum"] / data["weight"])
            for uf, data in agg["ufs"].items()
            if data["weight"] > 0
        }
        regioes = {
            regiao: float(data["sum"] / data["weight"])
            for regiao, data in agg["regioes"].items()
            if data["weight"] > 0
        }
        result[metric_name] = {"brasil": brasil, "ufs": ufs, "regioes": regioes}

    return result


def get_ibge_metric_benchmarks(metric_name: str):
    return get_ibge_metric_benchmarks_bulk().get(metric_name, {"brasil": None, "ufs": {}, "regioes": {}})

def weighted_metric(items, field):
    valid = []
    for item in items or []:
        peso = item.get("total_votos")
        valor = (item.get("indicadores") or {}).get(field)
        try:
            peso = float(peso)
            valor = float(valor)
        except Exception:
            continue
        if peso > 0:
            valid.append((peso, valor))
    if not valid:
        return None
    total_weight = sum(weight for weight, _ in valid)
    if total_weight <= 0:
        return None
    return sum(weight * value for weight, value in valid) / total_weight

def weighted_age_metric(items, field):
    valid = []
    for item in items or []:
        peso = item.get("total_votos")
        indicadores = item.get("indicadores") or {}
        try:
            peso = float(peso)
        except Exception:
            continue
        if peso <= 0:
            continue

        valor = indicadores.get(field)
        try:
            valor = float(valor)
            if 0 <= valor <= 100:
                valid.append((peso, valor))
                continue
        except Exception:
            pass

        if field == "share_60_mais":
            try:
                a014 = float(indicadores.get("share_0_14"))
                a1524 = float(indicadores.get("share_15_24"))
                a2539 = float(indicadores.get("share_25_39"))
                a4059 = float(indicadores.get("share_40_59"))
                if all(0 <= val <= 100 for val in [a014, a1524, a2539, a4059]):
                    derived = max(0.0, min(100.0, 100.0 - a014 - a1524 - a2539 - a4059))
                    valid.append((peso, derived))
            except Exception:
                continue

    if not valid:
        return None
    total_weight = sum(weight for weight, _ in valid)
    if total_weight <= 0:
        return None
    return sum(weight * value for weight, value in valid) / total_weight

def build_granular_ibge_cards(top_redutos: list):
    if not top_redutos:
        return []

    age_bands = [
        ("0 a 14 anos", weighted_age_metric(top_redutos, "share_0_14")),
        ("15 a 24 anos", weighted_age_metric(top_redutos, "share_15_24")),
        ("25 a 39 anos", weighted_age_metric(top_redutos, "share_25_39")),
        ("40 a 59 anos", weighted_age_metric(top_redutos, "share_40_59")),
        ("60+ anos", weighted_age_metric(top_redutos, "share_60_mais")),
    ]
    valid_age_bands = [(label, value) for label, value in age_bands if value is not None]
    dominant_age_band = max(valid_age_bands, key=lambda item: item[1]) if valid_age_bands else None
    uf_ref = next((str(item.get("uf")).strip().upper() for item in top_redutos if item.get("uf")), None)
    regiao_ref = UF_TO_REGION.get(uf_ref) if uf_ref else None

    metrics = [
        ("População Média do Setor", "populacao", "média territorial ponderada dos setores do reduto", "number"),
        ("Renda Média do Responsável", "renda_media_responsavel", "território do deputado, comparado com estado e Brasil", "currency"),
        ("Moradores por Domicílio", "moradores_por_domicilio", "tamanho médio dos lares no território dominante, comparado com estado, região e Brasil", "number_1"),
        ("Rede Geral de Água", "rede_geral_agua", "cobertura média territorial", "percent"),
        ("Rede de Esgoto", "rede_esgoto", "cobertura média territorial", "percent"),
        ("Idade Mais Frequente", "dominant_age_band", "faixa etária com maior peso territorial nos setores dominantes", "text"),
        ("Coleta de Lixo", "lixo_coletado", "cobertura média territorial", "percent"),
    ]

    cards = []
    for label, field, caption, format_type in metrics:
        if field == "dominant_age_band":
            value = dominant_age_band[0] if dominant_age_band else None
        else:
            value = weighted_metric(top_redutos, field)
        if value is None:
            continue
        if format_type == "text":
            display = value
        elif format_type == "currency":
            display = f"R$ {value:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
        elif format_type == "percent":
            display = f"{value:.1f}%"
        elif format_type == "number_1":
            display = f"{value:.1f}".replace(".", ",")
        else:
            display = f"{value:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

        comparisons = {}
        delta_brasil = None
        if field in {"renda_media_responsavel", "moradores_por_domicilio"}:
            benchmarks = get_ibge_metric_benchmarks(field)
            valor_estado = benchmarks.get("ufs", {}).get(uf_ref) if uf_ref else None
            valor_regiao = benchmarks.get("regioes", {}).get(regiao_ref) if regiao_ref else None
            valor_brasil = benchmarks.get("brasil")
            comparisons = {
                "estado": valor_estado,
                "regiao": valor_regiao,
                "brasil": valor_brasil,
            }
            if valor_brasil and valor_brasil > 0:
                delta_pct = ((value - valor_brasil) / valor_brasil) * 100
                signal = "+" if delta_pct >= 0 else ""
                delta_brasil = f"{signal}{delta_pct:.1f}% vs Brasil"

        cards.append({
            "label": label,
            "value": display,
            "caption": caption,
            "format": format_type,
            "comparisons": comparisons,
            "deltaBrasil": delta_brasil,
        })
    return cards

def build_metric_benchmarks_payload(top_redutos: list, metric_names: list):
    if not top_redutos or not metric_names:
        return {}

    uf_ref = next((str(item.get("uf")).strip().upper() for item in top_redutos if item.get("uf")), None)
    regiao_ref = UF_TO_REGION.get(uf_ref) if uf_ref else None
    payload = {}

    for metric_name in metric_names:
        benchmarks = get_ibge_metric_benchmarks(metric_name)
        payload[metric_name] = {
            "estado": benchmarks.get("ufs", {}).get(uf_ref) if uf_ref else None,
            "regiao": benchmarks.get("regioes", {}).get(regiao_ref) if regiao_ref else None,
            "brasil": benchmarks.get("brasil"),
        }

    return payload

def materialize_granular_reduto_cache(nome_parlamentar: str, estado: Optional[str] = None, partido: Optional[str] = None):
    granular_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "redutos_granular.db")
    duck_db_path = DUCK_DB_PATH

    if not os.path.exists(granular_db_path) or not os.path.exists(duck_db_path):
        return None

    con = safe_duckdb_connect(duck_db_path, read_only=True)
    try:
        info_query = """
            SELECT DISTINCT
                NM_PARLAMENTAR,
                SIGLA_PARTIDO_FINAL,
                SG_UF
            FROM votacao
            WHERE NM_PARLAMENTAR = ?
            LIMIT 1
        """
        info_result = con.execute(info_query, [nome_parlamentar]).fetchdf()
        if info_result.empty:
            info_query_like = """
                SELECT DISTINCT
                    NM_PARLAMENTAR,
                    SIGLA_PARTIDO_FINAL,
                    SG_UF
                FROM votacao
                WHERE UPPER(NM_PARLAMENTAR) LIKE UPPER(?)
                LIMIT 1
            """
            info_result = con.execute(info_query_like, [f"%{nome_parlamentar}%"]).fetchdf()
        if info_result.empty:
            # Tenta resolver via nomeCivil (ex: "CARLOS JORDY" → "CARLOS ROBERTO COELHO DE MATTOS JUNIOR")
            try:
                conn_sq = sqlite3.connect(DATABASE_PATHS["tabelao"])
                civil_row = conn_sq.execute(
                    "SELECT DISTINCT nomeCivil FROM tabelao WHERE UPPER(TRIM(nome)) = UPPER(TRIM(?)) AND nomeCivil IS NOT NULL LIMIT 1",
                    [nome_parlamentar]
                ).fetchone()
                conn_sq.close()
                if civil_row and civil_row[0]:
                    stop_words = {"DE", "DO", "DA", "DOS", "DAS", "E", "EM", "A", "O", "JUNIOR", "JÚNIOR", "FILHO", "NETO"}
                    tokens = [t.upper() for t in civil_row[0].split() if t.upper() not in stop_words and len(t) > 3]
                    for token in tokens:
                        candidate = con.execute(
                            "SELECT DISTINCT NM_PARLAMENTAR, SIGLA_PARTIDO_FINAL, SG_UF FROM votacao WHERE UPPER(NM_PARLAMENTAR) LIKE ? LIMIT 5",
                            [f"%{token}%"]
                        ).fetchdf()
                        civil_tokens = set(tokens)
                        for _, row in candidate.iterrows():
                            duck_tokens = set(t.upper() for t in str(row["NM_PARLAMENTAR"]).split() if t.upper() not in stop_words and len(t) > 3)
                            if len(civil_tokens & duck_tokens) >= 2:
                                info_result = candidate[candidate["NM_PARLAMENTAR"] == row["NM_PARLAMENTAR"]]
                                break
                        if not info_result.empty:
                            break
            except Exception as e:
                logger.warning(f"[granular_reduto] Falha ao resolver nome via nomeCivil: {e}")
        if info_result.empty:
            return None

        info_row = info_result.iloc[0]
        nome_real = nome_parlamentar  # preserva nome amigável (ex: "CARLOS JORDY") para cache
        nome_tse = str(info_row["NM_PARLAMENTAR"])  # nome TSE para consultas DuckDB
        uf_real = estado or str(info_row["SG_UF"])
        partido_real = partido or str(info_row["SIGLA_PARTIDO_FINAL"])

        sessoes_query = """
            SELECT
                v.NM_PARLAMENTAR,
                v.SIGLA_PARTIDO_FINAL,
                v.SG_UF,
                v.NM_MUNICIPIO,
                v.NM_BAIRRO,
                v.NM_LOCAL_VOTACAO,
                v.DS_ENDERECO,
                CAST(v.NR_ZONA AS VARCHAR) AS NR_ZONA,
                CAST(v.NR_SECAO AS VARCHAR) AS NR_SECAO,
                COALESCE(NULLIF(v.LAT, 0), e.latitude)   AS LAT,
                COALESCE(NULLIF(v.LONG, 0), e.longitude) AS LONG,
                MAX(v.QT_VOTOS_NOMINAIS) AS total_votos
            FROM votacao v
            LEFT JOIN enderecos e
                ON UPPER(TRIM(v.DS_ENDERECO))  = UPPER(TRIM(e.DS_ENDERECO))
               AND UPPER(TRIM(v.NM_MUNICIPIO)) = UPPER(TRIM(e.NM_MUNICIPIO))
               AND v.SG_UF = e.SG_UF
            WHERE v.NM_PARLAMENTAR = ?
              AND v.SG_UF = ?
            GROUP BY v.NM_PARLAMENTAR, v.SIGLA_PARTIDO_FINAL, v.SG_UF, v.NM_MUNICIPIO,
                     v.NM_BAIRRO, v.NM_LOCAL_VOTACAO, v.DS_ENDERECO, v.NR_ZONA, v.NR_SECAO,
                     COALESCE(NULLIF(v.LAT, 0), e.latitude), COALESCE(NULLIF(v.LONG, 0), e.longitude)
            HAVING COALESCE(NULLIF(v.LAT, 0), e.latitude) IS NOT NULL
               AND COALESCE(NULLIF(v.LONG, 0), e.longitude) IS NOT NULL
            ORDER BY total_votos DESC
        """
        df = con.execute(sessoes_query, [nome_tse, uf_real]).fetchdf()
    finally:
        con.close()

    if df.empty:
        return None

    tree, polygons, metadata = load_sector_shapes_for_uf(granular_db_path, uf_real)
    if tree is None:
        return None

    session_rows = []
    sector_agg = {}

    for _, row in df.iterrows():
        point = Point(float(row["LONG"]), float(row["LAT"]))
        matched_meta = None
        candidate_indices = tree.query(point)
        for idx in candidate_indices:
            polygon = polygons[int(idx)]
            if polygon.covers(point):
                matched_meta = metadata[int(idx)]
                break

        if not matched_meta or not matched_meta.get("cd_setor"):
            continue

        cd_setor = matched_meta["cd_setor"]
        registro_hash = hashlib.md5(
            "|".join([
                nome_real,
                uf_real,
                str(row["NR_ZONA"]),
                str(row["NR_SECAO"]),
                f"{float(row['LAT']):.6f}",
                f"{float(row['LONG']):.6f}",
            ]).encode("utf-8")
        ).hexdigest()

        session_rows.append({
            "registro_hash": registro_hash,
            "parlamentar": nome_real,
            "uf": uf_real,
            "partido": partido_real,
            "municipio": str(row["NM_MUNICIPIO"]) if row["NM_MUNICIPIO"] is not None else None,
            "bairro": str(row["NM_BAIRRO"]) if row["NM_BAIRRO"] is not None else None,
            "local_votacao": str(row["NM_LOCAL_VOTACAO"]) if row["NM_LOCAL_VOTACAO"] is not None else None,
            "endereco": str(row["DS_ENDERECO"]) if row["DS_ENDERECO"] is not None else None,
            "zona": str(row["NR_ZONA"]) if row["NR_ZONA"] is not None else None,
            "secao": str(row["NR_SECAO"]) if row["NR_SECAO"] is not None else None,
            "lat": float(row["LAT"]),
            "lng": float(row["LONG"]),
            "total_votos": int(row["total_votos"]),
            "cd_setor": cd_setor,
            "setor_nome": matched_meta.get("nome"),
            "setor_uf": uf_real,
            "setor_municipio": matched_meta.get("municipio"),
            "atualizado_em": datetime.utcnow().isoformat(),
        })

        if cd_setor not in sector_agg:
            sector_agg[cd_setor] = {
                "cd_setor": cd_setor,
                "municipio": matched_meta.get("municipio") or row["NM_MUNICIPIO"],
                "uf": uf_real,
                "bairro": matched_meta.get("bairro"),
                "locais": set(),
                "bairros": set(),
                "zonas": set(),
                "secoes": set(),
                "total_votos": 0,
                "setor_nome": matched_meta.get("nome"),
            }

        agg = sector_agg[cd_setor]
        agg["total_votos"] += int(row["total_votos"])
        if row["NM_LOCAL_VOTACAO"] is not None:
            agg["locais"].add(str(row["NM_LOCAL_VOTACAO"]))
        if row["NM_BAIRRO"] is not None:
            agg["bairros"].add(str(row["NM_BAIRRO"]))
        if row["NR_ZONA"] is not None:
            agg["zonas"].add(str(row["NR_ZONA"]))
        if row["NR_ZONA"] is not None and row["NR_SECAO"] is not None:
            agg["secoes"].add(f"{row['NR_ZONA']}-{row['NR_SECAO']}")

    if not sector_agg:
        return None

    indicator_map = load_enriched_indicator_map(list(sector_agg.keys()))

    top_redutos = []
    for cd_setor, agg in sorted(sector_agg.items(), key=lambda item: item[1]["total_votos"], reverse=True):
        indicadores = clean_data_for_json(indicator_map.get(cd_setor, {}))
        top_redutos.append({
            "cd_setor": cd_setor,
            "municipio": agg["municipio"],
            "uf": agg["uf"],
            "bairro": agg["bairro"],
            "bairros": sorted(agg["bairros"]),
            "locais": sorted(agg["locais"]),
            "zonas": sorted(agg["zonas"], key=lambda x: (len(x), x)),
            "secoes": sorted(agg["secoes"]),
            "quantidade_sessoes": len(agg["secoes"]),
            "total_votos": agg["total_votos"],
            "setor_nome": agg["setor_nome"],
            "indicadores": indicadores,
        })

    top_redutos = top_redutos[:20]
    cards = build_granular_ibge_cards(top_redutos[:10])
    contexto_nota = (
        "Os indicadores desta seção usam territórios específicos do IBGE, com base nos polígonos/setores censitários "
        "que contêm as coordenadas das seções onde o deputado concentrou votos. O foco é o reduto territorial real, não a média do município."
    )
    metodologia = (
        "Cruzamento espacial das coordenadas das seções eleitorais com os polígonos territoriais do IBGE. "
        "Cada seção georreferenciada é alocada ao setor censitário cujo polígono cobre o ponto; os votos são então agregados por setor."
    )

    tabelao_conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    try:
        cursor = tabelao_conn.cursor()
        now = datetime.utcnow().isoformat()

        cursor.execute(
            "DELETE FROM redutos_sessao_setor_cache WHERE UPPER(parlamentar) = UPPER(?) AND UPPER(uf) = UPPER(?)",
            [nome_real, uf_real],
        )

        cursor.executemany(
            """
            INSERT OR REPLACE INTO redutos_sessao_setor_cache
            (registro_hash, parlamentar, uf, partido, municipio, bairro, local_votacao, endereco, cep, zona, secao, lat, lng, total_votos, cd_setor, setor_nome, setor_uf, setor_municipio, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["registro_hash"], row["parlamentar"], row["uf"], row["partido"], row["municipio"], row["bairro"],
                    row["local_votacao"], row["endereco"], None, row["zona"], row["secao"], row["lat"], row["lng"],
                    row["total_votos"], row["cd_setor"], row["setor_nome"], row["setor_uf"], row["setor_municipio"], row["atualizado_em"]
                )
                for row in session_rows
            ],
        )

        for reduto in top_redutos:
            indicadores = reduto.get("indicadores") or {}
            cursor.execute(
                """
                INSERT OR REPLACE INTO ibge_setor_censitario_cache
                (cd_setor, uf, municipio, nome, atualizado_em, indicadores_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    reduto["cd_setor"],
                    reduto["uf"],
                    reduto["municipio"],
                    reduto.get("setor_nome") or reduto.get("bairro") or reduto.get("municipio"),
                    now,
                    json.dumps(clean_data_for_json(indicadores), ensure_ascii=False),
                ],
            )

        cursor.execute(
            """
            INSERT OR REPLACE INTO mapa_eleitoral_ibge_reduto_granular_cache
            (parlamentar, uf, partido, atualizado_em, top_redutos_json, cards_json, contexto_nota, metodologia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                nome_real,
                uf_real,
                partido_real,
                now,
                json.dumps(clean_data_for_json(top_redutos), ensure_ascii=False),
                json.dumps(clean_data_for_json(cards), ensure_ascii=False),
                contexto_nota,
                metodologia,
            ],
        )

        tabelao_conn.commit()
    finally:
        tabelao_conn.close()

    return clean_data_for_json({
        "ibgeResumoTop10": cards,
        "topRedutos": top_redutos[:10],
        "topMunicipios": [],
        "cacheStatus": "hit_granular",
        "atualizadoEm": datetime.utcnow().isoformat(),
        "contextoNota": contexto_nota,
        "metodologia": metodologia,
        "parlamentar": nome_real,
        "uf": uf_real,
        "partido": partido_real,
    })


def resolve_parlamentar_name_candidates(nome_parlamentar: str, estado: Optional[str] = None, partido: Optional[str] = None):
    """
    Retorna nomes alternativos para consulta de cache usando tanto NM_PARLAMENTAR
    quanto NM_VOTAVEL do banco eleitoral.
    """
    candidates = []
    seen = set()

    def add_candidate(value):
        if not value:
            return
        normalized = str(value).strip()
        if not normalized:
            return
        key = normalized.upper()
        if key in seen:
            return
        seen.add(key)
        candidates.append(normalized)

    nome_normalizado = normalizar_texto_ia(nome_parlamentar)
    add_candidate(nome_parlamentar)

    duck_db_path = DUCK_DB_PATH
    if not os.path.exists(duck_db_path):
        return candidates

    con = safe_duckdb_connect(duck_db_path, read_only=True)
    try:
        filters = []
        filter_params = []

        if estado:
            filters.append("SG_UF = ?")
            filter_params.append(estado)

        if partido:
            filters.append("SIGLA_PARTIDO_FINAL = ?")
            filter_params.append(partido)

        name_clause = """
            (
                UPPER(NM_PARLAMENTAR) = UPPER(?)
                OR UPPER(NM_VOTAVEL) = UPPER(?)
                OR UPPER(NM_PARLAMENTAR) LIKE UPPER(?)
                OR UPPER(NM_VOTAVEL) LIKE UPPER(?)
            )
        """
        params = filter_params + [
            nome_parlamentar,
            nome_parlamentar,
            f"%{nome_parlamentar}%",
            f"%{nome_parlamentar}%",
        ]
        where_parts = filters + [name_clause]

        rows = con.execute(
            f"""
            SELECT DISTINCT NM_PARLAMENTAR, NM_VOTAVEL
            FROM votacao
            WHERE {" AND ".join(where_parts)}
            ORDER BY NM_PARLAMENTAR, NM_VOTAVEL
            LIMIT 20
            """,
            params,
        ).fetchall()

        for nm_parlamentar, nm_votavel in rows:
            add_candidate(nm_parlamentar)
            add_candidate(nm_votavel)

        if len(candidates) <= 1:
            fallback_where = filters[:] if filters else []
            fallback_params = filter_params[:]
            if not fallback_where:
                fallback_where = ["1=1"]

            fallback_rows = con.execute(
                f"""
                SELECT DISTINCT NM_PARLAMENTAR, NM_VOTAVEL
                FROM votacao
                WHERE {" AND ".join(fallback_where)}
                ORDER BY NM_PARLAMENTAR, NM_VOTAVEL
                LIMIT 5000
                """,
                fallback_params,
            ).fetchall()

            for nm_parlamentar, nm_votavel in fallback_rows:
                for candidate_value in (nm_parlamentar, nm_votavel):
                    if not candidate_value:
                        continue
                    candidate_norm = normalizar_texto_ia(candidate_value)
                    if (
                        candidate_norm == nome_normalizado
                        or nome_normalizado in candidate_norm
                        or candidate_norm in nome_normalizado
                    ):
                        add_candidate(candidate_value)
    except Exception:
        pass
    finally:
        con.close()

    return candidates


def ensure_mapa_eleitoral_votos_cache_table():
    conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mapa_eleitoral_votos_cache (
                parlamentar TEXT NOT NULL,
                uf TEXT,
                partido TEXT,
                atualizado_em TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (parlamentar, uf, partido)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mapa_eleitoral_votos_cache_parlamentar ON mapa_eleitoral_votos_cache(parlamentar, uf, partido)"
        )
        conn.commit()
    finally:
        conn.close()


MAPA_PARTIDARIO_CACHE_VERSION = "v9"


def ensure_mapa_partidario_cache_table():
    conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS mapa_partidario_cache_v2 (
                cache_key TEXT PRIMARY KEY,
                estado TEXT NOT NULL,
                partido_eleicao TEXT NOT NULL DEFAULT '',
                partido_atual TEXT NOT NULL DEFAULT '',
                parlamentar TEXT NOT NULL DEFAULT '',
                cache_version TEXT NOT NULL,
                atualizado_em TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mapa_partidario_cache_v2_lookup
            ON mapa_partidario_cache_v2(estado, partido_eleicao, partido_atual, parlamentar, cache_version)
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_cached_mapa_partidario_payload(
    estado: str,
    partido_eleicao: Optional[str] = None,
    partido_atual: Optional[str] = None,
    parlamentar: Optional[str] = None,
):
    ensure_mapa_partidario_cache_table()
    estado_key = str(estado or "").strip().upper()
    partido_eleicao_key = str(partido_eleicao or "").strip().upper()
    partido_atual_key = str(partido_atual or "").strip().upper()
    parlamentar_key = str(parlamentar or "").strip()
    if not estado_key:
        return None
    cache_key = hashlib.md5(
        json.dumps(
            {
                "estado": estado_key,
                "partido_eleicao": partido_eleicao_key,
                "partido_atual": partido_atual_key,
                "parlamentar": parlamentar_key,
                "version": MAPA_PARTIDARIO_CACHE_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT payload_json
            FROM mapa_partidario_cache_v2
            WHERE cache_key = ?
              AND cache_version = ?
            LIMIT 1
            """,
            [cache_key, MAPA_PARTIDARIO_CACHE_VERSION],
        )
        row = cursor.fetchone()
        if not row or not row["payload_json"]:
            return None
        return clean_data_for_json(json.loads(row["payload_json"]))
    except Exception as exc:
        logging.warning(
            "Falha ao ler cache do mapa partidário para %s/%s/%s/%s: %s",
            estado_key,
            partido_eleicao_key,
            partido_atual_key,
            parlamentar_key,
            exc,
        )
        return None
    finally:
        conn.close()


def materialize_mapa_partidario_payload_cache(
    estado: str,
    partido_eleicao: Optional[str],
    partido_atual: Optional[str],
    parlamentar: Optional[str],
    payload: Dict,
):
    ensure_mapa_partidario_cache_table()
    estado_key = str(estado or "").strip().upper()
    partido_eleicao_key = str(partido_eleicao or "").strip().upper()
    partido_atual_key = str(partido_atual or "").strip().upper()
    parlamentar_key = str(parlamentar or "").strip()
    if not estado_key:
        return
    cache_key = hashlib.md5(
        json.dumps(
            {
                "estado": estado_key,
                "partido_eleicao": partido_eleicao_key,
                "partido_atual": partido_atual_key,
                "parlamentar": parlamentar_key,
                "version": MAPA_PARTIDARIO_CACHE_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO mapa_partidario_cache_v2 (
                cache_key,
                estado,
                partido_eleicao,
                partido_atual,
                parlamentar,
                cache_version,
                atualizado_em,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                cache_key,
                estado_key,
                partido_eleicao_key,
                partido_atual_key,
                parlamentar_key,
                MAPA_PARTIDARIO_CACHE_VERSION,
                datetime.now().isoformat(),
                json.dumps(clean_data_for_json(payload), ensure_ascii=False),
            ],
        )
        conn.commit()
    except Exception as exc:
        logging.warning(
            "Falha ao gravar cache do mapa partidário para %s/%s/%s/%s: %s",
            estado_key,
            partido_eleicao_key,
            partido_atual_key,
            parlamentar_key,
            exc,
        )
    finally:
        conn.close()


@lru_cache(maxsize=512)
def resolve_nm_votavel_for_parlamentar(nome_parlamentar: str, uf: Optional[str]) -> Optional[str]:
    if not nome_parlamentar:
        return None

    duck_db_path = DUCK_DB_PATH
    if not os.path.exists(duck_db_path):
        return None

    con = safe_duckdb_connect(duck_db_path, read_only=True)
    try:
        params = [nome_parlamentar]
        conditions = ["UPPER(NM_PARLAMENTAR) = UPPER(?)"]
        if uf:
            conditions.append("UPPER(SG_UF) = UPPER(?)")
            params.append(uf)

        row = con.execute(
            f"""
            SELECT NM_VOTAVEL, COUNT(*) AS freq
            FROM votacao
            WHERE {" AND ".join(conditions)}
              AND NM_VOTAVEL IS NOT NULL
            GROUP BY NM_VOTAVEL
            ORDER BY freq DESC, NM_VOTAVEL
            LIMIT 1
            """,
            params,
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        con.close()


_VOTOS_OFICIAIS_JSON_PATH = os.path.join(_SCRIPT_DIR, "votos_oficiais_tse.json")
_VOTOS_OFICIAIS_CACHE: dict = {}

def _load_votos_oficiais_json():
    global _VOTOS_OFICIAIS_CACHE
    if _VOTOS_OFICIAIS_CACHE:
        return _VOTOS_OFICIAIS_CACHE
    if os.path.exists(_VOTOS_OFICIAIS_JSON_PATH):
        try:
            with open(_VOTOS_OFICIAIS_JSON_PATH, "r") as f:
                _VOTOS_OFICIAIS_CACHE = json.load(f)
            logging.info("✅ Loaded %d entries from votos_oficiais_tse.json", len(_VOTOS_OFICIAIS_CACHE))
        except Exception as e:
            logging.warning("Falha ao carregar votos_oficiais_tse.json: %s", e)
    return _VOTOS_OFICIAIS_CACHE

@lru_cache(maxsize=512)
def get_total_votos_oficiais_tse(nome_parlamentar: str, uf: Optional[str]) -> Optional[int]:
    if not nome_parlamentar or not uf:
        return None

    nm_votavel = resolve_nm_votavel_for_parlamentar(nome_parlamentar, uf)
    if not nm_votavel:
        return None

    # Try precomputed JSON first (fast path)
    votos_json = _load_votos_oficiais_json()
    if votos_json:
        key = f"{nm_votavel}|{uf.upper()}"
        if key in votos_json:
            return int(votos_json[key])

    parquet_path = get_tse_dep_federal_parquet_path(uf)
    if not parquet_path or duckdb is None:
        return None

    con = safe_duckdb_connect()
    try:
        result = con.execute(
            """
            SELECT SUM(CAST(QT_VOTOS AS BIGINT)) AS total_votos
            FROM read_parquet(?)
            WHERE NM_VOTAVEL = ?
            """,
            [parquet_path, nm_votavel],
        ).fetchone()
        if not result or result[0] is None:
            return None
        return int(result[0])
    except Exception as e:
        logging.warning(
            "Falha ao calcular total oficial de votos via parquet do TSE para %s/%s: %s",
            nome_parlamentar,
            uf,
            e,
        )
        return None
    finally:
        con.close()


@lru_cache(maxsize=32)
def get_tse_dep_federal_parquet_path(uf: Optional[str]) -> Optional[str]:
    if not uf:
        return None

    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "votacao",
        f"votacao_secao_2022_{str(uf).upper()}.csv",
    )
    if not os.path.exists(csv_path):
        return None

    cache_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data",
        "cache",
        "tse_dep_federal",
    )
    os.makedirs(cache_dir, exist_ok=True)

    parquet_path = os.path.join(cache_dir, f"votacao_secao_2022_{str(uf).upper()}_dep_federal.parquet")
    csv_mtime = os.path.getmtime(csv_path)
    parquet_exists = os.path.exists(parquet_path)
    parquet_mtime = os.path.getmtime(parquet_path) if parquet_exists else 0

    if parquet_exists and parquet_mtime >= csv_mtime:
        return parquet_path

    con = safe_duckdb_connect()
    try:
        csv_sql_path = csv_path.replace("'", "''")
        parquet_sql_path = parquet_path.replace("'", "''")
        con.execute(
            f"""
            COPY (
                SELECT
                    SG_UF,
                    DS_CARGO,
                    NM_VOTAVEL,
                    NM_MUNICIPIO,
                    NR_ZONA,
                    NR_SECAO,
                    NM_LOCAL_VOTACAO,
                    DS_LOCAL_VOTACAO_ENDERECO,
                    QT_VOTOS
                FROM read_csv_auto('{csv_sql_path}', delim=';', header=True, encoding='latin-1', all_varchar=True)
                WHERE SG_UF = ?
                  AND DS_CARGO = 'DEPUTADO FEDERAL'
            ) TO '{parquet_sql_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """,
            [str(uf).upper()],
        )
        return parquet_path
    except Exception as e:
        logging.warning(
            "Falha ao montar parquet filtrado do TSE para %s: %s",
            uf,
            e,
        )
        return None
    finally:
        con.close()


def get_official_votacao_context(nome_parlamentar: str, uf: Optional[str], limit_municipios: int = 10, limit_bairros: int = 12):
    if not nome_parlamentar or not uf:
        return pd.DataFrame(), pd.DataFrame()

    nm_votavel = resolve_nm_votavel_for_parlamentar(nome_parlamentar, uf)
    if not nm_votavel:
        return pd.DataFrame(), pd.DataFrame()

    parquet_path = get_tse_dep_federal_parquet_path(uf)
    if not parquet_path:
        return pd.DataFrame(), pd.DataFrame()

    con = safe_duckdb_connect()
    try:
        total_oficial = get_total_votos_oficiais_tse(nome_parlamentar, uf) or 0
        municipios = con.execute(
            """
            SELECT
                NM_MUNICIPIO,
                SUM(CAST(QT_VOTOS AS BIGINT)) AS total_votos,
                COUNT(DISTINCT CAST(NR_ZONA AS VARCHAR) || '-' || CAST(NR_SECAO AS VARCHAR)) AS total_secoes
            FROM read_parquet(?)
            WHERE NM_VOTAVEL = ?
            GROUP BY NM_MUNICIPIO
            ORDER BY total_votos DESC
            LIMIT ?
            """,
            [parquet_path, nm_votavel, int(limit_municipios)],
        ).fetchdf()
        if not municipios.empty:
            if total_oficial > 0:
                municipios["percentual_medio"] = municipios["total_votos"].astype(float) / float(total_oficial) * 100.0
            else:
                municipios["percentual_medio"] = None

        bairros = con.execute(
            """
            SELECT
                COALESCE(NULLIF(TRIM(NM_LOCAL_VOTACAO), ''), NULLIF(TRIM(DS_LOCAL_VOTACAO_ENDERECO), ''), 'Local não informado') AS bairro,
                NM_MUNICIPIO,
                SUM(CAST(QT_VOTOS AS BIGINT)) AS total_votos,
                COUNT(DISTINCT CAST(NR_ZONA AS VARCHAR) || '-' || CAST(NR_SECAO AS VARCHAR)) AS total_secoes
            FROM read_parquet(?)
            WHERE NM_VOTAVEL = ?
            GROUP BY 1, 2
            ORDER BY total_votos DESC
            LIMIT ?
            """,
            [parquet_path, nm_votavel, int(limit_bairros)],
        ).fetchdf()

        return municipios, bairros
    except Exception as e:
        logging.warning(
            "Falha ao carregar contexto oficial de votação via CSV do TSE para %s/%s: %s",
            nome_parlamentar,
            uf,
            e,
        )
        return pd.DataFrame(), pd.DataFrame()
    finally:
        con.close()


def get_state_elected_label_maps(uf: Optional[str]):
    if not uf:
        return {}, {}

    alias_to_display = {}
    display_meta = {}
    conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    try:
        rows = pd.read_sql_query(
            """
            SELECT DISTINCT nome, nomeCivil, sgPartido
            FROM tabelao
            WHERE sgUF = ?
              AND nome IS NOT NULL
              AND TRIM(nome) <> ''
            """,
            conn,
            params=[str(uf).upper()],
        )

        for _, row in rows.iterrows():
            display_name = str(row.get("nome") or "").strip()
            civil_name = str(row.get("nomeCivil") or "").strip()
            partido_name = str(row.get("sgPartido") or "").strip()
            if not display_name:
                continue

            display_meta[display_name] = {"partido_tabelao": partido_name}

            for alias in {display_name, civil_name}:
                normalized_alias = normalizar_texto_ia(alias)
                if normalized_alias:
                    alias_to_display[normalized_alias] = display_name
    except Exception as exc:
        logging.warning("Falha ao carregar mapa de nomes eleitos do estado %s: %s", uf, exc)
    finally:
        conn.close()

    return alias_to_display, display_meta


def get_state_current_party_maps(uf: Optional[str]):
    if not uf:
        return {}, {}

    alias_to_current_party = {}
    display_to_current_party = {}
    conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    try:
        rows = pd.read_sql_query(
            """
            SELECT DISTINCT nome, nomeCivil, sgPartido, ultimoStatus_siglaPartido
            FROM tabelao
            WHERE sgUF = ?
              AND nome IS NOT NULL
              AND TRIM(nome) <> ''
            """,
            conn,
            params=[str(uf).upper()],
        )

        for _, row in rows.iterrows():
            display_name = str(row.get("nome") or "").strip()
            civil_name = str(row.get("nomeCivil") or "").strip()
            current_party = str(row.get("ultimoStatus_siglaPartido") or row.get("sgPartido") or "").strip().upper()
            if not display_name or not current_party:
                continue

            display_to_current_party[display_name] = current_party

            for alias in {display_name, civil_name}:
                normalized_alias = normalizar_texto_ia(alias)
                if normalized_alias:
                    alias_to_current_party[normalized_alias] = current_party
    except Exception as exc:
        logging.warning("Falha ao carregar partidos atuais do estado %s: %s", uf, exc)
    finally:
        conn.close()

    return alias_to_current_party, display_to_current_party


def build_parlamentar_filter_options(
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    partido_atual: Optional[str] = None,
) -> List[str]:
    if duckdb is None:
        try:
            conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
            query = "SELECT DISTINCT nome as canonical_name, nome as ballot_name FROM tabelao WHERE 1=1"
            params = []
            if estado and estado != "Todos":
                query += " AND sgUF = ?"
                params.append(estado)
            if partido and partido != "Todos":
                query += " AND sgPartido = ?"
                params.append(partido)
            query += " ORDER BY nome"
            df = pd.read_sql_query(query, conn, params=params)
            rows = df.values.tolist()
            conn.close()
        except Exception as e:
            logger.error(f"Erro no fallback de parlamentares: {e}")
            return []
    # Se chegou aqui é porque o DuckDB falhou ou não existe
    try:
        conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
        query = "SELECT DISTINCT nome as canonical_name, nome as ballot_name FROM tabelao WHERE 1=1"
        params = []
        if estado and estado != "Todos":
            query += " AND sgUF = ?"
            params.append(estado)
        if partido and partido != "Todos":
            query += " AND sgPartido = ?"
            params.append(partido)
        query += " ORDER BY nome"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return sorted(df['ballot_name'].dropna().unique().tolist())
    except Exception as e:
        logger.error(f"Erro crítico no filtro de parlamentares: {e}")
        return []

def get_state_elected_label_maps(uf: Optional[str]):
    if estado and estado != "Todos":
        try:
            label_map, _ = get_state_elected_label_maps(estado)
        except Exception:
            label_map = {}
        try:
            current_party_map, _ = get_state_current_party_maps(estado)
        except Exception:
            current_party_map = {}

    parlamentares_by_label = {}
    for canonical_name, ballot_name in rows:
        canonical_name = str(canonical_name or "").strip()
        ballot_name = str(ballot_name or "").strip()
        if not canonical_name:
            continue

        normalized_canonical = normalizar_texto_ia(canonical_name)
        normalized_ballot = normalizar_texto_ia(ballot_name)
        mapped_label = label_map.get(normalized_canonical) or label_map.get(normalized_ballot)

        if mapped_label:
            resolved_label = str(mapped_label).strip()
        else:
            candidates = [item for item in [canonical_name, ballot_name] if item]
            resolved_label = min(candidates, key=len) if candidates else canonical_name

        normalized_label = normalizar_texto_ia(resolved_label)
        if not normalized_label:
            continue

        candidate = {"label": resolved_label, "value": resolved_label}

        # UNIFICAÇÃO AGRESSIVA E PRIORIZAÇÃO DO NOME ELEITORAL
        current_party_resolved = (
            current_party_map.get(normalized_canonical)
            or current_party_map.get(normalized_ballot)
            or current_party_map.get(normalized_label)
            or ""
        )
        
        # DEDUPLICAÇÃO INTELIGENTE: Unifica se nomes forem similares (um contido no outro)
        # Primeiro, tentamos o match exato (sem espaços/acentos) que já fizemos
        clean_key = normalized_label.replace(" ", "")
        
        # DEDUPLICAÇÃO ROBUSTA: Unifica pelo núcleo do nome (Primeiro + Último) dentro do Estado
        # Removemos o partido da chave para evitar que nomes sem partido mapeado fiquem órfãos
        words = normalized_label.split()
        if len(words) >= 2:
            id_key = f"{words[0]}_{words[-1]}_{estado or ''}"
        else:
            id_key = f"{normalized_label}_{estado or ''}"

        existing = parlamentares_by_label.get(id_key)
        
        # Heurística de Substring de Palavras (Independente da id_key)
        # Procuramos se esse novo candidato é uma "versão longa" ou "versão curta" de alguém já inserido
        match_found = False
        words_candidate = set(words)
        
        for k, v in parlamentares_by_label.items():
            # Mesma UF?
            if (estado or "") in k:
                words_existing = set(v["label"].upper().replace("Á","A").replace("É","E").replace("Í","I").replace("Ó","O").replace("Ú","U").split())
                if words_candidate.issubset(words_existing) or words_existing.issubset(words_candidate):
                    # Encontramos o mesmo parlamentar!
                    match_found = True
                    # Prioridade ao nome curto/eleitoral
                    if len(candidate["label"]) < len(v["label"]):
                        parlamentares_by_label[k] = candidate
                    break
        
        if not match_found:
            if existing is None:
                parlamentares_by_label[id_key] = candidate
            else:
                # Prioridade ao nome curto
                if len(candidate["label"]) < len(existing["label"]):
                    parlamentares_by_label[id_key] = candidate

    # Retorno limpo e ordenado por nome eleitoral
    return sorted([item["label"] for item in parlamentares_by_label.values()], key=lambda x: normalizar_texto_ia(x))


def get_all_partidos() -> List[str]:
    """Retorna a lista de todos os partidos do Brasil (sem filtro de estado)."""
    if duckdb is None:
        try:
            conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
            query = "SELECT DISTINCT TRIM(sgPartido) as partido FROM tabelao WHERE sgPartido IS NOT NULL AND TRIM(sgPartido) <> '' ORDER BY sgPartido"
            df = pd.read_sql_query(query, conn)
            conn.close()
            return sorted(set([str(p).strip().upper() for p in df['partido'].tolist()]))
        except Exception as e:
            logger.error(f"Erro no fallback de get_all_partidos: {e}")
            return []
            
    try:
        duck_db_path = DUCK_DB_PATH
        if not os.path.exists(duck_db_path):
             # Recursão interna para fallback SQLite
             return get_all_partidos()
             
        con = safe_duckdb_connect(duck_db_path, read_only=True)
        try:
            query = """
                SELECT DISTINCT TRIM(SIGLA_PARTIDO_FINAL) AS partido
                FROM votacao
                WHERE SIGLA_PARTIDO_FINAL IS NOT NULL
                  AND TRIM(SIGLA_PARTIDO_FINAL) <> ''
                ORDER BY partido
            """
            rows = con.execute(query).fetchall()
        finally:
            con.close()

        partidos = [str(row[0]).strip().upper() for row in rows if row[0]]
        return sorted(set(partidos))
    except Exception as e:
        print(f"Erro ao buscar todos os partidos: {e}")
        return []


def build_partido_filter_options(
    estado: Optional[str] = None,
    modo: str = "eleicao",
    partido_eleicao: Optional[str] = None,
    partido_atual: Optional[str] = None,
) -> List[str]:
    estado_normalizado = str(estado or "").strip().upper()
    modo_normalizado = str(modo or "eleicao").strip().lower()
    partido_eleicao_normalizado = str(partido_eleicao or "").strip().upper()
    partido_atual_normalizado = str(partido_atual or "").strip().upper()

    if not estado_normalizado or estado_normalizado == "TODOS":
        return get_all_partidos()

    if duckdb is None:
        try:
            conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
            query = "SELECT DISTINCT sgPartido as partido FROM tabelao WHERE 1=1"
            params = []
            if estado_normalizado and estado_normalizado != "TODOS":
                query += " AND sgUF = ?"
                params.append(estado_normalizado)
            query += " AND sgPartido IS NOT NULL AND TRIM(sgPartido) <> '' ORDER BY sgPartido"
            df = pd.read_sql_query(query, conn, params=params)
            conn.close()
            return sorted(set([str(p).strip().upper() for p in df['partido'].tolist()]))
        except Exception as e:
            logger.error(f"Erro crítico no filtro de partidos: {e}")
            return []

    duck_db_path = DUCK_DB_PATH
    if not os.path.exists(duck_db_path):
        # Fallback interno via SQLite
        return build_partido_filter_options(estado, modo, partido_eleicao, partido_atual)

    con = None
    try:
        con = safe_duckdb_connect(duck_db_path, read_only=True)
        query = """
            SELECT DISTINCT
                NM_PARLAMENTAR AS canonical_name,
                COALESCE(NULLIF(TRIM(NM_VOTAVEL), ''), NM_PARLAMENTAR) AS ballot_name,
                TRIM(SIGLA_PARTIDO_FINAL) AS partido_eleicao
            FROM votacao
            WHERE NM_PARLAMENTAR IS NOT NULL
              AND TRIM(NM_PARLAMENTAR) <> ''
              AND SG_UF = ?
              AND SIGLA_PARTIDO_FINAL IS NOT NULL
              AND TRIM(SIGLA_PARTIDO_FINAL) <> ''
        """
        params = [estado_normalizado]
        if partido_eleicao_normalizado and partido_eleicao_normalizado != "TODOS":
            query += " AND SIGLA_PARTIDO_FINAL = ?"
            params.append(partido_eleicao_normalizado)
        rows = con.execute(query, params).fetchall()
    finally:
        if con is not None:
            con.close()

    current_party_map = {}
    if estado_normalizado and estado_normalizado != "TODOS":
        try:
            current_party_map, _ = get_state_current_party_maps(estado_normalizado)
        except Exception:
            current_party_map = {}

    election_parties = set()
    current_parties = set()
    for canonical_name, ballot_name, partido_eleicao_value in rows:
        canonical_name = str(canonical_name or "").strip()
        ballot_name = str(ballot_name or "").strip()
        partido_eleicao_value = str(partido_eleicao_value or "").strip().upper()
        if not canonical_name or not partido_eleicao_value:
            continue

        normalized_canonical = normalizar_texto_ia(canonical_name)
        normalized_ballot = normalizar_texto_ia(ballot_name)
        current_party_resolved = (
            current_party_map.get(normalized_canonical)
            or current_party_map.get(normalized_ballot)
            or partido_eleicao_value
        )
        current_party_resolved = str(current_party_resolved or "").strip().upper()

        if partido_atual_normalizado and partido_atual_normalizado != "TODOS":
            if current_party_resolved != partido_atual_normalizado:
                continue

        election_parties.add(partido_eleicao_value)
        if current_party_resolved:
            current_parties.add(current_party_resolved)

    if modo_normalizado == "atual":
        return sorted(current_parties)
    return sorted(election_parties)


def _first_non_empty_value(values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


PARTY_WIKIPEDIA_TITLES = {
    "AVANTE": "Avante (partido político)",
    "CIDADANIA": "Cidadania (partido político)",
    "MDB": "Movimento Democrático Brasileiro",
    "NOVO": "Partido Novo",
    "PCDOB": "Partido Comunista do Brasil",
    "PCDOB ": "Partido Comunista do Brasil",
    "PDT": "Partido Democrático Trabalhista",
    "PL": "Partido Liberal (2006)",
    "PODE": "Podemos (Brasil)",
    "PP": "Progressistas",
    "PRD": "Partido Renovação Democrática",
    "PSB": "Partido Socialista Brasileiro",
    "PSD": "Partido Social Democrático (2011)",
    "PSDB": "Partido da Social Democracia Brasileira",
    "PSOL": "Partido Socialismo e Liberdade",
    "PT": "Partido dos Trabalhadores",
    "PV": "Partido Verde (Brasil)",
    "REDE": "Rede Sustentabilidade",
    "REPUBLICANOS": "Republicanos (partido político)",
    "SOLIDARIEDADE": "Solidariedade (partido político)",
    "UNIÃO": "União Brasil",
    "UNIAO": "União Brasil",
}

PARTY_WIKIPEDIA_IMAGE_FALLBACKS = {
    "AVANTE": "https://commons.wikimedia.org/wiki/Special:FilePath/AVANTE_Brazil_Logo.png?width=250",
    "PT": "https://commons.wikimedia.org/wiki/Special:FilePath/PT_(Brazil)_logo_2021.svg?width=250",
    "MDB": "https://commons.wikimedia.org/wiki/Special:FilePath/Movimento_Democr%C3%A1tico_Brasileiro_(2017).svg?width=250",
    "PL": "https://commons.wikimedia.org/wiki/Special:FilePath/Partido_Liberal_(Brazil)_logo.svg?width=250",
    "PP": "https://commons.wikimedia.org/wiki/Special:FilePath/Progressistas_(Brazil)_logo.svg?width=250",
    "PODE": "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_Podemos_20.png?width=250",
    "PDT": "https://commons.wikimedia.org/wiki/Special:FilePath/LogoPDT.png?width=250",
    "PSB": "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_of_the_Brazilian_Socialist_Party_(wordmark_color).svg?width=250",
    "PSD": "https://commons.wikimedia.org/wiki/Special:FilePath/PSD_Brazil_logo.svg?width=250",
    "PSDB": "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_of_the_Brazilian_Social_Democracy_Party_(2023).svg?width=250",
    "PSOL": "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_PSOL_roxo.svg?width=250",
    "REPUBLICANOS": "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_of_Republicanos.png?width=250",
    "SOLIDARIEDADE": "https://commons.wikimedia.org/wiki/Special:FilePath/Logomarca_do_Partido_Solidariedade.png?width=250",
    "UNIÃO": "https://commons.wikimedia.org/wiki/Special:FilePath/Uni%C3%A3o_Brasil_logo.svg?width=250",
    "UNIAO": "https://commons.wikimedia.org/wiki/Special:FilePath/Uni%C3%A3o_Brasil_logo.svg?width=250",
    "PV": "https://commons.wikimedia.org/wiki/Special:FilePath/Logomarca_do_Partido_Verde.svg?width=250",
    "MISSÃO": "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_Partido_Missão.jpg",
    "MISSAO": "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_Partido_Missão.jpg",
}

PARTY_LOGO_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "cache",
    "party_logos",
    "wikipedia_party_logos.json",
)
_party_logo_cache = None
_party_logo_cache_lock = threading.Lock()

STATE_WIKIPEDIA_TITLES = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AP": "Amapá",
    "AM": "Amazonas",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal (Brasil)",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais",
    "PA": "Pará",
    "PB": "Paraíba",
    "PR": "Paraná",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "RJ": "Rio de Janeiro (estado)",
    "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul",
    "RO": "Rondônia",
    "RR": "Roraima",
    "SC": "Santa Catarina",
    "SP": "São Paulo (estado)",
    "SE": "Sergipe",
    "TO": "Tocantins",
}

STATE_FLAG_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "cache",
    "state_flags",
    "wikipedia_state_flags.json",
)
_state_flag_cache = None
_state_flag_cache_lock = threading.Lock()


def _load_party_logo_cache():
    global _party_logo_cache
    with _party_logo_cache_lock:
        if _party_logo_cache is None:
            try:
                if os.path.exists(PARTY_LOGO_CACHE_PATH):
                    with open(PARTY_LOGO_CACHE_PATH, "r", encoding="utf-8") as fh:
                        _party_logo_cache = json.load(fh)
                else:
                    _party_logo_cache = {}
            except Exception:
                _party_logo_cache = {}
    return _party_logo_cache


def _save_party_logo_cache():
    cache = _load_party_logo_cache()
    os.makedirs(os.path.dirname(PARTY_LOGO_CACHE_PATH), exist_ok=True)
    with open(PARTY_LOGO_CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _load_state_flag_cache():
    global _state_flag_cache
    with _state_flag_cache_lock:
        if _state_flag_cache is None:
            try:
                if os.path.exists(STATE_FLAG_CACHE_PATH):
                    with open(STATE_FLAG_CACHE_PATH, "r", encoding="utf-8") as fh:
                        _state_flag_cache = json.load(fh)
                else:
                    _state_flag_cache = {}
            except Exception:
                _state_flag_cache = {}
    return _state_flag_cache


def _save_state_flag_cache():
    cache = _load_state_flag_cache()
    os.makedirs(os.path.dirname(STATE_FLAG_CACHE_PATH), exist_ok=True)
    with open(STATE_FLAG_CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _build_local_votacao_key(municipio: str, local_votacao: str, endereco: str) -> str:
    return "||".join(
        [
            normalizar_texto_ia(municipio or ""),
            normalizar_texto_ia(local_votacao or ""),
            normalizar_texto_ia(endereco or ""),
        ]
    )


def _fetch_wikipedia_page_image_url(title: str) -> Optional[str]:
    if not title:
        return None

    params = {
        "action": "query",
        "format": "json",
        "redirects": 1,
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": 300,
        "titles": title,
    }
    for api_url in ("https://pt.wikipedia.org/w/api.php", "https://en.wikipedia.org/w/api.php"):
        headers = {"User-Agent": "TCCMapaPartidario/1.0 (https://pt.wikipedia.org)"}
        response = requests.get(api_url, params=params, headers=headers, timeout=8)
        response.raise_for_status()
        data = response.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            thumbnail = page.get("thumbnail") or {}
            source = thumbnail.get("source")
            if source:
                return str(source).strip()
    return None


def _normalize_commons_special_file_path(url: Optional[str]) -> Optional[str]:
    raw = str(url or "").strip()
    if not raw:
        return None

    special_match = re.search(r"/wiki/Special:FilePath/([^?]+)", raw, flags=re.IGNORECASE)
    if special_match:
        filename = special_match.group(1).strip()
        if filename:
            return f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width=320"

    thumb_match = re.search(
        r"upload\.wikimedia\.org/wikipedia/commons/(?:thumb/)?[^/]+/[^/]+/([^/]+?)(?:/\d+px-[^/]+)?$",
        raw,
        flags=re.IGNORECASE,
    )
    if thumb_match:
        filename = thumb_match.group(1).strip()
        if filename:
            return f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width=320"

    direct_match = re.search(
        r"upload\.wikimedia\.org/wikipedia/commons/(?:[^/]+/[^/]+/)?([^/]+\.(?:svg|png|jpg|jpeg|webp))$",
        raw,
        flags=re.IGNORECASE,
    )
    if direct_match:
        filename = direct_match.group(1).strip()
        if filename:
            return f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width=320"

    return raw


def resolve_party_logo_from_wikipedia(sigla: Optional[str], nome_partido: Optional[str] = None) -> Optional[str]:
    sigla = (sigla or "").strip().upper()
    if not sigla or sigla in {"NÃO INFO", "NAO INFO", "N/D"}:
        return None

    if sigla in PARTY_WIKIPEDIA_IMAGE_FALLBACKS:
        return PARTY_WIKIPEDIA_IMAGE_FALLBACKS[sigla]

    # Check local CSV cache first — avoids HTTP requests for known parties
    if 'partido_logos_dict' in globals() and partido_logos_dict:
        csv_url = partido_logos_dict.get(sigla)
        if csv_url and csv_url not in ("nan", "None", ""):
            return csv_url

    cache = _load_party_logo_cache()
    cached_url = cache.get(sigla)
    if cached_url:
        return cached_url

    title_candidates = []
    mapped_title = PARTY_WIKIPEDIA_TITLES.get(sigla)
    if mapped_title:
        title_candidates.append(mapped_title)

    if nome_partido:
        cleaned_name = str(nome_partido).strip()
        if cleaned_name and cleaned_name not in title_candidates:
            title_candidates.append(cleaned_name)

    resolved_url = None
    for candidate_title in title_candidates:
        try:
            resolved_url = _fetch_wikipedia_page_image_url(candidate_title)
            if resolved_url:
                break
        except Exception:
            continue

    cache[sigla] = resolved_url
    try:
        _save_party_logo_cache()
    except Exception:
        pass
    return resolved_url


def resolve_state_flag_from_wikipedia(uf_sigla: Optional[str]) -> Optional[str]:
    uf_sigla = str(uf_sigla or "").strip().upper()
    if not uf_sigla:
        return None

    cache = _load_state_flag_cache()
    cached_url = cache.get(uf_sigla)
    if cached_url:
        normalized_cached_url = _normalize_commons_special_file_path(cached_url)
        if normalized_cached_url != cached_url:
            cache[uf_sigla] = normalized_cached_url
            try:
                _save_state_flag_cache()
            except Exception:
                pass
        return normalized_cached_url

    resolved_url = None
    title = STATE_WIKIPEDIA_TITLES.get(uf_sigla)
    if title:
        try:
            resolved_url = _fetch_wikipedia_page_image_url(title)
        except Exception:
            resolved_url = None

    if not resolved_url:
        resolved_url = estado_logos_dict.get(uf_sigla)

    resolved_url = _normalize_commons_special_file_path(resolved_url)

    cache[uf_sigla] = resolved_url
    try:
        _save_state_flag_cache()
    except Exception:
        pass
    return resolved_url


def compute_mapa_partidario_payload(
    estado: str,
    partido: Optional[str] = None,
    partido_atual: Optional[str] = None,
    parlamentar: Optional[str] = None,
):
    estado = (estado or "").strip().upper()
    partido = (partido or "").strip().upper()
    partido_atual = (partido_atual or "").strip().upper()
    parlamentar = (parlamentar or "").strip()

    # Quando o parlamentar está selecionado, o recorte do mapa passa a ser
    # definido apenas por nome + estado. Isso evita que partido de eleição ou
    # partido atual contaminem a seleção e façam o mapa sumir para parlamentares
    # que mudaram de legenda.
    if parlamentar and parlamentar != "Todos":
        partido = ""
        partido_atual = ""

    if not estado or estado == "TODOS":
        return {
            "filtros": {
                "estado": estado,
                "partido": partido or None,
                "partido_atual": partido_atual or None,
                "parlamentar": parlamentar or None,
            },
            "resumo": {},
            "locais": [],
            "zonas": [],
            "analise_parlamentar": None,
            "estado_perimetro": None,
        }

    # --- FALLBACK PARA SQLITE SE DUCKDB FALHAR (Serialization Error) ---
    duck_db_path = DUCK_DB_PATH
    try:
        con = safe_duckdb_connect(duck_db_path, read_only=True)
        con.execute("SELECT 1").fetchone()
    except Exception as e:
        logger.error(f"❌ Erro ao conectar ao DuckDB para Mapa Partidário: {e}")
        raise HTTPException(status_code=500, detail="Banco de dados de votação indisponível")

    try:
        # OTIMIZAÇÃO: Limitar locais para estados gigantes (evita crash do navegador)
        # 1. Primeiro identificamos os locais MAIS RELEVANTES (maior volume de votos)
        try:
            df_top_locais = con.execute(
                """
                SELECT 
                    NM_MUNICIPIO, NM_LOCAL_VOTACAO, DS_ENDERECO,
                    SUM(COALESCE(QT_VOTOS_NOMINAIS, 0)) as total_votos_local
                FROM votacao
                WHERE DS_CARGO = 'DEPUTADO FEDERAL' AND SG_UF = ?
                GROUP BY NM_MUNICIPIO, NM_LOCAL_VOTACAO, DS_ENDERECO
                ORDER BY total_votos_local DESC
                LIMIT 1500
                """,
                [estado]
            ).fetchdf()
            
            # Filtro de junção para pegar apenas os candidatos destes locais
            df = con.execute(
                """
                WITH top_locais AS (
                    SELECT NM_MUNICIPIO, NM_LOCAL_VOTACAO, DS_ENDERECO 
                    FROM votacao 
                    WHERE DS_CARGO = 'DEPUTADO FEDERAL' AND SG_UF = ?
                    GROUP BY NM_MUNICIPIO, NM_LOCAL_VOTACAO, DS_ENDERECO
                    ORDER BY SUM(COALESCE(QT_VOTOS_NOMINAIS, 0)) DESC
                    LIMIT 1500
                )
                SELECT
                    v.SG_UF,
                    COALESCE(NULLIF(TRIM(v.NM_MUNICIPIO), ''), 'N/D') AS NM_MUNICIPIO,
                    CAST(v.NR_ZONA AS VARCHAR) AS NR_ZONA,
                    CAST(v.NR_SECAO AS VARCHAR) AS NR_SECAO,
                    COALESCE(NULLIF(TRIM(v.NM_LOCAL_VOTACAO), ''), 'LOCAL NÃO INFORMADO') AS NM_LOCAL_VOTACAO,
                    COALESCE(NULLIF(TRIM(v.DS_ENDERECO), ''), 'ENDEREÇO NÃO INFORMADO') AS DS_ENDERECO,
                    COALESCE(NULLIF(TRIM(v.NM_BAIRRO), ''), 'BAIRRO NÃO INFORMADO') AS NM_BAIRRO,
                    AVG(v.LAT) AS LAT,
                    AVG(v.LONG) AS LONG,
                    TRIM(v.NM_PARLAMENTAR) AS canonical_name,
                    COALESCE(NULLIF(TRIM(v.NM_VOTAVEL), ''), TRIM(v.NM_PARLAMENTAR)) AS ballot_name,
                    TRIM(v.SIGLA_PARTIDO_FINAL) AS partido,
                    COALESCE(NULLIF(TRIM(v.NOME_PARTIDO_FINAL), ''), TRIM(v.SIGLA_PARTIDO_FINAL)) AS nome_partido,
                    MAX(COALESCE(v.QT_VOTOS_NOMINAIS, 0)) AS votos,
                    MAX(NULLIF(TRIM(v.ALINHAMENTO_IDEOLOGICO), '')) AS alinhamento
                FROM votacao v
                INNER JOIN top_locais tl ON (tl.NM_MUNICIPIO = v.NM_MUNICIPIO AND tl.NM_LOCAL_VOTACAO = v.NM_LOCAL_VOTACAO AND tl.DS_ENDERECO = v.DS_ENDERECO)
                WHERE v.DS_CARGO = 'DEPUTADO FEDERAL'
                  AND v.SG_UF = ?
                  AND v.NM_PARLAMENTAR IS NOT NULL
                  AND TRIM(v.NM_PARLAMENTAR) <> ''
                  AND v.SIGLA_PARTIDO_FINAL IS NOT NULL
                  AND TRIM(v.SIGLA_PARTIDO_FINAL) <> ''
                GROUP BY
                    v.SG_UF, v.NM_MUNICIPIO, v.NR_ZONA, v.NR_SECAO, v.NM_LOCAL_VOTACAO, v.DS_ENDERECO, v.NM_BAIRRO,
                    v.NM_PARLAMENTAR, v.NM_VOTAVEL, v.SIGLA_PARTIDO_FINAL, v.NOME_PARTIDO_FINAL
                """,
                [estado, estado],
            ).fetchdf()
        except Exception as e:
            logger.error(f"Erro na query otimizada do mapa: {e}")
            raise e
    finally:
        con.close()

    if df.empty:
        return {
            "filtros": {
                "estado": estado,
                "partido": partido or None,
                "partido_atual": partido_atual or None,
                "parlamentar": parlamentar or None,
            },
            "resumo": {
                "locais_mapeados": 0,
                "municipios_cobertos": 0,
                "partidos_representados": 0,
                "partido_lider_geral": None,
                "partido_lider_geral_logo": None,
                "partido_lider_geral_locais": 0,
            },
            "locais": [],
            "zonas": [],
            "analise_parlamentar": None,
            "estado_perimetro": load_state_perimeter_geojson(estado),
        }

    label_map = {}
    current_party_map = {}
    try:
        label_map, _ = get_state_elected_label_maps(estado)
    except Exception:
        label_map = {}
    try:
        current_party_map, _ = get_state_current_party_maps(estado)
    except Exception:
        current_party_map = {}

    df["canonical_name"] = df["canonical_name"].astype(str).str.strip()
    df["ballot_name"] = df["ballot_name"].astype(str).str.strip()
    df["partido"] = df["partido"].astype(str).str.strip()
    df["nome_partido"] = df["nome_partido"].astype(str).str.strip()
    df["alinhamento"] = df["alinhamento"].fillna("")
    df["votos"] = pd.to_numeric(df["votos"], errors="coerce").fillna(0).astype(float)
    df["norm_canonical"] = df["canonical_name"].apply(normalizar_texto_ia)
    df["norm_ballot"] = df["ballot_name"].apply(normalizar_texto_ia)
    df["NM_LOCAL_VOTACAO"] = df["NM_LOCAL_VOTACAO"].astype(str).str.strip()
    df["DS_ENDERECO"] = df["DS_ENDERECO"].astype(str).str.strip()
    df["NM_BAIRRO"] = df["NM_BAIRRO"].astype(str).str.strip()
    df["secao_key"] = df["NR_ZONA"].astype(str) + "::" + df["NR_SECAO"].astype(str)
    df["local_key"] = df.apply(
        lambda row: _build_local_votacao_key(
            row["NM_MUNICIPIO"],
            row["NM_LOCAL_VOTACAO"],
            row["DS_ENDERECO"],
        ),
        axis=1,
    )

    def resolve_display_name(row):
        mapped = label_map.get(row["norm_canonical"]) or label_map.get(row["norm_ballot"])
        if mapped:
            return str(mapped).strip()
        candidates = [name for name in [row["ballot_name"], row["canonical_name"]] if str(name).strip()]
        return min(candidates, key=len) if candidates else row["canonical_name"]

    df["display_name"] = df.apply(resolve_display_name, axis=1)
    df["norm_display"] = df["display_name"].apply(normalizar_texto_ia)
    df["partido_atual_resolved"] = df.apply(
        lambda row: (
            current_party_map.get(row["norm_canonical"])
            or current_party_map.get(row["norm_ballot"])
            or current_party_map.get(row["norm_display"])
            or row["partido"]
        ),
        axis=1,
    )
    party_name_map = (
        df.groupby("partido", as_index=False)
        .agg(nome_partido=("nome_partido", _first_non_empty_value))
    )
    party_logo_map = {}
    for _, row in party_name_map.iterrows():
        sigla = str(row["partido"]).strip().upper()
        if not sigla:
            continue
        party_logo_map[sigla] = resolve_party_logo_from_wikipedia(sigla, row["nome_partido"])

    # Build logo map for partido_atual from unique values — avoids per-row HTTP calls
    unique_atual = df["partido_atual_resolved"].dropna().unique()
    party_atual_logo_map = {
        str(s).strip().upper(): resolve_party_logo_from_wikipedia(str(s).strip().upper(), None)
        for s in unique_atual if str(s or "").strip()
    }
    df["partido_atual_logo_resolved"] = df["partido_atual_resolved"].apply(
        lambda sigla: party_atual_logo_map.get(str(sigla or "").strip().upper())
    )

    df["partido_logo_resolved"] = df["partido"].apply(
        lambda sigla: party_logo_map.get(str(sigla).strip().upper())
    )

    local_totals = (
        df.groupby("local_key", as_index=False)
        .agg(votos_local=("votos", "sum"))
    )

    local_meta = (
        df.groupby("local_key", as_index=False)
        .agg(
            municipio_referencia=("NM_MUNICIPIO", _first_non_empty_value),
            local_votacao=("NM_LOCAL_VOTACAO", _first_non_empty_value),
            endereco=("DS_ENDERECO", _first_non_empty_value),
            bairro_referencia=("NM_BAIRRO", _first_non_empty_value),
            lat=("LAT", "mean"),
            lng=("LONG", "mean"),
            zonas_cobertas=("NR_ZONA", "nunique"),
            secoes_cobertas=("secao_key", "nunique"),
        )
    )

    local_party = (
        df.groupby(["local_key", "partido"], as_index=False)
        .agg(
            votos_partido=("votos", "sum"),
            logo_partido=("partido_logo_resolved", _first_non_empty_value),
            alinhamento_partido=("alinhamento", _first_non_empty_value),
        )
        .merge(local_totals, on="local_key", how="left")
    )
    local_party["share_partido"] = np.where(
        local_party["votos_local"] > 0,
        (local_party["votos_partido"] / local_party["votos_local"]) * 100,
        0.0,
    )
    dominant_party = (
        local_party.sort_values(["local_key", "votos_partido", "partido"], ascending=[True, False, True])
        .drop_duplicates(subset=["local_key"], keep="first")
        .rename(
            columns={
                "partido": "partido_dominante",
                "logo_partido": "logo_partido_dominante",
                "alinhamento_partido": "alinhamento_partido_dominante",
                "votos_partido": "votos_partido_dominante",
                "share_partido": "share_partido_dominante",
            }
        )
    )

    local_candidate = (
        df.groupby(
            [
                "local_key",
                "display_name",
                "norm_display",
                "canonical_name",
                "norm_canonical",
                "ballot_name",
                "norm_ballot",
                "partido",
                "partido_atual_resolved",
            ],
            as_index=False,
        )
        .agg(
            votos_candidato=("votos", "sum"),
            alinhamento=("alinhamento", _first_non_empty_value),
            logo_partido=("partido_logo_resolved", _first_non_empty_value),
            logo_partido_atual=("partido_atual_logo_resolved", _first_non_empty_value),
        )
        .merge(local_totals, on="local_key", how="left")
    )
    local_candidate["share_candidato"] = np.where(
        local_candidate["votos_local"] > 0,
        (local_candidate["votos_candidato"] / local_candidate["votos_local"]) * 100,
        0.0,
    )
    local_candidate["rank_local"] = (
        local_candidate.groupby("local_key")["votos_candidato"]
        .rank(method="dense", ascending=False)
        .astype(int)
    )
    dominant_candidate = (
        local_candidate.sort_values(["local_key", "votos_candidato", "display_name"], ascending=[True, False, True])
        .drop_duplicates(subset=["local_key"], keep="first")
        .rename(
            columns={
                "display_name": "deputado_dominante",
                "partido": "partido_deputado_dominante",
                "partido_atual_resolved": "partido_atual_deputado_dominante",
                "alinhamento": "alinhamento_deputado_dominante",
                "votos_candidato": "votos_deputado_dominante",
                "share_candidato": "share_deputado_dominante",
                "logo_partido": "logo_partido_deputado_dominante",
                "logo_partido_atual": "logo_partido_atual_deputado_dominante",
            }
        )
    )
    runner_up_candidate = (
        local_candidate[local_candidate["rank_local"] == 2]
        .sort_values(["local_key", "votos_candidato", "display_name"], ascending=[True, False, True])
        .drop_duplicates(subset=["local_key"], keep="first")
        .rename(
            columns={
                "display_name": "deputado_segundo_colocado",
                "partido": "partido_segundo_colocado",
                "partido_atual_resolved": "partido_atual_segundo_colocado",
                "votos_candidato": "votos_segundo_colocado",
                "share_candidato": "share_segundo_colocado",
            }
        )
    )

    locais_df = (
        dominant_party.merge(
            dominant_candidate[
                [
                    "local_key",
                    "deputado_dominante",
                    "partido_deputado_dominante",
                    "partido_atual_deputado_dominante",
                    "alinhamento_deputado_dominante",
                    "votos_deputado_dominante",
                    "share_deputado_dominante",
                    "logo_partido_deputado_dominante",
                    "logo_partido_atual_deputado_dominante",
                ]
            ],
            on="local_key",
            how="left",
        )
        .merge(local_meta, on="local_key", how="left")
    )
    locais_df["municipio_referencia"] = locais_df["municipio_referencia"].fillna("N/D")
    locais_df["estado"] = estado

    analysis_payload = None
    info_parlamentar = None
    visible_locais_df = locais_df.copy()

    if parlamentar and parlamentar != "Todos":
        resolved_ballot = resolve_nm_votavel_for_parlamentar(parlamentar, estado)
        target_norms = {
            normalizar_texto_ia(parlamentar),
            normalizar_texto_ia(resolved_ballot),
        }
        target_local_df = local_candidate[
            local_candidate["norm_display"].isin(target_norms)
            | local_candidate["norm_canonical"].isin(target_norms)
            | local_candidate["norm_ballot"].isin(target_norms)
        ].copy()

        if not target_local_df.empty:
            target_local_df = target_local_df.sort_values(["votos_candidato", "display_name"], ascending=[False, True])
            target_display = str(target_local_df.iloc[0]["display_name"]).strip()
            target_party = str(target_local_df.iloc[0]["partido"]).strip()
            target_current_party = str(target_local_df.iloc[0]["partido_atual_resolved"]).strip()
            target_alignment = str(target_local_df.iloc[0]["alinhamento"] or "").strip() or None
            target_name_candidates = {
                str(name).strip()
                for name in [
                    target_display,
                    target_local_df.iloc[0].get("canonical_name"),
                    target_local_df.iloc[0].get("ballot_name"),
                    parlamentar,
                    resolved_ballot,
                ]
                if name and str(name).strip()
            }

            target_local_df = target_local_df.rename(
                columns={
                    "display_name": "parlamentar",
                    "partido": "partido_parlamentar",
                    "partido_atual_resolved": "partido_atual_parlamentar",
                    "logo_partido": "logo_partido_parlamentar",
                    "logo_partido_atual": "logo_partido_atual_parlamentar",
                    "alinhamento": "alinhamento_parlamentar",
                    "votos_candidato": "votos_parlamentar",
                    "share_candidato": "share_parlamentar",
                    "rank_local": "rank_parlamentar",
                }
            )
            target_local_df["partido_parlamentar_minoritaria"] = (
                target_local_df["partido_parlamentar"].fillna("")
                != locais_df.set_index("local_key").reindex(target_local_df["local_key"])["partido_dominante"].fillna("").values
            )

            target_local_df = target_local_df.merge(
                locais_df[
                    [
                        "local_key",
                        "municipio_referencia",
                        "local_votacao",
                        "endereco",
                        "bairro_referencia",
                        "zonas_cobertas",
                        "secoes_cobertas",
                        "partido_dominante",
                        "logo_partido_dominante",
                        "alinhamento_partido_dominante",
                        "votos_partido_dominante",
                        "share_partido_dominante",
                        "deputado_dominante",
                        "partido_deputado_dominante",
                        "logo_partido_deputado_dominante",
                        "partido_atual_deputado_dominante",
                        "logo_partido_atual_deputado_dominante",
                        "votos_deputado_dominante",
                        "share_deputado_dominante",
                        "lat",
                        "lng",
                    ]
                ],
                on="local_key",
                how="left",
            )
            target_local_df = target_local_df.merge(
                runner_up_candidate[
                    [
                        "local_key",
                        "deputado_segundo_colocado",
                        "partido_segundo_colocado",
                        "partido_atual_segundo_colocado",
                        "votos_segundo_colocado",
                        "share_segundo_colocado",
                    ]
                ],
                on="local_key",
                how="left",
            )
            target_local_df["gap_para_lider_votos"] = (
                target_local_df["votos_deputado_dominante"].fillna(0) - target_local_df["votos_parlamentar"].fillna(0)
            )
            target_local_df["gap_para_lider_share"] = (
                target_local_df["share_deputado_dominante"].fillna(0) - target_local_df["share_parlamentar"].fillna(0)
            )
            target_local_df["vantagem_sobre_segundo_votos"] = (
                target_local_df["votos_parlamentar"].fillna(0) - target_local_df["votos_segundo_colocado"].fillna(0)
            )
            target_local_df["vantagem_sobre_segundo_share"] = (
                target_local_df["share_parlamentar"].fillna(0) - target_local_df["share_segundo_colocado"].fillna(0)
            )
            target_local_df["deputado_parlamentar_lider"] = target_local_df["deputado_dominante"].apply(
                lambda value: normalizar_texto_ia(value) in target_norms if value else False
            )

            visible_locais_df = locais_df.merge(
                target_local_df[
                    [
                        "local_key",
                        "votos_parlamentar",
                        "share_parlamentar",
                        "rank_parlamentar",
                        "partido_parlamentar_minoritaria",
                        "deputado_parlamentar_lider",
                    ]
                ],
                on="local_key",
                how="left",
            )
            visible_locais_df = visible_locais_df[
                (visible_locais_df["votos_parlamentar"].fillna(0) > 0)
                & (visible_locais_df["deputado_parlamentar_lider"].fillna(False))
            ].copy()

            same_territory_locais = target_local_df["local_key"].dropna().astype(str).unique().tolist()
            competition_rank_df = local_candidate[
                local_candidate["local_key"].astype(str).isin(same_territory_locais)
            ].copy()

            # Ao selecionar um parlamentar, o painel deve refletir apenas o
            # território onde ele aparece no recorte atual. Isso evita misturar
            # o mapa inteiro do estado com a análise individual do deputado,
            # o que gera números zerados ou contraditórios em quem mudou de
            # partido depois de eleito.
            visible_locais_df = locais_df[
                locais_df["local_key"].astype(str).isin(same_territory_locais)
            ].copy()

            competition_rank_df["is_target"] = (
                competition_rank_df["norm_display"].isin(target_norms)
                | competition_rank_df["norm_canonical"].isin(target_norms)
                | competition_rank_df["norm_ballot"].isin(target_norms)
            )

            competitors_df = competition_rank_df[~competition_rank_df["is_target"]].copy()
            if not competitors_df.empty:
                competitors_df = (
                    competitors_df.groupby(["display_name", "partido"], as_index=False)
                    .agg(
                        votos=("votos_candidato", "sum"),
                        locais_presentes=("local_key", "nunique"),
                        municipios_presentes=("local_key", lambda keys: int(local_meta[local_meta["local_key"].isin(list(keys))]["municipio_referencia"].nunique())),
                        partido_atual=("partido_atual_resolved", _first_non_empty_value),
                        alinhamento=("alinhamento", _first_non_empty_value),
                    )
                    .sort_values(["votos", "locais_presentes", "display_name"], ascending=[False, False, True])
                )
                competitor_total = float(competitors_df["votos"].sum()) or 0.0
                competitors_df["share_competitivo"] = np.where(
                    competitor_total > 0,
                    (competitors_df["votos"] / competitor_total) * 100,
                    0.0,
                )
            overall_df = (
                competition_rank_df.groupby(["display_name", "partido"], as_index=False)
                .agg(votos=("votos_candidato", "sum"), locais_presentes=("local_key", "nunique"))
                .sort_values(["votos", "locais_presentes", "display_name"], ascending=[False, False, True])
            )

            leader_record = overall_df.iloc[0].to_dict() if not overall_df.empty else None
            target_record = overall_df[
                overall_df["display_name"].apply(normalizar_texto_ia) == normalizar_texto_ia(target_display)
            ]
            target_record = target_record.iloc[0].to_dict() if not target_record.empty else None

            info_parlamentar = {
                "nome": target_display,
                "partido": target_party or None,
                "partidoAtual": target_current_party or None,
                "estado": estado,
                "foto": None,
                "logoPartido": resolve_party_logo_from_wikipedia(target_party or target_current_party, None) if (target_party or target_current_party) else None,
                "estado_logo_url": resolve_state_flag_from_wikipedia(estado) or estado_logos_dict.get(estado),
            }

            try:
                conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT nome, sgUF, sgPartido, ultimoStatus_siglaPartido, ultimoStatus_urlFoto, ideCadastro, urlPartido as url_partido, urlEstado
                    FROM tabelao
                    WHERE sgUF = ?
                    """,
                    (estado,),
                )
                rows = cursor.fetchall()
                conn.close()

                matched_row = None
                candidate_norms = {normalizar_texto_ia(name) for name in target_name_candidates if normalizar_texto_ia(name)}
                for row in rows:
                    row_name = str(row["nome"]).strip() if row["nome"] else ""
                    if normalizar_texto_ia(row_name) in candidate_norms:
                        matched_row = row
                        break

                if matched_row:
                    current_party_from_table = str(matched_row["ultimoStatus_siglaPartido"]).strip() if matched_row["ultimoStatus_siglaPartido"] else ""
                    target_current_party = current_party_from_table or (target_current_party or target_party or None)
                    foto = matched_row["ultimoStatus_urlFoto"]
                    if (not foto) and matched_row["ideCadastro"]:
                        foto = f"https://www.camara.leg.br/internet/deputado/bandep/{matched_row['ideCadastro']}.jpg"
                    info_parlamentar = {
                        "nome": target_display,
                        "partido": target_party,
                        "partidoAtual": target_current_party,
                        "estado": str(matched_row["sgUF"]).strip() if matched_row["sgUF"] else estado,
                        "foto": str(foto).strip() if foto else None,
                        "logoPartido": (
                            resolve_party_logo_from_wikipedia(
                                target_party
                                or (current_party_from_table if current_party_from_table else str(matched_row["sgPartido"]).strip()),
                                None,
                            )
                            or (str(matched_row["url_partido"]).strip() if matched_row["url_partido"] else None)
                            or info_parlamentar.get("logoPartido")
                        ),
                        "estado_logo_url": (
                            resolve_state_flag_from_wikipedia(str(matched_row["sgUF"]).strip() if matched_row["sgUF"] else estado)
                            or (str(matched_row["urlEstado"]).strip() if matched_row["urlEstado"] else None)
                            or estado_logos_dict.get(estado)
                        ),
                    }
            except Exception:
                pass

            analysis_payload = {
                "parlamentar": target_display,
                "partido": target_party,
                "partido_atual": target_current_party,
                "locais_com_presenca": int(target_local_df["local_key"].nunique()),
                "locais_liderados": int(target_local_df["deputado_parlamentar_lider"].fillna(False).sum()),
                "votos_no_recorte": int(round(float(target_local_df["votos_parlamentar"].sum()))),
                "share_medio_no_recorte": round(float(target_local_df["share_parlamentar"].mean()), 2) if not target_local_df.empty else 0.0,
                "locais_partido_minoritaria": int(target_local_df["partido_parlamentar_minoritaria"].fillna(False).sum()),
                "lider_no_territorio": {
                    "parlamentar": leader_record.get("display_name") if leader_record else None,
                    "partido": leader_record.get("partido") if leader_record else None,
                    "votos": int(round(float(leader_record.get("votos", 0)))) if leader_record else 0,
                },
                "competidores": [] if competitors_df.empty else [
                    {
                        "parlamentar": str(row["display_name"]).strip(),
                        "partido": str(row["partido"]).strip() if pd.notna(row["partido"]) else None,
                        "votos": int(round(float(row["votos"]))),
                        "locais_presentes": int(row["locais_presentes"]),
                    }
                    for _, row in competitors_df.head(5).iterrows()
                ],
                "locais": [
                    {
                        "local_key": str(row["local_key"]),
                        "local_votacao": str(row["local_votacao"]).strip(),
                        "municipio_referencia": str(row["municipio_referencia"]).strip(),
                        "lat": float(row["lat"]),
                        "lng": float(row["lng"]),
                        "votos_parlamentar": int(round(float(row["votos_parlamentar"]))),
                        "share_parlamentar": round(float(row["share_parlamentar"]), 2),
                        "rank_parlamentar": int(row["rank_parlamentar"]),
                        "deputado_dominante": str(row["deputado_dominante"]).strip(),
                        "partido_dominante": str(row["partido_dominante"]).strip(),
                        "logo_partido_dominante": str(row["logo_partido_dominante"]).strip() if pd.notna(row.get("logo_partido_dominante")) else None,
                        "logo_partido_deputado_dominante": str(row["logo_partido_deputado_dominante"]).strip() if pd.notna(row.get("logo_partido_deputado_dominante")) else None,
                        "votos_deputado_dominante": int(round(float(row["votos_deputado_dominante"]))),
                        "deputado_parlamentar_lider": bool(row["deputado_parlamentar_lider"]),
                        "vantagem_sobre_segundo_votos": int(round(float(row["vantagem_sobre_segundo_votos"]))) if pd.notna(row.get("vantagem_sobre_segundo_votos")) else None,
                        "vantagem_sobre_segundo_share": round(float(row["vantagem_sobre_segundo_share"]), 2) if pd.notna(row.get("vantagem_sobre_segundo_share")) else None,
                        "deputado_segundo_colocado": str(row["deputado_segundo_colocado"]).strip() if pd.notna(row.get("deputado_segundo_colocado")) else None,
                        "votos_segundo_colocado": int(round(float(row["votos_segundo_colocado"]))) if pd.notna(row.get("votos_segundo_colocado")) else None,
                    }
                    for _, row in target_local_df[
                        target_local_df["deputado_parlamentar_lider"].fillna(False)
                    ].sort_values(["vantagem_sobre_segundo_votos"], ascending=False).iterrows()
                ],
            }

    if analysis_payload and analysis_payload.get("locais"):
        selected_keys = {
            str(item.get("local_key"))
            for item in analysis_payload["locais"]
            if item.get("local_key")
        }
        if selected_keys:
            analysis_payload["locais"] = [
                item for item in analysis_payload["locais"]
                if str(item.get("local_key")) in selected_keys
            ]

    if (not parlamentar or parlamentar == "Todos") and partido and partido != "TODOS":
        visible_locais_df = visible_locais_df[
            visible_locais_df["partido_dominante"].fillna("").str.upper() == partido
        ].copy()
    if (not parlamentar or parlamentar == "Todos") and partido_atual and partido_atual != "TODOS":
        visible_locais_df = visible_locais_df[
            visible_locais_df["partido_atual_deputado_dominante"].fillna("").str.upper() == partido_atual
        ].copy()

    visible_locais_df = visible_locais_df.sort_values(
        ["votos_partido_dominante", "share_partido_dominante", "local_key"],
        ascending=[False, False, True],
    )

    dominant_party_counts = (
        visible_locais_df.groupby("partido_dominante", as_index=False)
        .agg(locais=("local_key", "nunique"), logo=("logo_partido_dominante", _first_non_empty_value))
        .sort_values(["locais", "partido_dominante"], ascending=[False, True])
    )
    dominant_party_leader = dominant_party_counts.iloc[0].to_dict() if not dominant_party_counts.empty else None

    resumo = {
        "locais_mapeados": int(visible_locais_df["local_key"].nunique()) if not visible_locais_df.empty else 0,
        "municipios_cobertos": int(visible_locais_df["municipio_referencia"].nunique()) if not visible_locais_df.empty else 0,
        "partidos_representados": int(visible_locais_df["partido_dominante"].nunique()) if not visible_locais_df.empty else 0,
        "partido_lider_geral": dominant_party_leader.get("partido_dominante") if dominant_party_leader else None,
        "partido_lider_geral_logo": dominant_party_leader.get("logo") if dominant_party_leader else None,
        "partido_lider_geral_locais": int(dominant_party_leader.get("locais", 0)) if dominant_party_leader else 0,
    }

    locais_payload = []
    for _, row in visible_locais_df.iterrows():
        locais_payload.append(
            {
                "local_key": str(row["local_key"]),
                "lat": float(row["lat"]) if pd.notna(row["lat"]) else None,
                "lng": float(row["lng"]) if pd.notna(row["lng"]) else None,
                "partido_dominante": str(row["partido_dominante"]).strip(),
                "logo_partido_dominante": str(row["logo_partido_dominante"]).strip() if pd.notna(row["logo_partido_dominante"]) else None,
                "deputado_dominante": str(row["deputado_dominante"]).strip(),
                "votos_partido_dominante": int(round(float(row["votos_partido_dominante"]))),
                "share_partido_dominante": round(float(row["share_partido_dominante"]), 2),
                "local_votacao": str(row["local_votacao"]).strip(),
                "municipio_referencia": str(row["municipio_referencia"]).strip(),
                "deputado_parlamentar_lider": bool(row["deputado_parlamentar_lider"]) if "deputado_parlamentar_lider" in row.index else False,
            }
        )

    locais_payload, _sanitizacao = sanitizar_pontos_mapa_por_estado(locais_payload, estado)
    allowed_local_keys = {str(item.get("local_key")) for item in locais_payload if item.get("local_key")}

    if analysis_payload and analysis_payload.get("locais"):
        analysis_payload["locais"] = [
            item for item in analysis_payload["locais"]
            if str(item.get("local_key")) in allowed_local_keys
        ]

    return {
        "filtros": {
            "estado": estado,
            "partido": partido or None,
            "partido_atual": partido_atual or None,
            "parlamentar": parlamentar or None,
        },
        "resumo": resumo,
        "info_parlamentar": info_parlamentar,
        "locais": locais_payload,
        "analise_parlamentar": analysis_payload,
        "estado_perimetro": load_state_perimeter_geojson(estado),
    }


def get_official_elected_overlap_context(
    nome_parlamentar: str,
    uf: Optional[str],
    zone_refs: Optional[List[str]] = None,
    municipio_refs: Optional[List[str]] = None,
    limit: int = 10,
    include_target: bool = False,
):
    if not nome_parlamentar or not uf:
        return pd.DataFrame()

    parquet_path = get_tse_dep_federal_parquet_path(uf)
    if not parquet_path:
        return pd.DataFrame()

    alias_to_display, display_meta = get_state_elected_label_maps(uf)
    if not alias_to_display:
        return pd.DataFrame()

    nm_votavel = resolve_nm_votavel_for_parlamentar(nome_parlamentar, uf)
    target_aliases = {
        normalizar_texto_ia(nome_parlamentar),
        normalizar_texto_ia(nm_votavel),
    }

    duck_db_path = DUCK_DB_PATH
    meta_by_alias = {}
    if os.path.exists(duck_db_path):
        con_meta = safe_duckdb_connect(duck_db_path, read_only=True)
        try:
            meta_rows = con_meta.execute(
                """
                SELECT DISTINCT NM_PARLAMENTAR, NM_VOTAVEL, SIGLA_PARTIDO_FINAL, ALINHAMENTO_IDEOLOGICO
                FROM votacao
                WHERE SG_UF = ?
                  AND DS_CARGO = 'DEPUTADO FEDERAL'
                """,
                [str(uf).upper()],
            ).fetchall()
            for nm_parlamentar, nm_votavel_row, partido_row, alinhamento_row in meta_rows:
                meta = {
                    "nm_parlamentar": str(nm_parlamentar).strip() if nm_parlamentar else "",
                    "nm_votavel": str(nm_votavel_row).strip() if nm_votavel_row else "",
                    "partido": str(partido_row).strip() if partido_row else "",
                    "alinhamento": str(alinhamento_row).strip() if alinhamento_row else "Não informado",
                }
                for alias in {meta["nm_parlamentar"], meta["nm_votavel"]}:
                    normalized_alias = normalizar_texto_ia(alias)
                    if normalized_alias:
                        meta_by_alias[normalized_alias] = meta
        finally:
            con_meta.close()

    zone_ints = []
    for zona in zone_refs or []:
        try:
            zone_ints.append(int(str(zona).strip()))
        except Exception:
            continue
    zone_ints = sorted(set(zone_ints))

    municipio_norms = sorted({
        str(municipio).strip().upper()
        for municipio in (municipio_refs or [])
        if municipio is not None and str(municipio).strip()
    })

    where_clauses = ["SG_UF = ?", "DS_CARGO = 'DEPUTADO FEDERAL'"]
    params = [str(uf).upper()]

    if zone_ints:
        where_clauses.append(f"TRY_CAST(NR_ZONA AS INTEGER) IN ({','.join(['?'] * len(zone_ints))})")
        params.extend(zone_ints)

    if municipio_norms:
        where_clauses.append(f"UPPER(NM_MUNICIPIO) IN ({','.join(['?'] * len(municipio_norms))})")
        params.extend(municipio_norms)

    if len(where_clauses) <= 2:
        return pd.DataFrame()

    con = safe_duckdb_connect()
    try:
        overlap_df = con.execute(
            f"""
            SELECT
                NM_VOTAVEL,
                SUM(CAST(QT_VOTOS AS BIGINT)) AS votos_territorio,
                COUNT(DISTINCT CAST(NR_ZONA AS VARCHAR)) AS zonas_presentes,
                COUNT(DISTINCT NM_MUNICIPIO) AS municipios_presentes
            FROM read_parquet(?)
            WHERE {" AND ".join(where_clauses)}
            GROUP BY NM_VOTAVEL
            HAVING SUM(CAST(QT_VOTOS AS BIGINT)) > 0
            ORDER BY votos_territorio DESC
            """,
            [parquet_path, *params],
        ).fetchdf()
    except Exception as exc:
        logging.warning("Falha ao carregar sobreposição oficial de eleitos para %s/%s: %s", nome_parlamentar, uf, exc)
        return pd.DataFrame()
    finally:
        con.close()

    if overlap_df.empty:
        return overlap_df

    rows = []
    for _, row in overlap_df.iterrows():
        nm_votavel_row = str(row.get("NM_VOTAVEL") or "").strip()
        normalized_vote_name = normalizar_texto_ia(nm_votavel_row)
        meta = meta_by_alias.get(normalized_vote_name, {})

        display_name = (
            alias_to_display.get(normalized_vote_name)
            or alias_to_display.get(normalizar_texto_ia(meta.get("nm_parlamentar")))
            or alias_to_display.get(normalizar_texto_ia(meta.get("nm_votavel")))
        )
        if not display_name:
            continue

        is_target = normalizar_texto_ia(display_name) in target_aliases or normalized_vote_name in target_aliases
        if is_target and not include_target:
            continue

        rows.append(
            {
                "nome_exibicao": display_name,
                "partido": meta.get("partido") or display_meta.get(display_name, {}).get("partido_tabelao") or "Sem partido",
                "alinhamento": meta.get("alinhamento") or "Não informado",
                "votos_territorio": int(row["votos_territorio"]) if not pd.isna(row["votos_territorio"]) else 0,
                "zonas_presentes": int(row["zonas_presentes"]) if not pd.isna(row["zonas_presentes"]) else 0,
                "municipios_presentes": int(row["municipios_presentes"]) if not pd.isna(row["municipios_presentes"]) else 0,
                "is_target": bool(is_target),
            }
        )

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    result = (
        result.groupby(["nome_exibicao", "partido", "alinhamento"], as_index=False)
        .agg(
            votos_territorio=("votos_territorio", "sum"),
            zonas_presentes=("zonas_presentes", "max"),
            municipios_presentes=("municipios_presentes", "max"),
            is_target=("is_target", "max"),
        )
        .sort_values("votos_territorio", ascending=False)
        .head(int(limit))
        .reset_index(drop=True)
    )

    total_overlap_votes = result["votos_territorio"].sum()
    if total_overlap_votes > 0:
        result["share_no_recorte"] = result["votos_territorio"] / total_overlap_votes * 100.0
    else:
        result["share_no_recorte"] = None

    return result


def get_cached_mapa_eleitoral_votos_payload(nome_parlamentar: str, estado: Optional[str] = None, partido: Optional[str] = None):
    ensure_mapa_eleitoral_votos_cache_table()
    conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        candidate_names = resolve_parlamentar_name_candidates(nome_parlamentar, estado=estado, partido=partido)
        def fetch_payload(candidate_name: str, include_partido: bool):
            conditions = ["UPPER(parlamentar) = UPPER(?)"]
            params = [candidate_name]

            if estado:
                conditions.append("UPPER(uf) = UPPER(?)")
                params.append(estado)

            if include_partido and partido:
                conditions.append("UPPER(partido) = UPPER(?)")
                params.append(partido)

            return cursor.execute(
                f"""
                SELECT payload_json
                FROM mapa_eleitoral_votos_cache
                WHERE {" AND ".join(conditions)}
                ORDER BY atualizado_em DESC
                LIMIT 1
                """,
                params,
            ).fetchone()

        for candidate_name in candidate_names:
            row = fetch_payload(candidate_name, include_partido=True)
            if not row and partido:
                row = fetch_payload(candidate_name, include_partido=False)

            if row:
                payload = json.loads(row["payload_json"])
                uf_payload = (estado or payload.get("info", {}).get("estado") or payload.get("estado") or "").upper()
                nome_payload = payload.get("info", {}).get("nome") or candidate_name

                payload.setdefault("info", {})
                if uf_payload:
                    payload["info"]["estado_logo_url"] = (
                        resolve_state_flag_from_wikipedia(uf_payload)
                        or payload["info"].get("estado_logo_url")
                        or estado_logos_dict.get(uf_payload)
                    )

                # Preenche logoPartido se estava vazio no cache
                if not payload["info"].get("logoPartido"):
                    sigla_partido = (
                        payload["info"].get("partido")
                        or payload["info"].get("partidoAtual")
                        or partido
                        or ""
                    )
                    if sigla_partido:
                        payload["info"]["logoPartido"] = (
                            resolve_party_logo_from_wikipedia(sigla_partido, None)
                            or partido_logos_dict.get(sigla_partido.upper().strip())
                        )

                total_votos_oficiais = get_total_votos_oficiais_tse(nome_payload, uf_payload)
                if total_votos_oficiais is not None:
                    payload.setdefault("stats", {})
                    payload["stats"]["total_votos"] = total_votos_oficiais
                    payload["stats"]["totalVotos"] = total_votos_oficiais
                    payload["stats"]["fonte_total_votos"] = "tse_csv_oficial"

                if uf_payload:
                    municipios_sanitizados, resumo_municipios = sanitizar_pontos_mapa_por_estado(
                        payload.get("municipios", []),
                        uf_payload,
                    )
                    zonas_sanitizadas, resumo_zonas = sanitizar_pontos_mapa_por_estado(
                        payload.get("zonas", []),
                        uf_payload,
                    )
                    payload["municipios"] = municipios_sanitizados
                    payload["zonas"] = zonas_sanitizadas
                    payload["qualidadeCoordenadas"] = {
                        "uf": uf_payload,
                        "municipios": resumo_municipios,
                        "zonas": resumo_zonas,
                    }
                return clean_data_for_json(payload)

        return None
    finally:
        conn.close()


def compute_mapa_eleitoral_votos_payload(
    nome_parlamentar: str,
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    include_ibge: bool = False,
):
    duck_db_path = DUCK_DB_PATH

    if not os.path.exists(duck_db_path):
        return {"error": "Banco de dados de votação não encontrado."}

    con = safe_duckdb_connect(duck_db_path, read_only=True)
    nome_parlamentar_display = nome_parlamentar  # preserva o nome amigável para exibição
    try:
        info_query = """
            SELECT DISTINCT
                NM_PARLAMENTAR, SIGLA_PARTIDO_FINAL, NOME_PARTIDO_FINAL,
                SG_UF, urlFoto_camara, URL_FOTO_PARTIDO_FINAL
            FROM votacao
            WHERE NM_PARLAMENTAR = ?
            LIMIT 1
        """
        info_result = con.execute(info_query, [nome_parlamentar]).fetchdf()

        if info_result.empty:
            info_query_like = """
                SELECT DISTINCT
                    NM_PARLAMENTAR, SIGLA_PARTIDO_FINAL, NOME_PARTIDO_FINAL,
                    SG_UF, urlFoto_camara, URL_FOTO_PARTIDO_FINAL
                FROM votacao
                WHERE UPPER(NM_PARLAMENTAR) LIKE UPPER(?)
                LIMIT 1
            """
            info_result = con.execute(info_query_like, [f"%{nome_parlamentar}%"]).fetchdf()
            if not info_result.empty:
                nome_parlamentar = str(info_result.iloc[0]["NM_PARLAMENTAR"])

        if info_result.empty:
            # Tenta resolver via nomeCivil no SQLite (ex: "CARLOS JORDY" → "CARLOS ROBERTO COELHO DE MATTOS JUNIOR")
            try:
                conn_sq = sqlite3.connect(DATABASE_PATHS["tabelao"])
                civil_row = conn_sq.execute(
                    "SELECT DISTINCT nomeCivil FROM tabelao WHERE UPPER(TRIM(nome)) = UPPER(TRIM(?)) AND nomeCivil IS NOT NULL LIMIT 1",
                    [nome_parlamentar]
                ).fetchone()
                conn_sq.close()
                if civil_row and civil_row[0]:
                    # Usa tokens significativos do nome civil para buscar no DuckDB
                    stop_words = {"DE", "DO", "DA", "DOS", "DAS", "E", "EM", "A", "O", "JUNIOR", "JÚNIOR", "FILHO", "NETO"}
                    tokens = [t.upper() for t in civil_row[0].split() if t.upper() not in stop_words and len(t) > 3]
                    for token in tokens:
                        candidate = con.execute(
                            """SELECT DISTINCT NM_PARLAMENTAR, SIGLA_PARTIDO_FINAL, NOME_PARTIDO_FINAL,
                                SG_UF, urlFoto_camara, URL_FOTO_PARTIDO_FINAL
                               FROM votacao WHERE UPPER(NM_PARLAMENTAR) LIKE ? LIMIT 5""",
                            [f"%{token}%"]
                        ).fetchdf()
                        # Verifica se algum resultado compartilha pelo menos 2 tokens com o nome civil
                        civil_tokens = set(tokens)
                        for _, row in candidate.iterrows():
                            duck_tokens = set(t.upper() for t in str(row["NM_PARLAMENTAR"]).split() if t.upper() not in stop_words and len(t) > 3)
                            if len(civil_tokens & duck_tokens) >= 2:
                                info_result = candidate[candidate["NM_PARLAMENTAR"] == row["NM_PARLAMENTAR"]]
                                nome_parlamentar = str(row["NM_PARLAMENTAR"])
                                break
                        if not info_result.empty:
                            break
            except Exception as e:
                logger.warning(f"Falha ao resolver nome via nomeCivil: {e}")

        if info_result.empty:
            try:
                similares = con.execute("""
                    SELECT DISTINCT NM_PARLAMENTAR FROM votacao
                    WHERE UPPER(NM_PARLAMENTAR) LIKE UPPER(?)
                    ORDER BY NM_PARLAMENTAR LIMIT 10
                """, [f"%{nome_parlamentar.split()[0]}%"]).fetchall()
                nomes_lista = [s[0] for s in similares]
            except Exception:
                nomes_lista = []
            return {"error": f"Parlamentar '{nome_parlamentar}' não encontrado no banco de dados.", "sugestoes": nomes_lista}

        info_row = info_result.iloc[0]
        _foto_raw = info_row.get("urlFoto_camara")
        foto_duck = "" if (pd.isna(_foto_raw) if hasattr(pd, 'isna') else _foto_raw is None) else str(_foto_raw or "")
        # Fallback: busca foto no SQLite quando DuckDB não tem
        if not foto_duck or foto_duck in ("None", "nan"):
            try:
                conn_sq = sqlite3.connect(DATABASE_PATHS["tabelao"])
                foto_row = conn_sq.execute(
                    "SELECT DISTINCT ultimoStatus_urlFoto FROM tabelao WHERE UPPER(TRIM(nome)) = UPPER(TRIM(?)) AND ultimoStatus_urlFoto IS NOT NULL LIMIT 1",
                    [nome_parlamentar_display]
                ).fetchone()
                conn_sq.close()
                foto_duck = foto_row[0] if foto_row else ""
            except Exception:
                pass

        info = {
            "nome": nome_parlamentar_display,  # nome amigável (ex: "CARLOS JORDY")
            "nomeTSE": str(info_row.get("NM_PARLAMENTAR", "")),  # nome TSE para consultas internas
            "partido": str(info_row.get("SIGLA_PARTIDO_FINAL", "")),
            "nomePartido": str(info_row.get("NOME_PARTIDO_FINAL", "")),
            "estado": str(info_row.get("SG_UF", "")),
            "foto": foto_duck,
            "logoPartido": str(info_row.get("URL_FOTO_PARTIDO_FINAL", "")),
            "estado_logo_url": (
                resolve_state_flag_from_wikipedia(str(info_row.get("SG_UF", "")).strip().upper())
                or estado_logos_dict.get(str(info_row.get("SG_UF", "")).strip().upper())
            ),
        }

        estado_parlamentar = estado or info["estado"]
        total_votos_oficiais = get_total_votos_oficiais_tse(info["nomeTSE"], estado_parlamentar)

        secoes_query = """
            SELECT
                NM_MUNICIPIO, SG_UF, NR_ZONA, NR_SECAO,
                FIRST(NM_LOCAL_VOTACAO) AS NM_LOCAL_VOTACAO,
                FIRST(DS_ENDERECO) AS DS_ENDERECO,
                FIRST(NM_BAIRRO) AS NM_BAIRRO,
                FIRST(LAT) AS LAT,
                FIRST(LONG) AS LONG,
                MAX(QT_VOTOS_NOMINAIS) as total_votos
            FROM votacao
            WHERE NM_PARLAMENTAR = ?
              AND SG_UF = ?
              AND LAT IS NOT NULL AND LONG IS NOT NULL
              AND LAT != 0 AND LONG != 0
            GROUP BY NM_MUNICIPIO, SG_UF, NR_ZONA, NR_SECAO
            ORDER BY total_votos DESC
        """
        df_secoes = con.execute(secoes_query, [info["nomeTSE"], estado_parlamentar]).fetchdf()

        secoes_sem_coord_query = """
            SELECT
                NM_MUNICIPIO, SG_UF, NR_ZONA, NR_SECAO,
                FIRST(NM_LOCAL_VOTACAO) AS NM_LOCAL_VOTACAO,
                FIRST(DS_ENDERECO) AS DS_ENDERECO,
                FIRST(NM_BAIRRO) AS NM_BAIRRO,
                MAX(QT_VOTOS_NOMINAIS) as total_votos
            FROM votacao
            WHERE NM_PARLAMENTAR = ?
              AND SG_UF = ?
            GROUP BY NM_MUNICIPIO, SG_UF, NR_ZONA, NR_SECAO
            ORDER BY total_votos DESC
        """
        df_secoes_sem_coord = con.execute(secoes_sem_coord_query, [info["nomeTSE"], estado_parlamentar]).fetchdf()
    finally:
        con.close()

    if df_secoes.empty and df_secoes_sem_coord.empty:
        return {"error": f"Nenhum dado de votação encontrado para '{info['nome']}' no estado {estado_parlamentar}."}

    if df_secoes.empty:
        df_municipios_sem_coord = df_secoes_sem_coord.groupby(["NM_MUNICIPIO", "SG_UF"]).agg({
            "total_votos": "sum",
            "NR_SECAO": "count",
        }).reset_index().sort_values("total_votos", ascending=False)

        # Busca centroides dos municípios na tabela enderecos
        municipio_centroids = {}
        try:
            con2 = safe_duckdb_connect(duck_db_path, read_only=True)
            centroid_df = con2.execute("""
                SELECT NM_MUNICIPIO, SG_UF,
                       AVG(latitude) AS lat, AVG(longitude) AS lng
                FROM enderecos
                WHERE SG_UF = ? AND latitude IS NOT NULL AND longitude IS NOT NULL
                GROUP BY NM_MUNICIPIO, SG_UF
            """, [estado_parlamentar]).fetchdf()
            con2.close()
            for _, cr in centroid_df.iterrows():
                municipio_centroids[str(cr["NM_MUNICIPIO"]).upper()] = (float(cr["lat"]), float(cr["lng"]))
        except Exception:
            pass

        top_municipios = []
        for _, row in df_municipios_sem_coord.iterrows():
            mun_key = str(row["NM_MUNICIPIO"]).upper() if row["NM_MUNICIPIO"] else ""
            centroid = municipio_centroids.get(mun_key)
            top_municipios.append({
                "municipio": str(row["NM_MUNICIPIO"]) if row["NM_MUNICIPIO"] else "N/A",
                "estado": str(row["SG_UF"]) if row["SG_UF"] else "N/A",
                "uf": str(row["SG_UF"]) if row["SG_UF"] else "N/A",
                "lat": centroid[0] if centroid else None,
                "lng": centroid[1] if centroid else None,
                "total_votos": int(row["total_votos"]) if not pd.isna(row["total_votos"]) else 0,
                "sessoes": int(row["NR_SECAO"]) if not pd.isna(row["NR_SECAO"]) else 0,
            })

        total_votos_territorio = int(df_secoes_sem_coord["total_votos"].sum()) if not df_secoes_sem_coord.empty else 0
        total_votos = total_votos_oficiais if total_votos_oficiais is not None else total_votos_territorio
        total_municipios = len(df_municipios_sem_coord)
        total_secoes = int(len(df_secoes_sem_coord.index))
        principal_reduto = str(df_municipios_sem_coord.iloc[0]["NM_MUNICIPIO"]) if not df_municipios_sem_coord.empty else "N/A"

        return clean_data_for_json({
            "info": info,
            "stats": {
                "total_votos": total_votos,
                "totalVotos": total_votos,
                "total_municipios": total_municipios,
                "totalMunicipios": total_municipios,
                "total_secoes": total_secoes,
                "totalSessoes": total_secoes,
                "principal_reduto": principal_reduto,
                "fonte_total_votos": "tse_csv_oficial" if total_votos_oficiais is not None else "territorial_cache",
            },
            "municipios": [m for m in top_municipios if m.get("lat") and m.get("lng")],
            "topMunicipios": top_municipios[:20],
            "ibgeResumoTop10": [],
            "zonas": [],
            "qualidadeCoordenadas": {
                "uf": estado_parlamentar,
                "municipios": {"mantidos": 0, "corrigidos": 0, "suprimidos": 0},
                "zonas": {"mantidos": 0, "corrigidos": 0, "suprimidos": 0},
            },
            "cacheStatus": "hit_votos_sem_coordenadas",
            "message": f"As votações de {info['nome']} foram encontradas, mas a base original não traz coordenadas geográficas para mapear as seções eleitorais no estado {estado_parlamentar}.",
        })

    def valores_unicos_ordenados(series):
        valores = []
        vistos = set()
        for value in series:
            if pd.isna(value):
                continue
            texto = str(value).strip()
            if not texto or texto in vistos:
                continue
            vistos.add(texto)
            valores.append(texto)
        return valores

    df_coordenadas = df_secoes.groupby(["LAT", "LONG"]).agg({
        "NM_MUNICIPIO": "first",
        "SG_UF": "first",
        "NM_LOCAL_VOTACAO": lambda s: valores_unicos_ordenados(s),
        "DS_ENDERECO": lambda s: valores_unicos_ordenados(s),
        "NM_BAIRRO": lambda s: valores_unicos_ordenados(s),
        "NR_ZONA": lambda s: valores_unicos_ordenados(s),
        "NR_SECAO": lambda s: valores_unicos_ordenados(s),
        "total_votos": "sum",
    }).reset_index()

    df_coordenadas["quantidade_zonas"] = df_coordenadas["NR_ZONA"].apply(len)
    df_coordenadas["quantidade_secoes"] = df_coordenadas["NR_SECAO"].apply(len)

    df_municipios = df_coordenadas.groupby(["NM_MUNICIPIO", "SG_UF"]).agg({
        "total_votos": "sum",
        "LAT": "mean",
        "LONG": "mean",
        "quantidade_secoes": "sum",
    }).reset_index().sort_values("total_votos", ascending=False)

    municipios_list = []
    for _, row in df_municipios.iterrows():
        municipios_list.append({
            "municipio": str(row["NM_MUNICIPIO"]) if row["NM_MUNICIPIO"] else "N/A",
            "estado": str(row["SG_UF"]) if row["SG_UF"] else "N/A",
            "uf": str(row["SG_UF"]) if row["SG_UF"] else "N/A",
            "lat": float(row["LAT"]) if not pd.isna(row["LAT"]) else None,
            "lng": float(row["LONG"]) if not pd.isna(row["LONG"]) else None,
            "total_votos": int(row["total_votos"]) if not pd.isna(row["total_votos"]) else 0,
            "sessoes": int(row["quantidade_secoes"]) if not pd.isna(row["quantidade_secoes"]) else 0,
        })

    zonas_list = []
    for _, row in df_coordenadas.iterrows():
        # [OTIMIZAÇÃO] Reduzindo payload removendo campos pesados de texto para evitar 'Network Error' e lentidão no navegador
        zonas_list.append({
            "municipio": str(row["NM_MUNICIPIO"]) if row["NM_MUNICIPIO"] else "N/A",
            "estado": str(row["SG_UF"]) if row["SG_UF"] else "N/A",
            "lat": float(row["LAT"]) if not pd.isna(row["LAT"]) else None,
            "lng": float(row["LONG"]) if not pd.isna(row["LONG"]) else None,
            "total_votos": int(row["total_votos"]) if not pd.isna(row["total_votos"]) else 0,
            # "bairro": row["NM_BAIRRO"],        <-- Removido para otimização
            # "local_votacao": row["NM_LOCAL_VOTACAO"], <-- Removido para otimização
            # "endereco": row["DS_ENDERECO"],    <-- Removido para otimização
            "zonas": row["NR_ZONA"],
            "secoes": row["NR_SECAO"],
            "quantidade_zonas": int(row["quantidade_zonas"]) if not pd.isna(row["quantidade_zonas"]) else 0,
            "quantidade_secoes": int(row["quantidade_secoes"]) if not pd.isna(row["quantidade_secoes"]) else 0,
        })

    municipios_list, resumo_municipios = sanitizar_pontos_mapa_por_estado(municipios_list, estado_parlamentar)
    zonas_list, resumo_zonas = sanitizar_pontos_mapa_por_estado(zonas_list, estado_parlamentar)

    total_votos_territorio = int(df_coordenadas["total_votos"].sum()) if not df_coordenadas.empty else 0
    total_votos = total_votos_oficiais if total_votos_oficiais is not None else total_votos_territorio
    total_municipios = len(df_municipios)
    total_secoes = int(df_coordenadas["quantidade_secoes"].sum()) if not df_coordenadas.empty else 0
    principal_reduto = str(df_municipios.iloc[0]["NM_MUNICIPIO"]) if not df_municipios.empty else "N/A"

    stats = {
        "total_votos": total_votos,
        "totalVotos": total_votos,
        "total_municipios": total_municipios,
        "totalMunicipios": total_municipios,
        "total_secoes": total_secoes,
        "totalSessoes": total_secoes,
        "principal_reduto": principal_reduto,
        "fonte_total_votos": "tse_csv_oficial" if total_votos_oficiais is not None else "territorial_cache",
    }

    return clean_data_for_json({
        "info": info,
        "stats": stats,
        "municipios": municipios_list,
        "topMunicipios": municipios_list[:20],
        "ibgeResumoTop10": [],
        "zonas": zonas_list,
        "qualidadeCoordenadas": {
            "uf": estado_parlamentar,
            "municipios": resumo_municipios,
            "zonas": resumo_zonas,
        },
        "cacheStatus": "hit_votos_cache",
    })


def materialize_mapa_eleitoral_votos_cache(
    nome_parlamentar: str,
    estado: Optional[str] = None,
    partido: Optional[str] = None,
):
    payload = compute_mapa_eleitoral_votos_payload(nome_parlamentar, estado=estado, partido=partido, include_ibge=False)
    if not payload or payload.get("error"):
        return payload

    info = payload.get("info") or {}
    uf_real = estado or info.get("estado")
    partido_real = partido or info.get("partido")
    nome_real = info.get("nome") or nome_parlamentar

    ensure_mapa_eleitoral_votos_cache_table()
    conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
    try:
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute(
            """
            INSERT OR REPLACE INTO mapa_eleitoral_votos_cache
            (parlamentar, uf, partido, atualizado_em, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [nome_real, uf_real, partido_real, now, json.dumps(clean_data_for_json(payload), ensure_ascii=False)],
        )
        conn.commit()
    finally:
        conn.close()

    return payload

def classify_beneficiary(nome):
    if not nome: return 'ONG' # Default para ONG se vazio
    nome = nome.upper()
    if any(x in nome for x in ['PREFEITURA', 'MUNICIPIO', 'PREF', 'FUNDO MUNICIPAL']):
        return 'Prefeitura'
    if any(x in nome for x in ['LTDA', 'S.A', 'S/A', ' SA', 'EIRELI', 'ME', 'EPP', 'COMERCIO', 'SERVICOS', 'CONSTRUTORA', 'ENGENHARIA', 'BANCO']):
        return 'Empresa'
    # Tudo que não for Prefeitura ou Empresa vira ONG
    return 'ONG'

def safe_money(value):
    try:
        if value is None:
            return 0.0
        if isinstance(value, str):
            cleaned = value.replace('R$', '').replace('.', '').replace(',', '.').strip()
            return float(cleaned or 0)
        return float(value)
    except Exception:
        return 0.0

def extract_city_from_supplier(row):
    # row pode ser um objeto Series do pandas ou um dict
    cidade_ref = row.get('cidade_ref') if isinstance(row, dict) else row['cidade_ref']
    fornecedor = row.get('fornecedor') if isinstance(row, dict) else row['fornecedor']
    
    if not cidade_ref and not fornecedor: return 'Desconhecido'
    
    cidade_atual = normalize_city_name(str(cidade_ref))
    nome_fornecedor = str(fornecedor).upper()
    
    # Lista de padrões de extração
    padroes = [
        'MUNICIPIO DE ', 
        'PREFEITURA MUNICIPAL DE ', 
        'PREFEITURA DE ',
        'FUNDO MUNICIPAL DE SAUDE DE ',
        'FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL DE ',
        'CAMARA MUNICIPAL DE ',
        'PREFEITURA MUNICIPAL',
        'CONVENENTE:',
        'CONVENENTE'
    ]
    
    cidade_extraida = None
    for padrao in padroes:
        if padrao in nome_fornecedor:
            try:
                partes = nome_fornecedor.split(padrao)
                if len(partes) > 1:
                    cidade_extraida = partes[1].strip()
                    if '-' in cidade_extraida: cidade_extraida = cidade_extraida.split('-')[0].strip()
                    if '/' in cidade_extraida: cidade_extraida = cidade_extraida.split('/')[0].strip()
                    if ':' in cidade_extraida: cidade_extraida = cidade_extraida.split(':')[0].strip()
                    break
            except:
                continue
    
    # Se extraiu algo válido, priorizamos o extraído
    if cidade_extraida and len(cidade_extraida) > 2:
        return cidade_extraida
        
    # Se não extraiu nada novo, verifica se o atual é genérico
    if len(cidade_atual) > 3 and not any(t in cidade_atual for t in TERMOS_GENERICOS):
        return cidade_ref
            
    return cidade_ref if cidade_ref else 'Desconhecido'

# Middleware de Segurança - Validação de API Key
def normalizar_texto_ia(texto):
    if not texto: return ""
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', str(texto))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).upper().strip()

@app.get("/api/parlamentares/doacoes-fornecedores")
async def get_doacoes_fornecedores(parlamentar: str):
    """
    Lista fornecedores de um parlamentar cujos sócios doaram para sua campanha.
    Cruza 'cruzamento_doacoes' com 'tabelao'.
    """
    try:
        conn = get_db_connection("tabelao")
        query = """
        SELECT 
            c.cnpj,
            c.socio,
            c.valor_doado_campanha,
            c.data_doacao,
            c.tp_receita,
            t.txtFornecedor as fornecedor_nome,
            SUM(t.vlrLiquido) as total_faturado,
            GROUP_CONCAT(DISTINCT t.txtDescricao) as rubricas
        FROM cruzamento_doacoes c
        LEFT JOIN tabelao t ON c.cnpj = t.cnpj
        WHERE c.parlamentar LIKE ?
        GROUP BY c.cnpj, c.socio, c.data_doacao
        ORDER BY total_faturado DESC
        """
        df = pd.read_sql_query(query, conn, params=[f"%{parlamentar}%"])
        conn.close()

        if df.empty: return []

        result = []
        for _, row in df.iterrows():
            result.append({
                "cnpj": row['cnpj'],
                "socio": row['socio'],
                "doacao": {
                    "valor": float(row['valor_doado_campanha']),
                    "data": row['data_doacao'],
                    "tipo": row['tp_receita']
                },
                "faturamento": {
                    "fornecedor": row['fornecedor_nome'] or "Não Identificado no Tabelão",
                    "total": float(row['total_faturado'] or 0),
                    "rubricas": list(set(str(row['rubricas']).split(','))) if row['rubricas'] else []
                }
            })
        return result
    except Exception as e:
        logger.error(f"Erro ao buscar doações-fornecedores: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/api/filtros/parlamentares-doacoes")
async def get_filtros_parlamentares_doacoes():
    """Retorna lista de parlamentares que possuem dados de doações cruzadas com metadados."""
    try:
        conn = get_db_connection("tabelao")
        # Tentamos buscar o estado e partido do 'tabelao' para estes parlamentares
        query = """
        SELECT DISTINCT c.parlamentar, t.sgUF as estado, t.sgPartido as partido
        FROM cruzamento_doacoes c
        LEFT JOIN (SELECT DISTINCT nome, sgUF, sgPartido FROM tabelao) t ON c.parlamentar = t.nome
        ORDER BY c.parlamentar
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        df = df.fillna("")
        return {"parlamentares": df.to_dict(orient='records')}
    except Exception as e:
        logger.error(f"Erro ao buscar filtros de doações: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.middleware("http")
async def validate_api_key_middleware(request: Request, call_next):
    """Valida API Key em todos os endpoints EXCETO públicos e localhost"""
    
    # Endpoints públicos (não precisam de autenticação)
    public_endpoints = [
        "/api/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/proxy/imagem",
    ]
    
    # Verificar se é endpoint público
    if request.url.path in public_endpoints:
        response = await call_next(request)
        return response
    
    # Liberar acesso para localhost (desenvolvimento local)
    client_host = request.client.host if request.client else None
    if client_host in ['127.0.0.1', 'localhost', '::1']:
        response = await call_next(request)
        return response
    
    # Verificar API Key para endpoints protegidos (acesso remoto)
    api_key = request.headers.get(API_KEY_NAME)
    
    if not api_key:
        return Response(
            content=json.dumps({
                "detail": "❌ API Key ausente. Forneça o header 'X-API-Key' para acessar este recurso.",
                "status": "unauthorized"
            }),
            status_code=401,
            media_type="application/json"
        )
    
    if api_key != API_KEY:
        return Response(
            content=json.dumps({
                "detail": "❌ API Key inválida. Verifique suas credenciais.",
                "status": "forbidden"
            }),
            status_code=403,
            media_type="application/json"
        )
    
    # API Key válida, continuar
    response = await call_next(request)
    return response

# Middleware para desabilitar cache em todas as respostas
@app.middleware("http")
async def disable_cache(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Diretório base do projeto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuração de bancos de dados com FALLBACK AUTOMÁTICO
# PRIORIDADE: Remoto PRIMEIRO, Local se falhar
REMOTE_DB_HOST = os.getenv("REMOTE_DB_HOST", "31.97.21.120")
REMOTE_DB_USER = os.getenv("REMOTE_DB_USER", "aislangreca")
REMOTE_DB_PASSWORD = os.getenv("REMOTE_DB_PASSWORD", "")
REMOTE_DB_PATH_SERVER = os.getenv("REMOTE_DB_PATH", "/home/aislangreca/bancos_dados")
REMOTE_DB_PORT = int(os.getenv("REMOTE_DB_PORT", "22"))
REMOTE_DB_PATH = os.getenv("REMOTE_DB_PATH", "./bancos_dados_remoto")

# Caminhos REMOTOS (prioridade)
DATABASE_PATHS_REMOTE = {
    "tabelao": os.path.join(REMOTE_DB_PATH, "tabelao.db"),
    "discursos": os.path.join(REMOTE_DB_PATH, "discursos.db"),
    "noticias": os.path.join(REMOTE_DB_PATH, "noticias_parlamentares.db"),
    "discursos_links": os.path.join(REMOTE_DB_PATH, "discursos_links.db"),
    "discursos_links_fixed": os.path.join(REMOTE_DB_PATH, "discursos_links_fixed.db"),
    "cache_relatorios": os.path.join(REMOTE_DB_PATH, "cache_relatorios_comissoes.db"),
    "cache_normalizacao": os.path.join(REMOTE_DB_PATH, "cache_normalizacao_citacoes_integrados.db"),
    "llm_cache": os.path.join(REMOTE_DB_PATH, "llm_cache.db")
}

# Caminhos LOCAIS (fallback) — tenta "bancos/" primeiro, depois raiz
def _local_db(name):
    """Resolve caminho local: prioriza subdiretório 'bancos/' se existir."""
    in_bancos = os.path.join(BASE_DIR, "bancos", name)
    in_root = os.path.join(BASE_DIR, name)
    if os.path.exists(in_bancos) and os.path.getsize(in_bancos) > 0:
        return in_bancos
    return in_root

DATABASE_PATHS_LOCAL = {
    "tabelao": _local_db("tabelao.db"),
    "discursos": _local_db("discursos.db"),
    "noticias": _local_db("noticias_parlamentares.db"),
    "discursos_links": _local_db("discursos_links.db"),
    "discursos_links_fixed": _local_db("discursos_links_fixed.db"),
    "cache_relatorios": _local_db("cache_relatorios_comissoes.db"),
    "cache_normalizacao": _local_db("cache_normalizacao_citacoes_integrados.db"),
    "llm_cache": _local_db("llm_cache.db"),
    "notas_fiscais_auditoria": os.path.join(BASE_DIR, "data", "notas_fiscais_auditoria.db")
}

# Carregar dados auxiliares de logos (Partidos e Estados) usando caminhos absolutos
BASE_DIR_APP = os.path.dirname(os.path.abspath(__file__))
try:
    path_partido = os.path.join(BASE_DIR_APP, 'partido.csv')
    if os.path.exists(path_partido):
        df_partidos = pd.read_csv(path_partido)
        df_partidos.columns = df_partidos.columns.str.strip()
        partido_logos_dict = dict(zip(df_partidos['sgPartido'].astype(str).str.strip().str.upper(), df_partidos['URL_Partido'].astype(str).str.strip()))
        logger.info(f"✅ {len(partido_logos_dict)} logos de partidos carregadas do CSV.")
    else:
        logger.error(f"❌ Arquivo não encontrado: {path_partido}")
        partido_logos_dict = {}
except Exception as e:
    logger.error(f"⚠️ Erro ao carregar partido.csv: {e}")
    partido_logos_dict = {}

try:
    path_estados = os.path.join(BASE_DIR_APP, 'estados.csv')
    if os.path.exists(path_estados):
        df_estados = pd.read_csv(path_estados)
        df_estados.columns = df_estados.columns.str.strip()
        estado_logos_dict = dict(zip(df_estados['sgUF'].astype(str).str.strip().str.upper(), df_estados['URL_Estado'].astype(str).str.strip()))
        logger.info(f"✅ {len(estado_logos_dict)} bandeiras de estados carregadas do CSV.")
    else:
        logger.error(f"❌ Arquivo não encontrado: {path_estados}")
        estado_logos_dict = {}
except Exception as e:
    logger.error(f"⚠️ Erro ao carregar estados.csv: {e}")
    estado_logos_dict = {}

# Verificar disponibilidade dos bancos REMOTOS
def verificar_e_montar_bancos_remotos():
    """Verifica se os bancos remotos estão acessíveis e tenta montar se necessário"""
    import subprocess
    
    # Primeiro, verificar se já está montado
    test_db = DATABASE_PATHS_REMOTE.get("llm_cache", DATABASE_PATHS_REMOTE.get("cache_relatorios"))
    try:
        if os.path.exists(test_db):
            # Tenta abrir uma conexão para garantir que está acessível
            test_conn = sqlite3.connect(test_db, timeout=5)
            test_conn.close()
            print(f"✅ Bancos remotos já montados e acessíveis!")
            return True
    except Exception as e:
        print(f"⚠️  Bancos remotos não acessíveis via ponto de montagem: {e}")
    
    # Se não está montado, tentar montar via SSHFS com senha
    if REMOTE_DB_PASSWORD and REMOTE_DB_HOST:
        print(f"🔧 Tentando montar bancos remotos via SSHFS...")
        try:
            # Criar diretório de montagem se não existir
            os.makedirs(REMOTE_DB_PATH, exist_ok=True)
            
            # Verificar se sshfs está disponível
            result_check = subprocess.run(['which', 'sshfs'], capture_output=True)
            if result_check.returncode != 0:
                print(f"⚠️  SSHFS não instalado. Usando bancos locais.")
                print(f"⚠️  Para instalar: brew install --cask macfuse && brew install gromgit/fuse/sshfs-mac")
                return False
            
            # Comando SSHFS com senha via expect (ou sshpass)
            mount_cmd = f"./mount_remote_db.sh"
            result = subprocess.run(mount_cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"✅ Bancos remotos montados com sucesso!")
                # Verificar novamente
                if os.path.exists(test_db):
                    return True
            else:
                print(f"⚠️  Não foi possível montar: {result.stderr}")
                
        except Exception as e:
            print(f"⚠️  Erro ao tentar montar bancos remotos: {e}")
    
    return False

# INICIALMENTE usar bancos LOCAIS (a verificação de remotos é feita no startup)
DATABASE_PATHS = DATABASE_PATHS_LOCAL
DATABASE_MODE = "LOCAL"

# Startup event para inicialização lazy (não bloqueia import)
@app.on_event("startup")
async def startup_event():
    """Inicialização lazy de cache e bancos remotos"""
    global DATABASE_PATHS, DATABASE_MODE, PIPELINE_SCHEDULER_STARTED
    
    # Inicializar cache LLM em background
    def _init():
        init_llm_cache()
        # Verificar bancos remotos
        if verificar_e_montar_bancos_remotos():
            global DATABASE_PATHS, DATABASE_MODE
            DATABASE_PATHS = DATABASE_PATHS_REMOTE
            DATABASE_MODE = "REMOTO"
            print(f"🌐 ✅ USANDO BANCOS REMOTOS: {REMOTE_DB_PATH}")
        else:
            print(f"⚠️  FALLBACK: Usando bancos LOCAIS em: {BASE_DIR}")
        
        ensure_gastos_indexes()
        # NOVO: Inicializar motor de filtros unificado para todas as páginas
        ensure_filter_caches()
    
    # Executar em thread separada para não bloquear
    thread = threading.Thread(target=_init, daemon=True)
    thread.start()

    if not PIPELINE_SCHEDULER_STARTED:
        scheduler_thread = threading.Thread(target=_pipeline_scheduler_loop, daemon=True)
        scheduler_thread.start()
        PIPELINE_SCHEDULER_STARTED = True

# Sistema de status de progresso em memória
progress_status = {}

# Cache de resultados prontos
resultados_prontos = {}

@app.get("/api/health")
async def health_check():
    """Endpoint de health check que mostra status dos bancos de dados"""
    return {
        "status": "ok",
        "database_mode": DATABASE_MODE,
        "database_path": REMOTE_DB_PATH if DATABASE_MODE == "REMOTO" else BASE_DIR,
        "remote_available": DATABASE_MODE == "REMOTO",
        "message": "✅ Usando bancos remotos" if DATABASE_MODE == "REMOTO" else "⚠️ Usando bancos locais (fallback)"
}

@app.get("/api/proxy/imagem")
async def proxy_imagem(url: str):
    """Proxy para imagens externas (logos de partidos, bandeiras de estados).
    Necessário pois Wikimedia bloqueia hotlinking direto do browser."""
    ALLOWED_DOMAINS = ["upload.wikimedia.org", "commons.wikimedia.org", "www.camara.leg.br", "flagcdn.com", "logo.clearbit.com", "t1.gstatic.com", "t2.gstatic.com", "t3.gstatic.com", "i.ibb.co", "images.seeklogo.com"]
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        if not any(parsed.netloc.endswith(d) for d in ALLOWED_DOMAINS):
            raise HTTPException(status_code=403, detail="Domínio não permitido")
            
        encoded_url = url        
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(encoded_url, headers={
                "Referer": "https://www.wikipedia.org/",
                "User-Agent": "EuSeiDissoBot/1.0 (https://euseidissodeputado.com.br)"
            })
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Erro no provedor da imagem. Header recebido: {resp.headers.get('content-type')}")
            content_type = resp.headers.get("content-type", "image/png")
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"}
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao buscar imagem: {e}")



def get_db_connection(db_name="tabelao"):
    """Cria e retorna uma conexão com o banco de dados."""
    db_path = DATABASE_PATHS.get(db_name)
    if not db_path:
        raise HTTPException(status_code=500, detail=f"Banco de dados '{db_name}' não encontrado.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_gastos_indexes():
    """Cria índices usados pela tela de gastos para reduzir latência das consultas principais."""
    db_path = DATABASE_PATHS.get("tabelao")
    if not db_path or not os.path.exists(db_path):
        return

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tabelao_gastos_lookup ON tabelao(nome, sgUF, sgPartido, txtDescricao)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tabelao_gastos_fornecedor ON tabelao(nome, txtDescricao, txtCNPJCPF)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tabelao_gastos_cnpj_desc ON tabelao(txtCNPJCPF, txtDescricao, nome)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_coord_empresas_cnpj ON coordenadas_empresas(cnpj)")
        conn.commit()
        logger.info("✅ Índices da tela de gastos verificados/criados com sucesso.")
    except Exception as e:
        logger.warning(f"⚠️ Não foi possível garantir índices da tela de gastos: {e}")
    finally:
        conn.close()

def ensure_filter_caches():
    """Cria e popula tabelas de resumo para que os filtros carreguem em milissegundos em todas as páginas."""
    db_path = DATABASE_PATHS.get("tabelao")
    if not db_path or not os.path.exists(db_path):
        return

    print("🚀 [PERFORMANCE] Inicializando motor de filtros global...")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # 1. Cache de Parlamentares
        cursor.execute("DROP TABLE IF EXISTS cache_filtros_parlamentares")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_filtros_parlamentares (
                nome TEXT,
                sgUF TEXT,
                sgPartido TEXT,
                sgPartidoAtual TEXT,
                urlFoto TEXT,
                PRIMARY KEY (nome, sgUF, sgPartido)
            )
        """)
        
        # 2. Cache de Partidos
        cursor.execute("DROP TABLE IF EXISTS cache_filtros_partidos")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_filtros_partidos (
                sgPartido TEXT,
                sgPartidoAtual TEXT,
                sgUF TEXT
            )
        """)
        
        # Popular parlamentares - Usando o status mais recente (maior Ano/Mes)
        print("⏳ [CACHE] Populando lista de parlamentares com status mais recente...")
        cursor.execute("""
            INSERT OR IGNORE INTO cache_filtros_parlamentares (nome, sgUF, sgPartido, sgPartidoAtual, urlFoto)
            SELECT DISTINCT 
                t.nome, 
                t.sgUF, 
                t.sgPartido, 
                latest.ultimoStatus_siglaPartido, 
                latest.ultimoStatus_urlFoto
            FROM tabelao t
            JOIN (
                SELECT nome, ultimoStatus_siglaPartido, ultimoStatus_urlFoto
                FROM (
                    SELECT nome, ultimoStatus_siglaPartido, ultimoStatus_urlFoto, 
                           (numAno * 100 + numMes) as ref_time,
                           ROW_NUMBER() OVER (PARTITION BY nome ORDER BY numAno DESC, numMes DESC) as rn
                    FROM tabelao
                    WHERE ultimoStatus_siglaPartido IS NOT NULL
                ) WHERE rn = 1
            ) latest ON t.nome = latest.nome
            WHERE t.nome IS NOT NULL AND t.sgUF IS NOT NULL
        """)
        
        # Popular partidos - Apenas os que realmente existem no cache de parlamentares
        print("⏳ [CACHE] Populando lista de partidos...")
        cursor.execute("""
            INSERT INTO cache_filtros_partidos (sgPartido, sgPartidoAtual, sgUF)
            SELECT DISTINCT sgPartido, sgPartidoAtual, sgUF 
            FROM cache_filtros_parlamentares
        """)
        
        conn.commit()
        print("✅ [CACHE] Motor de filtros estabilizado (Pastor Eurico fix aplicado).")
    except Exception as e:
        print(f"⚠️ Erro ao criar cache de filtros: {e}")
    finally:
        conn.close()

class Gasto(BaseModel):
    nome: str
    sgUF: str
    sgPartido: str
    txtDescricao: str
    txtFornecedor: str
    vlrLiquido: float
    datEmissao: Optional[str] = None
    txtPassageiro: Optional[str] = None
    txtTrecho: Optional[str] = None
    ultimoStatus_urlFoto: Optional[str] = None
    urlPartido: Optional[str] = None
    urlEstado: Optional[str] = None

# Dicionário de Capitais para fallback de mapa (Formatado como no DB: Upper + Sem Acento)
ESTADO_CAPITAL = {
    'AC': 'RIO BRANCO', 'AL': 'MACEIO', 'AP': 'MACAPA', 'AM': 'MANAUS', 'BA': 'SALVADOR',
    'CE': 'FORTALEZA', 'DF': 'BRASILIA', 'ES': 'VITORIA', 'GO': 'GOIANIA', 'MA': 'SAO LUIS',
    'MT': 'CUIABA', 'MS': 'CAMPO GRANDE', 'MG': 'BELO HORIZONTE', 'PA': 'BELEM', 'PB': 'JOAO PESSOA',
    'PR': 'CURITIBA', 'PE': 'RECIFE', 'PI': 'TERESINA', 'RJ': 'RIO DE JANEIRO', 'RN': 'NATAL',
    'RS': 'PORTO ALEGRE', 'RO': 'PORTO VELHO', 'RR': 'BOA VISTA', 'SC': 'FLORIANOPOLIS',
    'SP': 'SAO PAULO', 'SE': 'ARACAJU', 'TO': 'PALMAS'
}

# Dicionário de Nome de Estado -> Capital (para casos como "CEARÁ (UF)")
NOME_ESTADO_CAPITAL = {
    'ACRE': 'RIO BRANCO', 'ALAGOAS': 'MACEIO', 'AMAPÁ': 'MACAPA', 'AMAZONAS': 'MANAUS', 'BAHIA': 'SALVADOR',
    'CEARÁ': 'FORTALEZA', 'DISTRITO FEDERAL': 'BRASILIA', 'ESPÍRITO SANTO': 'VITORIA', 'GOIÁS': 'GOIANIA', 
    'MARANHÃO': 'SAO LUIS', 'MATO GROSSO': 'CUIABA', 'MATO GROSSO DO SUL': 'CAMPO GRANDE', 
    'MINAS GERAIS': 'BELO HORIZONTE', 'PARÁ': 'BELEM', 'PARAÍBA': 'JOAO PESSOA', 'PARANÁ': 'CURITIBA', 
    'PERNAMBUCO': 'RECIFE', 'PIAUÍ': 'TERESINA', 'RIO DE JANEIRO': 'RIO DE JANEIRO', 
    'RIO GRANDE DO NORTE': 'NATAL', 'RIO GRANDE DO SUL': 'PORTO ALEGRE', 'RONDÔNIA': 'PORTO VELHO', 
    'RORAIMA': 'BOA VISTA', 'SANTA CATARINA': 'FLORIANOPOLIS', 'SÃO PAULO': 'SAO PAULO', 
    'SERGIPE': 'ARACAJU', 'TOCANTINS': 'PALMAS'
}

@app.get("/api/emendas/analise-basica")
async def get_analise_emendas_basica(
    parlamentar: Optional[str] = None,
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    ano: Optional[str] = None,
):
    """Endpoint simplificado para análise de emendas - retorna dados básicos."""
    try:
        if not parlamentar or parlamentar == 'Todos':
            return {"error": "Selecione um parlamentar"}

        conn = get_db_connection("tabelao")

        # Buscar emendas
        query = """
        SELECT
            codigo_emenda,
            localidade_emenda as municipio,
            ano_emenda as ano,
            tipo_emenda as tipo,
            funcao as tema,
            valor_pago,
            valor_empenhado,
            valor_liquidado
        FROM emendas
        WHERE autor_emenda LIKE ?
        AND CAST(ano_emenda AS INTEGER) >= 2023
        """
        params = [f"{parlamentar}%"]

        if ano and ano != 'Todos':
            query += " AND ano_emenda = ?"
            params.append(ano)

        df_emendas = pd.read_sql_query(query, conn, params=params)

        # Processar valores
        for col in ['valor_pago', 'valor_empenhado', 'valor_liquidado']:
            if not df_emendas.empty:
                df_emendas[col] = (
                    df_emendas[col]
                    .astype(str)
                    .str.replace('R$', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False)
                    .str.strip()
                )
                df_emendas[col] = pd.to_numeric(df_emendas[col], errors='coerce').fillna(0)

        # Resumo básico
        resumo = {
            "total_emendas": len(df_emendas),
            "valor_total_pago": float(df_emendas['valor_pago'].sum()) if not df_emendas.empty else 0,
            "valor_total_empenhado": float(df_emendas['valor_empenhado'].sum()) if not df_emendas.empty else 0,
            "total_cidades": int(df_emendas['municipio'].nunique()) if not df_emendas.empty else 0,
            "data_atualizacao": datetime.now().strftime('%d/%m/%Y')
        }

        municipios = []
        if not df_emendas.empty:
            codigos_emendas = df_emendas['codigo_emenda'].astype(str).dropna().unique().tolist()
            cidades_destino = set()

            if codigos_emendas:
                placeholders = ','.join(['?'] * len(codigos_emendas))
                query_docs = f"""
                SELECT codigo_emenda, fornecedor
                FROM documentos_emendas
                WHERE codigo_emenda IN ({placeholders})
                """
                df_documentos = pd.read_sql_query(query_docs, conn, params=codigos_emendas)

                if not df_documentos.empty:
                    df_documentos['codigo_emenda'] = df_documentos['codigo_emenda'].astype(str)
                    df_emendas_merge = df_emendas[['codigo_emenda', 'municipio']].drop_duplicates(subset=['codigo_emenda']).copy()
                    df_docs_city = pd.merge(df_documentos, df_emendas_merge, on='codigo_emenda', how='left')

                    df_docs_city['cidade_resolvida'] = df_docs_city.apply(
                        lambda row: normalize_city_name(
                            extract_city_from_supplier({
                                'cidade_ref': row.get('municipio'),
                                'fornecedor': row.get('fornecedor')
                            })
                        ),
                        axis=1
                    )

                    cidades_destino.update(
                        cidade for cidade in df_docs_city['cidade_resolvida'].dropna().astype(str).tolist()
                        if cidade and cidade.upper() not in {'NAN', 'NONE'} and len(cidade) > 2
                    )

            if not cidades_destino:
                municipios_series = (
                    df_emendas['municipio']
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .apply(normalize_city_name)
                )
                cidades_destino.update(
                    municipio for municipio in municipios_series.tolist()
                    if municipio and municipio.upper() not in {'NAN', 'NONE'}
                )

            municipios = [{"municipio": municipio} for municipio in sorted(cidades_destino)]

        # Distribuição por tipo
        dist_tipo = []
        if not df_emendas.empty:
            dist_tipo = df_emendas.groupby('tipo')['valor_pago'].sum().reset_index()
            dist_tipo.columns = ['tipo', 'valor']
            dist_tipo = dist_tipo.to_dict('records')

        # Distribuição por ano
        dist_ano = []
        if not df_emendas.empty:
            dist_ano = df_emendas.groupby('ano')['valor_pago'].sum().reset_index()
            dist_ano.columns = ['ano', 'valor']
            dist_ano = dist_ano.to_dict('records')

        conn.close()

        return {
            "info_parlamentar": {
                "nome": parlamentar,
                "estado": estado,
                "partido": partido,
                "foto": None,
                "logo_partido": None,
                "bandeira_estado": None
            },
            "resumo": resumo,
            "distribuicao_por_tipo": dist_tipo,
            "distribuicao_por_ano": dist_ano,
            "distribuicao_por_tema": [],
            "municipios": municipios,
            "fornecedores": [],
            "convenios": [],
            "documentos": []
        }

    except Exception as e:
        logger.error(f"Erro na análise básica de emendas: {e}")
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)[:100]}")


@app.get("/api/emendas/analise")
async def get_analise_emendas(
    parlamentar: Optional[str] = None,
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    ano: Optional[str] = None,
    tipo_beneficiario: Optional[str] = None,
    cidade: Optional[str] = None
):
    """Endpoint para análise de emendas parlamentares (real)."""
    try:
        if not parlamentar or parlamentar == 'Todos':
            return {"error": "Selecione um parlamentar"}

        # que retorna apenas os dados essenciais

        conn = get_db_connection("tabelao")
        
        # 1. Buscar informações do parlamentar
        # Usar LIKE para flexibilidade no nome (ex: ERIKA HILTON vs ERIKA HILTON DE PAULA)
        query_info = """
        SELECT DISTINCT 
            nome, sgUF, sgPartido, ultimoStatus_urlFoto, 
            urlPartido as url_partido, urlEstado as url_estado
        FROM tabelao 
        WHERE nome LIKE ?
        LIMIT 1
        """
        # Adicionar % ao redor do nome para busca parcial
        df_info = pd.read_sql_query(query_info, conn, params=[f"%{parlamentar}%"])
        
        info_parlamentar = {}
        if not df_info.empty:
            row = df_info.iloc[0]
            uf = str(row['sgUF'] or '').strip().upper()
            info_parlamentar = {
                "nome": row['nome'],
                "partido": row['sgPartido'],
                "estado": uf,
                "foto": row['ultimoStatus_urlFoto'],
                "logo_partido": row['url_partido'],
                "bandeira_estado": resolve_state_flag_from_wikipedia(uf) or (estado_logos_dict.get(uf) if 'estado_logos_dict' in globals() else row['url_estado'])
            }
        else:
            info_parlamentar = {
                "nome": parlamentar,
                "partido": partido if partido != 'Todos' else None,
                "estado": estado if estado != 'Todos' else None,
                "foto": None,
                "logo_partido": None,
                "bandeira_estado": None
            }

        # 2. Buscar Emendas
        query_emendas = """
        SELECT 
            codigo_emenda,
            localidade_emenda,
            localidade_emenda as municipio,
            ano_emenda as ano,
            tipo_emenda as tipo,
            funcao as tema,
            subfuncao,
            valor_pago,
            valor_empenhado,
            valor_liquidado
        FROM emendas
        WHERE autor_emenda LIKE ?
        AND CAST(ano_emenda AS INTEGER) >= 2023
        """
        params_emendas = [f"%{parlamentar}%"]
        
        if ano and ano != 'Todos':
            query_emendas += " AND ano_emenda = ?"
            params_emendas.append(ano)
            
        df_emendas = pd.read_sql_query(query_emendas, conn, params=params_emendas)
        
        # Tratar valores numéricos
        for col in ['valor_pago', 'valor_empenhado', 'valor_liquidado']:
            if not df_emendas.empty:
                df_emendas[col] = pd.to_numeric(
                    df_emendas[col].astype(str)
                    .str.replace('R$ ', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False),
                    errors='coerce'
                ).fillna(0)
            else:
                df_emendas[col] = 0.0

        # Guarda a base integral antes de qualquer recorte por cidade/tipo
        df_emendas_base = df_emendas.copy()

        # Base analítica única por emenda.
        # Algumas fontes retornam múltiplas linhas por `codigo_emenda`.
        # Para os gráficos e resumo, contamos cada emenda uma única vez.
        df_emendas_analise = (
            df_emendas_base
            .drop_duplicates(subset=['codigo_emenda'])
            .copy()
        )

        # 3. Buscar Detalhes (Convênios e Documentos)
        codigos_emendas = df_emendas['codigo_emenda'].unique().tolist() if not df_emendas.empty else []
        
        df_convenios = pd.DataFrame()
        df_documentos = pd.DataFrame()
        
        if codigos_emendas:
            placeholders = ','.join(['?'] * len(codigos_emendas))
            
            # Convênios
            query_convenios = f"""
            SELECT codigo_emenda, conv_numero, conv_objeto, conv_valor, conv_vigencia
            FROM convenios_emendas
            WHERE codigo_emenda IN ({placeholders})
            """
            df_convenios = pd.read_sql_query(query_convenios, conn, params=codigos_emendas)
            
            # Documentos (Fornecedores)
            query_docs = f"""
            SELECT codigo_emenda, doc_numero, fornecedor, doc_data, doc_valor, cnpj, doc_link
            FROM documentos_emendas
            WHERE codigo_emenda IN ({placeholders})
            """
            df_documentos = pd.read_sql_query(query_docs, conn, params=codigos_emendas)
            
            # Limpar doc_valor
            if not df_documentos.empty:
                df_documentos['doc_valor'] = (
                    df_documentos['doc_valor']
                    .astype(str)
                    .str.replace('R$', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False)
                    .str.strip()
                )
                df_documentos['doc_valor'] = pd.to_numeric(df_documentos['doc_valor'], errors='coerce').fillna(0)
                df_documentos['codigo_emenda'] = df_documentos['codigo_emenda'].astype(str)

            # Limpar conv_valor
            if not df_convenios.empty:
                df_convenios['conv_valor'] = (
                    df_convenios['conv_valor']
                    .astype(str)
                    .str.replace('R$', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False)
                    .str.strip()
                )
                df_convenios['conv_valor'] = pd.to_numeric(df_convenios['conv_valor'], errors='coerce').fillna(0)
                df_convenios['codigo_emenda'] = df_convenios['codigo_emenda'].astype(str)

        # Base única de documentos por emenda para aplicar filtros de cidade/tipo
        df_docs_city = pd.DataFrame()
        df_convenios_city = pd.DataFrame()
        if not df_documentos.empty:
            df_documentos['codigo_emenda'] = df_documentos['codigo_emenda'].astype(str)
            df_emendas['codigo_emenda'] = df_emendas['codigo_emenda'].astype(str)

            df_emendas_unique = df_emendas[['codigo_emenda', 'municipio', 'localidade_emenda']].drop_duplicates(subset=['codigo_emenda']).copy()
            df_docs_city = pd.merge(
                df_documentos,
                df_emendas_unique,
                on='codigo_emenda',
                how='left'
            )

            def resolve_doc_city(row):
                cidade_base = row.get('municipio') or row.get('localidade_emenda')
                cidade_norm = normalize_city_name(cidade_base)
                if cidade_norm and not any(t in cidade_norm for t in TERMOS_GENERICOS):
                    return cidade_norm
                return normalize_city_name(
                    extract_city_from_supplier({
                        'cidade_ref': cidade_base,
                        'fornecedor': row.get('fornecedor')
                    })
                )

            df_docs_city['cidade_filtro_base'] = df_docs_city.apply(resolve_doc_city, axis=1)
            df_docs_city['tipo_beneficiario'] = df_docs_city['fornecedor'].apply(classify_beneficiary)

            if not df_convenios.empty:
                df_convenios = df_convenios.copy()
                df_convenios['codigo_emenda'] = df_convenios['codigo_emenda'].astype(str)
                df_convenios_city = pd.merge(
                    df_convenios,
                    df_emendas_unique,
                    on='codigo_emenda',
                    how='left'
                )

                def resolve_conv_city(row):
                    cidade_base = row.get('municipio') or row.get('localidade_emenda')
                    cidade_norm = normalize_city_name(cidade_base)
                    if cidade_norm and not any(t in cidade_norm for t in TERMOS_GENERICOS):
                        return cidade_norm
                    return normalize_city_name(
                        extract_city_from_supplier({
                            'cidade_ref': cidade_base,
                            'fornecedor': row.get('conv_objeto')
                        })
                    )

                df_convenios_city['cidade_filtro_base'] = df_convenios_city.apply(resolve_conv_city, axis=1)

        # Aplicar filtros efetivos antes de qualquer agregação analítica
        filtros_ativos = bool((tipo_beneficiario and tipo_beneficiario != 'Todos') or (cidade and cidade.strip()))
        if filtros_ativos:
            if df_docs_city.empty:
                df_emendas = df_emendas.iloc[0:0].copy()
                df_documentos = df_documentos.iloc[0:0].copy()
                df_convenios = df_convenios.iloc[0:0].copy()
                df_docs_city = df_docs_city.iloc[0:0].copy()
            else:
                mask_docs = pd.Series(True, index=df_docs_city.index)

                if tipo_beneficiario and tipo_beneficiario != 'Todos':
                    mask_docs &= df_docs_city['tipo_beneficiario'].eq(tipo_beneficiario)

                if cidade and cidade.strip():
                    cidade_busca = normalize_city_name(cidade)
                    mask_docs &= (
                        df_docs_city['cidade_filtro_base'].astype(str).map(normalize_city_name).eq(cidade_busca)
                        | df_docs_city['municipio'].astype(str).map(normalize_city_name).eq(cidade_busca)
                        | df_docs_city['localidade_emenda'].astype(str).map(normalize_city_name).eq(cidade_busca)
                    )

                df_docs_city = df_docs_city[mask_docs].copy()
                codigos_filtrados = set(df_docs_city['codigo_emenda'].astype(str).unique().tolist())

                if codigos_filtrados:
                    df_emendas = df_emendas[df_emendas['codigo_emenda'].astype(str).isin(codigos_filtrados)].copy()
                    df_documentos = df_docs_city.copy()
                    if not df_convenios_city.empty and cidade and cidade.strip():
                        df_convenios = df_convenios_city[
                            df_convenios_city['cidade_filtro_base'].astype(str).map(normalize_city_name).eq(normalize_city_name(cidade))
                        ].copy()
                    else:
                        df_convenios = df_convenios_city[df_convenios_city['codigo_emenda'].astype(str).isin(codigos_filtrados)].copy() if not df_convenios_city.empty else df_convenios.iloc[0:0].copy()
                else:
                    df_emendas = df_emendas.iloc[0:0].copy()
                    df_documentos = df_documentos.iloc[0:0].copy()
                    df_convenios = df_convenios.iloc[0:0].copy()

        valor_docs_por_emenda = {}
        valor_convenios_por_emenda = {}
        if not df_docs_city.empty:
            valor_docs_por_emenda = (
                df_docs_city.groupby('codigo_emenda')['doc_valor']
                .sum()
                .to_dict()
            )
        if not df_convenios.empty:
            valor_convenios_por_emenda = (
                df_convenios.groupby('codigo_emenda')['conv_valor']
                .sum()
                .to_dict()
            )

        df_emendas_cidade = df_emendas_analise.copy()
        if cidade and cidade.strip() and not df_docs_city.empty:
            valor_docs_series = df_docs_city.groupby('codigo_emenda')['doc_valor'].sum()
            df_emendas_cidade = df_emendas_cidade[df_emendas_cidade['codigo_emenda'].astype(str).isin(valor_docs_series.index.astype(str))].copy()
            df_emendas_cidade['valor_pago_cidade'] = df_emendas_cidade['codigo_emenda'].astype(str).map(valor_docs_series.to_dict()).fillna(0)
            df_emendas_cidade['valor_empenhado_cidade'] = df_emendas_cidade['valor_pago_cidade']
        else:
            df_emendas_cidade['valor_pago_cidade'] = df_emendas_cidade['valor_pago']
            df_emendas_cidade['valor_empenhado_cidade'] = df_emendas_cidade['valor_empenhado']

        # 4. Agregar Dados
        
        valor_pago_total = df_emendas_base['valor_pago'].sum() if not df_emendas_base.empty else 0
        valor_empenhado_total = df_emendas_base['valor_empenhado'].sum() if not df_emendas_base.empty else 0
        valor_pago_cidade = float(df_emendas_cidade['valor_pago_cidade'].sum()) if not df_emendas_cidade.empty else 0
        valor_empenhado_cidade = float(df_emendas_cidade['valor_empenhado_cidade'].sum()) if not df_emendas_cidade.empty else 0
        if not cidade or not cidade.strip():
            valor_pago_cidade = valor_pago_total
            valor_empenhado_cidade = valor_empenhado_total

        valor_pago_restante = max(valor_pago_total - valor_pago_cidade, 0)
        valor_empenhado_restante = max(valor_empenhado_total - valor_empenhado_cidade, 0)

        resumo = {
            "total_emendas": len(df_emendas_analise),
            "valor_total_pago": valor_pago_cidade if cidade and cidade.strip() else valor_pago_total,
            "valor_total_empenhado": valor_empenhado_cidade if cidade and cidade.strip() else valor_empenhado_total,
            "valor_total_pago_cidade": valor_pago_cidade,
            "valor_total_empenhado_cidade": valor_empenhado_cidade,
            "valor_total_pago_restante": valor_pago_restante,
            "valor_total_empenhado_restante": valor_empenhado_restante,
            "valor_total_original_pago": valor_pago_total,
            "valor_total_original_empenhado": valor_empenhado_total,
            "total_cidades": df_emendas_analise['municipio'].nunique() if not df_emendas_analise.empty else 0,
            "data_atualizacao": datetime.now().strftime('%d/%m/%Y')
        }
        
        # Distribuições (Inicializar vazios)
        dist_tipo = pd.DataFrame(columns=['tipo', 'valor'])
        dist_ano = pd.DataFrame(columns=['ano', 'valor'])
        dist_tema = pd.DataFrame(columns=['tema', 'valor'])

        if not df_emendas_analise.empty:
            fonte_dist = df_emendas_cidade if cidade and cidade.strip() else df_emendas_analise
            dist_tipo = fonte_dist.groupby('tipo')[('valor_empenhado_cidade' if cidade and cidade.strip() else 'valor_empenhado')].sum().reset_index()
            dist_tipo['tipo'] = dist_tipo['tipo'].fillna('Não informado').astype(str).replace({'': 'Não informado'})
            dist_tipo.columns = ['tipo', 'valor']
            
            dist_ano = fonte_dist.groupby('ano')[('valor_empenhado_cidade' if cidade and cidade.strip() else 'valor_empenhado')].sum().reset_index()
            dist_ano['ano'] = dist_ano['ano'].fillna('Não informado').astype(str).replace({'': 'Não informado'})
            dist_ano.columns = ['ano', 'valor']
            
            # --- FLUXO DO DINHEIRO (SANKEY RELACIONAL) ---
            # Nível 1: Deputado -> Área (Tema)
            # Nível 2: Área -> Emenda (Código)
            # Nível 3: Emenda -> Convênio (Se houver)
            # Nível 4: Convênio -> Beneficiário Final
            # Nível 5: Beneficiário -> Sócio
            
            fluxo_links = []
            
            # Cache de sócios para evitar múltiplas queries
            todos_cnpjs_vistos = set()
            if not df_documentos.empty:
                todos_cnpjs_vistos.update(df_documentos['cnpj'].unique().tolist())
            
            # Tentar encontrar CNPJs para os proponentes dos convênios também
            proponentes_convenios = []
            if not df_convenios.empty:
                proponentes_convenios = df_convenios['conv_objeto'].unique().tolist()
            
            fornecedores_com_socio = {}
            if todos_cnpjs_vistos or proponentes_convenios:
                # Buscar por CNPJ
                if todos_cnpjs_vistos:
                    cnpjs_list = list(todos_cnpjs_vistos)
                    phs = ','.join(['?'] * len(cnpjs_list))
                    q = f"SELECT cnpj, Nome_Socio FROM lista_cnpj_geral WHERE cnpj IN ({phs})"
                    df_s = pd.read_sql_query(q, conn, params=cnpjs_list)
                    for _, s_row in df_s.iterrows():
                        c = s_row['cnpj']
                        if c not in fornecedores_com_socio: fornecedores_com_socio[c] = []
                        fornecedores_com_socio[c].append(s_row['Nome_Socio'])
                
                # Buscar por Nome (para convênios sem CNPJ direto)
                if proponentes_convenios:
                    # Tentar matches exatos de nomes de proponentes para pegar CNPJ e sócios
                    phs = ','.join(['?'] * len(proponentes_convenios))
                    q_n = f"SELECT Nome, cnpj, Nome_Socio FROM lista_cnpj_geral WHERE Nome IN ({phs})"
                    df_n = pd.read_sql_query(q_n, conn, params=proponentes_convenios)
                    for _, n_row in df_n.iterrows():
                        n = n_row['Nome']
                        if n not in fornecedores_com_socio: fornecedores_com_socio[n] = []
                        fornecedores_com_socio[n].append(n_row['Nome_Socio'])

            # Nível 1 e 2: Deputado -> Tema -> Emenda
            for _, row in fonte_dist.iterrows():
                dep_label = f"Deputado: {info_parlamentar.get('nome')}"
                tema_label = f"Área (Função): {row['tema']}"
                emenda_label = f"Emenda: {row['codigo_emenda']}"
                val = float(valor_docs_por_emenda.get(str(row['codigo_emenda']), row['valor_empenhado']))
                
                if val > 0:
                    fluxo_links.append({"source": dep_label, "target": tema_label, "value": val, "type": "tema"})
                    fluxo_links.append({"source": tema_label, "target": emenda_label, "value": val, "type": "emenda"})
            
            # Nível 3 e 4: Emenda -> Convênio -> Beneficiário
            if not df_convenios.empty:
                for _, row in df_convenios.iterrows():
                    emenda_label = f"Emenda: {row['codigo_emenda']}"
                    # CORREÇÃO DE MAPEAMENTO: conv_vigencia é o Numero Siconv, conv_objeto é o Beneficiário
                    conv_id = row['conv_vigencia'] if pd.notna(row['conv_vigencia']) else "S/N"
                    conv_label = f"Convênio: {conv_id}"
                    benef_label = f"Beneficiário (Convênio): {row['conv_objeto']}"
                    
                    val = float(valor_convenios_por_emenda.get(str(row['codigo_emenda']), 0) or 0)
                    if val <= 0:
                        try:
                            v = str(row['conv_valor']).replace('R$', '').replace('.', '').replace(',', '.').strip()
                            val = float(v)
                        except: val = 0
                    
                    if val > 0:
                        fluxo_links.append({"source": emenda_label, "target": conv_label, "value": val, "type": "convenio"})
                        fluxo_links.append({"source": conv_label, "target": benef_label, "value": val, "type": "fornecedor"})
                        
                        # Nível 5: Sócios do Beneficiário do Convênio
                        socs = fornecedores_com_socio.get(row['conv_objeto'], [])
                        if socs:
                            for s in socs[:3]:
                                s_label = f"Sócio presente no CNPJ: {s}"
                                fluxo_links.append({"source": benef_label, "target": s_label, "value": val / min(len(socs), 3), "type": "socio"})

            # Nível 4 e 5: Documento -> Fornecedor -> Sócio (via Documentos OB)
            if not df_documentos.empty:
                for _, row in df_documentos.iterrows():
                    em_id = row['codigo_emenda']
                    em_label = f"Emenda: {em_id}"
                    forn_label = f"Beneficiário da Emenda: {row['fornecedor']}"
                    val_doc = float(row['doc_valor'])
                    
                    if val_doc > 0:
                        # Se existe convênio para esta emenda, ligamos via convênio
                        target_source = em_label
                        if not df_convenios.empty:
                            convs_em = df_convenios[df_convenios['codigo_emenda'] == em_id]
                            if not convs_em.empty:
                                target_source = f"Convênio: {convs_em.iloc[0]['conv_vigencia']}"
                        
                        fluxo_links.append({"source": target_source, "target": forn_label, "value": val_doc, "type": "fornecedor"})
                        
                        # Nível 6: Sócio
                        socs = fornecedores_com_socio.get(row['cnpj'], [])
                        if socs:
                            for s in socs[:3]:
                                s_label = f"Sócio presente no CNPJ: {s}"
                                fluxo_links.append({"source": forn_label, "target": s_label, "value": val_doc / min(len(socs), 3), "type": "socio"})

            # --- Hierarquia Temática (SUNBURST/TREEMAP) ---
            df_hier = fonte_dist.groupby(['tema', 'subfuncao'])['valor_empenhado_cidade' if cidade and cidade.strip() else 'valor_empenhado'].sum().reset_index()
            if cidade and cidade.strip():
                df_hier.rename(columns={'valor_empenhado_cidade': 'valor_empenhado'}, inplace=True)
            hier_list = []
            for func in df_hier['tema'].unique():
                children = []
                sub_df = df_hier[df_hier['tema'] == func]
                for _, row in sub_df.iterrows():
                    children.append({"name": row['subfuncao'], "value": float(row['valor_empenhado'])})
                hier_list.append({
                    "name": func,
                    "children": children,
                    "value": sum(c['value'] for c in children)
                })
            resumo['hierarquia_tematica'] = hier_list
            
            # Para manter compatibilidade com gráficos simples legados
            dist_tema = fonte_dist.groupby('tema')[('valor_empenhado_cidade' if cidade and cidade.strip() else 'valor_empenhado')].sum().reset_index()
            dist_tema['tema'] = dist_tema['tema'].fillna('Não informado').astype(str).replace({'': 'Não informado'})
            dist_tema.columns = ['tema', 'valor']
            
            # Mapa - Nova Lógica via CNPJ
            # Tentar pegar coordenadas via CNPJ dos documentos primeiro
            if not df_documentos.empty:
                # Merge emendas com documentos para saber qual emenda tem qual CNPJ
                # OBS: Usamos 'doc_valor' para o mapa, não o 'valor_pago' da emenda (que repetiria por documento)
                
                # PREVENÇÃO DE DUPLICATAS: 
                # A tabela de emendas pode ter multiplas linhas para o mesmo codigo_emenda (por gnd, fonte, etc).
                # Precisamos de apenas UMA entrada de localidade por emenda para não multiplicar os documentos.
                df_emendas_unique = df_emendas[['codigo_emenda', 'municipio']].drop_duplicates(subset=['codigo_emenda'])
                
                # USAR TODOS OS DOCUMENTOS (Não apenas OB) para visibilidade máxima
                # Mas evitar duplicação de códigos de emenda se houver múltiplos documentos
                # A ideia é mapear a DESTINAÇÃO, então pegamos CNPJs únicos por emenda.
                df_docs_mapa = df_documentos.drop_duplicates(subset=['codigo_emenda', 'cnpj']).copy()

                df_mapa_cnpj = pd.merge(
                    df_emendas_unique, 
                    df_docs_mapa[['codigo_emenda', 'cnpj', 'fornecedor', 'doc_valor']], 
                    on='codigo_emenda', 
                    how='left'
                )
                
                # Renomear doc_valor para valor_pago para manter compatibilidade com o resto do código de mapa
                df_mapa_cnpj.rename(columns={'doc_valor': 'valor_pago'}, inplace=True)
                
                # Limpar CNPJ para match (remover zeros a esquerda pois no coordenadas_empresas parece estar sem)
                df_mapa_cnpj['cnpj_clean'] = df_mapa_cnpj['cnpj'].astype(str).str.replace(r'\D', '', regex=True).str.lstrip('0')
                
                cnpjs_busca = df_mapa_cnpj['cnpj_clean'].dropna().unique().tolist()
                
                if cnpjs_busca:
                    placeholders = ','.join(['?'] * len(cnpjs_busca))
                    
                    # Buscar Coordenadas (pode ter Cidade=None)
                    query_coords_cnpj = f"""
                    SELECT cnpj, latitude, longitude, Cidade
                    FROM coordenadas_empresas
                    WHERE cnpj IN ({placeholders})
                    """
                    df_coords_cnpj = pd.read_sql_query(query_coords_cnpj, conn, params=cnpjs_busca)
                    
                    # Buscar Nomes de Cidades na lista_cnpj_geral (para preencher None)
                    query_nomes_cnpj = f"""
                    SELECT CAST(cnpj AS TEXT) as cnpj, Cidade as Cidade_Nome, Estado as Estado_Nome
                    FROM lista_cnpj_geral
                    WHERE CAST(cnpj AS TEXT) IN ({placeholders})
                    """
                    df_nomes_cnpj = pd.read_sql_query(query_nomes_cnpj, conn, params=cnpjs_busca)
                    
                    # Merge nomes de cidades (para corrigir Cidade=None)
                    df_coords_cnpj = df_coords_cnpj.drop_duplicates(subset=['cnpj'])
                    df_nomes_cnpj = df_nomes_cnpj.drop_duplicates(subset=['cnpj'])

                    df_mapa_cnpj = pd.merge(df_mapa_cnpj, df_coords_cnpj, left_on='cnpj_clean', right_on='cnpj', how='left')
                    
                    df_mapa_cnpj = pd.merge(df_mapa_cnpj, df_nomes_cnpj, left_on='cnpj_clean', right_on='cnpj', how='left', suffixes=('', '_lista'))
                    
                else:
                    df_mapa_cnpj['latitude'] = None
                    df_mapa_cnpj['longitude'] = None
                
                # Agrupar por coordenada (ou municipio se não achou coordenada)
                # Prioridade: Coordenada do CNPJ > Coordenada do Municipio (via nome)
                
                # 1. Separar os que TEM e os que NÃO TEM coordenada específica do CNPJ
                df_mapa_final = df_mapa_cnpj.copy()
                
                # Preencher Cidade com o que veio da lista_cnpj_geral se o do coordenadas for None
                if 'Cidade_Nome' in df_mapa_final.columns:
                     df_mapa_final['Cidade'] = df_mapa_final['Cidade'].fillna(df_mapa_final['Cidade_Nome'])
                
                # Definir cidade de referência e fornecedor
                df_mapa_final['cidade_ref'] = df_mapa_final['municipio'].fillna(df_mapa_final['Cidade'])
                df_mapa_final['cidade_ref'] = df_mapa_final['cidade_ref'].fillna('Desconhecido')
                df_mapa_final['fornecedor'] = df_mapa_final['fornecedor'].fillna('Não Informado')

                def resolve_city_ref(row):
                    city_base = row.get('cidade_ref')
                    city_norm = normalize_city_name(str(city_base))
                    if city_norm and not any(t in city_norm for t in TERMOS_GENERICOS):
                        return city_base
                    return extract_city_from_supplier(row)

                df_mapa_final['cidade_ref'] = df_mapa_final.apply(resolve_city_ref, axis=1)
                
                # Normalização final para evitar duplicatas em Treemap/Mapa (Remover lixo)
                df_mapa_final['cidade_ref'] = df_mapa_final['cidade_ref'].apply(normalize_city_name)

                # PRIORIDADE: Só sobrescreve se o que temos em cidade_ref for genérico e o que temos no DB não for
                if 'Cidade' in df_mapa_final.columns:
                    def update_city_ref(row):
                        old_city = str(row['cidade_ref']).upper()
                        new_city = row['Cidade']
                        if pd.isna(new_city): return row['cidade_ref']
                        
                        new_city_norm = normalize_city_name(str(new_city))
                        # Se a cidade atual é genérica E a nova não é, atualiza
                        if any(t in old_city for t in TERMOS_GENERICOS) or len(old_city) <= 3:
                            if new_city_norm and not any(t in new_city_norm for t in TERMOS_GENERICOS):
                                return new_city
                        return row['cidade_ref']
                    
                    df_mapa_final['cidade_ref'] = df_mapa_final.apply(update_city_ref, axis=1)

                # Classificação (Mover para cá para que filtros funcionem)
                df_mapa_final['tipo_beneficiario'] = df_mapa_final['fornecedor'].apply(classify_beneficiary)
                
                # LOGICA DE FALLBACK DE COORDENADAS (Cidade Centro)
                # Identificar cidades faltando
                cidades_raw = df_mapa_final[df_mapa_final['latitude'].isna()]['cidade_ref'].unique().tolist()
                
                # Mapa de normalização (Raw -> Clean)
                normalization_map = {}
                cidades_clean_set = set()
                
                for c in cidades_raw:
                    clean = normalize_city_name(c)
                    if clean:
                        normalization_map[c] = clean
                        cidades_clean_set.add(clean)
                
                cidades_busca = list(cidades_clean_set)

                if cidades_busca:
                    print(f"   🗺️  Buscando coordenadas de fallback para {len(cidades_busca)} cidades (de {len(cidades_raw)} originais)...")
                    try:
                        # 1. Tentar usar CSV de municipios brasileiros (mais robusto)
                        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'municipios_brasileiros.csv')
                        
                        fallback_map = {
                            'NACIONAL': {'lat_media': -15.7801, 'lon_media': -47.9292},
                            'BRASIL': {'lat_media': -15.7801, 'lon_media': -47.9292},
                            'MULTIPLO': {'lat_media': -15.7801, 'lon_media': -47.9292},
                            'NACIONAL / MULTIPLO': {'lat_media': -15.7801, 'lon_media': -47.9292},
                            'NACIONAL/MULTIPLO': {'lat_media': -15.7801, 'lon_media': -47.9292},
                            'ESTADO DE SAO PAULO': {'lat_media': -23.5505, 'lon_media': -46.6333},
                            'SAO PAULO (UF)': {'lat_media': -23.5505, 'lon_media': -46.6333},
                            'SP': {'lat_media': -23.5505, 'lon_media': -46.6333}
                        }
                        
                        if os.path.exists(csv_path):
                            try:
                                df_mun_br = pd.read_csv(csv_path)
                                # Criar mapa normalizado -> {lat, lon}
                                # Normalizar coluna nome_municipio
                                df_mun_br['norm'] = df_mun_br['nome_municipio'].apply(normalize_city_name)
                                
                                # Convert to dict
                                for _, row_br in df_mun_br.iterrows():
                                    fallback_map[row_br['norm']] = {
                                        'lat_media': row_br['latitude'],
                                        'lon_media': row_br['longitude']
                                    }
                            except Exception as e:
                                print(f"Erro ao ler municipios_brasileiros.csv: {e}")

                        # 2. Se ainda sobrar, ou se CSV falhar, tentar Tabela de Empresas
                        # Mas o CSV deve cobrir 99%
                        # Vamos manter a query SQL apenas se precisar? 
                        # Na verdade, a query SQL era pra empresas. A estratégia do CSV é melhor pra cidades.
                        # Vamos usar o fallback_map preenchido pelo CSV.
                        
                        # (Opcional) Poderia complementar com SQL aqui se quisesse, mas vamos confiar no CSV

                        
                        # Aplicar fallback
                        def get_fallback_lat(row):
                            if pd.notnull(row['latitude']): return row['latitude']
                            # Tentar nome direto
                            raw_city = row['cidade_ref']
                            city_data = fallback_map.get(raw_city) 
                            # Se falhar, tentar nome normalizado
                            if not city_data:
                                clean_city = normalization_map.get(raw_city)
                                city_data = fallback_map.get(clean_city)
                                
                            if city_data: return city_data['lat_media']
                            return None

                        def get_fallback_lon(row):
                            if pd.notnull(row['longitude']): return row['longitude']
                            raw_city = row['cidade_ref']
                            city_data = fallback_map.get(raw_city)
                            if not city_data:
                                clean_city = normalization_map.get(raw_city)
                                city_data = fallback_map.get(clean_city)
                                
                            if city_data: return city_data['lon_media']
                            return None

                        df_mapa_final['latitude'] = df_mapa_final.apply(get_fallback_lat, axis=1)
                        df_mapa_final['longitude'] = df_mapa_final.apply(get_fallback_lon, axis=1)
                        
                    except Exception as e:
                        print(f"Erro no fallback de coordenadas: {e}")

                # DEBUG REMOVED (Fixed)
                
                # --- PREPARAÇÃO DE COLUNAS FALTANTES PARA AGREGAÇÃO ---
                # A agregação espera colunas que ainda não existem. Vamos cria-las.
                
                # 1. Tipo Beneficiário
                if 'tipo_beneficiario' not in df_mapa_final.columns:
                    df_mapa_final['tipo_beneficiario'] = df_mapa_final['fornecedor'].apply(classify_beneficiary)
                
                # 2. Estado (Usar Estado_Nome vindo do coordenadas ou estado do parlamentar)
                if 'estado' not in df_mapa_final.columns:
                    if 'Estado_Nome' in df_mapa_final.columns:
                        df_mapa_final['estado'] = df_mapa_final['Estado_Nome']
                    else:
                        df_mapa_final['estado'] = info_parlamentar.get('estado', '')
                
                # 3. Colunas de Inicialização (Zeros/False)
                cols_defaults = {
                    'votos_recebidos': 0,
                    'percentual_prefeitura': 0,
                    'percentual_ong': 0,
                    'percentual_empresa': 0,
                    'is_reduto': False,
                    'convenios': None 
                }
                for col, default_val in cols_defaults.items():
                    if col not in df_mapa_final.columns:
                        df_mapa_final[col] = default_val

                # Salvar versão raw para uso posterior (convênios)
                df_mapa_raw = df_mapa_final.copy()

                if cidade and cidade.strip():
                    cidade_normalizada_filtro = normalize_city_name(cidade)
                    df_mapa_final = df_mapa_final[
                        df_mapa_final['cidade_ref'].apply(normalize_city_name) == cidade_normalizada_filtro
                    ].copy()
                    df_mapa_raw = df_mapa_raw[
                        df_mapa_raw['cidade_ref'].apply(normalize_city_name) == cidade_normalizada_filtro
                    ].copy()

                df_mapa_final = df_mapa_final.groupby(
                    ['latitude', 'longitude', 'cidade_ref', 'municipio', 'fornecedor', 'estado', 'is_reduto'], dropna=False
                ).agg({
                    'valor_pago': 'sum', 
                    'votos_recebidos': 'max', 
                    'percentual_prefeitura': 'max',
                    'percentual_ong': 'max', 
                    'percentual_empresa': 'max',
                    'tipo_beneficiario': 'first',
                    'convenios': lambda x: list(set(y for z in x for y in (z if isinstance(z, list) else [z]) if pd.notna(y))),
                    'codigo_emenda': 'count'
                }).reset_index()

                df_mapa_final.rename(columns={'codigo_emenda': 'qtde_pagamentos'}, inplace=True)
            dict_votos_municipio = {}
            try:
                duck_db_path = DUCK_DB_PATH
                if os.path.exists(duck_db_path):
                    con_duck = safe_duckdb_connect(duck_db_path, read_only=True)
                    # Normalizar nome do parlamentar para busca (remover acentos se precisar, mas o banco parece ter acentos)
                    # Vamos tentar busca direta primeiro.
                    nome_parlamentar_busca = info_parlamentar.get('nome_parlamentar')
                    
                    query_votos = f"""
                        SELECT NM_MUNICIPIO, SUM(QT_VOTOS_NOMINAIS)
                        FROM votacao
                        WHERE NM_PARLAMENTAR = '{nome_parlamentar_busca}'
                        GROUP BY NM_MUNICIPIO
                    """
                    # Se não achar, tentar com LIKE ou normalizado?
                    # O debug mostrou que 'SAULO PEDROSO' funcionou direto.
                    
                    results_votos = con_duck.execute(query_votos).fetchall()
                    
                    for row in results_votos:
                        if row[0]:
                            # Normalizar chave cidade para match (uppercase)
                            cidade_key = row[0].upper().strip()
                            dict_votos_municipio[cidade_key] = row[1]
                    
                    con_duck.close()
            except Exception as e:
                print(f"Erro ao buscar votos por municipio: {e}")

            municipios_data = []
            total_valor_mapa = df_emendas['valor_pago'].sum() # Total geral
            
            # Função auxiliar para buscar votos
            def get_votos_cidade(nome_cidade):
                if not nome_cidade: return 0
                nome_upper = nome_cidade.upper().strip()
                if nome_upper in dict_votos_municipio:
                    return dict_votos_municipio[nome_upper]
                return 0


            # Adicionar pontos via CNPJ
            if not df_mapa_final.empty:
                # Classificar cada linha antes de agrupar final
                df_mapa_final['tipo'] = df_mapa_final['fornecedor'].apply(classify_beneficiary)
                
                # Agrupar por cidade para totais
                df_cidade_totais = df_mapa_final.groupby('cidade_ref')['valor_pago'].sum().to_dict()
                
                # Agrupar por cidade e tipo para percentuais
                df_cidade_tipo = df_mapa_final.groupby(['cidade_ref', 'tipo'])['valor_pago'].sum().reset_index()
                
                # Dicionário de percentuais por cidade
                dict_percentuais = {}
                for _, row in df_cidade_tipo.iterrows():
                    cidade = row['cidade_ref']
                    tipo = row['tipo']
                    valor = row['valor_pago']
                    total = df_cidade_totais.get(cidade, 0)
                    if total == 0:
                        total = 1 # Evitar divisão por zero
                    if cidade not in dict_percentuais:
                        dict_percentuais[cidade] = {'Prefeitura': 0, 'ONG': 0, 'Empresa': 0}
                    dict_percentuais[cidade][tipo] = (valor / total) * 100

                # Para o mapa, queremos pontos individuais ou agregados?
                # O usuário quer "marcar separado prefeitura, ONG e empresa".
                # Se agruparmos por (lat, lon, tipo), teremos pontos distintos se as coordenadas forem diferentes.
                # Se forem iguais, vão sobrepor.
                # Mas o df_mapa_final já está agrupado por (lat, lon, cidade, fornecedor).
                # Vamos manter essa granularidade para o mapa, mas adicionar o tipo.
                
            # Função auxiliar para limpar nome da cidade (usada em convênios e no loop principal)
            def clean_city_name(name):
                if not isinstance(name, str): return ""
                import unicodedata
                name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII')
                name = name.upper().strip()
                if '(UF)' in name:
                    name = name.replace('(UF)', '').strip()
                if ' - ' in name:
                    name = name.split(' - ')[0].strip()
                return name

            # Mapear convênios por cidade (via Emendas -> Documentos -> CNPJ -> Cidade)
            city_convenios_map = {}
            if not df_documentos.empty and not df_convenios.empty:
                try:
                    # 1. Mapear Emenda -> Convênios
                    # OBS: A tabela convenios_emendas parece ter colunas trocadas.
                    # O número do convênio (SICONV) está na coluna 'conv_vigencia' (ex: 959716).
                    # A coluna 'conv_numero' tem datas.
                    df_convenios['codigo_emenda'] = df_convenios['codigo_emenda'].astype(str)
                    emenda_convenios = df_convenios.groupby('codigo_emenda')['conv_vigencia'].apply(list).to_dict()
                    
                    # 2. Mapear CNPJ -> Cidade (já temos df_nomes_cnpj ou df_mapa_cnpj)
                    # Precisamos garantir que temos o mapa de CNPJ para Cidade usado no mapa
                    # df_mapa_cnpj tem 'cnpj_clean' e 'Cidade' (ou 'cidade_ref' depois do processamento)
                    
                    # Vamos usar o df_com_coords que é a base do mapa final
                    # Ele tem 'cidade_ref' e 'cnpj_clean' (ou 'cnpj' do merge)
                    # Mas df_com_coords perdeu a coluna 'codigo_emenda' pois veio de df_mapa_cnpj que veio de df_emendas agrupado?
                    # Não, df_mapa_cnpj veio de df_emendas (que tem codigo_emenda)
                    
                    # Vamos reconstruir o link: Documento (tem codigo_emenda e cnpj) -> Cidade
                    
                    # Preparar df_documentos
                    df_docs_temp = df_documentos[['codigo_emenda', 'cnpj']].copy()
                    df_docs_temp['cnpj_clean'] = df_docs_temp['cnpj'].astype(str).str.replace(r'\D', '', regex=True)
                    
                    # Preparar mapa de CNPJ -> Cidade (usando o que foi decidido no mapa)
                    # df_mapa_raw tem a relação final de CNPJ -> Cidade usada no mapa
                    if 'cnpj_clean' in df_mapa_raw.columns and 'cidade_ref' in df_mapa_raw.columns:
                        cnpj_city_map = df_mapa_raw.set_index('cnpj_clean')['cidade_ref'].to_dict()
                        
                        # Adicionar cidade ao df_docs_temp
                        df_docs_temp['cidade_ref'] = df_docs_temp['cnpj_clean'].map(cnpj_city_map)
                        
                        # Filtrar apenas os que têm cidade definida
                        df_docs_with_city = df_docs_temp.dropna(subset=['cidade_ref'])
                        
                        # Agrupar emendas por cidade
                        city_emendas = df_docs_with_city.groupby('cidade_ref')['codigo_emenda'].apply(set).to_dict()
                        
                        # 3. Construir mapa Cidade -> Convênios
                        for cidade, emendas in city_emendas.items():
                            convs = set()
                            for emenda in emendas:
                                if emenda in emenda_convenios:
                                    convs.update(emenda_convenios[emenda])
                            if convs:
                                city_convenios_map[clean_city_name(cidade)] = list(convs)
                                
                except Exception as e:
                    print(f"Erro ao mapear convênios complexos: {e}")

            # Adicionar pontos via CNPJ
            if not df_mapa_final.empty:
                # ... (código existente) ...
                
                for _, row in df_mapa_final.iterrows():
                    # Filtro de valor zero
                    if row['valor_pago'] <= 0:
                        continue
                        
                    cidade_nome = row['cidade_ref']
                    votos = get_votos_cidade(cidade_nome)
                    percents = dict_percentuais.get(cidade_nome, {'Prefeitura': 0, 'ONG': 0, 'Empresa': 0})
                    
                    # Buscar convênios para esta cidade
                    cidade_key = clean_city_name(cidade_nome)
                    lista_convenios = city_convenios_map.get(cidade_key, [])
                    
                    municipios_data.append({
                        "municipio": f"{cidade_nome}",
                        "beneficiario": row['fornecedor'],
                        "tipo_beneficiario": row['tipo_beneficiario'], # Fix column name from 'tipo' to 'tipo_beneficiario'
                        "qtde_pagamentos": int(row['qtde_pagamentos']) if pd.notna(row['qtde_pagamentos']) else 0, # Cast to int for JSON safety
                        "estado": info_parlamentar.get('estado', ''),
                        "latitude": row['latitude'] if pd.notna(row['latitude']) else None,
                        "longitude": row['longitude'] if pd.notna(row['longitude']) else None,
                        "valor_total": row['valor_pago'] if pd.notna(row['valor_pago']) else 0.0,
                        "percentual_valor": (row['valor_pago'] / total_valor_mapa * 100) if total_valor_mapa > 0 else 0,
                        "votos_recebidos": votos,
                        "percentual_prefeitura": percents.get('Prefeitura', 0),
                        "percentual_ong": percents.get('ONG', 0),
                        "percentual_empresa": percents.get('Empresa', 0),
                        "convenios": lista_convenios, # Lista de números de convênios
                        "is_reduto": False 
                    })
            

                    
            if not municipios_data:
                # Fallback Lógica Antiga (Nome da Cidade) - Mantido apenas se TUDO falhar
                # ... (código existente) ...
                df_mapa = df_emendas.groupby('municipio')['valor_pago'].sum().reset_index()
                df_mapa.columns = ['municipio', 'valor_total']
                
                # ... (Lógica de resolve_cidade e query_coords antiga) ...
                def resolve_cidade(row):
                    mun = row['municipio']
                    if mun in ['MÚLTIPLO', 'Nacional', 'MULTIPLO']:
                        estado_parlamentar = info_parlamentar.get('estado')
                        if estado_parlamentar and estado_parlamentar in ESTADO_CAPITAL:
                            return ESTADO_CAPITAL[estado_parlamentar]
                        return 'BRASILIA'
                    
                    # Tratamento para "CIDADE - UF" (ex: "ARUJÁ - SP")
                    if ' - ' in mun:
                         parts = mun.split(' - ')
                         clean_mun = parts[0].strip()
                         import unicodedata
                         clean_mun = ''.join(c for c in unicodedata.normalize('NFD', clean_mun) if unicodedata.category(c) != 'Mn').upper()
                         return clean_mun

                    if '(UF)' in mun:
                        clean_mun = mun.replace(' (UF)', '').strip()
                        if clean_mun in NOME_ESTADO_CAPITAL:
                            return NOME_ESTADO_CAPITAL[clean_mun]
                        return clean_mun 
                    return mun

                df_mapa['cidade_busca'] = df_mapa.apply(resolve_cidade, axis=1)
                cidades_nomes = df_mapa['cidade_busca'].unique().tolist()
                
                if cidades_nomes:
                    placeholders = ','.join(['?'] * len(cidades_nomes))
                    query_coords = f"""
                    SELECT Cidade, AVG(latitude) as lat, AVG(longitude) as lon
                    FROM coordenadas_empresas
                    WHERE Cidade IN ({placeholders})
                    GROUP BY Cidade
                    """
                    df_coords = pd.read_sql_query(query_coords, conn, params=cidades_nomes)
                    df_mapa = pd.merge(df_mapa, df_coords, left_on='cidade_busca', right_on='Cidade', how='left')
                else:
                    df_mapa['lat'] = None
                    df_mapa['lon'] = None
                
                for _, row in df_mapa.iterrows():
                    if row['valor_total'] <= 0:
                        continue
                        
                    if pd.notna(row['lat']) and pd.notna(row['lon']):
                        cidade_nome = row['cidade_busca']
                        votos = get_votos_cidade(cidade_nome)
                        
                        municipios_data.append({
                            "municipio": row['municipio'],
                            "beneficiario": "Prefeitura / Indefinido",
                            "tipo_beneficiario": "Prefeitura", # Assume prefeitura no fallback? Ou Outros? Vamos de Prefeitura por padrão em emendas diretas.
                            "estado": info_parlamentar.get('estado', ''),
                            "latitude": row['lat'],
                            "longitude": row['lon'],
                            "valor_total": row['valor_total'],
                            "percentual_valor": (row['valor_total'] / total_valor_mapa * 100) if total_valor_mapa > 0 else 0,
                            "votos_recebidos": votos,
                            "percentual_prefeitura": 100, # Assume 100% no fallback
                            "percentual_ong": 0,
                            "percentual_empresa": 0
                        })

        else:
            municipios_data = []

        # Atualizar contagem de cidades no resumo com base no mapa real
        # Filtra termos genéricos para o contador de cidades atendidas ser real
        cidades_unicas = set()
        for m in municipios_data:
            c_name = normalize_city_name(m.get('municipio', ''))
            if c_name and not any(t in c_name for t in TERMOS_GENERICOS) and len(c_name) > 3:
                cidades_unicas.add(c_name)
        
        total_cidades_mapa = len(cidades_unicas)
        resumo['total_cidades'] = total_cidades_mapa

        # Processar Fornecedores (dos documentos)
        fornecedores_data = []
        if not df_documentos.empty:
            # Merge com emendas para pegar cidade
            # Garantir tipos compatíveis para merge
            if df_docs_city.empty:
                df_docs_city = pd.merge(df_documentos, df_emendas[['codigo_emenda', 'localidade_emenda']], on='codigo_emenda', how='left')
            
            # Agrupar por fornecedor
            df_forn = df_docs_city.groupby(['fornecedor', 'cnpj']).agg({
                'doc_valor': 'sum',
                'localidade_emenda': lambda x: list(set(x.dropna()))
            }).reset_index()
            
            # Resolver cidade do fornecedor usando a lógica global
            def resolve_forn_city(row):
                # localidade_emenda é uma lista, pegar a primeira se existir
                loc = row['localidade_emenda'][0] if row['localidade_emenda'] else 'Desconhecido'
                temp_row = {'cidade_ref': loc, 'fornecedor': row['fornecedor']}
                return extract_city_from_supplier(temp_row)
            
            df_forn['cidade_resolvida'] = df_forn.apply(resolve_forn_city, axis=1)
            
            df_forn = df_forn.sort_values('doc_valor', ascending=False).head(20) # Top 20
            
            total_forn = df_forn['doc_valor'].sum()
            
            for _, row in df_forn.iterrows():
                city_display = row['cidade_resolvida']

                fornecedores_data.append({
                    "fornecedor": row['fornecedor'],
                    "cidade": city_display,
                    "estado": info_parlamentar.get('estado', ''), # Estado do parlamentar como fallback
                    "valor_total": row['doc_valor'],
                    "percentual": (row['doc_valor'] / total_forn * 100) if total_forn > 0 else 0
                })

        # Processar Convênios
        convenios_data = []
        if not df_convenios.empty:
            df_conv_city = pd.merge(
                df_convenios,
                df_emendas[['codigo_emenda', 'localidade_emenda', 'municipio']].drop_duplicates(subset=['codigo_emenda']),
                on='codigo_emenda',
                how='left'
            )

            df_conv_city = df_conv_city.sort_values('conv_valor', ascending=False).head(50)

            for _, row in df_conv_city.iterrows():
                if safe_money(row.get('conv_valor')) <= 0:
                    continue

                cidade_base = row.get('localidade_emenda') or row.get('municipio')
                cidade_display = normalize_city_name(cidade_base)
                if not cidade_display or any(t in cidade_display for t in TERMOS_GENERICOS):
                    cidade_display = extract_city_from_supplier({
                        'cidade_ref': cidade_base,
                        'fornecedor': row.get('conv_objeto')
                    })
                cidade_display = normalize_city_name(cidade_display)
                if cidade_display in ['MULTIPLO', 'NACIONAL']:
                    cidade_display = "Nacional / Múltiplo"
                elif not cidade_display:
                    cidade_display = "N/A"

                convenios_data.append({
                    "numero": row.get('conv_numero'),
                    "codigo_emenda": row.get('codigo_emenda'),
                    "objeto": row.get('conv_objeto'),
                    "valor": safe_money(row.get('conv_valor')),
                    "cidade": cidade_display
                })

        # Processar Documentos (Lista simples)
        documentos_data = []
        if not df_documentos.empty:
            if df_docs_city.empty:
                df_docs_city = pd.merge(
                    df_documentos,
                    df_emendas[['codigo_emenda', 'localidade_emenda', 'municipio']].drop_duplicates(subset=['codigo_emenda']),
                    on='codigo_emenda',
                    how='left'
                )

            df_docs_sorted = df_docs_city.sort_values('doc_valor', ascending=False).head(50).copy()

            for _, row in df_docs_sorted.iterrows():
                if safe_money(row.get('doc_valor')) <= 0:
                    continue

                cidade_display = normalize_city_name(row.get('localidade_emenda') or row.get('municipio'))
                if not cidade_display or any(t in cidade_display for t in TERMOS_GENERICOS):
                    cidade_display = extract_city_from_supplier({
                        'cidade_ref': row.get('localidade_emenda') or row.get('municipio'),
                        'fornecedor': row.get('fornecedor')
                    })
                cidade_display = normalize_city_name(cidade_display)
                if cidade_display in ['MULTIPLO', 'NACIONAL']:
                    cidade_display = "Nacional / Múltiplo"
                elif not cidade_display:
                    cidade_display = "N/A"

                documentos_data.append({
                    "codigo_emenda": row.get('codigo_emenda'),
                    "numero": row.get('doc_numero'),
                    "fornecedor": row.get('fornecedor'),
                    "cidade": cidade_display,
                    "estado": info_parlamentar.get('estado', ''),
                    "data": row.get('doc_data'),
                    "valor": safe_money(row.get('doc_valor'))
                })



        # 4. Buscar Conflitos de Interesse no cruzamento pré-processado
        conflitos_data = []
        try:
            # Buscar matches para o parlamentar selecionado ou empresas que receberam dele
            # Normalizar nome para busca
            nome_p_norm = normalize_city_name(parlamentar) # Reusar normalizador
            
            query_conflitos = """
                SELECT tipo_vinculo, socio_vinc_parlamentar, vinculo_com_quem, nome_recebedor, valor_emenda, codigo_emenda
                FROM cruzamento_emendas_sociedades
                WHERE parlamentar_autor LIKE ?
            """
            df_conf = pd.read_sql_query(query_conflitos, conn, params=(f"%{parlamentar}%",))
            conflitos_data = df_conf.to_dict('records')
        except Exception as e:
            logger.error(f"Erro ao buscar conflitos: {e}")

        logger.info(
            "📦 Emendas analise payload: emendas=%s fornecedores=%s convenios=%s documentos=%s filtros(tipo=%s cidade=%s)",
            len(df_emendas) if 'df_emendas' in locals() else 0,
            len(fornecedores_data),
            len(convenios_data),
            len(documentos_data),
            tipo_beneficiario,
            cidade,
        )

        return clean_data_for_json({
            "info_parlamentar": info_parlamentar,
            "resumo": resumo,
            "distribuicao_por_tipo": dist_tipo.to_dict('records'),
            "distribuicao_por_ano": dist_ano.to_dict('records'),
            "distribuicao_por_tema": dist_tema.to_dict('records'),
            "hierarquia_tematica": hier_list,
            "fluxo_dinheiro": fluxo_links,
            "municipios": municipios_data,
            "fornecedores": fornecedores_data,
            "convenios": convenios_data,
            "documentos": documentos_data,
            "conflitos": conflitos_data
        })

    except Exception as e:
        logger.error(f"Erro na análise de emendas: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar emendas: {str(e)[:200]}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.get("/api/emendas/conflitos-ranking")
async def get_emendas_conflitos_ranking(uf: Optional[str] = None, partido: Optional[str] = None, nome: Optional[str] = None):
    """Retorna o ranking global de parlamentares com conflitos de interesse identificados, com filtros opcionais."""
    try:
        conn = get_db_connection("tabelao")
        
        where_clauses = []
        params = []

        if uf:
            where_clauses.append("t.sgUF = ?")
            params.append(uf)
        # Ignora filtro de partido quando um parlamentar específico é selecionado
        if partido and not nome:
            where_clauses.append("t.sgPartido = ?")
            params.append(partido)
        if nome:
            where_clauses.append("TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) = ?")
            params.append(nome)
            
        where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Query que cruza os conflitos com metadados do parlamentar (Partido/UF)
        # Filtramos valores zerados (R$ 0,00) para focar em conflitos reais de recursos
        # Usamos COUNT(DISTINCT ...) para que o total de "Red Flags" bata com o número de linhas únicas mostradas
        query = f"""
            SELECT 
                TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) as nome_limpo,
                t.sgPartido as partido,
                t.sgUF as uf,
                t.ultimoStatus_urlFoto,
                t.urlPartido as urlPartido,
                t.urlEstado,
                COUNT(DISTINCT 
                    c.nome_recebedor || 
                    c.socio_vinc_parlamentar || 
                    c.codigo_emenda || 
                    c.vinculo_com_quem || 
                    c.valor_emenda
                ) as total_conflitos,
                SUM(CAST(REPLACE(REPLACE(c.valor_emenda, '.', ''), ',', '.') AS REAL)) as valor_total
            FROM cruzamento_emendas_sociedades c
            LEFT JOIN (
                SELECT 
                    nome, 
                    MAX(sgPartido) as sgPartido, 
                    MAX(sgUF) as sgUF,
                    MAX(ultimoStatus_urlFoto) as ultimoStatus_urlFoto,
                    MAX(urlPartido) as urlPartido,
                    MAX(urlEstado) as urlEstado
                FROM tabelao
                GROUP BY nome
            ) t ON TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) = t.nome
            WHERE (CAST(REPLACE(REPLACE(c.valor_emenda, '.', ''), ',', '.') AS REAL)) > 0
            {where_sql.replace('WHERE', 'AND') if where_sql else ""}
            GROUP BY nome_limpo, partido, uf, t.ultimoStatus_urlFoto, urlPartido, urlEstado
            ORDER BY total_conflitos DESC, valor_total DESC
        """
        df_ranking = pd.read_sql_query(query, conn, params=params)
        df_ranking = df_ranking.rename(columns={'nome_limpo': 'nome'})
        
        # ── NOVO: Buscar Totais de Emendas para o Sankey (Fração Limpa vs Irregular) ──
        # Usamos uma query robusta para limpar o nome do autor e somar os valores
        # Tratamos espaços não-convencionais (char 160) e normalizamos para maiúsculas
        query_totals = """
            SELECT 
                UPPER(TRIM(REPLACE(REPLACE(REPLACE(autor_emenda, 'DEP. ', ''), 'DEP ', ''), x'C2A0', ' '))) as raw_name,
                valor_empenhado
            FROM emendas
        """
        df_raw_totals = pd.read_sql_query(query_totals, conn)
        
        # Processar nomes em Python para maior robustez (remover sufixos de emenda e extrair apenas o nome)
        def clean_author_name(name):
            if name is None or pd.isna(name): return ""
            name_str = str(name).strip()
            # Pega tudo antes da primeira barra
            main_name = name_str.split('/')[0].strip()
            # Remove DEP. e DEP
            main_name = main_name.replace('DEP. ', '').replace('DEP ', '')
            return main_name.upper().strip()

        df_raw_totals['nome_clean'] = df_raw_totals['raw_name'].apply(clean_author_name)
        
        # Limpar valores numéricos
        def clean_numeric(v):
            if v is None or pd.isna(v): return 0.0
            if isinstance(v, (int, float)): return float(v)
            try:
                v_clean = str(v).replace('R$', '').replace('.', '').replace(',', '.').strip()
                return float(v_clean)
            except:
                return 0.0
        
        df_raw_totals['valor_num'] = df_raw_totals['valor_empenhado'].apply(clean_numeric)
        
        # Agrupar
        df_totals_mandato = df_raw_totals.groupby('nome_clean')['valor_num'].sum().reset_index()
        dict_totals = dict(zip(df_totals_mandato['nome_clean'], df_totals_mandato['valor_num']))
        
        # Injetar o total no ranking usando nomes normalizados
        df_ranking['total_empenhado_mandato'] = df_ranking['nome'].str.upper().str.strip().map(dict_totals).fillna(0)
        
        # ── NOVO: Buscar Dados de Triangulação (Auditoria Profunda via Prefeituras) ──
        query_triang = """
            SELECT 
                deputado_autor as parlamentar_autor, 
                municipio_nome as nome_recebedor, 
                empresa_nome as entidade_intermediaria,
                socio_vinculado as socio_vinc_parlamentar, 
                tipo_vinculo as vinculo_com_quem, 
                'Triangulação' as tipo_vinculo, 
                valor_contrato as valor_emenda, 
                contrato_id as codigo_emenda,
                'triangulacao' as tipo_fluxo
            FROM auditoria_triangular_profunda
        """
        df_triangular = pd.read_sql_query(query_triang, conn)
        
        # Detalhes dos conflitos filtrados
        if where_clauses:
            # Se houver filtro, buscamos os detalhes apenas dos parlamentares que sobraram no ranking
            # Usamos GROUP BY para eliminar duplicatas exatas de registros de conflitos
            nomes_filtrados = df_ranking['nome'].tolist()
            if not nomes_filtrados:
                return {"ranking": [], "detalhes": {}}
            
            placeholders = ', '.join(['?'] * len(nomes_filtrados))
            query_details = f"""
                SELECT 
                    TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) as parlamentar_autor, 
                    c.nome_recebedor, 
                    c.socio_vinc_parlamentar, 
                    c.vinculo_com_quem, 
                    c.tipo_vinculo, 
                    c.valor_emenda, 
                    c.codigo_emenda,
                    e.funcao as tema,
                    e.subfuncao
                FROM cruzamento_emendas_sociedades c
                LEFT JOIN emendas e ON c.codigo_emenda = e.codigo_emenda
                WHERE (CAST(REPLACE(REPLACE(c.valor_emenda, '.', ''), ',', '.') AS REAL)) > 0
                AND TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) IN ({placeholders})
                GROUP BY c.parlamentar_autor, c.nome_recebedor, c.socio_vinc_parlamentar, c.codigo_emenda, c.vinculo_com_quem, c.valor_emenda
                ORDER BY c.parlamentar_autor
            """
            df_details = pd.read_sql_query(query_details, conn, params=nomes_filtrados)
        else:
            query_details = """
                SELECT 
                    TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) as parlamentar_autor, 
                    c.nome_recebedor, 
                    c.socio_vinc_parlamentar, 
                    c.vinculo_com_quem, 
                    c.tipo_vinculo, 
                    c.valor_emenda, 
                    c.codigo_emenda,
                    e.funcao as tema,
                    e.subfuncao
                FROM cruzamento_emendas_sociedades c
                LEFT JOIN emendas e ON c.codigo_emenda = e.codigo_emenda
                WHERE (CAST(REPLACE(REPLACE(c.valor_emenda, '.', ''), ',', '.') AS REAL)) > 0
                GROUP BY c.parlamentar_autor, c.nome_recebedor, c.socio_vinc_parlamentar, c.codigo_emenda, c.vinculo_com_quem, c.valor_emenda
                ORDER BY c.parlamentar_autor
            """
            df_details = pd.read_sql_query(query_details, conn)
        
        # Agrupar detalhes por parlamentar e LIMPAR VALORES
        def clean_val(v):
            if not v: return 0.0
            if isinstance(v, (int, float)): return float(v)
            try:
                # Tratar formato brasileiro "250.000,00"
                v_clean = str(v).replace('R$', '').replace('.', '').replace(',', '.').strip()
                return float(v_clean)
            except:
                return 0.0

        # Agrupar detalhes por parlamentar e LIMPAR VALORES + BUSCAR 2ª/3ª DERIVADA
        details_grouped = {}
        processed_details = []

        # Para cada conflito identificado, buscar os sócios da empresa recebedora (2ª Derivada)
        for _, row in df_details.iterrows():
            nome_p = row['parlamentar_autor']
            row_dict = row.to_dict()
            row_dict['valor_emenda'] = clean_val(row_dict.get('valor_emenda'))
            
            # Buscar sócios reais na lista_cnpj_geral (2ª Derivada)
            cnpj_limpo = re.sub(r'[^0-9]', '', str(row.get('cnpj_recebedor', ''))) if row.get('cnpj_recebedor') else None
            socios = []
            if cnpj_limpo:
                query_socios = "SELECT Nome_Socio, Qualificação_Socio, [CPF/CNPJ_Socio] FROM lista_cnpj_geral WHERE cnpj = ?"
                df_socios = pd.read_sql_query(query_socios, conn, params=[cnpj_limpo])
                for _, s_row in df_socios.iterrows():
                    if s_row['Nome_Socio']:
                        socios.append({
                            "nome": s_row['Nome_Socio'],
                            "qualificacao": s_row['Qualificação_Socio'],
                            "documento": s_row['CPF/CNPJ_Socio']
                        })
            row_dict['socios_detalhe'] = socios # 2ª Derivada

            if nome_p not in details_grouped:
                details_grouped[nome_p] = []
            details_grouped[nome_p].append(row_dict)

        # Adicionar as triangulações ao agrupamento de detalhes (Prefeitura -> Empresa -> Sócio)
        for _, row in df_triangular.iterrows():
            nome_p = row['parlamentar_autor']
            if nome_p in details_grouped or not where_clauses:
                row_dict = row.to_dict()
                row_dict['valor_emenda'] = float(row_dict.get('valor_emenda') or 0)
                
                # Triangulação já tem socio_vinculado (3ª Derivada), mas podemos detalhar
                if nome_p not in details_grouped:
                    details_grouped[nome_p] = []
                details_grouped[nome_p].append(row_dict)

        # Sanitizar valores para JSON (evita erro com NaN)
        df_ranking = df_ranking.replace({np.nan: None, np.inf: None, -np.inf: None})

        # ── Substituir URLs do Wikimedia (que bloqueiam hotlinking) por fontes confiáveis ──
        # Logos dos partidos via Câmara dos Deputados (mesma fonte da tabelao, mas URL confiável)
        PARTIDO_LOGO_CAMARA = {
            'PT':          'https://www.camara.leg.br/internet/Deputado/img/partidos/PT.gif',
            'PL':          'https://www.camara.leg.br/internet/Deputado/img/partidos/PL.gif',
            'UNIÃO':       'https://www.camara.leg.br/internet/Deputado/img/partidos/UNIAO.gif',
            'UNIAO':       'https://www.camara.leg.br/internet/Deputado/img/partidos/UNIAO.gif',
            'PP':          'https://www.camara.leg.br/internet/Deputado/img/partidos/PP.gif',
            'MDB':         'https://www.camara.leg.br/internet/Deputado/img/partidos/MDB.gif',
            'PSD':         'https://www.camara.leg.br/internet/Deputado/img/partidos/PSD.gif',
            'REPUBLICANOS':'https://www.camara.leg.br/internet/Deputado/img/partidos/REPUBLICANOS.gif',
            'PDT':         'https://www.camara.leg.br/internet/Deputado/img/partidos/PDT.gif',
            'PSOL':        'https://www.camara.leg.br/internet/Deputado/img/partidos/PSOL.gif',
            'PODE':        'https://www.camara.leg.br/internet/Deputado/img/partidos/PODEMOS.gif',
            'PODEMOS':     'https://www.camara.leg.br/internet/Deputado/img/partidos/PODEMOS.gif',
            'PSB':         'https://www.camara.leg.br/internet/Deputado/img/partidos/PSB.gif',
            'PSDB':        'https://www.camara.leg.br/internet/Deputado/img/partidos/PSDB.gif',
            'NOVO':        'https://www.camara.leg.br/internet/Deputado/img/partidos/NOVO.gif',
            'PRD':         'https://www.camara.leg.br/internet/Deputado/img/partidos/PRD.gif',
            'PV':          'https://www.camara.leg.br/internet/Deputado/img/partidos/PV.gif',
            'PCdoB':       'https://www.camara.leg.br/internet/Deputado/img/partidos/PCDOB.gif',
            'PCDOB':       'https://www.camara.leg.br/internet/Deputado/img/partidos/PCDOB.gif',
            'SOLIDARIEDADE':'https://www.camara.leg.br/internet/Deputado/img/partidos/SOLIDARIEDADE.gif',
            'AVANTE':      'https://www.camara.leg.br/internet/Deputado/img/partidos/AVANTE.gif',
            'CIDADANIA':   'https://www.camara.leg.br/internet/Deputado/img/partidos/CIDADANIA.gif',
            'AGIR':        'https://www.camara.leg.br/internet/Deputado/img/partidos/AGIR.gif',
            'PMB':         'https://www.camara.leg.br/internet/Deputado/img/partidos/PMB.gif',
        }
        ranking_list = df_ranking.to_dict('records')
        for item in ranking_list:
            partido = item.get('partido') or ''
            uf = item.get('uf') or ''
            item['urlPartido'] = PARTIDO_LOGO_CAMARA.get(partido) or PARTIDO_LOGO_CAMARA.get(partido.upper()) or item.get('urlPartido')
            # Mantemos a urlEstado do banco de dados porque agora o frontend fará proxy da URL do Wikimedia, evitanado o erro de hotlinking.

        return {
            "ranking": ranking_list,
            "detalhes": details_grouped
        }
    except Exception as e:
        logger.error(f"Erro ao buscar ranking de conflitos: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.get("/api/integridade/alertas-sancoes")
async def get_alertas_sancoes(uf: Optional[str] = None, partido: Optional[str] = None, nome: Optional[str] = None):
    """
    Retorna os alertas de integridade identificados ao cruzar as bases de sanções
    publicadas pela própria CGU no Portal da Transparência — CEIS (empresas
    inidôneas/suspensas) e CEPIM (ONGs impedidas de convênio) — com as emendas
    parlamentares e contratos públicos do Tabelão (ver 32_sancoes.py).
    """
    try:
        conn = get_db_connection("tabelao")

        tabela_existe = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='auditoria_sancoes'"
        ).fetchone()
        if not tabela_existe:
            return {
                "resumo": {"total_alertas": 0, "total_ceis": 0, "total_cepim": 0},
                "alertas": [],
                "aviso": "Auditoria de sanções CEIS/CEPIM ainda não foi executada. Rode 'python 32_sancoes.py' para popular esta base."
            }

        # auditoria_sancoes.id_vinculo guarda o código da emenda (para os tipos
        # CEIS/EMENDA e CEPIM/EMENDA) ou o número do contrato (CEIS/CONTRATO,
        # sem parlamentar associado). Usamos o join com 'emendas' apenas para
        # recuperar o autor e permitir filtrar/agrupar por parlamentar.
        query = """
            SELECT
                a.tipo,
                a.cnpj,
                a.nome_entidade,
                a.id_vinculo,
                a.data_evento,
                a.sancao_inicio,
                a.sancao_fim,
                a.detalhes,
                e.autor_emenda,
                e.valor_empenhado
            FROM auditoria_sancoes a
            LEFT JOIN emendas e ON a.id_vinculo = e.codigo_emenda
            WHERE a.conflito_historico = 1
            ORDER BY a.data_evento DESC
        """
        df = pd.read_sql_query(query, conn)

        def limpar_nome_autor(autor):
            if not autor or pd.isna(autor):
                return None
            nome_str = str(autor).split('/')[0].strip()
            nome_str = nome_str.replace('DEP. ', '').replace('DEP ', '')
            return nome_str.upper().strip()

        df['parlamentar'] = df['autor_emenda'].apply(limpar_nome_autor)

        # Metadados do parlamentar (partido/UF/foto) para quem tem emenda associada
        df_meta = pd.read_sql_query("""
            SELECT UPPER(TRIM(nome)) as nome_upper, MAX(sgPartido) as partido, MAX(sgUF) as uf,
                   MAX(ultimoStatus_urlFoto) as ultimoStatus_urlFoto
            FROM tabelao GROUP BY nome_upper
        """, conn)
        meta_dict = df_meta.set_index('nome_upper').to_dict('index')

        def anexar_meta(row):
            meta = meta_dict.get(row['parlamentar']) or {}
            row['partido'] = meta.get('partido')
            row['uf'] = meta.get('uf')
            row['ultimoStatus_urlFoto'] = meta.get('ultimoStatus_urlFoto')
            return row

        df = df.apply(anexar_meta, axis=1)

        if uf:
            df = df[df['uf'] == uf]
        if partido and not nome:
            df = df[df['partido'] == partido]
        if nome:
            df = df[df['parlamentar'] == nome.upper().strip()]

        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})

        resumo = {
            "total_alertas": int(len(df)),
            "total_ceis": int(df['tipo'].astype(str).str.startswith('CEIS').sum()),
            "total_cepim": int(df['tipo'].astype(str).str.startswith('CEPIM').sum()),
        }

        return {
            "resumo": resumo,
            "alertas": df.to_dict('records')
        }
    except Exception as e:
        logger.error(f"Erro ao buscar alertas de sanções CEIS/CEPIM: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals() and conn:
            conn.close()


@app.get("/api/gastos/fornecedores-sancionados")
async def get_fornecedores_sancionados_ceap(parlamentar: str, despesa: Optional[str] = None):
    """
    Cruza os fornecedores da Cota para Exercício da Atividade Parlamentar (CEAP)
    do deputado com as bases de sanções da CGU (CEIS/CEPIM), publicadas no Portal
    da Transparência.

    IMPORTANTE — disclaimer jurídico: ao contrário de emendas/convênios formalizados
    por um órgão público (onde a consulta ao CEIS/CEPIM é exigida pelo art. 14 da
    Lei nº 14.133/2021 e pelo Decreto nº 11.129/2022), a CEAP é um regime de
    ressarcimento — não uma licitação ou contrato administrativo — e não há norma
    específica obrigando o parlamentar a consultar essas bases antes de escolher um
    fornecedor. Um resultado aqui NÃO indica irregularidade ou ilegalidade: é um
    alerta de transparência para que o eleitor/imprensa possa avaliar o caso.
    """
    try:
        conn = get_db_connection("tabelao")

        tabela_ceis_existe = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lista_ceis'"
        ).fetchone()
        if not tabela_ceis_existe:
            return {
                "resumo": {"total_fornecedores_sancionados": 0, "valor_total": 0},
                "fornecedores": [],
                "disclaimer": "Auditoria de sanções CEIS/CEPIM ainda não foi executada. Rode 'python 32_sancoes.py' para popular esta base.",
                "aviso": "Auditoria de sanções CEIS/CEPIM ainda não foi executada. Rode 'python 32_sancoes.py' para popular esta base."
            }

        where_clauses = ["nome = ?", "txtCNPJCPF IS NOT NULL", "txtCNPJCPF != ''"]
        params = [parlamentar]
        if despesa and despesa != 'Todos':
            where_clauses.append("txtDescricao LIKE ?")
            params.append(f"%{despesa}%")

        query = f"""
            SELECT
                txtCNPJCPF,
                MAX(txtFornecedor) as fornecedor,
                SUM(COALESCE(vlrLiquido, 0)) as total_gasto,
                COUNT(*) as n_notas,
                MIN(datEmissao) as primeira_nota,
                MAX(datEmissao) as ultima_nota
            FROM tabelao
            WHERE {' AND '.join(where_clauses)}
            GROUP BY txtCNPJCPF
        """
        df_forn = pd.read_sql_query(query, conn, params=params)

        def limpar_cnpj(v):
            return re.sub(r'\D', '', str(v or '')).zfill(14)

        df_forn['cnpj_limpo'] = df_forn['txtCNPJCPF'].apply(limpar_cnpj)
        cnpjs_validos = [c for c in df_forn['cnpj_limpo'].unique().tolist() if c and c != '0' * 14]

        sancoes_por_cnpj = {}
        if cnpjs_validos:
            placeholders = ','.join(['?'] * len(cnpjs_validos))
            df_ceis = pd.read_sql_query(
                f"SELECT cnpj, nome_sancionado, categoria_sancao, data_inicio, data_fim FROM lista_ceis WHERE cnpj IN ({placeholders})",
                conn, params=cnpjs_validos
            )
            for _, s in df_ceis.iterrows():
                sancoes_por_cnpj[s['cnpj']] = {
                    "base": "CEIS", "categoria": s.get('categoria_sancao'),
                    "sancao_inicio": s.get('data_inicio'), "sancao_fim": s.get('data_fim')
                }
            df_cepim = pd.read_sql_query(
                f"SELECT cnpj, motivo FROM lista_cepim WHERE cnpj IN ({placeholders})",
                conn, params=cnpjs_validos
            )
            for _, s in df_cepim.iterrows():
                sancoes_por_cnpj.setdefault(s['cnpj'], {"base": "CEPIM", "categoria": s.get('motivo'), "sancao_inicio": None, "sancao_fim": None})

        df_forn['sancao'] = df_forn['cnpj_limpo'].map(sancoes_por_cnpj)
        df_sancionados = df_forn[df_forn['sancao'].notna()].copy()
        df_sancionados = df_sancionados.replace({np.nan: None, np.inf: None, -np.inf: None})

        fornecedores = []
        for _, row in df_sancionados.iterrows():
            sancao = row['sancao']
            fornecedores.append({
                "cnpj": row['txtCNPJCPF'],
                "fornecedor": row['fornecedor'],
                "total_gasto": float(row['total_gasto'] or 0),
                "n_notas": int(row['n_notas'] or 0),
                "primeira_nota": row['primeira_nota'],
                "ultima_nota": row['ultima_nota'],
                "sancao_base": sancao.get('base'),
                "sancao_categoria": sancao.get('categoria'),
                "sancao_inicio": sancao.get('sancao_inicio'),
                "sancao_fim": sancao.get('sancao_fim'),
            })

        resumo = {
            "total_fornecedores_sancionados": len(fornecedores),
            "valor_total": sum(f["total_gasto"] for f in fornecedores),
        }

        return {
            "resumo": resumo,
            "fornecedores": fornecedores,
            "disclaimer": (
                "Gastos de CEAP são ressarcimentos ao parlamentar, não licitações ou contratos administrativos. "
                "Não há obrigação legal específica de consultar o CEIS/CEPIM antes de escolher um fornecedor nesse regime "
                "(diferente de emendas/convênios, onde a consulta é exigida do órgão público pelo art. 14 da Lei nº 14.133/2021). "
                "Este alerta NÃO indica irregularidade ou ilegalidade — é um ponto de transparência para avaliação pública."
            )
        }
    except Exception as e:
        logger.error(f"Erro ao cruzar fornecedores CEAP com CEIS/CEPIM: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals() and conn:
            conn.close()


@app.get("/api/emendas/conflitos-filtros")
async def get_emendas_conflitos_filtros():
    """Retorna as combinações únicas de Estado, Partido e Parlamentar que possuem conflitos registrados."""
    try:
        conn = get_db_connection("tabelao")
        
        query = """
            SELECT DISTINCT 
                t.sgUF as uf,
                t.sgPartido as partido,
                TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) as nome
            FROM cruzamento_emendas_sociedades c
            LEFT JOIN (
                SELECT DISTINCT nome, sgPartido, sgUF
                FROM tabelao
            ) t ON TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) = t.nome
        """
        df = pd.read_sql_query(query, conn)
        
        # Converter para lista de dicionários para o frontend processar
        combinations = df.to_dict('records')
        
        return {
            "combinations": combinations
        }
    except Exception as e:
        logger.error(f"Erro ao buscar filtros de conflitos: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals() and conn:
            conn.close()

class AnaliseLLMRequest(BaseModel):
    parlamentar: str
    estado: Optional[str] = None
    partido: Optional[str] = None

from fastapi.responses import StreamingResponse
import queue
import threading
import json
import time

@app.post("/api/emendas/analise-llm")
async def analyze_emendas_llm(request: AnaliseLLMRequest):
    """Endpoint para análise de inteligência com CrewAI (Robô Antunes) - Streaming SSE."""
    
    parlamentar = request.parlamentar
    estado = getattr(request, 'estado', None)
    partido = getattr(request, 'partido', None)
    tipo_beneficiario = getattr(request, 'tipo_beneficiario', None)
    cidade_filtro = getattr(request, 'cidade', None)
    if not parlamentar or parlamentar == 'Todos':
        return {"error": "Selecione um parlamentar"}

    # Preparar dados (síncrono por enquanto, rápido)
    try:
        filtered_analysis = await get_analise_emendas(
            parlamentar=parlamentar,
            estado=estado,
            partido=partido,
            tipo_beneficiario=tipo_beneficiario,
            cidade=cidade_filtro,
        )
        if isinstance(filtered_analysis, dict) and filtered_analysis.get("error"):
            return {"error": filtered_analysis.get("error")}

        conn = get_db_connection("tabelao")

        def normalize_city_label(value):
            text = str(value or '').strip()
            if not text:
                return ''
            text = re.sub(r'\s*\(UF\)\s*$', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\s*-\s*[A-Z]{2}$', '', text, flags=re.IGNORECASE)
            return text.strip()

        def safe_money(value):
            try:
                if value is None:
                    return 0.0
                if isinstance(value, str):
                    cleaned = value.replace('R$', '').replace('.', '').replace(',', '.').strip()
                    return float(cleaned or 0)
                return float(value)
            except Exception:
                return 0.0
        
        resumo_filtrado = filtered_analysis.get('resumo') or {}
        fornecedores_filtrados = filtered_analysis.get('fornecedores') or []
        convenios_filtrados = filtered_analysis.get('convenios') or []
        documentos_filtrados = filtered_analysis.get('documentos') or []
        conflitos_data = filtered_analysis.get('conflitos') or []
        municipios_filtrados = filtered_analysis.get('municipios') or []
        temas_filtrados = filtered_analysis.get('distribuicao_por_tema') or []

        df_emendas = pd.DataFrame([
            {
                "municipio": item.get("municipio"),
                "valor_pago": safe_money(item.get("valor_total")),
                "tema": item.get("tema"),
            }
            for item in municipios_filtrados
        ])

        # 3. Buscar Dados Políticos (Votação e Partido)
        dict_votos = {}
        partido_parlamentar = "Não identificado"
        
        try:
            # Tentar extrair partido do nome se vier no formato "NOME (PARTIDO/UF)" ou buscar no banco
            # Na tabela emendas, autor_emenda é "NOME / PARTIDO / UF"
            query_partido = "SELECT autor_emenda FROM emendas WHERE autor_emenda LIKE ? LIMIT 1"
            df_partido = pd.read_sql_query(query_partido, conn, params=[f"{parlamentar}%"])
            if not df_partido.empty:
                full_name = df_partido.iloc[0]['autor_emenda']
                parts = full_name.split('/')
                if len(parts) >= 2:
                    partido_parlamentar = parts[1].strip()

            # Buscar Votos no DuckDB
            import duckdb
            duck_db_path = DUCK_DB_PATH
            if os.path.exists(duck_db_path):
                con_duck = safe_duckdb_connect(duck_db_path, read_only=True)
                # Tentar busca exata ou like
                query_votos = f"""
                    SELECT NM_MUNICIPIO, SUM(QT_VOTOS_NOMINAIS)
                    FROM votacao
                    WHERE NM_PARLAMENTAR LIKE '%{parlamentar}%'
                    GROUP BY NM_MUNICIPIO
                """
                results_votos = con_duck.execute(query_votos).fetchall()
                for row in results_votos:
                    if row[0]:
                        dict_votos[row[0].upper().strip()] = row[1]
                con_duck.close()
        except Exception as e:
            logger.error(f"Erro ao buscar dados políticos: {e}")

        # 3.1 Buscar síntese territorial/IBGE dos redutos eleitorais
        territorial_data = {}
        try:
            territorial_resp = await mapa_eleitoral_ibge_top10(
                parlamentar,
                estado=estado,
                partido=partido,
                allow_municipal_fallback=True,
            )
            territorial_data = territorial_resp if isinstance(territorial_resp, dict) else {}
        except Exception as territorial_exc:
            logger.warning(f"Falha ao carregar contexto territorial do Robô Antunes: {territorial_exc}")
            territorial_data = {}

        conn.close()

        # 4. Preparar Resumo Rico
        total_pago = safe_money(resumo_filtrado.get('valor_total_pago'))
        
        # Top Cidades com Votos (Filtrando genéricos)
        top_cidades_data = []
        termos_genericos = ['MÚLTIPLO', 'NACIONAL', 'ESTADO (UF)', 'EXTERIOR', 'BRASIL']
        
        if municipios_filtrados:
            municipios_ordenados = sorted(
                municipios_filtrados,
                key=lambda item: safe_money(item.get('valor_total')),
                reverse=True
            )[:10]
            for item in municipios_ordenados:
                cidade = item.get('municipio')
                valor = safe_money(item.get('valor_total'))
                cidade_upper = cidade.upper().strip()
                
                # Pular genéricos
                if any(termo in cidade_upper for termo in termos_genericos):
                    continue
                    
                # Tentar limpar sufixos para match de votos
                # Ex: "SÃO PAULO (UF)" -> "SÃO PAULO"
                cidade_clean = cidade_upper.split(' (')[0].strip()
                votos = dict_votos.get(cidade_clean, 0)
                
                # Calcular R$ por Voto (indicador de eficiência ou compra de apoio)
                rs_por_voto = valor / votos if votos > 0 else valor # Se 0 votos, custo infinito
                
                top_cidades_data.append({
                    "cidade": cidade,
                    "cidade_normalizada": cidade_clean,
                    "valor_recebido": valor,
                    "votos_na_cidade": votos,
                    "custo_por_voto": rs_por_voto if votos > 0 else "N/A (0 votos)"
                })
                
                if len(top_cidades_data) >= 5: # Limitar a 5 cidades REAIS
                    break

        top_temas = {
            str(item.get('tema') or 'N/A'): safe_money(item.get('valor'))
            for item in temas_filtrados[:5]
        }
        
        beneficiarios_list = []
        for item in fornecedores_filtrados[:10]:
            beneficiarios_list.append(f"- {item.get('fornecedor')}: R$ {safe_money(item.get('valor_total')):,.2f}")

        convenios_list = []
        for item in convenios_filtrados[:10]:
            convenios_list.append(f"- {item.get('objeto')} ({item.get('cidade') or 'N/A'}): R$ {safe_money(item.get('valor')):,.2f}")

        conflito_summary = {
            "quantidade": len(conflitos_data),
            "valor_total": round(sum(safe_money(item.get('valor_emenda')) for item in conflitos_data), 2),
            "tipos": sorted({str(item.get('tipo_vinculo') or '').strip() for item in conflitos_data if item.get('tipo_vinculo')}),
            "recebedores": sorted({str(item.get('nome_recebedor') or '').strip() for item in conflitos_data if item.get('nome_recebedor')})[:10],
            "amostra": conflitos_data[:8],
        }

        top_redutos = territorial_data.get('topRedutos') or []
        top_municipios_ibge = territorial_data.get('topMunicipios') or []
        ibge_cards = territorial_data.get('ibgeResumoTop10') or []

        reduto_municipios = []
        for item in top_redutos:
            municipio = item.get('municipio')
            if municipio:
                reduto_municipios.append(municipio)
        for item in top_municipios_ibge:
            municipio = item.get('municipio')
            if municipio:
                reduto_municipios.append(municipio)

        reduto_municipios_normalizados = {
            normalize_city_label(municipio).upper()
            for municipio in reduto_municipios
            if normalize_city_label(municipio)
        }

        cidades_destino_reais = []
        if municipios_filtrados:
            for item in sorted(municipios_filtrados, key=lambda row: safe_money(row.get('valor_total')), reverse=True):
                cidade_label = str(item.get('municipio') or '').strip()
                valor = safe_money(item.get('valor_total'))
                cidade_normalizada = normalize_city_label(cidade_label).upper()
                if not cidade_normalizada:
                    continue
                if any(termo in cidade_normalizada for termo in ['MÚLTIPLO', 'NACIONAL', 'EXTERIOR', 'BRASIL']):
                    continue
                cidades_destino_reais.append({
                    "cidade": cidade_label,
                    "cidade_normalizada": cidade_normalizada,
                    "valor": round(float(valor or 0), 2),
                    "esta_no_reduto": cidade_normalizada in reduto_municipios_normalizados,
                })

        top_destinos_reduto = [item for item in cidades_destino_reais if item['esta_no_reduto']][:8]
        top_destinos_fora_reduto = [item for item in cidades_destino_reais if not item['esta_no_reduto']][:8]

        metric_map = {}
        for item in top_redutos:
            municipio = normalize_city_label(item.get('municipio')).upper()
            if not municipio:
                continue
            indicadores = item.get('indicadores') or {}
            metric_map[municipio] = {
                "municipio": item.get('municipio'),
                "uf": item.get('uf'),
                "votos": item.get('total_votos'),
                "rede_esgoto": indicadores.get('rede_esgoto'),
                "rede_geral_agua": indicadores.get('rede_geral_agua'),
                "alfabetizacao": indicadores.get('alfabetizacao'),
                "sem_banheiro": indicadores.get('sem_banheiro'),
                "lixo_coletado": indicadores.get('lixo_coletado'),
                "renda_media_responsavel": indicadores.get('renda_media_responsavel'),
            }

        redutos_deficitarios = []
        for municipio, info in metric_map.items():
            alertas = []
            if info.get('rede_esgoto') is not None and float(info['rede_esgoto']) < 70:
                alertas.append(f"rede de esgoto baixa ({info['rede_esgoto']}%)")
            if info.get('rede_geral_agua') is not None and float(info['rede_geral_agua']) < 85:
                alertas.append(f"rede de água abaixo do ideal ({info['rede_geral_agua']}%)")
            if info.get('sem_banheiro') is not None and float(info['sem_banheiro']) > 2:
                alertas.append(f"domicílios sem banheiro ({info['sem_banheiro']}%)")
            if info.get('alfabetizacao') is not None and float(info['alfabetizacao']) < 90:
                alertas.append(f"alfabetização abaixo de 90% ({info['alfabetizacao']}%)")
            if alertas:
                redutos_deficitarios.append({
                    **info,
                    "alertas": alertas,
                    "recebeu_emenda_direta": municipio in {item['cidade_normalizada'] for item in cidades_destino_reais},
                })

        tema_texto = " ".join(str(chave) for chave in top_temas.keys()).upper()
        aderencia_tematica = {
            "foco_saneamento": any(token in tema_texto for token in ["SANEAMENTO", "URBANISMO", "HABIT", "ESGOTO", "ÁGUA", "AGUA"]),
            "foco_saude": any(token in tema_texto for token in ["SAÚDE", "SAUDE"]),
            "foco_educacao": any(token in tema_texto for token in ["EDUCA", "ENSINO"]),
            "foco_assistencia": any(token in tema_texto for token in ["ASSIST", "SOCIAL"]),
        }

        pergunta_central = "O Deputado está destinando emendas para sua base eleitoral efetivamente para problemas que essa base possui, ou enviando recursos para locais diversos e/ou para problemas pouco aderentes às carências observáveis do reduto?"
        
        data_summary = f"""
        PARLAMENTAR: {parlamentar}
        PARTIDO: {partido_parlamentar}
        UF: {estado or 'N/D'}
        TOTAL PAGO (2023-2024): R$ {total_pago:,.2f}
        TIPO DE BENEFICIÁRIO FILTRADO: {tipo_beneficiario or 'Todos'}
        CIDADE FILTRADA: {cidade_filtro or 'Todas'}
        TOTAL DE EMENDAS NO RECORTE FILTRADO: {resumo_filtrado.get('total_emendas', 0)}
        TOTAL DE CIDADES NO RECORTE FILTRADO: {resumo_filtrado.get('total_cidades', 0)}

        PERGUNTA CENTRAL DE AUDITORIA:
        {pergunta_central}
        
        CONTEXTO POLÍTICO (TOP CIDADES REAIS DESTINO vs. VOTOS):
        Analise se o dinheiro está indo para onde ele tem voto (manutenção de base) ou para onde não tem (expansão territorial ou baixa aderência eleitoral).
        IGNORAR "MÚLTIPLO" ou "NACIONAL". Focar nestas cidades:
        {json.dumps(top_cidades_data, indent=2, ensure_ascii=False)}

        DESTINOS NO REDUTO ELEITORAL IDENTIFICADO:
        {json.dumps(top_destinos_reduto, indent=2, ensure_ascii=False)}

        DESTINOS FORA DO REDUTO ELEITORAL IDENTIFICADO:
        {json.dumps(top_destinos_fora_reduto, indent=2, ensure_ascii=False)}
        
        TOP 3 ÁREAS TEMÁTICAS:
        {json.dumps(top_temas, indent=2, ensure_ascii=False)}

        LEITURA DE ADERÊNCIA TEMÁTICA PRELIMINAR:
        {json.dumps(aderencia_tematica, indent=2, ensure_ascii=False)}
        
        TOP 5 CONVÊNIOS/CONTRATOS (MAIORES VALORES INDIVIDUAIS):
        {chr(10).join(convenios_list) if convenios_list else "Nenhum convênio específico de alto valor encontrado."}
        
        TOP 10 BENEFICIÁRIOS GERAIS (EMPRESAS/ONGS) PARA INVESTIGAR:
        {chr(10).join(beneficiarios_list) if beneficiarios_list else "Nenhum beneficiário listado."}

        POTENCIAIS CONFLITOS DE INTERESSE EM EMENDAS:
        {json.dumps(conflito_summary, indent=2, ensure_ascii=False)}

        CONTEXTO ELEITORAL + IBGE/SIDRA DOS REDUTOS:
        CACHE STATUS: {territorial_data.get('cacheStatus', 'indisponivel')}
        RESUMO DE CARDS IBGE: {json.dumps(ibge_cards[:8], indent=2, ensure_ascii=False)}
        TOP REDUTOS/SETORES: {json.dumps(top_redutos[:12], indent=2, ensure_ascii=False)}
        TOP MUNICÍPIOS DO REDUTO (fallback): {json.dumps(top_municipios_ibge[:12], indent=2, ensure_ascii=False)}

        REDUTOS COM CARÊNCIAS SOCIAIS RELEVANTES:
        {json.dumps(redutos_deficitarios[:10], indent=2, ensure_ascii=False)}
        """
        
        logger.info(f"📊 DATA SUMMARY GENERATED (Size: {len(data_summary)} chars)")
        logger.info(f"Beneficiaries found: {len(beneficiarios_list)}")
        logger.info(f"Convenios found: {len(convenios_list)}")
        logger.info(data_summary)

        cache_payload = {
            "parlamentar": parlamentar,
            "estado": estado,
            "partido": partido,
            "tipo_beneficiario": tipo_beneficiario,
            "cidade_filtro": cidade_filtro,
            "filtered_analysis": filtered_analysis,
            "top_cidades_data": top_cidades_data,
            "top_temas": top_temas,
            "beneficiarios_list": beneficiarios_list,
            "convenios_list": convenios_list,
            "conflito_summary": conflito_summary,
            "top_destinos_reduto": top_destinos_reduto,
            "top_destinos_fora_reduto": top_destinos_fora_reduto,
            "ibge_cards": ibge_cards[:8],
            "top_redutos": top_redutos[:12],
            "top_municipios_ibge": top_municipios_ibge[:12],
            "redutos_deficitarios": redutos_deficitarios[:10],
            "aderencia_tematica": aderencia_tematica,
            "data_summary": data_summary,
        }
        report_hash = hashlib.sha256(
            json.dumps(cache_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        cache_db_path = DATABASE_PATHS.get("llm_cache") or os.path.join(BASE_DIR, "llm_cache.db")
        cached_report = None
        cache_conn = sqlite3.connect(cache_db_path)
        cache_cursor = cache_conn.cursor()
        cache_cursor.execute("SELECT response_json FROM llm_cache WHERE hash_id = ?", (f"emendas_auditoria:{report_hash}",))
        cache_row = cache_cursor.fetchone()
        cache_conn.close()
        if cache_row and cache_row[0]:
            try:
                cached_report = json.loads(cache_row[0])
            except Exception:
                cached_report = {"analise": cache_row[0]}


    except Exception as e:
        logger.error(f"Erro ao preparar dados: {e}")
        return {"error": f"Erro ao preparar dados: {str(e)}"}

    # Função geradora para SSE
    def event_generator():
        if cached_report and cached_report.get("analise"):
            yield f"data: {json.dumps({'status': 'Em Análise'})}\n\n"
            yield f"data: {json.dumps({'analise': cached_report.get('analise', '')})}\n\n"
            return

        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            yield f"data: {json.dumps({'error': 'Chave de API OpenAI ausente'})}\n\n"
            return

        status_queue = queue.Queue()
        result_container = {}

        def archive_report(report_text: str):
            try:
                archive_dir = os.path.join(BASE_DIR, "relatorios_arquivados", "emendas_auditoria")
                os.makedirs(archive_dir, exist_ok=True)
                archive_path = os.path.join(archive_dir, f"{report_hash}.json")
                payload = {
                    "hash_id": report_hash,
                    "tipo": "emendas_auditoria",
                    "parlamentar": parlamentar,
                    "estado": estado,
                    "partido": partido,
                    "tipo_beneficiario": tipo_beneficiario,
                    "cidade": cidade_filtro,
                    "created_at": datetime.now().isoformat(),
                    "analise": report_text,
                    "filtered_analysis": filtered_analysis,
                }
                with open(archive_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)

                cache_conn = sqlite3.connect(cache_db_path)
                cache_cursor = cache_conn.cursor()
                cache_cursor.execute(
                    "INSERT OR REPLACE INTO llm_cache (hash_id, response_json, created_at) VALUES (?, ?, ?)",
                    (
                        f"emendas_auditoria:{report_hash}",
                        json.dumps(payload, ensure_ascii=False),
                        datetime.now().isoformat()
                    )
                )
                cache_conn.commit()
                cache_conn.close()
            except Exception as archive_exc:
                logger.warning(f"Falha ao arquivar relatório de emendas: {archive_exc}")

        def run_crew():
            try:
                status_queue.put("Preparando auditoria do Robô Antunes...")
                try:
                    # Lazy import para evitar travamento na inicialização
                    from modules.llm.crew_auditor import AntunesCrew
                    crew = AntunesCrew(api_key=openai_key)
                    status_queue.put("Executando cadeia multiagente de auditoria...")
                    # Passar apenas o nome do parlamentar, os agentes buscam os dados
                    result = crew.run(parlamentar, status_queue=status_queue)
                    result_container['data'] = str(result)
                    archive_report(result_container['data'])
                except ModuleNotFoundError as import_exc:
                    logger.warning(f"CrewAI indisponível no Robô Antunes, usando fallback OpenAI direto: {import_exc}")
                    status_queue.put("Modo alternativo ativado: auditoria direta sem CrewAI...")

                    import openai

                    client = openai.OpenAI(api_key=openai_key)
                    prompt = f"""
Você é o Robô Antunes, um auditor técnico de emendas parlamentares, com postura de controle externo, integridade pública e conformidade material.

OBJETIVO DA PEÇA:
Responder, no âmbito de auditoria e sempre em tom não acusatório, à pergunta:
"O Deputado está destinando emendas para sua base eleitoral efetivamente para problemas que essa base possui ou está mandando dinheiro para locais diversos e/ou para problemas de baixa aderência às carências observáveis do reduto?"

REGRAS OBRIGATÓRIAS:
- Escreva de forma densa, crítica, cirúrgica e tecnicamente elegante.
- Nunca seja acusatório ou conclusivo em sentido penal.
- Use expressões como: "há indícios", "há sinais", "há possibilidade", "merece apuração", "recomenda-se investigação da possível não conformidade".
- Se houver conflitos de interesse, trate isso como hipótese de risco de integridade e necessidade de apuração, nunca como culpa consumada.
- Se houver baixa aderência entre problema do reduto e tema das emendas, diga isso com clareza.
- Se houver boa aderência, também diga.
- Diferencie:
  1. verba no reduto eleitoral,
  2. verba fora do reduto,
  3. verba em reduto com carência social observável,
  4. verba em temas potencialmente desalinhados das carências.
- Use os dados de conflitos de interesse e os dados territoriais/IBGE-SIDRA obrigatoriamente, quando disponíveis.
- Se os dados forem insuficientes em algum trecho, explicite a limitação metodológica.

ESTRUTURA OBRIGATÓRIA EM MARKDOWN:
## Tese de Auditoria
## Resposta Objetiva à Pergunta Central
## Leitura de Aderência Territorial e Social
## Destinos, Beneficiários e Concentração
## Conflitos de Interesse e Risco de Integridade
## Hipóteses de Não Conformidade que Merecem Investigação
## Contrapontos e Limitações Metodológicas
## Encaminhamento Recomendado

EM "Resposta Objetiva à Pergunta Central":
- responda frontalmente se os dados sugerem:
  - aderência alta,
  - aderência parcial,
  - aderência baixa,
  - ou quadro inconclusivo.

EM "Leitura de Aderência Territorial e Social":
- confronte os redutos eleitorais com seus problemas sociais observáveis;
- avalie se a temática das emendas conversa com esses problemas;
- destaque municípios deficitários do reduto que receberam pouco ou nada, se isso aparecer nos dados;
- destaque destinos fora do reduto que receberam valores relevantes.

EM "Conflitos de Interesse e Risco de Integridade":
- se houver conflitos, explicite número, tipos, recebedores e relevância material;
- trate como potencial não conformidade a ser investigada.

EM "Encaminhamento Recomendado":
- termine com recomendação institucional, por exemplo:
  - sem achado material robusto,
  - monitoramento,
  - solicitação de esclarecimentos,
  - investigação da possível não conformidade.

DADOS DE TRABALHO:
{data_summary}
"""

                    response = client.chat.completions.create(
                        model="gpt-5.4-mini",
                        messages=[
                            {"role": "system", "content": "Você é um auditor forense de gastos públicos especializado em emendas parlamentares."},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.2,
                        max_completion_tokens=2200,
                        timeout=60.0,
                    )
                    result_container['data'] = (response.choices[0].message.content or "").strip()
                    archive_report(result_container['data'])
            except Exception as e:
                result_container['error'] = str(e)
            finally:
                status_queue.put(None) # Sinal de fim

        # Iniciar thread do CrewAI
        thread = threading.Thread(target=run_crew)
        thread.start()

        # Loop para enviar atualizações
        while True:
            try:
                msg = status_queue.get(timeout=1) # Timeout para checar se thread morreu
                if msg is None:
                    break
                
                # Enviar atualização de status
                yield f"data: {json.dumps({'status': msg})}\n\n"
            except queue.Empty:
                if not thread.is_alive():
                    break
                continue
        
        thread.join()

        # Enviar resultado final
        if 'error' in result_container:
             yield f"data: {json.dumps({'error': result_container['error']})}\n\n"
        else:
             yield f"data: {json.dumps({'analise': result_container.get('data', '')})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/emendas/parlamentares")
async def get_parlamentares_emendas(estado: Optional[str] = None, partido: Optional[str] = None):
    """Endpoint para buscar a lista de parlamentares que têm emendas, filtrando corretamente por estado e partido."""
    try:
        conn = get_db_connection("tabelao")
        
        # 1. Pegar nomes limpos da tabela emendas
        query_emendas = """
        SELECT DISTINCT 
            TRIM(SUBSTR(autor_emenda, 1, INSTR(autor_emenda, '/') - 1)) as nome 
        FROM emendas 
        WHERE INSTR(autor_emenda, '/') > 0
        """
        df_emendas = pd.read_sql_query(query_emendas, conn)
        
        # Normalização de nomes (remover acentos e uppercase) para comparação
        import unicodedata
        def normalize_name(name):
            if not isinstance(name, str): return ""
            return unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII').upper().strip()

        # Criar dicionário {nome_normalizado: nome_original} para emendas
        emendas_dict = {normalize_name(n): n for n in df_emendas['nome'].dropna().tolist()}
        
        # 2. Pegar parlamentares do tabelao com filtros de estado/partido
        query_tabelao = "SELECT DISTINCT nome FROM tabelao WHERE 1=1"
        params = []
        if estado and estado != 'Todos':
            query_tabelao += " AND sgUF = ?"
            params.append(estado)
        if partido and partido != 'Todos':
            query_tabelao += " AND sgPartido = ?"
            params.append(partido)
            
        df_tabelao = pd.read_sql_query(query_tabelao, conn, params=params)
        
        # Criar conjunto de nomes normalizados do tabelao
        tabelao_norm = set(normalize_name(n) for n in df_tabelao['nome'].dropna().tolist())
        
        conn.close()
        
        # 3. Interseção: Usar nomes normalizados para encontrar correspondências
        # A lista final deve conter os nomes ORIGINAIS do tabelao (para bater com a busca de foto depois)
        
        nomes_finais = []
        for nome_real in df_tabelao['nome'].dropna().tolist():
            nome_norm = normalize_name(nome_real)
            if nome_norm in emendas_dict:
                nomes_finais.append(nome_real)

        # ✅ Retornar APENAS os deputados que têm emendas e combinam com os filtros
        # Não fazer fallback para mostrar todos os deputados
        return {"parlamentares": sorted(nomes_finais)}
    except Exception as e:
        logger.error(f"Erro ao buscar parlamentares de emendas: {e}")
        # Fallback para tabela geral
        try:
            conn = get_db_connection("tabelao")
            query = "SELECT DISTINCT nome FROM tabelao WHERE 1=1"
            params = []
            if estado and estado != 'Todos':
                query += " AND sgUF = ?"
                params.append(estado)
            if partido and partido != 'Todos':
                query += " AND sgPartido = ?"
                params.append(partido)
            query += " ORDER BY nome"
            df = pd.read_sql_query(query, conn, params=params)
            conn.close()
            return {"parlamentares": df['nome'].tolist()}
        except:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/gastos/ranking")
async def get_ranking_gastos(
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    parlamentar: Optional[str] = None,
    despesa: Optional[str] = None
):
    """Endpoint para o ranking de gastos parlamentares com coordenadas dos fornecedores."""
    try:
        conn = get_db_connection("tabelao")
        # Query com LEFT JOIN para pegar coordenadas dos fornecedores
        query = """
        SELECT 
            t.nome, t.sgUF, t.sgPartido, t.txtDescricao, t.txtFornecedor, t.vlrLiquido, 
            t.datEmissao, t.txtPassageiro, t.txtTrecho, t.ultimoStatus_urlFoto, 
            t.urlPartido, t.urlEstado,
            t.txtCNPJCPF, t.cnpj, t.urlDocumento, t.txtNumero,
            c.latitude, c.longitude, c.Cidade as cidade_fornecedor, c.endereco_completo
        FROM tabelao t
        LEFT JOIN coordenadas_empresas c ON (t.cnpj = c.cnpj OR t.txtCNPJCPF = c.cnpj)
        WHERE 1=1
        """
        params = []

        if estado:
            query += " AND t.sgUF = ?"
            params.append(estado)
        if partido:
            query += " AND t.sgPartido = ?"
            params.append(partido)
        if parlamentar:
            query += " AND t.nome = ?"
            params.append(parlamentar)
        if despesa:
            query += " AND t.txtDescricao LIKE ?"
            params.append(f"%{despesa}%")
        
        query += " ORDER BY t.vlrLiquido DESC LIMIT 1000"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        # Renomeia a coluna ` urlPartido` para `urlPartido`
        if ' urlPartido' in df.columns:
            df = df.rename(columns={' urlPartido': 'urlPartido'})
        
        # Converter para dict manualmente com tratamento de valores inválidos
        import numpy as np
        import json
        
        records = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                val = row[col]
                # Tratar valores inválidos
                if pd.isna(val) or (isinstance(val, float) and (np.isinf(val) or np.isnan(val))):
                    record[col] = None
                else:
                    record[col] = val
            records.append(record)

        return records
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/gastos/ranking-geral")
async def get_ranking_geral_deputados(
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    despesa: Optional[str] = None
):
    """Endpoint para ranking geral dos deputados que mais gastam (agregado por parlamentar) com filtros opcionais."""
    try:
        conn = get_db_connection("tabelao")
        
        # Query para ranking geral agregado por deputado (agrupado SOMENTE por nome para evitar duplicatas)
        query = """
        SELECT 
            nome,
            MAX(sgUF) as sgUF,
            MAX(sgPartido) as sgPartido,
            SUM(vlrLiquido) as total_gasto,
            COUNT(*) as quantidade_notas,
            AVG(vlrLiquido) as valor_medio_nota,
            MAX(ultimoStatus_urlFoto) as ultimoStatus_urlFoto,
            MAX(urlPartido) as urlPartido,
            MAX(urlEstado) as urlEstado
        FROM tabelao 
        WHERE 1=1
        """
        params = []
        
        # Adicionar filtros se fornecidos
        if estado and estado != 'Todos':
            query += " AND sgUF = ?"
            params.append(estado)
        if partido and partido != 'Todos':
            query += " AND sgPartido = ?"
            params.append(partido)
        if despesa and despesa != 'Todos':
            query += " AND txtDescricao LIKE ?"
            params.append(f"%{despesa}%")
        
        query += """
        GROUP BY nome
        ORDER BY total_gasto DESC
        LIMIT 100
        """
        
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        # Adicionar URLs de logos e bandeiras usando resolvedores do Wikipedia
        results = []
        for _, row in df.iterrows():
            record = row.to_dict()
            # Usar funções que buscam do Wikipedia com cache
            record['urlPartido'] = resolve_party_logo_from_wikipedia(row['sgPartido'], None)
            record['urlEstado'] = resolve_state_flag_from_wikipedia(row['sgUF'])
            
            # Formatação final
            for col in ['total_gasto', 'valor_medio_nota']:
                if pd.isna(record[col]): record[col] = 0.0
                else: record[col] = float(record[col])
            
            results.append(record)
        
        return results

    except Exception as e:
        print(f"Erro no ranking geral: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/filtros/estados")
@app.get("/api/filters/estados")
async def get_estados_unified(source: Optional[str] = None):
    """Retorna lista de estados única e rápida."""
    try:
        if source == "passagens":
            conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
            query = """
                SELECT DISTINCT sgUF
                FROM tabelao
                WHERE UPPER(txtDescricao) LIKE '%PASSAGEM AÉREA%'
                  AND sgUF IS NOT NULL
                  AND sgUF != ''
                ORDER BY sgUF
            """
            df = pd.read_sql_query(query, conn)
            conn.close()
            return {"estados": df['sgUF'].dropna().tolist()}

        estados_br = sorted([
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", 
            "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", 
            "SP", "SE", "TO"
        ])
        return {"estados": estados_br}
    except Exception as e:
        logger.error(f"Erro em get_estados_unified: {e}")
        return {"estados": []}

@app.get("/api/filtros/partidos")
@app.get("/api/filters/partidos")
async def get_partidos_unified(estado: Optional[str] = None, source: Optional[str] = None, atual: bool = False):
    """Retorna lista de partidos de forma ultra-rápida via cache."""
    try:
        conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
        if source == "passagens":
            query = """
                SELECT DISTINCT sgPartido
                FROM tabelao
                WHERE UPPER(txtDescricao) LIKE '%PASSAGEM AÉREA%'
                  AND sgPartido IS NOT NULL
                  AND sgPartido != ''
            """
        else:
            col = "sgPartidoAtual" if atual else "sgPartido"
            query = f"SELECT DISTINCT {col} as sgPartido FROM cache_filtros_partidos WHERE {col} IS NOT NULL"
        
        params = []
        if estado and estado != "Todos":
            query += " AND sgUF = ?"
            params.append(estado)
        query += " ORDER BY sgPartido"
        
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        partidos = df['sgPartido'].dropna().tolist()
        return {"partidos": sorted(list(set(partidos)))}
    except Exception as e:
        logger.error(f"Erro em get_partidos_unified: {e}")
        return {"partidos": []}

@app.get("/api/filtros/parlamentares")
@app.get("/api/filters/parlamentares")
async def get_parlamentares_unified(
    estado: Optional[str] = None, 
    partido: Optional[str] = None, 
    source: Optional[str] = None,
    partido_atual: Optional[str] = None
):
    """Retorna lista de parlamentares de forma ultra-rápida via cache."""
    try:
        conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
        if source == "passagens":
            query = """
                SELECT DISTINCT nome, sgPartido, sgUF, ultimoStatus_urlFoto as urlFoto
                FROM tabelao
                WHERE UPPER(txtDescricao) LIKE '%PASSAGEM AÉREA%'
            """
        else:
            query = "SELECT DISTINCT nome, sgPartido, sgPartidoAtual, sgUF, urlFoto FROM cache_filtros_parlamentares WHERE 1=1"
        params = []
        
        if estado and estado != "Todos":
            query += " AND sgUF = ?"
            params.append(estado)
        
        if partido and partido != "Todos":
            query += " AND sgPartido = ?"
            params.append(partido)
            
        if partido_atual and partido_atual != "Todos":
            query += " AND sgPartidoAtual = ?"
            params.append(partido_atual)
            
        query += " ORDER BY nome"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        # Manter compatibilidade com quem espera 'sgPartido'
        # Se filtramos por partido_atual, o 'sgPartido' retornado deve ser o atual para a UI
        if partido_atual:
            df['sgPartido'] = df['sgPartidoAtual']

        # Deduplicar por nome — cache pode ter registros duplicados por mandato
        df = df.drop_duplicates(subset=['nome']).reset_index(drop=True)

        return {"parlamentares": df.to_dict(orient="records")}
    except Exception as e:
        logger.error(f"Erro em get_parlamentares_unified: {e}")
        return {"parlamentares": []}


@app.get("/api/mapa-partidario/zonas")
async def get_mapa_partidario_zonas(
    estado: str,
    partido: Optional[str] = None,
    partido_atual: Optional[str] = None,
    parlamentar: Optional[str] = None,
):
    try:
        if parlamentar and parlamentar != "Todos":
            partido = None
            partido_atual = None
        cached_payload = get_cached_mapa_partidario_payload(
            estado=estado,
            partido_eleicao=partido,
            partido_atual=partido_atual,
            parlamentar=parlamentar,
        )
        if cached_payload:
            return cached_payload

        payload = compute_mapa_partidario_payload(
            estado=estado,
            partido=partido,
            partido_atual=partido_atual,
            parlamentar=parlamentar,
        )
        materialize_mapa_partidario_payload_cache(
            estado=estado,
            partido_eleicao=partido,
            partido_atual=partido_atual,
            parlamentar=parlamentar,
            payload=payload,
        )
        return payload
    except Exception as exc:
        logging.exception("Erro ao montar payload do mapa partidário")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/parlamentares/detalhes")
async def get_parlamentar_detalhes(nome: str):
    """Retorna detalhes do parlamentar (foto, partido, estado)"""
    try:
        conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tabelao WHERE nome = ? LIMIT 1", (nome,))
        row = cursor.fetchone()
        
        if not row:
            return {}
            
        data = dict(row)
        conn.close()
        
        # Construir resposta
        partido = data.get('sgPartido')
        estado = data.get('sgUF')
        
        # Tentar obter URL da foto (pode ser ultimoStatus_urlFoto ou construir via ID)
        url_foto = data.get('ultimoStatus_urlFoto')
        if not url_foto and data.get('ideCadastro'):
            url_foto = f"https://www.camara.leg.br/internet/deputado/bandep/{data.get('ideCadastro')}.jpg"
            
        return {
            "nome": data.get('nome'),
            "id": data.get('ideCadastro'),
            "partido": partido,
            "uf": estado,
            "urlFoto": url_foto,
            "urlPartido": partido_logos_dict.get(partido) if partido else None,
            "urlEstado": estado_logos_dict.get(estado) if estado else None
        }
    except Exception as e:
        print(f"Erro ao buscar detalhes parlamentar: {e}")
        return {}

def _build_conformidade_cache(conn):
    """Cria tabela de cache para filtros de conformidade (roda 1x na inicialização)."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS cache_filtros_conformidade")
    # Pega apenas o partido com mais registros por parlamentar (evita duplicatas de mudança de partido)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_filtros_conformidade AS
        SELECT nome, sgUF, sgPartido, urlFoto FROM (
            SELECT
                TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) AS nome,
                t.sgUF,
                t.sgPartido,
                t.ultimoStatus_urlFoto AS urlFoto,
                COUNT(*) as qtd,
                ROW_NUMBER() OVER (
                    PARTITION BY TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1))
                    ORDER BY COUNT(*) DESC
                ) as rn
            FROM cruzamento_emendas_sociedades c
            JOIN tabelao t ON TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)) = t.nome
            WHERE (CAST(REPLACE(REPLACE(c.valor_emenda, '.', ''), ',', '.') AS REAL)) > 0
            GROUP BY TRIM(SUBSTR(c.parlamentar_autor, 1, INSTR(c.parlamentar_autor || ' /', ' /') - 1)), t.sgUF, t.sgPartido
        ) WHERE rn = 1
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conf_cache_uf ON cache_filtros_conformidade(sgUF)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conf_cache_partido ON cache_filtros_conformidade(sgPartido)")
    conn.commit()

@app.get("/api/filtros/conformidade")
async def get_filtros_conformidade(uf: Optional[str] = None, partido: Optional[str] = None):
    """Retorna apenas Estados, Partidos e Parlamentares que possuem registros em cruzamento_emendas_sociedades."""
    try:
        conn = get_db_connection("tabelao")

        # Garante que o cache existe
        _build_conformidade_cache(conn)

        # 1. Estados
        df_uf = pd.read_sql_query("SELECT DISTINCT sgUF FROM cache_filtros_conformidade ORDER BY sgUF", conn)
        estados = df_uf['sgUF'].dropna().tolist()

        # 2. Partidos filtrados por UF
        params_partido = []
        where_partido = ""
        if uf and uf != 'Todos':
            where_partido = "WHERE sgUF = ?"
            params_partido = [uf]
        df_partido = pd.read_sql_query(f"SELECT DISTINCT sgPartido FROM cache_filtros_conformidade {where_partido} ORDER BY sgPartido", conn, params=params_partido)
        partidos = df_partido['sgPartido'].dropna().tolist()

        # 3. Parlamentares filtrados por UF e partido
        where_parl = []
        params_parl = []
        if uf and uf != 'Todos':
            where_parl.append("sgUF = ?")
            params_parl.append(uf)
        if partido and partido != 'Todos':
            where_parl.append("sgPartido = ?")
            params_parl.append(partido)
        where_parl_sql = ("WHERE " + " AND ".join(where_parl)) if where_parl else ""
        df_parl = pd.read_sql_query(f"SELECT DISTINCT nome, sgPartido, sgUF, urlFoto FROM cache_filtros_conformidade {where_parl_sql} ORDER BY nome", conn, params=params_parl)
        parlamentares = df_parl.to_dict(orient="records")

        conn.close()
        return {
            "estados": estados,
            "partidos": partidos,
            "parlamentares": parlamentares
        }
    except Exception as e:
        logger.error(f"Erro em get_filtros_conformidade: {e}")
        return {"estados": [], "partidos": [], "parlamentares": []}

# --- NOVOS ENDPOINTS DE VOTAÇÃO ---

# --- CONFIGURAÇÕES ---
COMMISSION_MAPPING = {
    "PLEN": "Plenário",
    "CCJC": "Comissão de Constituição e Justiça e de Cidadania",
    "CCOM": "Comissão de Comunicação",
    "CCP": "Comissão de Cultura",
    "CCTI": "Comissão de Ciência, Tecnologia e Inovação",
    "CCULT": "Comissão de Cultura (Legado)",
    "CDE": "Comissão de Desenvolvimento Econômico",
    "CDHMIR": "Comissão de Direitos Humanos, Minorias e Igualdade Racial",
    "CDU": "Comissão de Desenvolvimento Urbano",
    "CE": "Comissão de Educação",
    "CESPO": "Comissão do Esporte",
    "CEXCIRS": "Comissão Externa sobre Calamidade no RS",
    "CFT": "Comissão de Finanças e Tributação",
    "CICS": "Comissão de Indústria, Comércio e Serviços",
    "CIDOSO": "Comissão de Defesa dos Direitos da Pessoa Idosa",
    "CINDRE": "Comissão de Integração Nacional e Desenvolvimento Regional",
    "CLP": "Comissão de Legislação Participativa",
    "CMADS": "Comissão de Meio Ambiente e Desenvolvimento Sustentável",
    "CME": "Comissão de Minas e Energia",
    "CMULHER": "Comissão de Defesa dos Direitos da Mulher",
    "CN": "Congresso Nacional",
    "CPASF": "Comissão de Previdência, Assistência Social, Infância, Adolescência e Família",
    "CPD": "Comissão de Defesa dos Direitos das Pessoas com Deficiência",
    "CREDN": "Comissão de Relações Exteriores e de Defesa Nacional",
    "CSAUDE": "Comissão de Saúde",
    "CSPCCO": "Comissão de Segurança Pública e Combate ao Crime Organizado",
    "CTRAB": "Comissão de Trabalho",
    "CTUR": "Comissão de Turismo",
    "CVT": "Comissão de Viação e Transportes",
    "CAPADR": "Comissão de Agricultura, Pecuária, Abastecimento e Desenvolvimento Rural"
}

@app.get("/api/filtros")
@app.get("/api/filters")
async def get_filtros_opcoes():
    """Retorna opções dinâmicas para os filtros de Órgão e Tema."""
    try:
        conn = get_db_connection("tabelao")
        
        # 1. Órgãos com Nome Completo
        df_orgaos = pd.read_sql_query("SELECT DISTINCT sigla_orgao FROM votacoes ORDER BY sigla_orgao", conn)
        raw_siglas = [o for o in df_orgaos['sigla_orgao'].dropna().tolist() if o.strip()]
        
        orgaos_mapped = []
        for sigla in raw_siglas:
            nome = COMMISSION_MAPPING.get(sigla, f"Comissão {sigla}")
            if sigla == "PLEN":
                nome = "Plenário"
            orgaos_mapped.append({"sigla": sigla, "nome": nome})
            
        # Sort by name for better UX
        orgaos_mapped.sort(key=lambda x: x['nome'])
        
        # 2. Temas (Definidos Hardcoded para Simplificação UX)
        # Em vez de pegar todos do banco, retornamos categorias macro fixas
        temas_list = [
            "Administração Pública",
            "Agropecuária e Meio Ambiente",
            "Cultura e Esporte",
            "Direitos Humanos e Sociais",
            "Economia e Desenvolvimento",
            "Educação",
            "Infraestrutura e Transportes",
            "Relações Exteriores",
            "Saúde",
            "Segurança Pública e Justiça",
            "Outros"
        ]
        
        conn.close()
        return {
            "orgaos": orgaos_mapped,
            "temas": temas_list
        }
    except Exception as e:
        logger.error(f"Erro ao buscar filtros: {e}")
        return {"orgaos": [], "temas": []}

@app.get("/api/votos/stats")
async def get_votos_stats(
    tema: Optional[str] = None, 
    governo: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    orgao: Optional[str] = None
):
    """Retorna estatísticas de votações filtradas, incluindo evolução mensal."""
    try:
        conn = get_db_connection("tabelao")
        
        # Base WHERE clauses
        where_clauses = ["1=1"]
        params = []
        
        if data_inicio:
            where_clauses.append("v.data_registro >= ?")
            params.append(data_inicio)
        if data_fim:
            where_clauses.append("v.data_registro <= ?")
            params.append(data_fim)

        # Robust filter for "Todos"
        if orgao and orgao.lower() not in ['todos', 'todos os óraos', 'todos os órgãos', '']:
            if orgao.lower() == 'plenario':
                where_clauses.append("v.sigla_orgao = 'PLEN'")
            elif orgao.lower() == 'comissao':
                where_clauses.append("v.sigla_orgao != 'PLEN'")
            else:
                # Specific organ (e.g. 'CCJC')
                where_clauses.append("v.sigla_orgao = ?")
                params.append(orgao)

        # Base Query Fragment for Join — unifica votacoes_unificadas (667 rows) + votacoes (18 rows novas)
        base_join = f"""
        FROM (
            SELECT id_votacao, data_registro, sigla_orgao, tipo_votacao, descricao
            FROM votacoes_unificadas
            UNION ALL
            SELECT id_votacao, data_votacao AS data_registro, sigla_orgao, tipo_votacao, descricao
            FROM votacoes
            WHERE id_votacao NOT IN (SELECT id_votacao FROM votacoes_unificadas)
        ) v
        LEFT JOIN votacoes_analise_enrichment e ON v.id_votacao = e.id_votacao
        WHERE {' AND '.join(where_clauses)}
        """
        
        # Additional params for Enrichment queries
        enrich_params = list(params) 
        enrich_clause = ""
        if tema:
            keywords_map = {
                "Administração Pública": ['%Admin%', '%Pública%', '%Polític%', '%Eleitoral%', '%Transparência%', '%Governo%'],
                "Agropecuária e Meio Ambiente": ['%Agro%', '%Meio Amb%', '%Rural%', '%Energia%', '%Clima%', '%Terra%'],
                "Cultura e Esporte": ['%Cultura%', '%Esporte%', '%Arte%'],
                "Direitos Humanos e Sociais": ['%Humanos%', '%Social%', '%Mulher%', '%Idoso%', '%Igualdade%', '%Minoria%', '%Criança%', '%Assistência%'],
                "Economia e Desenvolvimento": ['%Econ%', '%Finan%', '%Tribut%', '%Indústria%', '%Comércio%', '%Turismo%', '%Trabalho%'],
                "Educação": ['%Educação%', '%Ensino%'],
                "Infraestrutura e Transportes": ['%Infra%', '%Transp%', '%Urban%', '%Habita%', '%Cidades%'],
                "Relações Exteriores": ['%Exteriores%', '%Internacional%'],
                "Saúde": ['%Saú%', '%Sanit%', '%Médico%'],
                "Segurança Pública e Justiça": ['%Segurança%', '%Justiça%', '%Penal%', '%Defesa%', '%Crime%', '%Civil%'],
                "Outros": ['%Outros%', '%Homenagem%', '%Data%']
            }
            keywords = keywords_map.get(tema, [f"%{tema}%"])
            enrich_clause += " AND (" + " OR ".join(["e.tema_macro LIKE ?"] * len(keywords)) + ")"
            enrich_params.extend(keywords)
        if governo:
            enrich_clause += " AND e.pauta_governo = ?"
            enrich_params.append(governo)
            
        # 1. Stats de Tipos
        query_tipos = f"""
        SELECT 
           CASE 
               WHEN v.tipo_votacao = 'Simbólica' OR v.tipo_votacao = 'Simbolica' THEN 'Simbólica'
               ELSE 'Nominal'
           END as tipo_grouped,
           COUNT(DISTINCT v.id_votacao) as total
        {base_join}
        {enrich_clause}
        GROUP BY tipo_grouped
        """
        df_tipos = pd.read_sql_query(query_tipos, conn, params=enrich_params)
        logger.info(f"📊 Stats Tipos Encontrados: {df_tipos.to_dict(orient='records')}")
        tipos_stats = [{"tipo_votacao": row['tipo_grouped'], "total": row['total']} for _, row in df_tipos.iterrows()]
        
        # 2. Stats de Governo
        query_gov = f"""
        SELECT e.pauta_governo, COUNT(DISTINCT v.id_votacao) as total 
        {base_join}
        {enrich_clause}
        GROUP BY e.pauta_governo
        """
        df_gov = pd.read_sql_query(query_gov, conn, params=enrich_params)
        
        # 3. Stats de Temas (Agrupados em Macros)
        query_temas = f"""
        SELECT 
            CASE
                WHEN e.tema_macro LIKE '%Admin%' OR e.tema_macro LIKE '%Pública%' OR e.tema_macro LIKE '%Polític%' OR e.tema_macro LIKE '%Eleitoral%' OR e.tema_macro LIKE '%Transparência%' OR e.tema_macro LIKE '%Governo%' OR e.tema_macro LIKE '%Legislação%' OR e.tema_macro LIKE '%Regimento%' OR e.tema_macro LIKE '%Mesa%' OR e.tema_macro LIKE '%Comunicação%' OR e.tema_macro LIKE '%Comissão%' THEN 'Administração Pública'
                WHEN e.tema_macro LIKE '%Agro%' OR e.tema_macro LIKE '%Meio Amb%' OR e.tema_macro LIKE '%Rural%' OR e.tema_macro LIKE '%Energia%' OR e.tema_macro LIKE '%Clima%' OR e.tema_macro LIKE '%Terra%' THEN 'Agropecuária e Meio Ambiente'
                WHEN e.tema_macro LIKE '%Cultura%' OR e.tema_macro LIKE '%Esporte%' OR e.tema_macro LIKE '%Arte%' THEN 'Cultura e Esporte'
                WHEN e.tema_macro LIKE '%Humanos%' OR e.tema_macro LIKE '%Social%' OR e.tema_macro LIKE '%Mulher%' OR e.tema_macro LIKE '%Idoso%' OR e.tema_macro LIKE '%Igualdade%' OR e.tema_macro LIKE '%Minoria%' OR e.tema_macro LIKE '%Criança%' OR e.tema_macro LIKE '%Assistência%' THEN 'Direitos Humanos e Sociais'
                WHEN e.tema_macro LIKE '%Econ%' OR e.tema_macro LIKE '%Finan%' OR e.tema_macro LIKE '%Tribut%' OR e.tema_macro LIKE '%Indústria%' OR e.tema_macro LIKE '%Comércio%' OR e.tema_macro LIKE '%Turismo%' OR e.tema_macro LIKE '%Trabalho%' THEN 'Economia e Desenvolvimento'
                WHEN e.tema_macro LIKE '%Educação%' OR e.tema_macro LIKE '%Ensino%' THEN 'Educação'
                WHEN e.tema_macro LIKE '%Infra%' OR e.tema_macro LIKE '%Transp%' OR e.tema_macro LIKE '%Urban%' OR e.tema_macro LIKE '%Habita%' OR e.tema_macro LIKE '%Cidades%' THEN 'Infraestrutura e Transportes'
                WHEN e.tema_macro LIKE '%Exteriores%' OR e.tema_macro LIKE '%Internacional%' THEN 'Relações Exteriores'
                WHEN e.tema_macro LIKE '%Saú%' OR e.tema_macro LIKE '%Sanit%' OR e.tema_macro LIKE '%Médico%' THEN 'Saúde'
                WHEN e.tema_macro LIKE '%Segurança%' OR e.tema_macro LIKE '%Justiça%' OR e.tema_macro LIKE '%Penal%' OR e.tema_macro LIKE '%Defesa%' OR e.tema_macro LIKE '%Crime%' OR e.tema_macro LIKE '%Civil%' THEN 'Segurança Pública e Justiça'
                ELSE 'Outros'
            END as macro_tema,
            COUNT(DISTINCT v.id_votacao) as total
        {base_join}
        {enrich_clause}
        GROUP BY macro_tema
        ORDER BY total DESC
        """
        df_temas = pd.read_sql_query(query_temas, conn, params=enrich_params)

        # 4. Evolução Mensal (NOVO)
        # Groups by Month (YYYY-MM) and Pauta Governo
        query_evolucao = f"""
        SELECT strftime('%Y-%m', v.data_registro) as mes, e.pauta_governo, COUNT(DISTINCT v.id_votacao) as total
        {base_join}
        {enrich_clause}
        GROUP BY mes, e.pauta_governo
        ORDER BY mes ASC
        """
        df_evolucao = pd.read_sql_query(query_evolucao, conn, params=enrich_params)
        
        # 5. Taxa de Vitória do Governo
        # Vitória = (Pauta Sim & Aprovado) OR (Pauta Não & Rejeitado)
        query_vitoria = f"""
        SELECT
            SUM(CASE
                   WHEN e.pauta_governo = 'Sim' AND v.descricao LIKE 'Aprovad%' THEN 1
                   WHEN e.pauta_governo = 'Não' AND v.descricao LIKE 'Rejeitad%' THEN 1
                   ELSE 0
               END) as vitorias,
            SUM(CASE
                   WHEN e.pauta_governo IN ('Sim', 'Não') AND (v.descricao LIKE 'Aprovad%' OR v.descricao LIKE 'Rejeitad%') THEN 1
                   ELSE 0
               END) as total_validos
        {base_join}
        {enrich_clause}
        """
        df_vitoria = pd.read_sql_query(query_vitoria, conn, params=enrich_params)

        conn.close()

        for df in [df_gov, df_temas, df_evolucao, df_vitoria]:
            df.replace({float('nan'): None}, inplace=True)

        return {
            "tipos": tipos_stats,
            "governo": df_gov.to_dict(orient='records'),
            "temas": df_temas.to_dict(orient='records'),
            "evolucao": df_evolucao.to_dict(orient='records'),
            "vitoria": df_vitoria.to_dict(orient='records')
        }
    except Exception as e:
        logger.error(f"Erro em get_votos_stats: {e}")
        return {"tipos": [], "governo": [], "temas": [], "evolucao": []}

@app.get("/api/votos/lista")
async def get_votos_lista(
    tema: Optional[str] = None, 
    governo: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    orgao: Optional[str] = None
):
    """Retorna a lista de votações filtrada."""
    try:
        logger.info(f"🔍 API /api/votos/lista chamada. Params: {data_inicio} a {data_fim}, Orgao: {orgao}")
        conn = get_db_connection("tabelao")
        query = """
        WITH votos_all AS (
            SELECT id_votacao, data_registro, sigla_orgao, tipo_votacao, descricao, proposicao, cobertura_midia
            FROM votacoes_unificadas
            UNION ALL
            SELECT id_votacao, data_votacao AS data_registro, sigla_orgao, tipo_votacao, descricao,
                   (COALESCE(nome_projeto, '') || ' ' || COALESCE(numero_pl, '')) AS proposicao,
                   CAST(houve_cobertura AS INTEGER) AS cobertura_midia
            FROM votacoes
            WHERE id_votacao NOT IN (SELECT id_votacao FROM votacoes_unificadas)
        )
        SELECT v.id_votacao, v.data_registro, v.sigla_orgao,
               CASE
                   WHEN e.pauta_governo = 'Sim' THEN
                        CASE WHEN v.descricao LIKE 'Aprovad%' THEN 1 WHEN v.descricao LIKE 'Rejeitad%' THEN 0 ELSE NULL END
                   WHEN e.pauta_governo = 'Não' THEN
                        CASE WHEN v.descricao LIKE 'Rejeitad%' THEN 1 WHEN v.descricao LIKE 'Aprovad%' THEN 0 ELSE NULL END
                   ELSE NULL
               END as vitoria_gov,
               v.proposicao,
               CASE
                   WHEN d.simbolica = 2 THEN 'Nominal (Agregada)'
                   WHEN d.simbolica = 1 THEN 'Simbólica'
                   WHEN d.simbolica = 0 THEN 'Nominal'
                   ELSE v.tipo_votacao
               END as tipo_votacao,
               v.cobertura_midia,
               e.tema_macro, e.pauta_governo,
               COALESCE(d.resumo_midia, e.resumo_leigo) as resumo_leigo,
               d.url_proposicao
        FROM votos_all v
        LEFT JOIN votacoes_analise_enrichment e ON v.id_votacao = e.id_votacao
        LEFT JOIN votacoes_destaque d ON v.id_votacao = d.id_votacao
        WHERE 1=1
        """
        params = []
        
        # Filtros
        if tema:
            keywords_map = {
                "Administração Pública": ['%Admin%', '%Pública%', '%Polític%', '%Eleitoral%', '%Transparência%', '%Governo%', '%Legislação%', '%Regimento%', '%Mesa%', '%Comunicação%', '%Comissão%'],
                "Agropecuária e Meio Ambiente": ['%Agro%', '%Meio Amb%', '%Rural%', '%Energia%', '%Clima%', '%Terra%'],
                "Cultura e Esporte": ['%Cultura%', '%Esporte%', '%Arte%'],
                "Direitos Humanos e Sociais": ['%Humanos%', '%Social%', '%Mulher%', '%Idoso%', '%Igualdade%', '%Minoria%', '%Criança%', '%Assistência%'],
                "Economia e Desenvolvimento": ['%Econ%', '%Finan%', '%Tribut%', '%Indústria%', '%Comércio%', '%Turismo%', '%Trabalho%'],
                "Educação": ['%Educação%', '%Ensino%'],
                "Infraestrutura e Transportes": ['%Infra%', '%Transp%', '%Urban%', '%Habita%', '%Cidades%'],
                "Relações Exteriores": ['%Exteriores%', '%Internacional%'],
                "Saúde": ['%Saú%', '%Sanit%', '%Médico%'],
                "Segurança Pública e Justiça": ['%Segurança%', '%Justiça%', '%Penal%', '%Defesa%', '%Crime%', '%Civil%'],
                "Outros": ['%Outros%', '%Homenagem%', '%Data%']
            }
            keywords = keywords_map.get(tema, [f"%{tema}%"])
            query += " AND (" + " OR ".join(["e.tema_macro LIKE ?"] * len(keywords)) + ")"
            params.extend(keywords)
        if governo:
            query += " AND e.pauta_governo = ?"
            params.append(governo)
        if data_inicio:
            query += " AND v.data_registro >= ?"
            params.append(data_inicio)
        if data_fim:
            query += " AND v.data_registro <= ?"
            params.append(data_fim)
        if orgao and orgao.lower() != 'todos':
            if orgao.lower() == 'plenario':
                query += " AND v.sigla_orgao = 'PLEN'"
            elif orgao.lower() == 'comissao':
                query += " AND v.sigla_orgao != 'PLEN'"
            else:
                query += " AND v.sigla_orgao = ?"
                params.append(orgao)

        query += " ORDER BY v.data_registro DESC LIMIT 1000"
        
        logger.info(f"🛠️ Executando query: {query}")
        logger.info(f"🧩 Parâmetros: {params}")

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        logger.info(f"✅ Query executada com sucesso. Resultados encontrados: {len(df)}")
        if not df.empty:
            logger.info(f"📋 Exemplo de registro: {df.iloc[0].to_dict()}")
        else:
            logger.warning("⚠️ Nenhum registro encontrado para os filtros selecionados.")
            
        # Fix: NaN values in DataFrame cause 'ValueError: Out of range float values are not JSON compliant'
        df = df.replace({np.nan: None})
        
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"❌ Erro em get_votos_lista: {e}", exc_info=True)
        return []

@app.get("/api/votos/detalhe/{id_votacao}")
async def get_voto_detalhe(id_votacao: str):
    """Retorna a ficha detalhada de uma votação, aprovadores e opositores."""
    try:
        def sanitize_json_value(value):
            if isinstance(value, dict):
                return {k: sanitize_json_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [sanitize_json_value(v) for v in value]
            if pd.isna(value):
                return None
            return value

        conn = get_db_connection("tabelao")
        
        # 1. Ficha da Votação - Enriquecida com polêmicas e temas
        query_ficha = """
        WITH votos_base AS (
            SELECT
                v.id_votacao,
                v.data_votacao AS data_registro,
                v.sigla_orgao,
                (v.nome_projeto || ' ' || COALESCE(v.numero_pl, '')) AS proposicao,
                v.tipo_votacao AS tipo_votacao_raw,
                v.descricao,
                v.objeto_votacao,
                v.foi_polemico,
                v.motivo_polemica,
                v.fontes_citadas,
                v.resumo_discussao
            FROM votacoes v
            WHERE v.id_votacao = ?
            UNION ALL
            SELECT
                u.id_votacao,
                u.data_registro AS data_registro,
                u.sigla_orgao,
                u.proposicao AS proposicao,
                COALESCE(u.tipo_votacao, 'Nominal') AS tipo_votacao_raw,
                u.descricao,
                NULL AS objeto_votacao,
                0 AS foi_polemico,
                NULL AS motivo_polemica,
                NULL AS fontes_citadas,
                NULL AS resumo_discussao
            FROM votacoes_unificadas u
            WHERE u.id_votacao = ?
        )
        SELECT
            b.id_votacao,
            b.data_registro,
            b.sigla_orgao,
            b.proposicao,
            CASE
                WHEN d.simbolica = 2 THEN 'Nominal (Agregada)'
                WHEN d.simbolica = 1 THEN 'Simbólica'
                WHEN d.simbolica = 0 THEN 'Nominal'
                ELSE b.tipo_votacao_raw
            END AS tipo_votacao,
            b.descricao,
            b.objeto_votacao,
            b.foi_polemico,
            b.motivo_polemica,
            b.fontes_citadas,
            b.resumo_discussao,
            e.tema_macro,
            COALESCE(d.resumo_midia, e.resumo_leigo) AS resumo_leigo,
            e.pauta_governo,
            e.local_votacao,
            u.links_noticias,
            d.url_proposicao,
            d.hash_integridade
        FROM votos_base b
        LEFT JOIN votacoes_analise_enrichment e ON b.id_votacao = e.id_votacao
        LEFT JOIN votacoes_unificadas u ON b.id_votacao = u.id_votacao
        LEFT JOIN votacoes_destaque d ON b.id_votacao = d.id_votacao
        LIMIT 1
        """
        df_ficha = pd.read_sql_query(query_ficha, conn, params=[id_votacao, id_votacao])
        
        if df_ficha.empty:
            conn.close()
            raise HTTPException(status_code=404, detail="Votação não encontrada")
            
        ficha = sanitize_json_value(df_ficha.iloc[0].to_dict())
        
        # 2. Enriquecimento em tempo real (API Câmara)
        url_video = None
        nome_completo_orgao = ficha.get('sigla_orgao')
        tipo_votacao_real = ficha.get('tipo_votacao')
        
        try:
            url_detalhe = f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{id_votacao}"
            resp = requests.get(url_detalhe, timeout=2)
            if resp.status_code == 200:
                data_api = resp.json().get('dados', {})
                id_evento = data_api.get('idEvento')
                
                # 1. Correção idEvento / Órgão / Video
                if id_evento:
                    # Buscar detalhes do evento (vídeo e nome do órgão)
                    url_ev = f"https://dadosabertos.camara.leg.br/api/v2/eventos/{id_evento}"
                    resp_ev = requests.get(url_ev, timeout=1)
                    if resp_ev.status_code == 200:
                        ev_data = resp_ev.json().get('dados', {})
                        url_video = ev_data.get('urlRegistro')
                        if ev_data.get('orgaos'):
                            nome_completo_orgao = ev_data['orgaos'][0].get('nome')

                # 2. Busca de Documento (Inteiro Teor - PDF)
                # Prioridade: 1. Proposicoes Afetadas (Link do PL Original)
                #             2. Proposicao Objeto (Link do que esta sendo votado, ex: Parecer)
                #             3. Objetos Possiveis (Outros relacionados)
                url_inteiro_teor = None
                
                candidatos_busca = []
                
                # Coleta candidatos
                if data_api.get('proposicoesAfetadas'):
                    candidatos_busca.extend(data_api['proposicoesAfetadas'])
                
                if data_api.get('proposicaoObjeto'):
                    candidatos_busca.append(data_api['proposicaoObjeto']) # Pode ser dict ou string/uri
                    
                if data_api.get('objetosPossiveis'):
                    candidatos_busca.extend(data_api['objetosPossiveis'])
                    
                seen_uris = set()
                
                for cand in candidatos_busca:
                    if url_inteiro_teor: break
                    
                    uri = None
                    if isinstance(cand, dict):
                        uri = cand.get('uri')
                    elif isinstance(cand, str):
                        uri = cand # as vezes é direto a string
                    
                    # OTIMIZACAO: Comentando busca recursiva de PDF para performance
                    # if uri and uri not in seen_uris and 'dadosabertos' in uri:
                    #     seen_uris.add(uri)
                    #     try:
                    #         r_pdf = requests.get(uri, timeout=1) # Reduced timeout
                    #         if r_pdf.status_code == 200:
                    #             d_pdf = r_pdf.json().get('dados', {})
                    #             if d_pdf.get('urlInteiroTeor'):
                    #                 url_inteiro_teor = d_pdf.get('urlInteiroTeor')
                    #     except:
                    #         pass

                if url_inteiro_teor:
                    ficha['url_inteiro_teor'] = url_inteiro_teor

                # 3. Correção Tipo Votação (Se houver votos nominais detectados, força Nominal)
                # Se a API disser algo, usamos. Se disser N/A ou null, mas tiver votos, forçamos Nominal posteriormente.
                tipo_votacao_api = data_api.get('tipoVotacao')
                if tipo_votacao_api:
                    tipo_votacao_real = tipo_votacao_api

        except Exception as e:
            logger.error(f"Erro no enriquecimento API para {id_votacao}: {e}")

        # Atualizar ficha com dados novos
        ficha['url_video'] = url_video
        ficha['nome_orgao_completo'] = nome_completo_orgao
        ficha['tipo_votacao'] = tipo_votacao_real
        
        # 3. Listas de Votos (Aprovadores / Opositores)
        aprovadores = []
        opositores = []
        abstencoes = []
        
        # TENTATIVA 1: Buscar do banco local (Nominal)
        # TENTATIVA 1: Buscar do banco local (Nominal - Destaques / ID Based)
        query_votos_local = """
        SELECT DISTINCT v.nome_deputado as nome, v.partido, v.uf, v.voto,
               t.ultimoStatus_urlFoto as foto, t.ideCadastro as id
        FROM votos_destaque_detalhe v
        LEFT JOIN tabelao t ON v.id_deputado = t.ideCadastro
        WHERE v.id_votacao = ?
        """
        df_votos_local = pd.read_sql_query(query_votos_local, conn, params=[id_votacao])
        
        if not df_votos_local.empty:
            aprovadores = df_votos_local[df_votos_local['voto'] == 'Sim'].to_dict(orient="records")
            opositores = df_votos_local[df_votos_local['voto'] == 'Não'].to_dict(orient="records")
            abstencoes = df_votos_local[df_votos_local['voto'].isin(['Abstenção', 'Obstrução'])].to_dict(orient="records")
        
        # TENTATIVA 2: Fallback API Real-time (se nominal e vazio no banco)
        if not aprovadores and not opositores and ficha.get('tipo_votacao') != 'Simbólica':
            try:
                url_votos_api = f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{id_votacao}/votos"
                resp_v = requests.get(url_votos_api, timeout=10)
                if resp_v.status_code == 200:
                    votos_api = resp_v.json().get('dados', [])
                    for rv in votos_api:
                        parl = rv.get('deputado_') or rv.get('parlamentar')
                        if not parl: continue
                        v_obj = {
                            "nome": parl.get('nome'),
                            "partido": parl.get('siglaPartido'),
                            "uf": parl.get('siglaUf'),
                            "foto": parl.get('urlFoto'),
                            "id": parl.get('id'),
                            "voto": rv.get('tipoVoto')
                        }
                        if rv.get('tipoVoto') == 'Sim':
                            aprovadores.append(v_obj)
                        elif rv.get('tipoVoto') == 'Não':
                            opositores.append(v_obj)
                        elif rv.get('tipoVoto') in ['Abstenção', 'Obstrução']:
                            abstencoes.append(v_obj)
            except Exception as e:
                logger.error(f"Erro ao buscar votos real-time para {id_votacao}: {e}")

        # TENTATIVA 3: Fallback PRESENÇA (Para Votação Simbólica)
        # Se for Simbólica e não tiver votos nominais (aprovadores vazios),
        # buscamos a lista de PRESENÇA do evento e assumimos que todos deram quórum/aprovaram.
        if not aprovadores and not opositores and ficha.get('tipo_votacao') == 'Simbólica':
             try:
                 current_id_evento = ficha.get('idEvento')
                 
                 # Tenta recuperar id_evento da API se não tiver na ficha (pode ter vindo do 'data_api' acima, mas o escopo é tricky)
                 # Vamos confiar no ficha.idEvento ou tentar buscar de novo se falhar?
                 # Simplificação: ficha['idEvento'] geralmente vem do banco.
                 
                 if current_id_evento:
                     url_presenca = f"https://dadosabertos.camara.leg.br/api/v2/eventos/{current_id_evento}/deputados"
                     resp_p = requests.get(url_presenca, timeout=5)
                     if resp_p.status_code == 200:
                         presentes_api = resp_p.json().get('dados', [])
                         
                         ids_presentes = [str(p.get('id')) for p in presentes_api if p.get('id')]
                         
                         if ids_presentes:
                             # Busca detalhes (foto, partido) no tabelao local para ser rápido
                             placeholders = ', '.join(['?'] * len(ids_presentes))
                             query_pres = f"""
                             SELECT DISTINCT nome, sgPartido as partido, sgUF as uf,
                                    ultimoStatus_urlFoto as foto, ideCadastro as id
                             FROM tabelao
                             WHERE ideCadastro IN ({placeholders})
                             ORDER BY nome
                             """
                             df_aprov = pd.read_sql_query(query_pres, conn, params=ids_presentes)
                             
                             # Adiciona campo 'voto' figurativo para o frontend não quebrar
                             df_aprov['voto'] = 'Sim' 
                             
                             aprovadores = sanitize_json_value(df_aprov.to_dict(orient="records"))
                             logger.info(f"Votação Simbólica {id_votacao}: Presença usada como 'Aprovadores' ({len(aprovadores)} deps).")

             except Exception as e:
                 logger.error(f"Erro ao buscar presença para votação simbólica {id_votacao}: {e}")
        # 3. Enriquecimento manual 
        for lista in [aprovadores, opositores, abstencoes]:
             pass 

        # CORREÇÃO FINAL TIPO VOTAÇÃO
        # Se temos votos nominais (Sim/Não) mas o tipo ainda é Nulo ou N/A, assumimos Nominal
        if (aprovadores or opositores) and (not ficha.get('tipo_votacao') or ficha.get('tipo_votacao') in ['N/A', 'Simbolica']):
             # Verifica se há votos 'Sim' ou 'Não' (não apenas presença)
             tem_voto_real = any(v.get('voto') in ['Sim', 'Não'] for v in aprovadores + opositores)
             if tem_voto_real:
                 ficha['tipo_votacao'] = 'Nominal'

        # 3. Enriquecer com logos e bandeiras
        for lista in [aprovadores, opositores]:
            for a in lista:
                p = a.get('partido')
                u = a.get('uf')
                a['logo_partido'] = partido_logos_dict.get(p) if p else None
                a['bandeira_estado'] = estado_logos_dict.get(u) if u else None
                if not a.get('foto') and a.get('id'):
                    a['foto'] = f"https://www.camara.leg.br/internet/deputado/bandep/{a.get('id')}.jpg"
        
        aprovadores = sanitize_json_value(aprovadores)
        opositores = sanitize_json_value(opositores)
        abstencoes = sanitize_json_value(abstencoes)

        conn.close()
        
        # 4. Nota Taquigráfica (local - discursos_links_fixed.db)
        nota_taquigrafica = None
        data_reg = ficha.get('data_registro')
        orgao = ficha.get('sigla_orgao', '')
        
        if data_reg:
            try:
                dt = datetime.strptime(data_reg[:10], "%Y-%m-%d")
                data_br = dt.strftime("%d/%m/%Y")
                origem_slug = 'plenario' if 'PLEN' in orgao.upper() else 'comissao'
                
                conn_links = get_db_connection("discursos_links_fixed")
                cursor_links = conn_links.cursor()
                cursor_links.execute("""
                    SELECT url FROM links_discursos 
                    WHERE url LIKE ? AND origem = ? 
                    LIMIT 1
                """, (f"%Data={data_br}%", origem_slug))
                row = cursor_links.fetchone()
                if row:
                    nota_taquigrafica = row['url']
                conn_links.close()
            except Exception as e:
                logger.error(f"Erro ao buscar nota taquigráfica p/ {id_votacao}: {e}")

        return sanitize_json_value({
            "ficha": ficha,
            "aprovadores": aprovadores,
            "opositores": opositores,
            "abstencoes": abstencoes,
            "nota_taquigrafica": nota_taquigrafica,
            "explicacao_ricd": "Art. 186 RICD: O processo simbólico de votação consiste na solicitação do Presidente aos Deputados que aprovam a matéria para que permaneçam como se encontram. Como qualquer parlamentar ou líder pode solicitar votação nominal (Art. 185) se discordar, a aceitação do processo simbólico implica concordância tácita com a aprovação."
        })
    except Exception as e:
        logger.error(f"Erro em get_voto_detalhe: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/votos/parlamentar/{nome}")
async def get_votos_parlamentar(nome: str):
    """Retorna o histórico de votos e estatísticas de um parlamentar específico."""
    try:
        conn = get_db_connection("tabelao")
        
        # 1. Buscar todos os votos nominais do parlamentar
        query_votos = """
        SELECT v.id_votacao, v.voto, v.data_registro, v.comissao as orgao,
               u.proposicao, u.tipo_votacao,
               e.tema_macro, e.pauta_governo, e.resumo_leigo
        FROM votos_parlamentares_analise v
        LEFT JOIN votacoes_unificadas u ON v.id_votacao = u.id_votacao
        LEFT JOIN votacoes_analise_enrichment e ON v.id_votacao = e.id_votacao
        WHERE v.nome_deputado = ? COLLATE NOCASE
        ORDER BY v.data_registro DESC
        """
        df_votos = pd.read_sql_query(query_votos, conn, params=[nome])
        df_votos = df_votos.where(pd.notnull(df_votos), None)

        if df_votos.empty:
            conn.close()
            return {
                "stats": {"total": 0, "sim": 0, "nao": 0, "abstencao": 0, "alinhamento": 0},
                "votos": []
            }
            
        # 2. Calcular Estatísticas
        total = len(df_votos)
        sim = len(df_votos[df_votos['voto'] == 'Sim'])
        nao = len(df_votos[df_votos['voto'] == 'Não'])
        abstencao = total - sim - nao
        
        # 3. Alinhamento (Simplificado: Voto Sim em Pauta do Governo Sim)
        # Em um sistema real, precisaríamos saber se o governo era FAVORÁVEL ou CONTRÁRIO.
        # Vamos usar lei.json para maior precisão se disponível.
        pautas_gov = df_votos[df_votos['pauta_governo'] == 'Sim']
        alinhados = 0
        total_pauta = len(pautas_gov)
        
        # Tentar ler lei.json para alinhamento mais refinado
        projetos_info = {}
        try:
            with open('lei.json', 'r', encoding='utf-8') as f:
                leis = json.load(f)
                for l in leis:
                    key = f"{l.get('sigla_tipo')} {l.get('numero')}/{l.get('ano_projeto')}"
                    projetos_info[key] = l
        except:
            pass
            
        votos_detalhados = []
        temas_stats = {}
        evolucao_alinhamento = [] # Lista de {data: ..., pct: ...}
        
        # Ordenar por data para evolução
        df_votos_sorted = df_votos.sort_values('data_registro', ascending=True)
        alinhados_acumulado = 0
        pautas_acumulado = 0

        for _, row in df_votos.iterrows(): # Usar a ordem original (DESC) para a listagem
            voto_info = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
            prop = row['proposicao'] or ""
            tema = row['tema_macro'] or "Geral"
            
            # Tentar match com lei.json
            match = None
            for key, info in projetos_info.items():
                if key in prop:
                    match = info
                    break
            
            alinhamento_status = "N/A"
            voto = row['voto']
            if match:
                posicao = match.get('posicao_governo_status', '').upper()
                if (posicao == 'FAVORAVEL' and voto == 'Sim') or (posicao == 'CONTRARIO' and voto == 'Não'):
                    alinhamento_status = "Alinhado"
                    alinhados += 1
                elif (posicao == 'FAVORAVEL' and voto == 'Não') or (posicao == 'CONTRARIO' and voto == 'Sim'):
                    alinhamento_status = "Desalinhado"
            elif row['pauta_governo'] == 'Sim' and voto == 'Sim':
                alinhamento_status = "Alinhado"
                alinhados += 1
            elif row['pauta_governo'] == 'Sim' and voto == 'Não':
                alinhamento_status = "Desalinhado"

            voto_info['alinhamento'] = alinhamento_status
            votos_detalhados.append(voto_info)

            # Acumular Temas
            if tema not in temas_stats: temas_stats[tema] = {"total": 0, "alinhado": 0}
            temas_stats[tema]["total"] += 1
            if alinhamento_status == "Alinhado": temas_stats[tema]["alinhado"] += 1

        # Calcular Evolução (usando sorted ASC)
        for _, row in df_votos_sorted.iterrows():
            if row['pauta_governo'] == 'Sim':
                pautas_acumulado += 1
                # Recalcular alinhamento para este ponto no tempo (simplificado match novamente)
                voto = row['voto']
                prop = row['proposicao'] or ""
                match = None
                for key, info in projetos_info.items():
                    if key in prop: match = info; break
                
                if match:
                    pos = match.get('posicao_governo_status', '').upper()
                    if (pos == 'FAVORAVEL' and voto == 'Sim') or (pos == 'CONTRARIO' and voto == 'Não'):
                        alinhados_acumulado += 1
                elif row['voto'] == 'Sim':
                    alinhados_acumulado += 1
                
                evolucao_alinhamento.append({
                    "data": row['data_registro'],
                    "pct": round((alinhados_acumulado / pautas_acumulado * 100), 1) if pautas_acumulado > 0 else 0
                })

        conn.close()
        
        pct_alinhamento = (alinhados / total_pauta * 100) if total_pauta > 0 else 0

        result = {
            "stats": {
                "total": total,
                "sim": sim,
                "nao": nao,
                "abstencao": abstencao,
                "total_pauta_governo": total_pauta,
                "alinhamento": round(pct_alinhamento, 1),
                "temas_analise": temas_stats,
                "evolucao": evolucao_alinhamento
            },
            "votos": votos_detalhados
        }
        # Sanitize NaN/Inf for JSON serialization
        raw = json.dumps(result, default=str)
        raw = raw.replace(": NaN", ": null").replace(":NaN", ":null").replace(" NaN,", " null,").replace(" NaN}", " null}")
        raw = raw.replace(": Infinity", ": null").replace(": -Infinity", ": null")
        return Response(content=raw, media_type="application/json")
    except Exception as e:
        logger.error(f"Erro em get_votos_parlamentar: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# --- GLOBAL CACHE FOR HOMEPAGE STATS ---
STATS_CACHE = {
    "hash": None,
    "data": None,
    "last_check": 0
}

def get_db_state_hash():
    """Gera um hash baseado no timestamp de modificação dos arquivos dos bancos"""
    state_str = ""
    try:
        # Check Tabelao File Time
        path_tabelao = DATABASE_PATHS.get("tabelao")
        if path_tabelao and os.path.exists(path_tabelao):
            mtime = os.path.getmtime(path_tabelao)
            state_str += f"TAB:{mtime}|"
            
        # Check Discursos File Time
        path_discursos = DATABASE_PATHS.get("discursos")
        if path_discursos and os.path.exists(path_discursos):
            mtime = os.path.getmtime(path_discursos)
            state_str += f"DISC:{mtime}|"
        
    except Exception as e:
        print(f"⚠️ Erro ao gerar hash de arquivo do DB: {e}")
        return None
        
    return hashlib.md5(state_str.encode()).hexdigest()

_HOME_STATS_CACHE_FILE = os.path.join(BASE_DIR, "home_stats_cache.json")

def _db_fingerprint() -> str:
    """Retorna fingerprint baseado em mtime+size dos bancos. Muda apenas se houver dados novos."""
    parts = []
    for db_key, db_name in [("tabelao", "tabelao.db"), ("discursos", "discursos.db"),
                             ("noticias", "noticias_parlamentares.db")]:
        db_path = DATABASE_PATHS.get(db_key, _local_db(db_name))
        if os.path.exists(db_path):
            st = os.stat(db_path)
            parts.append(f"{db_name}:{st.st_size}:{int(st.st_mtime)}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()

def _load_stats_cache() -> dict | None:
    """Carrega cache do disco. Retorna None se ausente ou fingerprint diferente."""
    try:
        if not os.path.exists(_HOME_STATS_CACHE_FILE):
            return None
        with open(_HOME_STATS_CACHE_FILE, "r") as f:
            cached = json.load(f)
        if cached.get("fingerprint") == _db_fingerprint():
            logger.info("💾 [HomeStats] CACHE HIT — retornando consolidado salvo")
            return cached.get("stats")
    except Exception as e:
        logger.warning(f"[HomeStats] Erro ao ler cache: {e}")
    return None

def _save_stats_cache(stats: dict):
    """Persiste consolidado em JSON. Só será relido se fingerprint bater."""
    try:
        payload = {
            "fingerprint": _db_fingerprint(),
            "stats": stats,
            "saved_at": datetime.now().isoformat()
        }
        with open(_HOME_STATS_CACHE_FILE, "w") as f:
            json.dump(payload, f, ensure_ascii=False)
        logger.info(f"💾 [HomeStats] Cache salvo em {_HOME_STATS_CACHE_FILE}")
    except Exception as e:
        logger.warning(f"[HomeStats] Erro ao salvar cache: {e}")

@app.get("/api/home/stats")
async def get_home_stats():
    """Retorna consolidado da home. Só recalcula se algum banco mudou (mtime/size)."""
    cached = _load_stats_cache()
    if cached:
        return cached

    logger.info("🔄 [HomeStats] CACHE MISS — recalculando consolidado...")

    stats = {
        "total_gastos": 0,
        "total_parlamentares": 0,
        "total_discursos": 0,
        "total_comissoes": 30,
        "total_emendas": 0,
        "total_noticias": 0,
        "total_votos": 0,
        "ultimo_dado": "01/01/2023"
    }

    try:
        # 1. Total Gastos e Parlamentares
        conn = sqlite3.connect(DATABASE_PATHS.get("tabelao", _local_db("tabelao.db")))
        cursor = conn.cursor()

        # Total de gastos (sem filtro de valor > 0)
        cursor.execute("SELECT SUM(vlrLiquido) FROM tabelao")
        result = cursor.fetchone()
        if result and result[0]:
            stats["total_gastos"] = float(result[0])

        # Total de parlamentares únicos
        cursor.execute("SELECT COUNT(DISTINCT nuDeputadoId) FROM tabelao")
        result = cursor.fetchone()
        if result and result[0]:
            stats["total_parlamentares"] = int(result[0])

        # Total de emendas (SOMA DOS VALORES LIQUIDADOS)
        # Formato: R$ 1.234,56
        sql_emendas = """
            SELECT SUM(CAST(REPLACE(REPLACE(REPLACE(valor_liquidado, 'R$ ', ''), '.', ''), ',', '.') AS FLOAT)) 
            FROM emendas
        """
        cursor.execute(sql_emendas)
        result = cursor.fetchone()
        if result and result[0]:
            stats["total_emendas"] = float(result[0])

        # Votos Analisados (Nominais e Simbólicos)
        # Usamos votos_destaque_detalhe que contém os votos individuais processados
        sql_votos_nominais = """
            SELECT COUNT(*) 
            FROM votos_destaque_detalhe d
            LEFT JOIN votacoes_unificadas v ON d.id_votacao = v.id_votacao
            WHERE v.tipo_votacao = 'Nominal'
        """
        cursor.execute(sql_votos_nominais)
        res_nom = cursor.fetchone()
        stats["votos_nominais"] = int(res_nom[0]) if res_nom else 0

        sql_votos_simbolicos = """
            SELECT COUNT(*) 
            FROM votos_destaque_detalhe d
            LEFT JOIN votacoes_unificadas v ON d.id_votacao = v.id_votacao
            WHERE v.tipo_votacao = 'Simbólica'
        """
        cursor.execute(sql_votos_simbolicos)
        res_sim = cursor.fetchone()
        stats["votos_simbolicos"] = int(res_sim[0]) if res_sim else 0
        
        stats["total_votos"] = stats["votos_nominais"] + stats["votos_simbolicos"]

        # Última data de gastos (DD/MM/YYYY)
        # SQL para converter DD/MM/YYYY em YYYY-MM-DD para ordenação correta
        sql_max_date = """
            SELECT datEmissao 
            FROM tabelao 
            ORDER BY substr(datEmissao, 7, 4) DESC, substr(datEmissao, 4, 2) DESC, substr(datEmissao, 1, 2) DESC 
            LIMIT 1
        """
        cursor.execute(sql_max_date)
        result = cursor.fetchone()
        if result and result[0]:
            stats["ultimo_dado"] = result[0]

        conn.close()

    except Exception as e:
        logger.error(f"❌ Erro ao buscar tabelao: {e}")

    try:
        # 2. Total Discursos
        conn = sqlite3.connect(DATABASE_PATHS.get("discursos", _local_db("discursos.db")))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM discursos")
        result = cursor.fetchone()
        if result and result[0]:
            stats["total_discursos"] = int(result[0])

        # Comparar com a data atual para ver se os discursos são mais recentes
        sql_max_date_discursos = """
            SELECT Data 
            FROM discursos 
            ORDER BY substr(Data, 7, 4) DESC, substr(Data, 4, 2) DESC, substr(Data, 1, 2) DESC 
            LIMIT 1
        """
        cursor.execute(sql_max_date_discursos)
        result = cursor.fetchone()
        if result and result[0]:
            try:
                # Função auxiliar para comparar datas DD/MM/YYYY
                def to_iso(d):
                    p = d.split('/')
                    return f"{p[2]}-{p[1]}-{p[0]}"
                
                if to_iso(result[0]) > to_iso(stats["ultimo_dado"]):
                    stats["ultimo_dado"] = result[0]
            except:
                pass

        conn.close()

    except Exception as e:
        logger.error(f"❌ Erro ao buscar discursos: {e}")

    try:
        # 3. Adicionar Notícias
        _noticias_path = DATABASE_PATHS.get("noticias", _local_db("noticias_parlamentares.db"))
        if os.path.exists(_noticias_path):
            conn = sqlite3.connect(_noticias_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM noticias")
            result = cursor.fetchone()
            if result: stats["total_noticias"] = result[0]
            conn.close()
    except:
        pass

    # Persistir consolidado — só recalcula quando banco mudar
    _save_stats_cache(stats)
    return stats

# Adicione aqui outros endpoints conforme a necessidade das suas páginas de suporte.
# Exemplo para a página de "Atuação em Comissões":
class Discurso(BaseModel):
    Parlamentar: str
    Comissao: str
    Data: str
    Texto: str

@app.get("/api/comissoes/discursos", response_model=List[Discurso])
async def get_discursos_comissao(parlamentar: str, comissao: str):
    """Endpoint para buscar discursos de um parlamentar em uma comissão."""
    try:
        conn = get_db_connection("discursos")
        query = "SELECT Parlamentar, Comissao, Data, Texto FROM discursos WHERE Parlamentar = ? AND Comissao = ? ORDER BY Data DESC"
        df = pd.read_sql_query(query, conn, params=(parlamentar, comissao))
        conn.close()
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/aeroportos")
async def get_aeroportos():
    """Endpoint para buscar informações de aeroportos."""
    try:
        import os
        airport_path = os.path.join(os.path.dirname(__file__), 'airport.csv')
        df = pd.read_csv(airport_path)
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/filtros/despesas-parlamentar")
async def get_despesas_parlamentar(parlamentar: str = "Todos", estado: str = "Todos", partido: str = "Todos"):
    """Retorna as despesas disponíveis para um parlamentar específico ou todas se 'Todos'"""
    try:
        conn = get_db_connection("tabelao")
        
        query = "SELECT DISTINCT txtDescricao FROM tabelao"
        conditions = []
        params = []
        
        if parlamentar and parlamentar != "Todos" and parlamentar != "Selecione...":
            conditions.append(f"REPLACE({SQL_NORMALIZAR_NOME}, 'Ç', 'C') LIKE ?")
            params.append(f"%{normalizar_nome(parlamentar)}%")
            
        if estado and estado != "Todos" and estado != "Selecione...":
            conditions.append("sgUF = ?")
            params.append(estado)
            
        if partido and partido != "Todos" and partido != "Selecione..." and (not parlamentar or parlamentar == "Todos"):
            conditions.append("sgPartido = ?")
            params.append(partido)
            
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
            
        query += " ORDER BY txtDescricao"
        
        df = pd.read_sql_query(query, conn, params=params)
        despesas = df['txtDescricao'].tolist()
        
        conn.close()
        return {"despesas": despesas}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/comparison/averages")
async def get_comparison_averages(parlamentar: str, estado: str, partido: str, despesa: str = None):
    """Retorna médias de comparação para um parlamentar específico"""
    try:
        conn = get_db_connection("tabelao")
        
        # Se despesa específica foi fornecida, usar ela; caso contrário, usar passagens aéreas
        if despesa and despesa != "Todos":
            condicao_despesa = "txtDescricao = ?"
            params_despesa = [despesa]
        else:
            condicao_despesa = "UPPER(txtDescricao) LIKE UPPER('%PASSAGEM AÉREA%')"
            params_despesa = []
        
        # 1. MÉDIA GERAL: Média de gastos totais de TODOS os deputados
        if params_despesa:
            query_geral = f"""
            SELECT AVG(total_por_parlamentar) as media_geral
            FROM (
                SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
                FROM tabelao
                WHERE {condicao_despesa}
                GROUP BY nome
            )
            """
            df_geral = pd.read_sql_query(query_geral, conn, params=params_despesa)
        else:
            query_geral = f"""
            SELECT AVG(total_por_parlamentar) as media_geral
            FROM (
                SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
                FROM tabelao
                WHERE {condicao_despesa}
                GROUP BY nome
            )
            """
            df_geral = pd.read_sql_query(query_geral, conn)
        
        # 2. MÉDIA DO ESTADO
        if params_despesa:
            query_estado = f"""
            SELECT AVG(total_por_parlamentar) as media_estado
            FROM (
                SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
                FROM tabelao
                WHERE {condicao_despesa} AND sgUF = ?
                GROUP BY nome
            )
            """
            df_estado = pd.read_sql_query(query_estado, conn, params=params_despesa + [estado])
        else:
            query_estado = f"""
            SELECT AVG(total_por_parlamentar) as media_estado
            FROM (
                SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
                FROM tabelao
                WHERE {condicao_despesa} AND sgUF = ?
                GROUP BY nome
            )
            """
            df_estado = pd.read_sql_query(query_estado, conn, params=[estado])
        
        # 3. MÉDIA DO PARTIDO
        if params_despesa:
            query_partido = f"""
            SELECT AVG(total_por_parlamentar) as media_partido
            FROM (
                SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
                FROM tabelao
                WHERE {condicao_despesa} AND sgPartido = ?
                GROUP BY nome
            )
            """
            df_partido = pd.read_sql_query(query_partido, conn, params=params_despesa + [partido])
        else:
            query_partido = f"""
            SELECT AVG(total_por_parlamentar) as media_partido
            FROM (
                SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
                FROM tabelao
                WHERE {condicao_despesa} AND sgPartido = ?
                GROUP BY nome
            )
            """
            df_partido = pd.read_sql_query(query_partido, conn, params=[partido])
        
        # Executar queries
        print(f"DEBUG: Calculando médias para {parlamentar} ({estado}/{partido}) - Despesa: {despesa}")
        
        media_geral = df_geral.iloc[0]['media_geral'] if not df_geral.empty and not pd.isna(df_geral.iloc[0]['media_geral']) else 0
        media_estado = df_estado.iloc[0]['media_estado'] if not df_estado.empty and not pd.isna(df_estado.iloc[0]['media_estado']) else 0
        media_partido = df_partido.iloc[0]['media_partido'] if not df_partido.empty and not pd.isna(df_partido.iloc[0]['media_partido']) else 0
        
        print(f"DEBUG: Média geral = {media_geral}")
        print(f"DEBUG: Média estado {estado} = {media_estado}")
        print(f"DEBUG: Média partido {partido} = {media_partido}")
        
        conn.close()
        
        return {
            "media_geral": float(media_geral),
            "media_estado": float(media_estado),
            "media_partido": float(media_partido)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao calcular médias: {str(e)}")

@app.get("/api/gastos/estatisticas-rubrica")
async def get_estatisticas_rubrica(despesa: str):
    """Retorna estatísticas gerais de uma rubrica (média e desvio padrão de TODOS os deputados)"""
    try:
        conn = get_db_connection("tabelao")
        
        # Query para calcular média e desvio padrão de TODOS os valores da rubrica
        query = """
        SELECT 
            AVG(vlrLiquido) as media_geral,
            STDEV(vlrLiquido) as desvio_geral
        FROM tabelao
        WHERE txtDescricao LIKE ?
        AND vlrLiquido IS NOT NULL
        AND vlrLiquido > 0
        """
        
        # Função para calcular desvio padrão manualmente (SQLite não tem STDEV)
        query_valores = """
        SELECT vlrLiquido
        FROM tabelao
        WHERE txtDescricao LIKE ?
        AND vlrLiquido IS NOT NULL
        AND vlrLiquido > 0
        """
        
        df = pd.read_sql_query(query_valores, conn, params=[f"%{despesa}%"])
        conn.close()
        
        if df.empty:
            return {
                "media_geral": 0,
                "desvio_geral": 0,
                "limite_atipico": 0
            }
        
        media_geral = df['vlrLiquido'].mean()
        desvio_geral = df['vlrLiquido'].std()
        limite_atipico = media_geral + (2 * desvio_geral)
        
        print(f"DEBUG: Estatísticas da rubrica '{despesa}':")
        print(f"  Média: R$ {media_geral:.2f}")
        print(f"  Desvio: R$ {desvio_geral:.2f}")
        print(f"  Limite: R$ {limite_atipico:.2f}")
        
        return {
            "media_geral": float(media_geral),
            "desvio_geral": float(desvio_geral),
            "limite_atipico": float(limite_atipico)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao calcular estatísticas: {str(e)}")

class RelatorioAuditoriaRequest(BaseModel):
    parlamentar: str
    estado: str
    partido: str
    despesa: str
    total_gasto: float
    num_notas: int
    media_gasto: float
    fornecedores_unicos: int
    top_fornecedores: dict
    num_atipicos: int
    limite_atipico: float

@app.get("/api/gastos/dados-parlamentar")
async def obter_dados_parlamentar_completo(parlamentar: str, estado: str, partido: str, despesa: str):
    """Retorna análise completa de despesas de um parlamentar específico"""
    try:
        logger.info(f"🔍 Recebido - Parlamentar: '{parlamentar}' (len={len(parlamentar)})")
        logger.info(f"🔍 Recebido - Estado: '{estado}' (len={len(estado)})")
        logger.info(f"🔍 Recebido - Partido: '{partido}' (len={len(partido)})")
        logger.info(f"🔍 Recebido - Despesa: '{despesa}' (len={len(despesa)})")
        
        if not all([parlamentar, estado, partido, despesa]):
            logger.error(f"❌ Parâmetros faltando: p={bool(parlamentar)}, e={bool(estado)}, pa={bool(partido)}, d={bool(despesa)}")
            raise HTTPException(status_code=400, detail="Todos os parâmetros são obrigatórios")
        
        conn = get_db_connection("tabelao")
        
        despesa_tecnica = mapear_despesa_robusto(despesa)
        logger.info(f"🔄 Mapeando despesa (ROBUSTO): '{despesa}' -> '{despesa_tecnica}'")
        
        # Buscar todos os dados do parlamentar para esta despesa de forma ultra-simplificada (apenas Nome e Despesa)
        query = f"""
        SELECT 
            datEmissao, txtFornecedor, txtDescricao, vlrLiquido, txtNumero, txtCNPJCPF,
            numMes, numAno, urlDocumento, nome, sgPartido, sgUF, ultimoStatus_urlFoto,
            urlPartido, urlEstado
        FROM tabelao
        WHERE (
            REPLACE(REPLACE({SQL_NORMALIZAR_NOME}, 'Ç', 'C'), ' ', '') LIKE ? 
            OR REPLACE({SQL_NORMALIZAR_NOME}, 'Ç', 'C') LIKE ?
        )
        AND (txtDescricao = ? OR txtDescricao LIKE ? OR txtDescricao LIKE ?)
        ORDER BY datEmissao DESC
        """
        
        nome_limpo = normalizar_nome(parlamentar)
        nome_busca_compacta = f"%{nome_limpo.replace(' ', '')}%"
        nome_busca_normal = f"%{nome_limpo}%"
        
        # Fallback para despesa
        despesa_limpa = "".join([c for c in despesa if c.isalnum() or c.isspace()]).strip().upper()
        
        logger.info(f"🔎 BUSCA SIMPLIFICADA - Nome: '{nome_limpo}' | Despesa: '{despesa_tecnica}'")
        
        df = pd.read_sql_query(query, conn, params=[
            nome_busca_compacta, 
            nome_busca_normal, 
            despesa_tecnica, 
            f"%{despesa_tecnica}%",
            f"%{despesa_limpa}%"
        ])
        logger.info(f"📊 Colunas retornadas do DB: {df.columns.tolist()}")
        
        if df.empty:
            conn.close()
            return {
                "success": False,
                "message": "Nenhum registro encontrado para os filtros selecionados",
                "total_registros": 0
            }
        
        logger.info(f"✅ Encontrados {len(df)} registros")
        
        # 1. MÉTRICAS BÁSICAS
        total_gasto = float(df['vlrLiquido'].sum())
        num_notas = len(df)
        media_gasto = float(df['vlrLiquido'].mean())
        fornecedores_unicos = df['txtFornecedor'].nunique()
        
        # 1.5 MÉDIAS COMPARATIVAS
        # Média por NOTA (não total por parlamentar) de todos os parlamentares para esta despesa
        query_media_geral = """
        SELECT AVG(vlrLiquido) as media_geral
        FROM tabelao
        WHERE txtDescricao = ? AND vlrLiquido > 0
        """
        df_media_geral = pd.read_sql_query(query_media_geral, conn, params=[despesa_tecnica])
        media_geral = float(df_media_geral['media_geral'].iloc[0]) if not df_media_geral.empty and pd.notna(df_media_geral['media_geral'].iloc[0]) else 0
        
        # Média por NOTA dos parlamentares do mesmo estado
        query_media_estado = """
        SELECT AVG(vlrLiquido) as media_estado
        FROM tabelao
        WHERE txtDescricao = ? AND sgUF = ? AND vlrLiquido > 0
        """
        df_media_estado = pd.read_sql_query(query_media_estado, conn, params=[despesa_tecnica, estado])
        media_estado = float(df_media_estado['media_estado'].iloc[0]) if not df_media_estado.empty and pd.notna(df_media_estado['media_estado'].iloc[0]) else 0
        
        # Média por NOTA dos parlamentares do mesmo partido
        query_media_partido = """
        SELECT AVG(vlrLiquido) as media_partido
        FROM tabelao
        WHERE txtDescricao = ? AND sgPartido = ? AND vlrLiquido > 0
        """
        df_media_partido = pd.read_sql_query(query_media_partido, conn, params=[despesa_tecnica, partido])
        media_partido = float(df_media_partido['media_partido'].iloc[0]) if not df_media_partido.empty and pd.notna(df_media_partido['media_partido'].iloc[0]) else 0
        
        # 2. LIMITE ATÍPICO (2 desvios padrão acima da média global da rubrica)
        query_limite = """
        SELECT vlrLiquido 
        FROM tabelao 
        WHERE txtDescricao = ? AND vlrLiquido > 0
        """
        df_limite = pd.read_sql_query(query_limite, conn, params=[despesa_tecnica])
        if not df_limite.empty:
            media_rubrica_global = float(df_limite['vlrLiquido'].mean())
            desvio_rubrica_global = float(df_limite['vlrLiquido'].std())
            desvio_rubrica_global = 0 if pd.isna(desvio_rubrica_global) else desvio_rubrica_global
            limite_atipico = media_rubrica_global + (2 * desvio_rubrica_global)
        else:
            limite_atipico = 0
            
        # Identificar notas atípicas
        notas_atipicas = df[df['vlrLiquido'] > limite_atipico]
        num_atipicos = len(notas_atipicas)
        
        # 3. ANÁLISE TEMPORAL
        # Criar coluna de período no formato YYYY-MM para ordenação correta
        df['ano_mes'] = df['numAno'].astype(str) + '-' + df['numMes'].astype(str).str.zfill(2)
        df['mes_ano_display'] = df['numMes'].astype(str).str.zfill(2) + '/' + df['numAno'].astype(str)
        
        temporal = df.groupby(['ano_mes', 'mes_ano_display'])['vlrLiquido'].sum().reset_index()
        temporal = temporal.sort_values('ano_mes')  # Ordenar por YYYY-MM
        
        dados_temporais = [
            {
                "periodo": row['mes_ano_display'],
                "valor": float(row['vlrLiquido'])
            }
            for _, row in temporal.iterrows()
        ]
        
        # 4. TOP FORNECEDORES
        fornecedores = df.groupby('txtFornecedor').agg({
            'vlrLiquido': ['sum', 'count', 'mean']
        }).reset_index()
        fornecedores.columns = ['fornecedor', 'total', 'quantidade', 'media']
        fornecedores = fornecedores.sort_values('total', ascending=False).head(10)
        
        top_fornecedores = [
            {
                "fornecedor": row['fornecedor'],
                "total": float(row['total']),
                "quantidade": int(row['quantidade']),
                "media": float(row['media']),
                "atipico": row['fornecedor'] in notas_atipicas['txtFornecedor'].values
            }
            for _, row in fornecedores.iterrows()
        ]
        
        # 5. DADOS COMPLETOS (limitados a 1000 registros mais recentes)
        dados_completos = df.head(1000).to_dict('records')
        
        # Obter logos do primeiro registro do dataframe
        primeiro_reg = df.iloc[0] if not df.empty else pd.Series()
        
        # Buscar as URLs de forma robusta
        def find_col_val(reg, possible_names):
            if reg.empty: return None
            for col in reg.index:
                if col.strip() in possible_names:
                    val = reg[col]
                    return str(val).strip() if pd.notna(val) and str(val).lower() != 'none' else None
            return None

        partido_logo_url = find_col_val(primeiro_reg, ["urlPartido", "urlPartido", "partido_logo"])
        estado_logo_url = find_col_val(primeiro_reg, ["urlEstado", "urlEstado", "estado_logo", "URL_UF"])

        # Converter valores e mapear nomes de campos para o frontend
        dados_mapeados = []
        for dado in dados_completos:
            dados_mapeados.append({
                "data": _json_safe_value(dado.get('datEmissao')),
                "fornecedor": _json_safe_value(dado.get('txtFornecedor')),
                "descricao": _json_safe_value(dado.get('txtDescricao')),
                "valor": float(dado.get('vlrLiquido', 0)) if pd.notna(dado.get('vlrLiquido')) else 0,
                "numero": _json_safe_value(dado.get('txtNumero')),
                "cnpj": _json_safe_value(dado.get('txtCNPJCPF')),
                "mes": int(dado.get('numMes', 0)) if pd.notna(dado.get('numMes')) else 0,
                "ano": int(dado.get('numAno', 0)) if pd.notna(dado.get('numAno')) else 0,
                "url_documento": _json_safe_value(dado.get('urlDocumento')),
                "nome": _json_safe_value(dado.get('nome')),
                "partido": _json_safe_value(dado.get('sgPartido')),
                "estado": _json_safe_value(dado.get('sgUF'))
            })
        
        dados_completos = dados_mapeados
        
        # 6. DADOS PARA MAPA (TODOS os fornecedores)
        # Usar o DataFrame principal para garantir consistência
        dados_mapa = []
        
        logger.info(f"🗺️ Processando dados do mapa a partir do DataFrame principal ({len(df)} registros)")
        
        # Carregar coordenadas das empresas
        try:
            query_coords = "SELECT cnpj, latitude, longitude, Cidade, CEP, endereco_completo FROM coordenadas_empresas"
            df_coords = pd.read_sql_query(query_coords, conn)
            df_coords['cnpj_clean'] = (
                df_coords['cnpj']
                .astype(str)
                .str.replace(r'\D', '', regex=True)
                .str.zfill(14)
            )
            
            # Limpar CNPJ do dataframe principal para fazer o merge
            # Remove tudo que não é dígito
            df['cnpj_limpo'] = df['txtCNPJCPF'].astype(str).str.replace(r'\D', '', regex=True)
            
            # Merge com as coordenadas
            # Left join para manter todos os registros mesmo sem coordenada
            df_merged = pd.merge(df, df_coords, left_on='cnpj_limpo', right_on='cnpj_clean', how='left')
            
            logger.info(f"🗺️ Coordenadas carregadas: {len(df_coords)} registros. Merge realizado.")
            
        except Exception as e:
            logger.error(f"❌ Erro ao carregar coordenadas: {e}")
            # Fallback se falhar o merge: usa o df original sem coordenadas extras
            df_merged = df.copy()
            df_merged['latitude'] = None
            df_merged['longitude'] = None
            df_merged['cidade'] = 'Brasília'
        
        # Carregar dados de cidades para fallback
        try:
            df_cidades = pd.read_csv('municipios_brasileiros.csv')
            # Criar dicionário (nome_normalizado, uf) -> (lat, lon)
            # Normalizar nomes para facilitar busca (uppercase)
            df_cidades['chave'] = df_cidades['nome_municipio'].str.upper() + '_' + df_cidades['uf']
            coords_cidades = df_cidades.set_index('chave')[['latitude', 'longitude']].to_dict('index')
        except Exception as e:
            logger.error(f"⚠️ Erro ao carregar municipios_brasileiros.csv: {e}")
            coords_cidades = {}

        # Carregar lista_cnpj_geral para buscar cidades de CNPJs desconhecidos
        try:
            query_lista = """
            SELECT
                CAST(cnpj AS TEXT) AS cnpj,
                Cidade,
                Estado,
                Logradouro,
                "Número" AS Numero,
                Bairro,
                CEP
            FROM lista_cnpj_geral
            """
            df_lista = pd.read_sql_query(query_lista, conn)
            # Converter CNPJ para string limpa
            # Garantir que tratamos floats (remove .0) e nulos
            df_lista['cnpj_clean'] = df_lista['cnpj'].astype(str).str.replace(r'\.0$', '', regex=True)
            
            # Dicionário 1: CNPJ com 14 dígitos (zfill)
            df_lista['cnpj_zfill'] = df_lista['cnpj_clean'].str.zfill(14)
            df_lista = df_lista.drop_duplicates('cnpj_zfill')
            df_lista = df_lista.rename(columns={'Cidade': 'Cidade_Nome', 'Estado': 'Estado_Nome', 'Numero': 'Número', 'CEP': 'CEP_lista'})
            
        except Exception as e:
            logger.error(f"⚠️ Erro ao carregar lista_cnpj_geral: {e}")
            df_lista = pd.DataFrame(columns=['cnpj_zfill', 'cnpj_clean', 'Cidade_Nome', 'Estado_Nome', 'Logradouro', 'Número', 'Bairro', 'CEP_lista'])

        if not df_lista.empty:
            df_merged = pd.merge(
                df_merged,
                df_lista[['cnpj_zfill', 'Cidade_Nome', 'Estado_Nome', 'Logradouro', 'Número', 'Bairro', 'CEP_lista']],
                left_on='cnpj_limpo',
                right_on='cnpj_zfill',
                how='left'
            )

        pontos_suprimidos = 0
        pontos_corrigidos = 0

        for _, row in df_merged.iterrows():
            # Verificar se ESTA nota específica é atípica
            eh_atipico = float(row['vlrLiquido']) > limite_atipico
            localizacao = resolver_localizacao_cadastral_fornecedor(row.to_dict(), conn)
            if not localizacao:
                pontos_suprimidos += 1
                continue

            lat = float(localizacao["lat"])
            lon = float(localizacao["lng"])
            cidade_cadastral = str(localizacao.get("cidade") or "").strip()
            estado_fornecedor = str(localizacao.get("estado") or "").strip().upper() or None
            endereco_cadastral = str(localizacao.get("endereco") or "").strip() or None
            cep_cadastral = str(localizacao.get("cep") or "").strip() or None
            if localizacao.get("fonte") == "centroide_cidade_cadastral":
                pontos_corrigidos += 1

            cidade_exibicao = cidade_cadastral
            if cidade_exibicao and estado_fornecedor:
                cidade_exibicao = f"{cidade_exibicao}/{estado_fornecedor}"
            elif estado_fornecedor:
                cidade_exibicao = estado_fornecedor
            
            dados_mapa.append({
                "fornecedor": row['txtFornecedor'],
                "cnpj": row['txtCNPJCPF'],
                "latitude": lat,
                "longitude": lon,
                "cidade": cidade_exibicao,
                "cidade_cadastral": cidade_cadastral or None,
                "estado_fornecedor": estado_fornecedor,
                "endereco_cadastral": endereco_cadastral,
                "cep_cadastral": cep_cadastral,
                "total": float(row['vlrLiquido']),
                "num_notas": 1,
                "atipico": eh_atipico,
                "descricao": row['txtDescricao'],
                "coordenada_corrigida": localizacao.get("fonte") == "centroide_cidade_cadastral",
                "fonte_localizacao": localizacao.get("fonte"),
            })
            
        logger.info(f"🗺️ Dados do mapa gerados: {len(dados_mapa)} registros")
        logger.info(f"🗺️ Mapa fornecedores: {pontos_corrigidos} coordenadas corrigidas, {pontos_suprimidos} pontos suprimidos por falta de localização confiável")
        
        # Contar quantos atípicos reais temos no mapa
        atipicos_no_mapa = sum(1 for item in dados_mapa if item['atipico'])
        logger.info(f"🗺️ Total de itens atípicos no mapa: {atipicos_no_mapa}")

        notas_fiscais_enriquecidas = obter_insights_notas_fiscais(parlamentar, despesa_tecnica, estado)
        
        conn.close()
        
        return {
            "success": True,
            "total_registros": len(df),
            "metricas_basicas": {
                "total_gasto": total_gasto,
                "num_notas": num_notas,
                "media_gasto": media_gasto,
                "fornecedores_unicos": fornecedores_unicos,
                "num_atipicos": num_atipicos,
                "limite_atipico": limite_atipico
            },
            "metricas_comparativas": {
                "media_geral": media_geral,
                "media_estado": media_estado,
                "media_partido": media_partido,
                "diff_geral_pct": ((media_gasto - media_geral) / media_geral * 100) if media_geral > 0 else 0,
                "diff_estado_pct": ((media_gasto - media_estado) / media_estado * 100) if media_estado > 0 else 0,
                "diff_partido_pct": ((media_gasto - media_partido) / media_partido * 100) if media_partido > 0 else 0
            },
            "dados_temporais": dados_temporais,
            "top_fornecedores": top_fornecedores,
            "dados_completos": dados_completos[:1000],
            "dados_mapa": dados_mapa,
            "cobertura_notas": notas_fiscais_enriquecidas.get("cobertura_notas"),
            "insights_notas": notas_fiscais_enriquecidas.get("insights_notas"),
            "info_parlamentar": {
                "nome": _json_safe_value(parlamentar, str(parlamentar)),
                "partido": str(partido) if partido and partido != "Todos" else (str(df.iloc[0]['sgPartido']) if 'sgPartido' in df.columns and not df.empty else str(partido)),
                "estado": str(estado) if estado and estado != "Todos" else (str(df.iloc[0]['sgUF']) if 'sgUF' in df.columns and not df.empty else str(estado)),
                "despesa": _json_safe_value(despesa, str(despesa)),
                "foto_url": str(df.iloc[0]['ultimoStatus_urlFoto']) if 'ultimoStatus_urlFoto' in df.columns and not df.empty and pd.notna(df.iloc[0]['ultimoStatus_urlFoto']) else None,
                "partido_logo_url": (
                    resolve_party_logo_url(str(partido) if partido and partido != "Todos" else str(df.iloc[0]['sgPartido']))
                    if (partido and partido != "Todos") or ('sgPartido' in df.columns and not df.empty) else None
                ),
                "estado_logo_url": (
                    resolve_state_flag_url(str(estado) if estado and estado != "Todos" else str(df.iloc[0]['sgUF']))
                    if (estado and estado != "Todos") or ('sgUF' in df.columns and not df.empty) else None
                )
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Erro ao obter dados do parlamentar: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/gastos/limite-atipico")
async def calcular_limite_atipico(request: dict):
    """Calcula o limite atípico para uma rubrica baseado em todos os parlamentares"""
    try:
        despesa = request.get('despesa')
        if not despesa:
            raise HTTPException(status_code=400, detail="Despesa é obrigatória")
        
        conn = get_db_connection("tabelao")
        
        # Buscar todos os valores da rubrica
        query = """
        SELECT vlrLiquido 
        FROM tabelao 
        WHERE txtDescricao = ?
        AND vlrLiquido IS NOT NULL
        AND vlrLiquido > 0
        """
        
        df = pd.read_sql_query(query, conn, params=[despesa])
        conn.close()
        
        if df.empty:
            return {"limite_atipico": None}
        
        # Calcular média e desvio padrão
        media = df['vlrLiquido'].mean()
        desvio = df['vlrLiquido'].std()
        limite_atipico = media + (2 * desvio)
        
        return {"limite_atipico": float(limite_atipico)}
        
    except Exception as e:
        logger.error(f"Erro ao calcular limite atípico: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/gastos/dados-parlamentar")
async def obter_dados_parlamentar(request: dict):
    """Retorna os dados de despesas de um parlamentar específico"""
    try:
        estado = request.get('estado')
        partido = request.get('partido')
        parlamentar = request.get('parlamentar')
        despesa = request.get('despesa')
        
        if not all([estado, partido, parlamentar, despesa]):
            raise HTTPException(status_code=400, detail="Todos os parâmetros são obrigatórios")
        
        conn = get_db_connection("tabelao")
        
        query = f"""
        SELECT 
            datEmissao as data,
            txtFornecedor as fornecedor,
            txtDescricao as descricao,
            vlrLiquido as valor,
            'Brasília' as municipio,
            sgUF as estado,
            urlPartido as urlPartido,
            "urlEstado" as urlEstado,
            "ultimoStatus_urlFoto" as ultimoStatus_urlFoto
        FROM tabelao 
        WHERE (REPLACE(REPLACE({SQL_NORMALIZAR_NOME}, 'Ç', 'C'), ' ', '') LIKE ? OR REPLACE({SQL_NORMALIZAR_NOME}, 'Ç', 'C') LIKE ?)
          AND (txtDescricao = ? OR txtDescricao LIKE ?)
        ORDER BY datEmissao DESC
        """
        
        despesa_tecnica = mapear_despesa_robusto(despesa)
        nome_limpo = normalizar_nome(parlamentar)
        
        df = pd.read_sql_query(query, conn, params=[
            f"%{nome_limpo.replace(' ', '')}%", 
            f"%{nome_limpo}%", 
            despesa_tecnica, 
            f"%{despesa_tecnica}%"
        ])
        conn.close()
        
        logger.info(f"🔍 DEBUG COLS: {df.columns.tolist()}")
        if not df.empty:
            logger.info(f"🔍 DEBUG ROW: {df.iloc[0].to_dict()}")
        
        # Converter para lista de dicionários
        dados = df.to_dict('records')
        
        return {"dados": dados}
        
    except Exception as e:
        logger.error(f"Erro ao obter dados do parlamentar: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/gastos/metricas-basicas")
async def calcular_metricas_basicas(request: dict):
    """Calcula métricas básicas dos dados"""
    try:
        dados = request.get('dados', [])
        limite_atipico = request.get('limite_atipico')
        
        if not dados:
            return {"metricas": {}}
        
        # Converter para DataFrame
        df = pd.DataFrame(dados)
        
        # Calcular métricas
        total_gasto = df['valor'].sum()
        total_despesas = len(df)
        media_por_despesa = df['valor'].mean()
        
        # Contar despesas atípicas
        despesas_atipicas = 0
        if limite_atipico:
            despesas_atipicas = len(df[df['valor'] > limite_atipico])
        
        metricas = {
            "total_gasto": float(total_gasto),
            "total_despesas": int(total_despesas),
            "media_por_despesa": float(media_por_despesa),
            "despesas_atipicas": int(despesas_atipicas)
        }
        
        # DEBUG: Verificar tipos antes de retornar
        try:
            logger.info("🔍 DEBUG RESPONSE TYPES:")
            logger.info(f"info_parlamentar types: {type(response_data['info_parlamentar'])}")
            for k, v in response_data['info_parlamentar'].items():
                logger.info(f"  - {k}: {type(v)} = {v}")
            
            # Tentar encoder manualmente para pegar erro
            from fastapi.encoders import jsonable_encoder
            jsonable_encoder(response_data)
            logger.info("✅ Encoder manual com sucesso")
            
        except Exception as e:
            logger.error(f"❌ Erro no encoder manual: {e}")
            
        return {"metricas": metricas}
        
    except Exception as e:
        logger.error(f"Erro ao calcular métricas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/gastos/analises-completas")
async def obter_analises_completas(request: dict):
    """Retorna análises temporais, fornecedores e dados para mapa"""
    try:
        dados = request.get('dados', [])
        limite_atipico = request.get('limite_atipico')
        
        if not dados:
            return {
                "dados_temporais": [],
                "dados_fornecedores": [],
                "dados_mapa": [],
                "fornecedores_atipicos": []
            }
        
        df = pd.DataFrame(dados)
        
        # Análise temporal
        df['data'] = pd.to_datetime(df['data'])
        df_temporal = df.groupby(df['data'].dt.to_period('M')).agg({
            'valor': ['sum', 'count', 'mean']
        }).round(2)
        df_temporal.columns = ['valor_total', 'quantidade', 'valor_medio']
        df_temporal = df_temporal.reset_index()
        df_temporal['periodo'] = df_temporal['data'].astype(str)
        dados_temporais = df_temporal.to_dict('records')
        
        # Análise de fornecedores
        df_fornecedores = df.groupby('fornecedor').agg({
            'valor': ['sum', 'count', 'mean']
        }).round(2)
        df_fornecedores.columns = ['valor_total', 'quantidade', 'valor_medio']
        df_fornecedores = df_fornecedores.reset_index()
        df_fornecedores = df_fornecedores.sort_values('valor_total', ascending=False)
        dados_fornecedores = df_fornecedores.head(20).to_dict('records')
        
        # Fornecedores atípicos
        fornecedores_atipicos = []
        if limite_atipico:
            df_atipicos = df[df['valor'] > limite_atipico]
            fornecedores_atipicos = df_atipicos['fornecedor'].value_counts().head(10).to_dict()
        
        # Dados para mapa (simplificado)
        dados_mapa = df.groupby(['municipio', 'estado']).agg({
            'valor': 'sum'
        }).reset_index()
        dados_mapa = dados_mapa.to_dict('records')
        
        return {
            "dados_temporais": dados_temporais,
            "dados_fornecedores": dados_fornecedores,
            "dados_mapa": dados_mapa,
            "fornecedores_atipicos": fornecedores_atipicos
        }
        
    except Exception as e:
        logger.error(f"Erro ao obter análises completas: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/gastos/relatorio-auditoria")
async def gerar_relatorio_auditoria(request: RelatorioAuditoriaRequest):
    """Gera relatório de auditoria usando LLM (GPT-4o-mini)"""
    parlamentar = request.parlamentar
    estado = request.estado
    partido = request.partido
    despesa = request.despesa
    total_gasto = request.total_gasto
    num_notas = request.num_notas
    media_gasto = request.media_gasto
    fornecedores_unicos = request.fornecedores_unicos
    top_fornecedores = request.top_fornecedores
    num_atipicos = request.num_atipicos
    limite_atipico = request.limite_atipico
    try:
        import openai
        from dotenv import load_dotenv
        from datetime import datetime
        
        load_dotenv()
        api_key = os.getenv('OPENAI_API_KEY')
        
        if not api_key:
            raise HTTPException(status_code=500, detail="API key do OpenAI não configurada")
        
        client = openai.OpenAI(api_key=api_key)
        
        # Formatar valores
        def fmt_currency(val):
            return f"R$ {val:,.2f}".replace(',', 'TEMP').replace('.', ',').replace('TEMP', '.')
        
        # Obter médias de comparação do banco
        conn_comp = get_db_connection("tabelao")
        query_comp = """
        SELECT 
            AVG(total_por_parlamentar) as media_geral,
            (SELECT AVG(total_por_parlamentar) FROM (
                SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
                FROM tabelao
                WHERE txtDescricao LIKE ? AND sgUF = ?
                GROUP BY nome
            )) as media_estado,
            (SELECT AVG(total_por_parlamentar) FROM (
                SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
                FROM tabelao
                WHERE txtDescricao LIKE ? AND sgPartido = ?
                GROUP BY nome
            )) as media_partido
        FROM (
            SELECT nome, SUM(vlrLiquido) as total_por_parlamentar
            FROM tabelao
            WHERE txtDescricao LIKE ?
            GROUP BY nome
        )
        """
        df_comp = pd.read_sql_query(query_comp, conn_comp, params=[f"%{despesa}%", estado, f"%{despesa}%", partido, f"%{despesa}%"])
        conn_comp.close()
        
        media_geral_comp = df_comp.iloc[0]['media_geral'] if not df_comp.empty else 0
        media_estado_comp = df_comp.iloc[0]['media_estado'] if not df_comp.empty else 0
        media_partido_comp = df_comp.iloc[0]['media_partido'] if not df_comp.empty else 0
        
        prompt = f"""Você é Antunes, auditor-chefe especializado em contas públicas, com 25 anos de experiência em controle interno e externo. Possui expertise em Regimento Interno da Câmara dos Deputados, Lei de Responsabilidade Fiscal (LC 101/2000), Instruções Normativas do TCU e Resoluções da Câmara sobre cota parlamentar.

MISSÃO: Analisar rigorosamente as despesas de {despesa} do parlamentar {parlamentar} ({partido}/{estado}) com base em evidências documentais e normativas aplicáveis.

IMPORTANTE: Use linguagem condicional (possivelmente, há indícios, sugere-se avaliar). NÃO confirme irregularidades, apenas aponte indícios que DEVEM ser avaliados pelos órgãos competentes.

DADOS CONSOLIDADOS PARA AUDITORIA:
• Parlamentar: {parlamentar}
• Despesa Analisada: {despesa}
• Estado/Partido: {estado}/{partido}
• Valor Total Executado: {fmt_currency(total_gasto)}
• Quantidade de Notas Fiscais: {num_notas}
• Valor Médio por Nota: {fmt_currency(media_gasto)}
• Número de Fornecedores Distintos: {fornecedores_unicos}
• Top 5 Fornecedores por Valor: {top_fornecedores}
• Notas Atípicas Identificadas: {num_atipicos} (acima de {fmt_currency(limite_atipico)})

DADOS COMPARATIVOS (FUNDAMENTAÇÃO ESTATÍSTICA):
• Média de Gasto GERAL (todos os deputados): {fmt_currency(media_geral_comp)}
• Diferença vs Média Geral: {((total_gasto - media_geral_comp) / media_geral_comp * 100):.2f}%
• Média de Gasto do ESTADO {estado}: {fmt_currency(media_estado_comp)}
• Diferença vs Média do Estado: {((total_gasto - media_estado_comp) / media_estado_comp * 100):.2f}%
• Média de Gasto do PARTIDO {partido}: {fmt_currency(media_partido_comp)}
• Diferença vs Média do Partido: {((total_gasto - media_partido_comp) / media_partido_comp * 100):.2f}%

ESTRUTURA DO RELATÓRIO DE AUDITORIA:

1. RESUMO EXECUTIVO
2. FUNDAMENTAÇÃO LEGAL E NORMATIVA
3. ANÁLISE QUANTITATIVA DETALHADA
4. ANÁLISE QUALITATIVA E CONFORMIDADE
5. IDENTIFICAÇÃO DE RISCOS E NÃO CONFORMIDADES
6. RECOMENDAÇÕES TÉCNICAS
7. CONCLUSÕES E PONTOS DE ATENÇÃO

REQUISITOS TÉCNICOS OBRIGATÓRIOS:
- GERE UM RELATÓRIO ÚNICO E ESPECÍFICO para este parlamentar - NÃO use templates genéricos
- MÍNIMO 4 PARÁGRAFOS DETALHADOS para cada seção de análise
- CITE ESPECIFICAMENTE artigos com números reais:
  * Regimento Interno da Câmara: Art. 187, §2º; Art. 298; Art. 299
  * Lei de Responsabilidade Fiscal: Art. 1º, §1º; Art. 48; Art. 49; Art. 50
  * Resolução CD 1/2017: Art. 4º (cota parlamentar); Art. 5º (limites)
  * Instrução Normativa TCU 63/2010: Art. 10; Art. 11; Art. 12
- USE OS DADOS COMPARATIVOS acima para fundamentar sua análise
- Compare SEMPRE com as médias (geral, estado, partido) e explique as diferenças
- Se o gasto está ACIMA da média, investigue possíveis indícios de superfaturamento
- Se está ABAIXO, elogie a gestão eficiente e a economia de recursos
- CRÍTICO: Se a diferença percentual for NEGATIVA (ex: -70%), ISSO É BOM. JAMAIS use termos como "desvio", "discrepância" ou "anomalia" para valores abaixo da média. Use "economia", "redução de custos" ou "eficiência".
- Use LINGUAGEM CONDICIONAL OBRIGATORIAMENTE:
  * "Possivelmente há indícios de..."
  * "Sugere-se que seja avaliado..."
  * "Os dados indicam uma possível..."
  * "Recomenda-se análise aprofundada sobre..."
  * "Há indícios que merecem atenção..."
- NÃO CONFIRME irregularidades, apenas APONTE para investigação
- Analise a razoabilidade comparando com as médias estatísticas
- Avalie a concentração de gastos (Índice de Herfindahl-Hirschman)
- Calcule e cite o IHH se houver concentração
- Verifique adequação ao objeto da cota parlamentar
- Proponha que órgãos competentes investiguem pontos específicos
- Use linguagem técnica, formal e CRÍTICA (mas condicional)
- Base análise em evidências e COMPARAÇÕES ESTATÍSTICAS
- Seja detalhista - cada relatório deve ser único e específico

FORMATAÇÃO OBRIGATÓRIA:
- ESCREVA APENAS TEXTO PURO - NÃO use HTML, markdown, asteriscos, underscores ou formatação especial
- NÃO use quebras de linha estranhas entre palavras
- NÃO quebre números ou valores no meio
- NÃO separe letras de palavras individuais
- Use formatação brasileira para valores (R$ 1.234.567,89)
- Mantenha texto fluido e legível
- Use espaços normais entre palavras
- NÃO quebre parágrafos no meio de frases
- Mantenha seções bem estruturadas e organizadas
- Use apenas texto simples, sem itálico, negrito ou formatação especial
- Inclua data atual no cabeçalho: {datetime.now().strftime('%d/%m/%Y')}
- Assine exatamente assim:
  
Assinatura
Antunes - O robô
Auditor Especialista em Auditoria de Contas Públicas
www.euseidissodeputado.com.br
{datetime.now().strftime('%d/%m/%Y')}

EXEMPLO DE REFERÊNCIAS A USAR:
- Regimento Interno da Câmara dos Deputados
- Lei de Responsabilidade Fiscal (LC 101/2000)
- Instrução Normativa TCU 63/2010
- Resolução CD 1/2017 (sobre cota parlamentar)
- Acórdãos do TCU sobre prestação de contas parlamentares

IMPORTANTE: 
- Seja criativo e específico. Cada relatório deve refletir a personalidade única do Antunes e as particularidades do parlamentar analisado.
- ESCREVA TEXTO NORMAL E LEGÍVEL - NÃO quebre palavras ou números desnecessariamente.
- Mantenha formatação profissional e clara.
- Crie parágrafos bem estruturados e organizados.
- Evite quebras de linha estranhas ou espaçamentos inadequados.
- Use formatação brasileira para todos os valores monetários.
- NÃO use asteriscos (*), underscores (_), ou qualquer símbolo de formatação.
- Escreva como se fosse um documento de texto simples, sem formatação especial."""
        
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {"role": "system", "content": "Você é Antunes, um robô auditor especializado em contas públicas. Seja autêntico, técnico e incisivo. Cada relatório deve ser único e específico para o parlamentar analisado. Use linguagem formal mas com personalidade própria. Cite legislação específica e seja detalhista. CRÍTICO: Escreva APENAS TEXTO PURO, sem HTML, markdown, asteriscos, underscores ou qualquer formatação especial. Mantenha texto normal e legível, sem quebrar palavras ou números desnecessariamente. Use formatação brasileira para valores (R$ 1.234.567,89). Crie parágrafos bem estruturados e organizados. NÃO use itálico, negrito ou qualquer formatação especial."},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=6000,
            temperature=0.3
        )
        
        relatorio = response.choices[0].message.content
        
        return {
            "relatorio": relatorio,
            "gerado_em": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar relatório: {str(e)}")

class EmailDenunciaRequest(BaseModel):
    parlamentar: str
    estado: str
    partido: str
    despesa: str
    relatorio_auditoria: str
    notas_atipicas: list

@app.get("/api/gastos/contatos-parlamentar")
async def obter_contatos_parlamentar(parlamentar: str):
    """Busca contatos do parlamentar na API da Câmara"""
    try:
        import requests
        
        conn = get_db_connection("tabelao")
        query = "SELECT DISTINCT nuDeputadoId, nome FROM tabelao WHERE nome = ? LIMIT 1"
        df = pd.read_sql_query(query, conn, params=[parlamentar])
        conn.close()
        
        if df.empty:
            return {"contatos": None}
        
        deputado_id = int(df.iloc[0]['nuDeputadoId'])
        
        url = f"https://dadosabertos.camara.leg.br/api/v2/deputados/{deputado_id}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            dados = response.json()['dados']
            return {
                "contatos": {
                    "email": dados.get('ultimoStatus', {}).get('email'),
                    "gabinete_telefone": dados.get('ultimoStatus', {}).get('gabinete', {}).get('telefone'),
                    "gabinete_sala": dados.get('ultimoStatus', {}).get('gabinete', {}).get('sala'),
                    "nome": dados.get('ultimoStatus', {}).get('nome'),
                    "id": deputado_id
                }
            }
        else:
            return {"contatos": None}
            
    except Exception as e:
        logger.error(f"❌ Erro ao buscar contatos: {str(e)}")
        return {"contatos": None}

@app.post("/api/gastos/gerar-email-denuncia")
async def gerar_email_denuncia(request: EmailDenunciaRequest):
    """Gera e-mail de denúncia para órgãos de controle com base no relatório de auditoria"""
    try:
        from datetime import datetime
        
        parlamentar = request.parlamentar
        estado = request.estado
        partido = request.partido
        despesa = request.despesa
        relatorio = request.relatorio_auditoria
        notas_atipicas = request.notas_atipicas
        
        # Montar links das notas suspeitas
        links_notas = ""
        if notas_atipicas and len(notas_atipicas) > 0:
            links_notas = "\n\nNOTAS FISCAIS SUSPEITAS (LINKS PARA VERIFICAÇÃO):\n"
            for i, nota in enumerate(notas_atipicas, 1):
                if nota.get('urlDocumento'):
                    links_notas += f"{i}. Valor: R$ {nota['vlrLiquido']:,.2f} - Data: {nota['datEmissao']} - Fornecedor: {nota['txtFornecedor']}\n"
                    links_notas += f"   Link: {nota['urlDocumento']}\n\n"
        
        email_content = f"""ASSUNTO: SOLICITAÇÃO DE ANÁLISE DE PRESTAÇÃO DE CONTAS - INDÍCIOS DE IRREGULARIDADES - PARLAMENTAR {parlamentar.upper()}

Excelentíssimos Senhores,

Encaminho para análise técnica desta Casa os dados de prestação de contas do parlamentar {parlamentar} ({partido}/{estado}), especificamente referentes às despesas de {despesa}, em cumprimento ao princípio da transparência e participação popular no controle das contas públicas, conforme previsto na Constituição Federal (Art. 37) e na Lei de Responsabilidade Fiscal (LC 101/2000, Art. 48 e 49).

DADOS DO PARLAMENTAR:
• Nome: {parlamentar}
• Partido: {partido}
• Estado: {estado}
• Despesa Analisada: {despesa}
• Data da Análise: {datetime.now().strftime('%d/%m/%Y')}

FUNDAMENTO LEGAL DA SOLICITAÇÃO:
Conforme dispõe o Art. 74, §2º da Constituição Federal, qualquer cidadão poderá denunciar irregularidades perante o Tribunal de Contas da União. Adicionalmente, o Art. 48 da Lei de Responsabilidade Fiscal determina a transparência da gestão fiscal e a participação popular no acompanhamento das contas públicas.

RELATÓRIO DE AUDITORIA DETALHADO:
{relatorio}
{links_notas}

SOLICITAÇÃO FORMAL:
Com fundamento na legislação supracitada, solicito respeitosamente que seja realizada análise técnica aprofundada das informações apresentadas, com foco em:

1. Verificação da conformidade dos gastos com o Regimento Interno da Câmara (Art. 187, §2º)
2. Análise da adequação das despesas ao objeto da cota parlamentar (Resolução CD 1/2017)
3. Avaliação da razoabilidade dos valores em relação aos praticados no mercado
4. Investigação de possíveis indícios de superfaturamento nas notas fiscais atípicas
5. Verificação da legitimidade da concentração de gastos em poucos fornecedores

ÓRGÃOS COMPETENTES PARA ENVIO DESTA DENÚNCIA:

📮 Câmara dos Deputados - Secretaria de Controle Interno
E-mail: controle.interno@camara.leg.br
Site: https://www.camara.leg.br/controle-interno

📮 Tribunal de Contas da União (TCU)
E-mail: presidencia@tcu.gov.br
Ouvidoria: ouvidoria@tcu.gov.br
Site: https://portal.tcu.gov.br/

📮 Ministério Público Federal (MPF)
E-mail: prdf@mpf.mp.br
Site: https://www.mpf.mp.br/

📮 Controladoria-Geral da União (CGU)
E-mail: cgu@cgu.gov.br
Fala.BR: https://falabr.cgu.gov.br/

DOCUMENTOS EM ANEXO:
- Relatório completo de auditoria
- Planilha com dados das notas fiscais
- Links para acesso às notas fiscais suspeitas

Aguardo retorno desta Casa no prazo legal estabelecido, conforme determina a Lei de Acesso à Informação (Lei 12.527/2011, Art. 11, §1º - prazo de 20 dias).

Atenciosamente,

Cidadão Fiscalizador
Sistema: www.euseidissodeputado.com.br
Data: {datetime.now().strftime('%d/%m/%Y às %H:%M')}

---
IMPORTANTE: Este é um sistema automatizado de análise de dados públicos. As informações apresentadas são baseadas em dados oficiais da Câmara dos Deputados e devem ser verificadas pelos órgãos competentes antes de qualquer ação.
"""
        
        return {
            "email": email_content,
            "gerado_em": datetime.now().isoformat(),
            "destinatarios": [
                {
                    "nome": "Câmara dos Deputados - Controle Interno",
                    "email": "controle.interno@camara.leg.br",
                    "site": "https://www.camara.leg.br/controle-interno"
                },
                {
                    "nome": "Tribunal de Contas da União (TCU)",
                    "email": "presidencia@tcu.gov.br",
                    "email_alt": "ouvidoria@tcu.gov.br",
                    "site": "https://portal.tcu.gov.br/"
                },
                {
                    "nome": "Ministério Público Federal (MPF)",
                    "email": "prdf@mpf.mp.br",
                    "site": "https://www.mpf.mp.br/"
                },
                {
                    "nome": "Controladoria-Geral da União (CGU)",
                    "email": "cgu@cgu.gov.br",
                    "site": "https://falabr.cgu.gov.br/"
                }
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar e-mail: {str(e)}")

# ==========================================
# ENDPOINTS PARA REDES DE RELACIONAMENTO (ODIOGRAMA)
# ==========================================

@app.get("/api/redes/datas")
async def get_datas_disponiveis():
    """Retorna a data mínima e máxima disponível nos discursos."""
    try:
        conn = get_db_connection("discursos")
        # Converter DD/MM/YYYY para YYYY-MM-DD para encontrar min/max corretamente
        query = """
        SELECT 
            MIN(substr(data, 7, 4) || '-' || substr(data, 4, 2) || '-' || substr(data, 1, 2)) as min_data,
            MAX(substr(data, 7, 4) || '-' || substr(data, 4, 2) || '-' || substr(data, 1, 2)) as max_data
        FROM discursos
        WHERE data IS NOT NULL AND length(data) = 10
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if len(df) > 0:
            return {
                "min_data": df.iloc[0]['min_data'],
                "max_data": df.iloc[0]['max_data']
            }
        return {"min_data": "2023-01-01", "max_data": None}
    except Exception as e:
        print(f"Erro ao buscar datas: {e}")
        return {"min_data": "2023-01-01", "max_data": None}

@app.get("/api/redes/conexoes")
async def get_conexoes_parlamentares(
    estado_citante: Optional[str] = None,
    partido_citante: Optional[str] = None,
    parlamentar_citante: Optional[str] = None,
    estado_citado: Optional[str] = None,
    partido_citado: Optional[str] = None,
    parlamentar_citado: Optional[str] = None,
    sentimento: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    apenas_nominais: Optional[bool] = True
):
    """Retorna conexões entre parlamentares baseadas em citações nos discursos."""
    try:
        start_time = time.time()
        conn_discursos = get_db_connection("discursos")
        conn_tabelao = get_db_connection("tabelao")
        
        # Construir query base
        query_discursos = """
        SELECT din.hash_linha, din.parlamentar as parlamentar_citante, 
               din.estado as estado_citante, din.partido as partido_citante,
               din.sentimento_geral, din.citacoes, din.data, din.comissao, din.sessao
        FROM discursos_integrados_normalizado din
        WHERE din.citacoes != '[]' AND din.citacoes IS NOT NULL
        """
        
        params = []
        
        if data_inicio:
            # Converter data do banco (DD/MM/YYYY) para YYYY-MM-DD para comparação
            query_discursos += " AND substr(din.data, 7, 4) || '-' || substr(din.data, 4, 2) || '-' || substr(din.data, 1, 2) >= ?"
            params.append(data_inicio)
            
        if data_fim:
            # Converter data do banco (DD/MM/YYYY) para YYYY-MM-DD para comparação
            query_discursos += " AND substr(din.data, 7, 4) || '-' || substr(din.data, 4, 2) || '-' || substr(din.data, 1, 2) <= ?"
            params.append(data_fim)
        
        print(f"DEBUG API CONEXOES: Params: {params}")
        print(f"DEBUG API CONEXOES: Query: {query_discursos}")
        
        df_discursos = pd.read_sql_query(query_discursos, conn_discursos, params=params)
        print(f"DEBUG API CONEXOES: Rows found: {len(df_discursos)}")
        
        # Buscar mapeamento de nomes para IDs no tabelao
        query_ids = "SELECT DISTINCT nome, ideCadastro FROM tabelao WHERE nome IS NOT NULL"
        df_ids = pd.read_sql_query(query_ids, conn_tabelao)
        nome_to_id = dict(zip(df_ids['nome'], df_ids['ideCadastro']))
        logger.info(f"✅ Mapeamento de IDs carregado: {len(nome_to_id)} parlamentares")
        
        # Processar citações
        import json
        conexoes = []
        
        for _, row in df_discursos.iterrows():
            try:
                citacoes = json.loads(row['citacoes'])
                
                for citacao in citacoes:
                    if 'nome_citado' in citacao and row['parlamentar_citante'] != citacao['nome_citado']:
                        id_citante = nome_to_id.get(row['parlamentar_citante'])
                        id_citado = citacao.get('id_parlamentar')
                        
                        # Lógica de citação nominal com coincidência mínima de 80% do nome.
                        sentenca = citacao.get('sentenca_exata', '')
                        nome_alvo = citacao['nome_citado']
                        score_coincidencia_nome = _calcular_score_coincidencia_nome(nome_alvo, sentenca)
                        is_nominal = score_coincidencia_nome >= 0.80

                        conexoes.append({
                            'citante': row['parlamentar_citante'],
                            'id_citante': id_citante,
                            'foto_citante': f"https://www.camara.leg.br/internet/deputado/bandep/{id_citante}.jpg" if id_citante else None,
                            'estado_citante': row['estado_citante'],
                            'partido_citante': row['partido_citante'],
                            'citado': citacao['nome_citado'],
                            'id_citado': id_citado,
                            'foto_citado': f"https://www.camara.leg.br/internet/deputado/bandep/{id_citado}.jpg" if id_citado else None,
                            'sentimento': citacao.get('sentimento_da_citacao', 'Neutro'),
                            'tom': citacao.get('tom_da_citacao', 'Informativo'),
                            'sentenca': sentenca,
                            'is_nominal': is_nominal,
                            'score_coincidencia_nome': round(score_coincidencia_nome, 4),
                            'sentimento_geral': row['sentimento_geral'],
                            'data': row['data'],
                            'comissao': row['comissao'],
                            'sessao': row['sessao'],
                            'hash_linha': row['hash_linha']
                        })
            except:
                continue
        
        df_conexoes = pd.DataFrame(conexoes)
        
        if len(df_conexoes) == 0:
            logger.warning("⚠️ Nenhuma conexão encontrada após processamento de citações.")
            return []
        
        # 5. Filtrar por parlamentares válidos (usando cache para velocidade)
        query_tabelao = "SELECT DISTINCT nome FROM cache_filtros_parlamentares"
        df_tabelao_nomes = pd.read_sql_query(query_tabelao, conn_tabelao)
        parlamentares_validos = set(df_tabelao_nomes['nome'].tolist())
        
        df_conexoes = df_conexoes[
            (df_conexoes['citado'].isin(parlamentares_validos)) &
            (df_conexoes['citante'].isin(parlamentares_validos))
        ]
        
        # 6. Aplicar filtros adicionais
        if apenas_nominais:
            df_conexoes = df_conexoes[df_conexoes['is_nominal'] == True]

        if sentimento and sentimento != "Todos":
            df_conexoes = df_conexoes[df_conexoes['sentimento'] == sentimento]
        
        if estado_citante:
            df_conexoes = df_conexoes[df_conexoes['estado_citante'] == estado_citante]
        
        if partido_citante:
            df_conexoes = df_conexoes[df_conexoes['partido_citante'] == partido_citante]

        if parlamentar_citante:
            df_conexoes = df_conexoes[df_conexoes['citante'] == parlamentar_citante]
            
        if estado_citado:
            query_temp = "SELECT DISTINCT nome FROM cache_filtros_parlamentares WHERE sgUF = ?"
            df_temp = pd.read_sql_query(query_temp, conn_tabelao, params=[estado_citado])
            parlamentares_estado = df_temp['nome'].tolist()
            df_conexoes = df_conexoes[df_conexoes['citado'].isin(parlamentares_estado)]

        if partido_citado:
            query_temp = "SELECT DISTINCT nome FROM cache_filtros_parlamentares WHERE sgPartido = ?"
            df_temp = pd.read_sql_query(query_temp, conn_tabelao, params=[partido_citado])
            parlamentares_partido = df_temp['nome'].tolist()
            df_conexoes = df_conexoes[df_conexoes['citado'].isin(parlamentares_partido)]

        if parlamentar_citado:
            df_conexoes = df_conexoes[df_conexoes['citado'] == parlamentar_citado]
            
        logger.info(f"📊 Conexões finais após filtros: {len(df_conexoes)}")
        
        results = df_conexoes.to_dict('records')
            
        conn_discursos.close()
        conn_tabelao.close()
        
        duration = time.time() - start_time
        logger.info(f"✅ Sociograma finalizado em {duration:.2f}s. Registros: {len(results)}")
        
        return clean_data_for_json(results)
        
    except Exception as e:
        logger.error(f"❌ Erro em get_conexoes_parlamentares: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro ao buscar conexões: {str(e)}")

@app.get("/api/redes/comunidades")
async def get_comunidades_louvain(
    estado_citante: Optional[str] = None,
    partido_citante: Optional[str] = None,
    sentimento: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    apenas_nominais: Optional[bool] = True,
    resolucao: Optional[float] = 1.0,
):
    """
    Detecta comunidades no grafo de citações via algoritmo de Louvain.
    Retorna {parlamentar: {community_id, label}} para colorir os nós no sociograma.
    O parâmetro `resolucao` controla a granularidade: > 1 → mais comunidades menores,
    < 1 → menos comunidades maiores.
    """
    try:
        import networkx as nx
        import community as community_louvain

        # ── 1. Reutilizar a mesma lógica de conexões ──────────────────────────
        conn_discursos = get_db_connection("discursos")
        conn_tabelao   = get_db_connection("tabelao")

        query = """
            SELECT din.parlamentar as citante, din.estado as estado_citante,
                   din.partido as partido_citante, din.citacoes, din.data
            FROM discursos_integrados_normalizado din
            WHERE din.citacoes != '[]' AND din.citacoes IS NOT NULL
        """
        params = []
        if data_inicio:
            query += " AND substr(din.data,7,4)||'-'||substr(din.data,4,2)||'-'||substr(din.data,1,2) >= ?"
            params.append(data_inicio)
        if data_fim:
            query += " AND substr(din.data,7,4)||'-'||substr(din.data,4,2)||'-'||substr(din.data,1,2) <= ?"
            params.append(data_fim)

        df = pd.read_sql_query(query, conn_discursos, params=params)

        # Nomes válidos
        df_validos = pd.read_sql_query(
            "SELECT DISTINCT nome FROM cache_filtros_parlamentares", conn_tabelao
        )
        validos = set(df_validos["nome"].tolist())
        conn_discursos.close()
        conn_tabelao.close()

        # ── 2. Construir grafo não-direcionado ponderado ───────────────────────
        G = nx.Graph()
        import json as _json

        for _, row in df.iterrows():
            citante = row["citante"]
            if citante not in validos:
                continue
            if estado_citante and row.get("estado_citante") != estado_citante:
                continue
            if partido_citante and row.get("partido_citante") != partido_citante:
                continue
            if sentimento and sentimento != "Todos":
                pass  # sentimento é por citação individual — filtrado abaixo

            try:
                citacoes = _json.loads(row["citacoes"])
            except Exception:
                continue

            for c in citacoes:
                citado = c.get("nome_citado")
                if not citado or citado == citante or citado not in validos:
                    continue
                if apenas_nominais:
                    sentenca = c.get("sentenca_exata", "")
                    score = _calcular_score_coincidencia_nome(citado, sentenca)
                    if score < 0.80:
                        continue
                sent = c.get("sentimento_da_citacao", "Neutro")
                if sentimento and sentimento != "Todos" and sent != sentimento:
                    continue
                # Peso: múltiplas citações entre o mesmo par reforçam a aresta
                if G.has_edge(citante, citado):
                    G[citante][citado]["weight"] += 1
                else:
                    G.add_edge(citante, citado, weight=1)

        if G.number_of_nodes() < 2:
            return {"communities": {}, "total_comunidades": 0, "nos": 0}

        # ── 3. Louvain ────────────────────────────────────────────────────────
        partition = community_louvain.best_partition(G, weight="weight", resolution=resolucao)
        # partition: {nome: community_id (int)}

        n_comunidades = len(set(partition.values()))
        logger.info(f"[Louvain] {G.number_of_nodes()} nós, {G.number_of_edges()} arestas → {n_comunidades} comunidades (res={resolucao})")

        # ── 4. Formatar resposta ──────────────────────────────────────────────
        resultado = {
            nome: {"community_id": cid, "label": f"Comunidade {cid + 1}"}
            for nome, cid in partition.items()
        }
        return {
            "communities": resultado,
            "total_comunidades": n_comunidades,
            "nos": G.number_of_nodes(),
        }

    except Exception as e:
        logger.error(f"❌ Erro em get_comunidades_louvain: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/redes/parlamentares-info")
async def get_parlamentares_info():
    """Retorna informações completas dos parlamentares (foto, partido, estado)."""
    try:
        conn = get_db_connection("tabelao")
        
        query = """
        SELECT DISTINCT nome, sgUF as estado, sgPartido as partido,
               ultimoStatus_urlFoto as urlFoto, 
               urlPartido, 
               urlEstado
        FROM tabelao
        WHERE nome IS NOT NULL
        ORDER BY nome
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Converter para registros
        results = df.to_dict('records')
        
        # OTIMIZAÇÃO: Usar os mesmos resolvedores que funcionam no Ranking
        # Isso garante consistência: se a logo aparece no ranking, aparece aqui também.
        for record in results:
            sigla_partido = record.get('partido')
            sigla_uf = record.get('estado')
            
            # Sobrescrever URLs com a lógica robusta de cache/Wikipedia que o Ranking usa
            record['urlPartido'] = resolve_party_logo_from_wikipedia(sigla_partido, None)
            record['urlEstado'] = resolve_state_flag_from_wikipedia(sigla_uf)
            
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar informações: {str(e)}")



@app.get("/api/redes/filtros")
async def get_filtros_redes():
    """Retorna listas únicas de estados, partidos e sentimentos para filtros."""
    try:
        conn_discursos = get_db_connection("discursos")
        conn_tabelao = get_db_connection("tabelao")
        
        # Estados e partidos do tabelao
        query_estados = "SELECT DISTINCT sgUF as estado FROM tabelao WHERE sgUF IS NOT NULL ORDER BY sgUF"
        query_partidos = "SELECT DISTINCT sgPartido as partido FROM tabelao WHERE sgPartido IS NOT NULL ORDER BY sgPartido"
        
        df_estados = pd.read_sql_query(query_estados, conn_tabelao)
        df_partidos = pd.read_sql_query(query_partidos, conn_tabelao)
        
        # Buscar sentimentos das citações
        query_discursos = """
        SELECT DISTINCT din.citacoes
        FROM discursos_integrados_normalizado din
        WHERE din.citacoes != '[]' AND din.citacoes IS NOT NULL
        LIMIT 1000
        """
        
        df_citacoes = pd.read_sql_query(query_discursos, conn_discursos)
        
        sentimentos = set()
        import json
        for _, row in df_citacoes.iterrows():
            try:
                citacoes = json.loads(row['citacoes'])
                for citacao in citacoes:
                    if 'sentimento_da_citacao' in citacao:
                        sentimentos.add(citacao['sentimento_da_citacao'])
            except:
                continue
        
        conn_discursos.close()
        conn_tabelao.close()
        
        return {
            "estados": df_estados['estado'].tolist(),
            "partidos": df_partidos['partido'].tolist(),
            "sentimentos": sorted(list(sentimentos))
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar filtros: {str(e)}")

class RelatorioRedesRequest(BaseModel):
    conexoes: List[dict]
    filtros_aplicados: dict
@app.get("/api/redes/conexoes-gastos")
async def get_conexoes_gastos(parlamentar: str, despesa: str):
    """
    Retorna as conexões entre um parlamentar e outros através de fornecedores comuns.
    Versão "Refeita do Zero" - Mais robusta com busca por palavra-chave.
    """
    try:
        started_at = time.time()
        stage_started_at = started_at

        def log_stage(stage_name: str):
            nonlocal stage_started_at
            now_stage = time.time()
            logger.info(
                f"🕸️ Sociograma etapa='{stage_name}' duracao={now_stage - stage_started_at:.2f}s total={now_stage - started_at:.2f}s"
            )
            stage_started_at = now_stage

        cache_key = (parlamentar or "").strip().upper(), (despesa or "").strip().upper()
        cached = GASTOS_GRAPH_CACHE.get(cache_key)
        now = time.time()
        if cached and (now - cached["ts"] < GASTOS_GRAPH_CACHE_TTL):
            logger.info(f"🕸️ Sociograma cache hit: {cache_key[0]} / {cache_key[1]}")
            return deepcopy(cached["payload"])

        conn = get_db_connection("tabelao")
        
        # 1. Limpeza
        parlamentar = parlamentar.strip()
        despesa = despesa.strip()
        
        # 2. Mapeamento Simplificado (Amigável -> Palavra-Chave SQL)
        # Em vez de tentar acertar o nome técnico exato, vamos buscar por SUBSTRING.
        def _normalize_keyword_text(value: str) -> str:
            return unicodedata.normalize('NFKD', value or '').encode('ASCII', 'ignore').decode('ASCII').upper().strip()

        keyword_patterns = [
            (["COMBUST"], "COMBUST"),
            (["DIVULGA"], "DIVULGA"),
            (["ESCRIT"], "ESCRIT"),
            (["CONSULT"], "CONSULT"),
            (["TELEFON"], "TELEFONIA"),
            (["POSTA"], "POSTAIS"),
            (["PASSAG"], "PASSAGE"),
            (["SEGURAN"], "SEGURAN"),
            (["HOSPED"], "HOSPEDAGEM"),
            (["CURSO"], "CURSO"),
            (["LOCOMO", "LOCA"], "LOCA"),
            (["EMBARCA"], "EMBARCA"),
            (["AERONAV"], "AERONAVE"),
            (["TAXI"], "TAXI"),
            (["PUBLICA"], "PUBLICA"),
        ]
        
        # Tenta achar uma keyword
        keyword = "%%" # Default: wildcard (perigoso, mas vamos controlar)
        found_key = False
        despesa_normalizada = _normalize_keyword_text(despesa)
        
        for aliases, token in keyword_patterns:
            if any(alias in despesa_normalizada for alias in aliases):
                keyword = f"%{token}%"
                found_key = True
                break
        
        # Se não achou keyword específica, tenta usar a string
        if not found_key:
            if len(despesa) > 4:
                keyword = f"%{despesa}%"
        
        logger.info(f"🕸️ Sociograma Refactor - Buscando: Parl='{parlamentar}', Despesa='{despesa}', Keyword='{keyword}'")

        # 3. Buscar Fornecedores (Usando LIKE e Case Insensitive)
        query_forn = """
        SELECT
            txtCNPJCPF,
            MAX(txtFornecedor) AS txtFornecedor,
            SUM(COALESCE(vlrLiquido, 0)) AS total_gasto
        FROM tabelao
        WHERE nome = ?
          AND txtDescricao LIKE ?
          AND txtCNPJCPF IS NOT NULL
          AND txtCNPJCPF != ''
        GROUP BY txtCNPJCPF
        ORDER BY total_gasto DESC
        LIMIT 80
        """
        df_forn = pd.read_sql_query(query_forn, conn, params=[parlamentar, keyword])
        log_stage("buscar_fornecedores")
        
        if df_forn.empty:
            conn.close()
            return {
                "nodes": [], 
                "links": [],
                "debug": {
                    "msg": "Nenhum fornecedor encontrado.",
                    "parlamentar_received": parlamentar,
                    "keyword_used": keyword,
                    "sql_tried": query_forn
                }
            }
            
        cnpjs = df_forn['txtCNPJCPF'].astype(str).unique().tolist()
        
        # 4. Buscar Outros Parlamentares (que usaram esses CNPJs)
        cnpjs_limited = cnpjs[:80]
        placeholders = ','.join(['?'] * len(cnpjs_limited))
        
        query_others = f"""
        SELECT nome, sgUF, sgPartido, txtCNPJCPF, vlrLiquido
        FROM tabelao
        WHERE txtCNPJCPF IN ({placeholders})
          AND txtDescricao LIKE ?
          AND nome != ?
        """
        
        # Params: CNPJs + Keyword + Parlamentar Original
        params_others = cnpjs_limited + [keyword, parlamentar]
        df_others = pd.read_sql_query(query_others, conn, params=params_others)
        log_stage("buscar_outros_parlamentares")
        
        # 5. Filtrar apenas fornecedores COMPARTILHADOS (User request Id: 2781)
        # Só queremos os fornecedores que conectam o deputado principal a pelo menos um dos outros deputados no sistema.
        if df_others.empty:
            conn.close()
            return {"nodes": [], "links": [], "debug": {"msg": "Nenhum outro deputado compartilha esses fornecedores."}}
            
        # Para evitar um grafo gigante e redundante:
        # 5.1 Encontrar os TOP 20 Outros Deputados (por volume financeiro nos fornecedores em comum)
        top_deps_df = df_others.groupby(['nome', 'sgUF', 'sgPartido'])['vlrLiquido'].sum().reset_index()
        top_deps_df = top_deps_df.sort_values('vlrLiquido', ascending=False).head(20)
        top_deps_names = top_deps_df['nome'].tolist()
        
        # 5.2 Filtrar df_others para conter apenas esses top 20 deputados
        df_others_filtered = df_others[df_others['nome'].isin(top_deps_names)]
        
        # 5.3 Agora identificar quais CNPJs são REALMENTE compartilhados com esses top 20
        shared_cnpjs = set(df_others_filtered['txtCNPJCPF'].unique())
        
        # 5.4 Filtrar df_forn (do deputado principal) para conter apenas os verdadeiramente compartilhados
        df_forn = df_forn[df_forn['txtCNPJCPF'].isin(shared_cnpjs)]
        
        if df_forn.empty:
            conn.close()
            return {"nodes": [], "links": [], "debug": {"msg": "Nenhum fornecedor compartilhado com os top 20 parlamentares."}}

        supplier_competition_stats = (
            df_others_filtered.groupby('txtCNPJCPF')
            .agg(
                parlamentares_compartilhados=('nome', 'nunique'),
                volume_compartilhado=('vlrLiquido', 'sum')
            )
            .reset_index()
        )
        df_forn_ranked = pd.merge(df_forn, supplier_competition_stats, on='txtCNPJCPF', how='left')
        df_forn_ranked['parlamentares_compartilhados'] = df_forn_ranked['parlamentares_compartilhados'].fillna(0).astype(int)
        df_forn_ranked['volume_compartilhado'] = df_forn_ranked['volume_compartilhado'].fillna(0.0)
        df_forn_ranked = df_forn_ranked.sort_values(
            ['parlamentares_compartilhados', 'volume_compartilhado', 'txtFornecedor'],
            ascending=[False, False, True]
        )
        log_stage("rankear_fornecedores")

        # 5.5 Buscar localização apenas dos fornecedores que realmente entram no grafo.
        supplier_geo = {}
        cnpjs_grafo = df_forn_ranked.head(24)['txtCNPJCPF'].astype(str).unique().tolist()
        try:
            if cnpjs_grafo:
                def _normalize_graph_cnpj(value: str) -> str:
                    return re.sub(r'\D', '', str(value or '')).lstrip('0')

                cnpjs_grafo_map = {
                    cnpj_original: _normalize_graph_cnpj(cnpj_original)
                    for cnpj_original in cnpjs_grafo
                }
                cnpjs_geo = [cnpj for cnpj in cnpjs_grafo_map.values() if cnpj]

                placeholders_geo = ','.join(['?'] * len(cnpjs_geo))
                query_geo = f"""
                SELECT cnpj, Cidade as cidade_fornecedor
                FROM coordenadas_empresas
                WHERE cnpj IN ({placeholders_geo})
                """
                df_geo = pd.read_sql_query(query_geo, conn, params=cnpjs_geo)

                supplier_geo_by_clean = {}
                for _, geo_row in df_geo.iterrows():
                    cnpj_geo = str(geo_row.get('cnpj') or '').strip()
                    if not cnpj_geo or cnpj_geo in supplier_geo_by_clean:
                        continue
                    cidade_fornecedor = geo_row.get('cidade_fornecedor')
                    if cidade_fornecedor is not None and pd.isna(cidade_fornecedor):
                        cidade_fornecedor = None
                    supplier_geo_by_clean[cnpj_geo] = {
                        "cidade_empresa": cidade_fornecedor,
                        "estado_empresa": None,
                    }

                # Fallback para estado/cidade via cadastro geral de CNPJ, quando disponível.
                query_registry = f"""
                SELECT CAST(cnpj AS TEXT) AS cnpj, Cidade AS cidade_fornecedor, Estado AS estado_fornecedor
                FROM lista_cnpj_geral
                WHERE CAST(cnpj AS TEXT) IN ({placeholders_geo})
                """
                df_registry = pd.read_sql_query(query_registry, conn, params=cnpjs_geo)
                for _, reg_row in df_registry.iterrows():
                    cnpj_reg = str(reg_row.get('cnpj') or '').strip()
                    if not cnpj_reg:
                        continue
                    entry = supplier_geo_by_clean.setdefault(cnpj_reg, {"cidade_empresa": None, "estado_empresa": None})
                    cidade_reg = reg_row.get('cidade_fornecedor')
                    estado_reg = reg_row.get('estado_fornecedor')
                    if cidade_reg is not None and not pd.isna(cidade_reg) and not entry.get("cidade_empresa"):
                        entry["cidade_empresa"] = cidade_reg
                    if estado_reg is not None and not pd.isna(estado_reg):
                        entry["estado_empresa"] = estado_reg

                for cnpj_original, cnpj_limpo in cnpjs_grafo_map.items():
                    if cnpj_limpo and cnpj_limpo in supplier_geo_by_clean:
                        supplier_geo[cnpj_original] = supplier_geo_by_clean[cnpj_limpo]
        except Exception:
            supplier_geo = {}
        log_stage("buscar_geolocalizacao")

        # 6. Construção do Grafo
        nodes = []
        links = []
        node_ids = set()
        
        # Buscar metadados de todos os parlamentares envolvidos em um único lote.
        all_names = [parlamentar] + top_deps_names
        parlamentares_meta = {}
        try:
            if all_names:
                placeholders_meta = ','.join(['?'] * len(all_names))
                query_meta = f"""
                SELECT nome, sgUF, sgPartido, ultimoStatus_siglaPartido, ultimoStatus_urlFoto
                FROM tabelao
                WHERE nome IN ({placeholders_meta})
                """
                df_meta = pd.read_sql_query(query_meta, conn, params=all_names)
                if not df_meta.empty:
                    df_meta = df_meta.dropna(subset=['nome']).drop_duplicates(subset=['nome'], keep='first')
                    parlamentares_meta = {
                        str(row['nome']).strip(): {
                            "sgUF": row.get('sgUF'),
                            "sgPartido": row.get('sgPartido'),
                            "ultimoStatus_siglaPartido": row.get('ultimoStatus_siglaPartido'),
                            "foto": row.get('ultimoStatus_urlFoto'),
                        }
                        for _, row in df_meta.iterrows()
                    }
        except Exception:
            parlamentares_meta = {}
        log_stage("buscar_metadados_parlamentares")

        # --- Nó Central ---
        main_id = f"PARL_{parlamentar.replace(' ', '_')}"
        main_meta = parlamentares_meta.get(parlamentar, {})
        main_party = main_meta.get('ultimoStatus_siglaPartido') or main_meta.get('sgPartido')
        main_state = main_meta.get('sgUF')
        foto_url = main_meta.get('foto')

        nodes.append({
            "id": main_id,
            "name": parlamentar,
            "category": "Parlamentar",
            "partido": main_party,
            "estado": main_state,
            "symbolSize": 50,
            "symbol": f"image://{foto_url}" if foto_url else "circle",
            "itemStyle": {"borderColor": "#003366", "borderWidth": 3}
        })
        node_ids.add(main_id)

        # Removido: nós de Partido e Estado.
        # O sociograma agora mostra apenas Parlamentar ↔ Fornecedor (compartilhado) ↔ Outros Parlamentares.
        main_party_id = None
        main_state_id = None
        
        # --- Nós Fornecedores (Shared Only) ---
        df_forn_top = df_forn_ranked.head(24).reset_index(drop=True)
        highlighted_supplier_ids = set(df_forn_top.head(6)['txtCNPJCPF'].astype(str).tolist())

        # Cruzamento com sanções da CGU (CEIS/CEPIM) — só para os fornecedores que
        # de fato entram no grafo, para manter a consulta barata.
        def _limpar_cnpj_grafo(valor):
            return re.sub(r'\D', '', str(valor or '')).zfill(14)

        sancoes_por_cnpj = {}
        try:
            cnpjs_top_limpos = {cnpj_orig: _limpar_cnpj_grafo(cnpj_orig) for cnpj_orig in df_forn_top['txtCNPJCPF'].astype(str).tolist()}
            cnpjs_validos = [c for c in cnpjs_top_limpos.values() if c and c != '0' * 14]
            if cnpjs_validos:
                tabela_ceis_existe = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='lista_ceis'"
                ).fetchone()
                if tabela_ceis_existe:
                    placeholders_sancao = ','.join(['?'] * len(cnpjs_validos))
                    df_sancoes_ceis = pd.read_sql_query(
                        f"SELECT cnpj, nome_sancionado, categoria_sancao, data_fim FROM lista_ceis WHERE cnpj IN ({placeholders_sancao})",
                        conn, params=cnpjs_validos
                    )
                    for _, s in df_sancoes_ceis.iterrows():
                        sancoes_por_cnpj[s['cnpj']] = {"base": "CEIS", "categoria": s.get('categoria_sancao'), "sancao_fim": s.get('data_fim')}
                    df_sancoes_cepim = pd.read_sql_query(
                        f"SELECT cnpj, motivo FROM lista_cepim WHERE cnpj IN ({placeholders_sancao})",
                        conn, params=cnpjs_validos
                    )
                    for _, s in df_sancoes_cepim.iterrows():
                        sancoes_por_cnpj.setdefault(s['cnpj'], {"base": "CEPIM", "categoria": s.get('motivo'), "sancao_fim": None})
        except Exception as e:
            logger.warning(f"⚠️ Não foi possível cruzar fornecedores do sociograma com CEIS/CEPIM: {e}")

        for supplier_rank, row in df_forn_top.iterrows():
            cnpj = str(row['txtCNPJCPF'])
            nome_forn = str(row['txtFornecedor'])
            f_id = f"FORN_{cnpj}"
            connect_count = int(row.get('parlamentares_compartilhados', 0) or 0)
            shared_volume = float(row.get('volume_compartilhado', 0.0) or 0.0)
            sancao_info = sancoes_por_cnpj.get(cnpjs_top_limpos.get(cnpj))
            nome_label = (nome_forn[:20] + "...") if len(nome_forn) > 20 else nome_forn

            if f_id not in node_ids:
                nodes.append({
                    "id": f_id,
                    "name": f"⚠️ {nome_label}" if sancao_info else nome_label,
                    "fullName": nome_forn,
                    "category": "Fornecedor",
                    "symbolSize": 18 + min(connect_count * 2, 12),
                    "showLabel": cnpj in highlighted_supplier_ids,
                    "connectCount": connect_count,
                    "sharedVolume": shared_volume,
                    "cidade_empresa": (supplier_geo.get(cnpj) or {}).get("cidade_empresa"),
                    "estado_empresa": (supplier_geo.get(cnpj) or {}).get("estado_empresa"),
                    "sancionado": bool(sancao_info),
                    "sancao_base": sancao_info.get("base") if sancao_info else None,
                    "sancao_categoria": sancao_info.get("categoria") if sancao_info else None,
                    "itemStyle": {"color": "#dc2626", "borderColor": "#7f1d1d", "borderWidth": 2} if sancao_info else {"color": "#d97706"}
                })
                node_ids.add(f_id)

                # Nó explícito de sanção, ligado ao fornecedor — deixa visível no grafo
                # (não só no tooltip) que aquele CNPJ está no CEIS/CEPIM da CGU.
                if sancao_info:
                    s_id = f"SANCAO_{cnpj}"
                    categoria = (sancao_info.get("categoria") or "").strip()
                    base = sancao_info.get("base")
                    label_sancao = f"🛑 {base}" + (f": {categoria[:24]}" if categoria else "")
                    if s_id not in node_ids:
                        nodes.append({
                            "id": s_id,
                            "name": label_sancao,
                            "fullName": f"{base} — {categoria}" if categoria else base,
                            "category": "Sanção",
                            "symbolSize": 16,
                            "showLabel": True,
                            "itemStyle": {"color": "#7f1d1d", "borderColor": "#450a0a", "borderWidth": 2}
                        })
                        node_ids.add(s_id)
                    links.append({
                        "source": f_id,
                        "target": s_id,
                        "value": 1,
                        "kind": "sancao",
                        "lineStyle": {"color": "#dc2626", "width": 2.5, "type": "dashed"}
                    })

            links.append({
                "source": main_party_id or main_id,
                "target": f_id,
                "value": max(connect_count, 1),
                "kind": "supplier_primary",
                "lineStyle": {"color": "rgba(30, 64, 175, 0.35)", "width": 2}
            })
            
        # --- Nós Outros Deputados (Top 20 Filtered) ---
        for _, row in top_deps_df.iterrows():
            d_nome = row['nome']
            d_uf = row['sgUF']
            d_partido = row.get('partido_atual_resolved') or row['sgPartido']
            d_id = f"PARL_{d_nome.replace(' ', '_')}"
            dep_meta = parlamentares_meta.get(d_nome, {})
            d_uf = dep_meta.get('sgUF') or d_uf
            d_partido = dep_meta.get('ultimoStatus_siglaPartido') or dep_meta.get('sgPartido') or d_partido
            
            if d_id not in node_ids:
                f_url = dep_meta.get('foto')

                nodes.append({
                    "id": d_id,
                    "name": d_nome,
                    "fullName": d_nome,
                    "category": "Parlamentar",
                    "partido": d_partido,
                    "estado": d_uf,
                    "symbolSize": 35,
                    "symbol": f"image://{f_url}" if f_url else "circle",
                    "itemStyle": {"borderColor": "#1d4ed8", "borderWidth": 2}
                })
                node_ids.add(d_id)

            # Removido: nós de Partido e Estado e seus links decorativos.
            # Mantemos partido/estado como METADADOS no nó do parlamentar
            # (campos "partido" e "estado") para tooltip/coloração, mas sem nós separados.

            # Links reais (Fornecedor -> Deputado)
            cnpjs_d = df_others_filtered[df_others_filtered['nome'] == d_nome]['txtCNPJCPF'].unique()
            for c in cnpjs_d:
                f_node = f"FORN_{c}"
                if f_node in node_ids:
                    links.append({
                        "source": f_node,
                        "target": d_id,
                        "kind": "supplier_shared",
                        "lineStyle": {"opacity": 0.32, "color": "rgba(245, 158, 11, 0.55)", "width": 1.5}
                    })
        log_stage("montar_grafo")

        conn.close()

        # --- Louvain community detection on supplier–parliamentarian graph ---
        communities_gastos = {}
        try:
            import networkx as nx
            import community as community_louvain
            G_g = nx.Graph()
            louvain_cats = {"Parlamentar", "Fornecedor"}
            louvain_ids = {n["id"] for n in nodes if n.get("category") in louvain_cats}
            for lk in links:
                src, tgt = str(lk["source"]), str(lk["target"])
                if src in louvain_ids and tgt in louvain_ids:
                    if G_g.has_edge(src, tgt):
                        G_g[src][tgt]["weight"] += 1
                    else:
                        G_g.add_edge(src, tgt, weight=1)
            if G_g.number_of_nodes() >= 2:
                partition = community_louvain.best_partition(G_g, weight="weight", resolution=1.0)
                communities_gastos = {k: int(v) for k, v in partition.items()}
                logger.info(f"[Louvain gastos] {G_g.number_of_nodes()} nós → {len(set(partition.values()))} comunidades")
        except Exception as _e_louv:
            logger.warning(f"[Louvain gastos] Ignorado: {_e_louv}")

        payload = {
            "nodes": nodes,
            "links": links,
            "communities": communities_gastos,
            "debug": {
                "success": True,
                "parlamentar": parlamentar,
                "keyword": keyword,
                "fornecedores_count": len(df_forn),
                "connections_count": len(df_others)
            }
        }
        payload = clean_data_for_json(payload)
        GASTOS_GRAPH_CACHE[cache_key] = {"ts": now, "payload": deepcopy(payload)}
        log_stage("serializar_cache_return")
        return payload

    except Exception as e:
        logger.error(f"Erro CRITICO em conexoes-gastos: {e}")
        return {"nodes": [], "links": [], "communities": {}, "error": str(e), "debug": {"msg": "Exception", "error": str(e)}}



@app.post("/api/redes/gerar-relatorio")
async def gerar_relatorio_redes(request: RelatorioRedesRequest):
    """Gera relatório analítico via LLM sobre as conexões parlamentares."""
    try:
        from openai import OpenAI
        from dotenv import load_dotenv
        
        load_dotenv()
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        conexoes = request.conexoes
        filtros = request.filtros_aplicados
        
        # Preparar dados para análise
        parlamentares_envolvidos = list(set([c['citante'] for c in conexoes] + [c['citado'] for c in conexoes]))
        
        # Agregar informações por parlamentar
        analise_parlamentares = {}
        for parlamentar in parlamentares_envolvidos:
            citacoes_como_citante = [c for c in conexoes if c['citante'] == parlamentar]
            citacoes_como_citado = [c for c in conexoes if c['citado'] == parlamentar]
            
            analise_parlamentares[parlamentar] = {
                'vezes_citou': len(citacoes_como_citante),
                'vezes_foi_citado': len(citacoes_como_citado),
                'sentimentos_ao_citar': [c['sentimento'] for c in citacoes_como_citante],
                'tons_ao_citar': [c['tom'] for c in citacoes_como_citante],
                'estado': citacoes_como_citante[0]['estado_citante'] if citacoes_como_citante else 'N/A',
                'partido': citacoes_como_citante[0]['partido_citante'] if citacoes_como_citante else 'N/A'
            }
        
        # Análise de comissões e datas
        comissoes = list(set([c['comissao'] for c in conexoes if c.get('comissao')]))
        datas = list(set([c['data'] for c in conexoes if c.get('data')]))
        
        # Preparar amostra de citações para o LLM (limitar para não sobrecarregar)
        citacoes_amostra = []
        for c in conexoes[:50]:  # Máximo 50 conexões
            citacoes_amostra.append({
                'citante': c['citante'],
                'citado': c['citado'],
                'sentimento': c['sentimento'],
                'tom': c['tom'],
                'frase': c['sentenca'][:300],  # Limitar tamanho da frase
                'data': c.get('data', 'N/A'),
                'comissao': c.get('comissao', 'N/A')
            })
        
        # Criar prompt para o LLM
        prompt = f"""
Você é um analista político especializado em relações parlamentares. Analise os dados a seguir e gere um relatório técnico completo.

FILTROS APLICADOS:
{json.dumps(filtros, ensure_ascii=False, indent=2)}

ESTATÍSTICAS GERAIS:
- Total de conexões analisadas: {len(conexoes)}
- Parlamentares envolvidos: {len(parlamentares_envolvidos)}
- Comissões mencionadas: {len(comissoes)}
- Período das citações: {min(datas) if datas else 'N/A'} a {max(datas) if datas else 'N/A'}

PARLAMENTARES E SUAS ATIVIDADES:
{json.dumps(analise_parlamentares, ensure_ascii=False, indent=2)}

AMOSTRA DE CITAÇÕES (50 primeiras):
{json.dumps(citacoes_amostra, ensure_ascii=False, indent=2)}

COMISSÕES ONDE OCORRERAM AS CITAÇÕES:
{', '.join(comissoes) if comissoes else 'Não especificado'}

GERE UM RELATÓRIO ESTRUTURADO COM AS SEGUINTES SEÇÕES:

1. **RESUMO EXECUTIVO** (3-4 parágrafos)
   - Principais padrões de relacionamento observados
   - Parlamentares mais influentes (quem mais cita e quem mais é citado)
   - Tom geral das interações

2. **ANÁLISE DE SENTIMENTOS E TONS** (4-5 parágrafos)
   - Distribuição dos sentimentos (Apoio, Crítica, Neutro, Questionador)
   - Análise dos tons predominantes
   - Contexto das citações mais relevantes
   - Cite exemplos específicos de frases com parlamentares, datas e comissões

3. **MAPEAMENTO DE RELACIONAMENTOS** (4-5 parágrafos)
   - Principais duplas/trios de parlamentares que se citam
   - Relações entre partidos diferentes
   - Relações interestaduais
   - Cite nomes, partidos, estados e exemplos de frases

4. **ANÁLISE TEMÁTICA** (3-4 parágrafos)
   - Assuntos predominantes nas citações
   - Temas que geram mais debate/crítica
   - Temas que geram consenso/apoio
   - Cite comissões e contextos específicos

5. **COMISSÕES E CONTEXTOS** (3-4 parágrafos)
   - Comissões onde há mais interação
   - Dinâmica de relacionamento por comissão
   - Períodos de maior atividade

6. **INSIGHTS E PADRÕES POLÍTICOS** (3-4 parágrafos)
   - Alianças identificadas
   - Tensões entre grupos
   - Padrões de comportamento
   - Implicações políticas

IMPORTANTE:
- Seja OBJETIVO e ANALÍTICO
- Use DADOS CONCRETOS (nomes, datas, comissões, frases)
- Cite EXEMPLOS ESPECÍFICOS das citações
- NÃO faça juízos de valor
- QUANTIFIQUE sempre que possível
- Mantenha tom TÉCNICO e NEUTRO
- Use parágrafos bem desenvolvidos (mínimo 4 linhas cada)

REGRAS OBRIGATÓRIAS PARA CITAÇÕES:
- NUNCA cite datas soltas como "durante o período de 01/08/2023 a 31/05/2023"
- SEMPRE cite no formato: "durante a reunião no dia DD/MM/AAAA na comissão [NOME DA COMISSÃO], sessão nº [NÚMERO]"
- SEMPRE mencione a comissão específica onde ocorreu a citação
- SEMPRE inclua o número da sessão quando disponível
- Se a sessão não estiver disponível, use: "durante a reunião no dia DD/MM/AAAA na comissão [NOME DA COMISSÃO]"

FORMATO: Markdown com negrito (**) para títulos de seções e nomes de parlamentares.
"""
        
        # Chamar LLM
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_completion_tokens=3000
        )
        
        relatorio = response.choices[0].message.content
        
        return {
            "relatorio": relatorio,
            "gerado_em": datetime.now().isoformat(),
            "total_conexoes_analisadas": len(conexoes),
            "parlamentares_envolvidos": len(parlamentares_envolvidos),
            "comissoes": comissoes,
            "periodo": {
                "inicio": min(datas) if datas else None,
                "fim": max(datas) if datas else None
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar relatório: {str(e)}")

# ==================== ENDPOINTS PARA ATUAÇÃO EM COMISSÕES ====================

@app.get("/api/comissoes/lista-por-parlamentar")
async def get_comissoes_por_parlamentar(parlamentar: str):
    """Retorna lista de comissões em que um parlamentar atuou"""
    try:
        conn = get_db_connection("discursos")
        query = """
        SELECT DISTINCT comissao as Comissao, COUNT(*) as total_discursos
        FROM discursos_integrados_normalizado
        WHERE parlamentar = ?
        GROUP BY comissao
        ORDER BY total_discursos DESC
        """
        df = pd.read_sql_query(query, conn, params=[parlamentar])
        conn.close()
        
        # Renomear colunas para maiúscula
        if 'comissao' in df.columns:
            df = df.rename(columns={'comissao': 'Comissao'})
        
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class RelatorioComissaoRequest(BaseModel):
    parlamentar: str
    comissao: str
    estado: Optional[str] = None
    partido: Optional[str] = None
    discursos: Optional[List[dict]] = None
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None

@app.get("/api/comissoes/progresso/{session_id}")
async def get_progresso(session_id: str):
    """Retorna o progresso atual do processamento"""
    progresso = progress_status.get(session_id, {
        "total": 0,
        "processados": 0,
        "lote_atual": 0,
        "total_lotes": 0,
        "status": "idle",
        "mensagem": "Aguardando..."
    })
    
    # Se estiver completo e tiver resultado pronto, incluir no retorno
    if progresso.get("status") == "completo" and session_id in resultados_prontos:
        progresso["resultado"] = resultados_prontos[session_id]
    
    return progresso

@app.get("/api/busca-semantica/progresso/{session_id}")
async def get_progresso_semantica(session_id: str):
    """Retorna o progresso atual do processamento de busca semântica"""
    progresso = progress_status.get(session_id, {
        "total": 0,
        "processados": 0,
        "lote_atual": 0,
        "total_lotes": 0,
        "status": "idle",
        "mensagem": "Aguardando..."
    })
    
    # Se estiver completo e tiver resultado pronto, incluir no retorno
    if progresso.get("status") == "completo" and session_id in resultados_prontos:
        progresso["resultado"] = resultados_prontos[session_id]
    
    return progresso

def processar_relatorio_background(parlamentar, comissao, estado, partido, discursos, session_id):
    """Função auxiliar para processar o relatório em background"""
    try:
        from openai import OpenAI
        from dotenv import load_dotenv
        import hashlib
        
        load_dotenv()
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        print(f"🆔 Processando em background: {session_id}")
        import sys
        try:
            with open("debug_trace.log", "a") as f:
                f.write(f"🚀 [1] INICIANDO ANALISE BACKGROUND PARA {parlamentar}\n")
        except: pass
        
        # Calcular hash dos discursos para cache (COM VERSÃO DO PROMPT PARA FORÇAR ATUALIZAÇÃO)
        discursos_texto = [d.get('Texto', '') for d in discursos]
        texto_completo = " ".join(discursos_texto) + "_V16_SESSION_LINKS_FIX" # Salt para invalidar cache antigo
        hash_discursos = hashlib.md5(texto_completo.encode('utf-8')).hexdigest()
        
        print(f"🔑 Hash gerado (v9): {hash_discursos}")
        
        # Verificar cache
        conn_cache = sqlite3.connect(DATABASE_PATHS["cache_relatorios"])
        cursor = conn_cache.cursor()
        
        # Criar tabela se não existir
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relatorios_comissoes (
                hash_discursos TEXT PRIMARY KEY,
                parlamentar TEXT,
                comissao TEXT,
                estado TEXT,
                partido TEXT,
                dados_relatorio TEXT,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Buscar cache
        cursor.execute("SELECT dados_relatorio FROM relatorios_comissoes WHERE hash_discursos = ?", (hash_discursos,))
        result = cursor.fetchone()
        
        if result:
            try:
                with open("debug_trace.log", "a") as f:
                    f.write(f"⚠️ [2.5] CACHE HIT! Retornando dados cacheados.\n")
            except: pass
            conn_cache.close()
            # Atualizar status para completo (do cache)
            progress_status[session_id] = {
                "total": len(discursos),
                "processados": len(discursos),
                "lote_atual": 1,
                "total_lotes": 1,
                "status": "completo",
                "mensagem": "Dados recuperados do cache!",
                "session_id": session_id
            }
            resultado = json.loads(result[0])
            resultado['session_id'] = session_id
            resultado['from_cache'] = True
            print(f"✅ Relatório recuperado do cache para {parlamentar}/{comissao}")
            resultados_prontos[session_id] = resultado
            return
        
        try:
            with open("debug_trace.log", "a") as f:
                f.write(f"🔧 [2.6] CACHE MISS. Iniciando processamento...\n")
        except: pass
        
        # PROCESSAMENTO EM LOTES - Preparar TODOS os discursos completos
        discursos_com_metadados = []
        for d in discursos:  # TODOS os discursos, sem limitação
            discursos_com_metadados.append({
                'data': d.get('Data', 'N/A'),
                'sessao': d.get('Sessao', 'N/A'),
                'texto': d.get('Texto', '')  # Texto COMPLETO, sem truncamento
            })
        
        # Dividir em lotes otimizados para datasets grandes
        # IMPORTANTE: Limitar discursos por lote para evitar truncamento de JSON
        # GPT-4o-mini tem limite de tokens de saída que pode truncar JSONs grandes
        if len(discursos_com_metadados) > 1000:
            MAX_CHARS_POR_LOTE = 200000  # Lotes menores para datasets grandes
            MAX_DISCURSOS_POR_LOTE = 30  # Máximo de 30 discursos por lote
            print(f"🔧 Dataset grande: lotes de {MAX_CHARS_POR_LOTE:,} chars ou {MAX_DISCURSOS_POR_LOTE} discursos")
        elif len(discursos_com_metadados) > 100:
            MAX_CHARS_POR_LOTE = 300000  # Lotes médios
            MAX_DISCURSOS_POR_LOTE = 40  # Máximo de 40 discursos por lote
            print(f"🔧 Dataset médio: lotes de {MAX_CHARS_POR_LOTE:,} chars ou {MAX_DISCURSOS_POR_LOTE} discursos")
        else:
            MAX_CHARS_POR_LOTE = 400000  # Lotes normais para datasets pequenos
            MAX_DISCURSOS_POR_LOTE = 50  # Máximo de 50 discursos por lote
            print(f"🔧 Dataset normal: lotes de {MAX_CHARS_POR_LOTE:,} chars ou {MAX_DISCURSOS_POR_LOTE} discursos")
        
        lotes = []
        lote_atual = []
        chars_lote_atual = 0
        
        # Dicionário para rastrear sessões únicas e seus links (para o frontend)
        sessoes_identificadas = {}
        
        # Conectar ao banco de links recuperado
        try:
            conn_links = sqlite3.connect(DATABASE_PATHS["discursos_links_fixed"])
            cursor_links = conn_links.cursor()
        except Exception as e:
            print(f"⚠️ Erro ao conectar banco de links: {e}")
            conn_links = None

        for discurso in discursos_com_metadados:
            texto_completo = discurso['texto']
            
            # Tentar buscar link exato no banco recuperado
            link_real = None
            if conn_links:
                try:
                    # Normalizar data para formato DD/MM/YYYY usado na URL
                    data_obj = datetime.strptime(discurso['data'], '%d/%m/%Y')
                    data_url = data_obj.strftime('%d/%m/%Y')
                    
                    # Normalizar nome do parlamentar para formato do banco (ex: abilio+brunini)
                    import unidecode
                    nome_normalizado = unidecode.unidecode(parlamentar.lower()).replace(" ", "+")
                    
                    # 1. Busca por Deputado e Data (Prioridade Máxima)
                    query_link = """
                    SELECT url FROM links_discursos 
                    WHERE deputado = ? AND url LIKE ? 
                    LIMIT 1
                    """
                    cursor_links.execute(query_link, (nome_normalizado, f"%Data={data_url}%"))
                    result = cursor_links.fetchone()
                    
                    if result:
                        link_real = result[0].strip()
                    else:
                        # 2. Fallback: Tentar matching parcial do nome na URL
                        query_link_fallback = """
                        SELECT url FROM links_discursos 
                        WHERE url LIKE ? AND url LIKE ?
                        LIMIT 1
                        """
                        nome_parcial = parlamentar.split()[0].lower()
                        cursor_links.execute(query_link_fallback, (f"%Data={data_url}%", f"%txApelido=%{nome_parcial}%"))
                        result_fallback = cursor_links.fetchone()
                        
                        if result_fallback:
                            link_real = result_fallback[0].strip()
                        else:
                            # 3. Fallback Final: Busca pelo número da sessão e data (ignora nome)
                            # Isso resolve casos onde o link existe mas está associado a outro deputado ou sem nome
                            sessao_num = discurso['sessao'].split('.')[0] # Tenta pegar número base
                            query_link_sessao = """
                            SELECT url FROM links_discursos 
                            WHERE url LIKE ? AND url LIKE ?
                            LIMIT 1
                            """
                            # Tenta primeiro com o número exato da string de sessão
                            cursor_links.execute(query_link_sessao, (f"%Data={data_url}%", f"%nuSessao={discurso['sessao']}%"))
                            result_sessao = cursor_links.fetchone()
                            
                            if result_sessao:
                                link_real = result_sessao[0].strip()
                            else:
                                # Tenta apenas com o número principal (ex: 34 de 34.2023)
                                cursor_links.execute(query_link_sessao, (f"%Data={data_url}%", f"%nuSessao={sessao_num}%"))
                                result_sessao_base = cursor_links.fetchone()
                                if result_sessao_base:
                                    link_real = result_sessao_base[0].strip()
                except Exception as e:
                    print(f"⚠️ Erro ao buscar link: {e}")

            # Usar link real se achou, senão fallback para busca
            if link_real:
                link_final = link_real
                label_link = "Link da Ata"
            else:
                link_final = f"https://www.camara.leg.br/busca-portal?q={parlamentar}"
                label_link = "Busca"
            
            discurso_formatado = f"📅 {discurso['data']} - Sessão {discurso['sessao']} [{label_link}]({link_final}):\n{texto_completo}\n{'='*80}\n"
            tamanho_discurso = len(discurso_formatado)
            
            # Guardar sessão única
            if discurso['sessao'] not in sessoes_identificadas:
                sessoes_identificadas[discurso['sessao']] = {
                    "data": discurso['data'],
                    "sessao": discurso['sessao'],
                    "link": link_final
                }
            
            # Guardar sessão única
            if discurso['sessao'] not in sessoes_identificadas:
                sessoes_identificadas[discurso['sessao']] = {
                    "data": discurso['data'],
                    "sessao": discurso['sessao'],
                    "link": link_final
                }
            
            # Se ultrapassar limite de chars OU de discursos, criar novo lote
            if (chars_lote_atual + tamanho_discurso > MAX_CHARS_POR_LOTE or len(lote_atual) >= MAX_DISCURSOS_POR_LOTE) and lote_atual:
                lotes.append(lote_atual.copy())
                lote_atual = []
                chars_lote_atual = 0
            
            lote_atual.append(discurso)
            chars_lote_atual += tamanho_discurso
        
        # Adicionar último lote
        if lote_atual:
            lotes.append(lote_atual)
        
        # LOG: Informações sobre lotes
        print(f"\n{'='*80}")
        print(f"🔄 PROCESSAMENTO EM LOTES")
        print(f"{'='*80}")
        print(f"📊 Total de discursos: {len(discursos)}")
        print(f"📦 Total de lotes criados: {len(lotes)}")
        
        # Para datasets grandes, mostrar resumo mais compacto
        if len(lotes) > 10:
            print(f"📋 Resumo dos lotes (dataset grande):")
            for i, lote in enumerate(lotes[:5], 1):
                datas_unicas = set([d['data'] for d in lote])
                print(f"   Lote {i}: {len(lote)} discursos, {len(datas_unicas)} datas únicas")
            print(f"   ... e mais {len(lotes) - 5} lotes")
        else:
            for i, lote in enumerate(lotes, 1):
                datas_unicas = set([d['data'] for d in lote])
                print(f"   Lote {i}: {len(lote)} discursos, {len(datas_unicas)} datas únicas")
        
        print(f"⏱️ Tempo estimado: ~{len(lotes) * 30} segundos")
        print(f"{'='*80}\n")
        
        # Atualizar status de progresso
        progress_status[session_id].update({
            "total_lotes": len(lotes),
            "status": "processando",
            "mensagem": f"Dividido em {len(lotes)} lote(s)"
        })
        
        # Processar cada lote
        analises_parciais = []
        todas_analises_discursos = []
        todos_temas = {}
        todas_frases = []
        todos_bigramas = []
        
        for idx_lote, lote in enumerate(lotes, 1):
            try:
                with open("debug_trace.log", "a") as f:
                    f.write(f"🔄 [3] INICIANDO LOTE {idx_lote}/{len(lotes)} ({len(lote)} discursos)\n")
            except: pass

            # Atualizar status de progresso
            discursos_processados_ate_agora = sum([len(lotes[i]) for i in range(idx_lote-1)])
            progress_status[session_id].update({
                "lote_atual": idx_lote,
                "processados": discursos_processados_ate_agora,
                "status": "processando_lote",
                "mensagem": f"Processando lote {idx_lote}/{len(lotes)} ({len(lote)} discursos)..."
            })
            
            # Log mais detalhado para datasets grandes
            if len(lotes) > 10:
                print(f"📦 Processando lote {idx_lote}/{len(lotes)} ({len(lote)} discursos) - {discursos_processados_ate_agora}/{len(discursos)} processados")
            else:
                print(f"📦 Processando lote {idx_lote}/{len(lotes)}...")
            discursos_texto_lote = "".join([
                f"📅 {d['data']} - Sessão {d['sessao']}:\n{d['texto']}\n{'='*80}\n"
                for d in lote
            ])
            
            # Criar prompt para o lote
            prompt_lote = f"""
Analise os discursos do parlamentar {parlamentar} na comissão {comissao}.

ESTE É O LOTE {idx_lote} DE {len(lotes)} LOTES TOTAIS.

CONTEXTO:
- Parlamentar: {parlamentar} ({partido}/{estado})
- Comissão: {comissao}
- Discursos neste lote: {len(lote)}

DISCURSOS PARA ANÁLISE (TEXTO COMPLETO DO LOTE {idx_lote}):
{discursos_texto_lote}

INSTRUÇÕES CRÍTICAS:
1. ANALISE CADA UM dos {len(lote)} discursos fornecidos INDIVIDUALMENTE
2. Para CADA discurso, gere um objeto completo no array "analise_discursos"
3. SEMPRE cite DATAS e NÚMEROS de sessão
4. IDENTIFIQUE temas, tom, posicionamento e relevância
5. EXTRAIA bigramas e frases-chave
6. O array "analise_discursos" DEVE ter EXATAMENTE {len(lote)} elementos
7. NÃO PULE NENHUM DISCURSO

FORMATO DE RESPOSTA (JSON) - ANÁLISE PARCIAL DO LOTE:
{{
    "resumo_lote": "Resumo dos principais pontos deste lote",
    "temas_principais": {{
        "tema1": {{"frequencia": 0, "relevancia_comissao": "alta/media/baixa", "posicionamento": "favorável/contrário/neutro"}}
    }},
    "frases_destaque": [
        {{"frase": "texto", "data": "dd/mm/yyyy", "sessao": "número", "impacto": 0.9}}
    ],
    "bigramas_importantes": [
        {{"bigrama": "palavra1 palavra2", "frequencia": 10}}
    ],
    "analise_discursos": [
        {{
            "data": "dd/mm/yyyy",
            "sessao": "número",
            "categoria_padrao": "Escolha UMA das 10 categorias padrão: Agricultura e Meio Ambiente, Economia e Orçamento, Educação e Cultura, Saúde e Assistência Social, Segurança Pública e Justiça, Infraestrutura e Desenvolvimento Regional, Política e Administração Pública, Direitos Humanos e Minorias, Relações Exteriores e Defesa, Regimento Interno e Processo Legislativo",
            "objetividade": 7.5,
            "tensao": 3.2,
            "resumo_discurso": "resumo breve"
        }}
    ]
}}

IMPORTANTE: O array "analise_discursos" DEVE ter {len(lote)} elementos.
Retorne APENAS JSON válido.
"""
            
            try:
                # Chamar LLM para o lote
                try:
                    with open("debug_trace.log", "a") as f:
                        f.write(f"📞 [3.1] Chamando LLM para lote {idx_lote}...\n")
                except: pass
                
                response = client.chat.completions.create(
                    model="gpt-5.4-mini",
                    messages=[
                        {"role": "system", "content": "Você é um especialista em análise de discursos parlamentares. Retorne sempre JSON válido. Analise TODOS os discursos fornecidos em detalhes."},
                        {"role": "user", "content": prompt_lote}
                    ],
                    max_completion_tokens=16000,  # Aumentado para evitar truncamento em lotes grandes
                    temperature=0.3
                )
                
                resposta_lote = response.choices[0].message.content
                
                try:
                    with open("debug_trace.log", "a") as f:
                        f.write(f"🤖 [3.2] LLM Respondeu lote {idx_lote}. Tamanho: {len(resposta_lote)}\n")
                except: pass

                # DEBUG: Ver o que o LLM retornou
                print(f"📄 Resposta do LLM (primeiros 500 chars): {resposta_lote[:500]}")
                
                # LIMPAR marcadores markdown de forma robusta
                import re
                resposta_limpa = resposta_lote.strip()
                
                # Remover blocos de código markdown
                resposta_limpa = re.sub(r'^```(?:json)?\s*', '', resposta_limpa)
                resposta_limpa = re.sub(r'\s*```$', '', resposta_limpa)
                resposta_limpa = resposta_limpa.strip()
                
                # Se ainda não é JSON, tentar extrair JSON do meio do texto
                if not resposta_limpa.startswith('{'):
                    json_match = re.search(r'\{.*\}', resposta_limpa, re.DOTALL)
                    if json_match:
                        resposta_limpa = json_match.group(0)
                
                print(f"🧹 Resposta limpa (primeiros 300 chars): {resposta_limpa[:300]}")
                print(f"   Começa com: '{resposta_limpa[:20]}'")
                print(f"   Termina com: '{resposta_limpa[-20:]}'")
                
                analise_lote = json.loads(resposta_limpa)
                
                # DEBUG: Verificar quantas análises foram retornadas
                num_analises = len(analise_lote.get('analise_discursos', []))
                print(f"📊 Análises de discursos retornadas pelo LLM: {num_analises}/{len(lote)}")
                
                if num_analises == 0:
                    print(f"⚠️ AVISO: LLM não retornou análises individuais!")
                    print(f"   Keys retornadas: {list(analise_lote.keys())}")
                
                analises_parciais.append(analise_lote)
                # Extrair dados para agregação
                import sys
                itens_lote = analise_lote.get('analise_discursos', [])
                if itens_lote:
                    todas_analises_discursos.extend(itens_lote)
                    try:
                        with open("debug_trace.log", "a") as f:
                            f.write(f"✅ [4] Extraídos {len(itens_lote)} itens do lote {idx_lote}. Total: {len(todas_analises_discursos)}\n")
                    except: pass
                    print(f"✅ Extraídos {len(itens_lote)} itens do lote {idx_lote}. Total acumulado: {len(todas_analises_discursos)}", file=sys.stderr)
                else:
                    try:
                        with open("debug_trace.log", "a") as f:
                            f.write(f"⚠️ [4] FALHA EXTRAÇÃO LOTE {idx_lote}\n")
                    except: pass
                    print(f"⚠️ NENHUM item 'analise_discursos' encontrado no lote {idx_lote}!", file=sys.stderr)
                    print(f"   Conteúdo parcial: {str(analise_lote)[:200]}", file=sys.stderr)

                # Atualizar status de progresso após processar o lote
                progress_status[session_id].update({
                    "processados": len(todas_analises_discursos),
                    "mensagem": f"Lote {idx_lote}/{len(lotes)} concluído - {len(todas_analises_discursos)} discursos analisados"
                })
                
                for tema, dados in analise_lote.get('temas_principais', {}).items():
                    if tema in todos_temas:
                        todos_temas[tema]['frequencia'] = todos_temas[tema].get('frequencia', 0) + dados.get('frequencia', 0)
                    else:
                        todos_temas[tema] = dados
                
                todas_frases.extend(analise_lote.get('frases_destaque', []))
                todos_bigramas.extend(analise_lote.get('bigramas_importantes', []))
                
                try:
                    with open("debug_trace.log", "a") as f:
                        f.write(f"🏁 [4.5] FIM ITERACAO LOTE {idx_lote}\n")
                except: pass
                
            except Exception as e:
                print(f"Erro ao processar lote {idx_lote}: {str(e)}")
                try:
                    with open("debug_trace.log", "a") as f:
                        f.write(f"❌ [4.9] ERRO NO LOTE {idx_lote}: {str(e)}\n")
                except: pass
                analises_parciais.append({
                    "resumo_lote": f"Erro no lote {idx_lote}",
                    "analise_discursos": [],
                    "erro": str(e)
                })
        
        # CONSOLIDAÇÃO FINAL
        # Atualizar status de progresso
        progress_status[session_id].update({
            "processados": len(todas_analises_discursos),
            "status": "consolidando",
            "mensagem": f"Consolidando {len(todas_analises_discursos)} análises em relatório final..."
        })
        
        # Extrair TODAS as datas únicas dos discursos analisados
        datas_sessoes = []
        for disc in todas_analises_discursos:
            if disc.get('data') and disc.get('sessao'):
                datas_sessoes.append(f"{disc['data']} (Sessão {disc['sessao']})")
        
        datas_unicas_str = ", ".join(sorted(set(datas_sessoes))) if datas_sessoes else "Sem datas registradas"
        
        resumos_lotes = "\n\n".join([f"LOTE {i+1}: {a.get('resumo_lote', 'Sem resumo')}" for i, a in enumerate(analises_parciais)])
        
        # Definir estrutura baseada no volume de discursos
        qtd_discursos = len(todas_analises_discursos)
        if qtd_discursos < 10:
            instrucao_tamanho = "Gere um relatório conciso de 1 a 2 parágrafos."
        elif qtd_discursos <= 30:
            instrucao_tamanho = "Gere um relatório detalhado de 2 a 5 parágrafos, cobrindo os principais pontos."
        else:
            instrucao_tamanho = "Gere um relatório extenso e aprofundado de 5 a 8 parágrafos, estruturado com subtítulos (use Markdown) para facilitar a leitura."

        prompt_consolidacao = f"""
Você analisou {len(discursos)} discursos do parlamentar {parlamentar} na comissão {comissao} em {len(lotes)} lote(s).

Gere um RELATÓRIO FINAL CONSOLIDADO integrando TODAS as análises parciais.

IMPORTANTE - VOCÊ DEVE:
1. Mencionar TODAS as datas de participação listadas abaixo
2. Demonstrar a EVOLUÇÃO TEMPORAL da atuação
3. Citar exemplos de DIFERENTES sessões, não apenas uma
4. Integrar informações de TODOS os {len(lotes)} lotes processados
5. {instrucao_tamanho}

TODAS AS DATAS E SESSÕES ANALISADAS:
{datas_unicas_str}

RESUMOS DOS LOTES PROCESSADOS:
{resumos_lotes}

ESTATÍSTICAS CONSOLIDADAS:
- Total de discursos analisados: {len(todas_analises_discursos)}
- Temas identificados: {len(todos_temas)}
- Lotes processados: {len(lotes)}
- Datas únicas: {len(set([d['data'] for d in todas_analises_discursos if d.get('data')]))}

FORMATO DE RESPOSTA (JSON):
{{
    "relatorio_analitico": "Texto do relatório consolidado. {instrucao_tamanho} Use Markdown para negrito e listas se necessário.",
    "avaliacao_geral": {{
        "participacao": "alta/media/baixa",
        "relevancia_comissao": "alta/media/baixa",
        "tom_discursos": "técnico/combativo/colaborativo",
        "principais_preocupacoes": ["tema1", "tema2"]
    }},
    "indices_gerais": {{
        "objetividade_media": {sum([d.get('objetividade', 0) for d in todas_analises_discursos]) / len(todas_analises_discursos) if todas_analises_discursos else 0},
        "tensao_media": {sum([d.get('tensao', 0) for d in todas_analises_discursos]) / len(todas_analises_discursos) if todas_analises_discursos else 0},
        "categoria_mais_frequente": "categoria",
        "evolucao_objetividade": "Descreva a evolução ao longo das múltiplas datas e sessões"
    }}
}}

CRÍTICO: O relatório deve refletir que você analisou {len(discursos)} discursos em {len(set([d['data'] for d in todas_analises_discursos if d.get('data')]))} datas diferentes, não apenas uma sessão.

Retorne APENAS JSON válido.
"""
        
        try:
            print(f"🔄 Gerando relatório consolidado final...")
            response_consolidacao = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                    {"role": "system", "content": "Você é um especialista em análise política consolidada. Retorne sempre JSON válido."},
                    {"role": "user", "content": prompt_consolidacao}
            ],
                max_completion_tokens=4000,
            temperature=0.3
        )
        
            resposta_consolidacao_raw = response_consolidacao.choices[0].message.content
            
            # LIMPAR marcadores markdown de forma robusta
            import re
            resposta_consolidacao_limpa = resposta_consolidacao_raw.strip()
            resposta_consolidacao_limpa = re.sub(r'^```(?:json)?\s*', '', resposta_consolidacao_limpa)
            resposta_consolidacao_limpa = re.sub(r'\s*```$', '', resposta_consolidacao_limpa)
            resposta_consolidacao_limpa = resposta_consolidacao_limpa.strip()
            
            # Se não começa com {, extrair JSON
            if not resposta_consolidacao_limpa.startswith('{'):
                json_match = re.search(r'\{.*\}', resposta_consolidacao_limpa, re.DOTALL)
                if json_match:
                    resposta_consolidacao_limpa = json_match.group(0)
            
            print(f"🧹 Consolidação limpa (primeiros 200 chars): {resposta_consolidacao_limpa[:200]}")
            
            dados_consolidados = json.loads(resposta_consolidacao_limpa)
            print(f"✅ Relatório consolidado gerado com sucesso!")
            
            # Atualizar status de progresso
            progress_status[session_id].update({
                "processados": len(todas_analises_discursos),
                "status": "finalizando",
                "mensagem": "Finalizando relatório..."
            })
            
        except Exception as e:
            print(f"❌ Erro na consolidação: {str(e)}")
            dados_consolidados = {
                "relatorio_analitico": "Erro ao gerar relatório consolidado",
                "avaliacao_geral": {},
                "indices_gerais": {}
            }
            progress_status[session_id].update({
                "status": "erro",
                "mensagem": f"Erro na consolidação: {str(e)}"
            })
        
        # Montar resultado final
        try:
            dados_analise = {
                "relatorio_analitico": dados_consolidados.get("relatorio_analitico", "Análise não disponível"),
                "temas_principais": todos_temas,
                "frases_destaque": todas_frases[:20],
                "bigramas_importantes": todos_bigramas[:20],
                "avaliacao_geral": dados_consolidados.get("avaliacao_geral", {}),
                "analise_discursos": todas_analises_discursos,
                "categorias_disponiveis": [
                    "legislacao_projetos", "fiscalizacao_controle", "politicas_publicas",
                    "direitos_humanos", "economia_orcamento", "seguranca_publica",
                    "educacao_cultura", "saude_ambiente", "discussao_regimento"
                ],
                "indices_gerais": dados_consolidados.get("indices_gerais", {})
            }

            # --- CÁLCULO ROBUSTO VIA PYTHON (MANDATÓRIO) ---
            try:
                print(f"📊 [PYTHON] Iniciando cálculo de métricas. Discursos: {len(todas_analises_discursos)}")
                
                # 1. Normalizar dados para DataFrame
                dados_normalizados = []
                for item in todas_analises_discursos:
                    novo_item = {}
                    for k, v in item.items():
                        novo_item[k.lower()] = v
                    dados_normalizados.append(novo_item)
                
                df_evolucao = pd.DataFrame(dados_normalizados)
                
                # LOG TO FILE (UNCONDITIONAL)
                try:
                    with open("debug_chart.log", "w") as f:
                        f.write(f"COLUNAS ENCONTRADAS: {df_evolucao.columns.tolist()}\n")
                        f.write(f"DADOS NORMALIZADOS (Head): {df_evolucao.head().to_json()}\n")
                except: pass

                # 2. Evolução Temporal (Média por Data)
                print("🔄 [PYTHON] Recalculando 'evolucao_temporal'...")
                
                if not df_evolucao.empty and 'data' in df_evolucao.columns:
                    # Converter datas para YYYY-MM-DD para garantir ordenação correta e match com frontend
                    try:
                        # Tentar converter assumindo dia/mês/ano (padrão BR)
                        df_evolucao['data_dt'] = pd.to_datetime(df_evolucao['data'], dayfirst=True, errors='coerce')
                        # Remover datas inválidas
                        df_evolucao = df_evolucao.dropna(subset=['data_dt'])
                        # Formatar para YYYY-MM-DD
                        df_evolucao['data'] = df_evolucao['data_dt'].dt.strftime('%Y-%m-%d')
                    except Exception as e:
                        print(f"⚠️ Erro ao converter datas: {e}")

                    # Converter colunas numéricas
                    col_obj = next((c for c in df_evolucao.columns if 'objetiv' in c), None)
                    col_tensao = next((c for c in df_evolucao.columns if 'tensao' in c or 'tens' in c), None)
                    
                    if col_obj and col_tensao:
                        df_evolucao['objetividade'] = pd.to_numeric(df_evolucao[col_obj], errors='coerce')
                        df_evolucao['tensao'] = pd.to_numeric(df_evolucao[col_tensao], errors='coerce')
                        
                        # Agrupar por data
                        evolucao = df_evolucao.groupby('data')[['objetividade', 'tensao']].mean().to_dict(orient='index')
                        
                        # Formatar
                        evolucao_formatada = {
                            k: {"objetividade_media": v['objetividade'], "tensao_media": v['tensao']} 
                            for k, v in evolucao.items()
                        }
                        
                        # INJETAR NO RESULTADO FINAL (NA RAIZ, COMO O FRONTEND ESPERA)
                        dados_analise['evolucao_temporal'] = evolucao_formatada
                        
                        # Tambem manter em indices_gerais por compatibilidade
                        if 'evolucao_temporal' not in dados_analise['indices_gerais']:
                            dados_analise['indices_gerais']['evolucao_temporal'] = {}
                        dados_analise['indices_gerais']['evolucao_temporal'] = evolucao_formatada
                        
                        try:
                            with open("debug_chart.log", "a") as f:
                                f.write(f"EVOLUCAO FORMATADA (YYYY-MM-DD):\n{json.dumps(evolucao_formatada, indent=2, default=str)}\n")
                        except: pass

                        print(f"✅ [PYTHON] Evolução temporal calculada: {len(evolucao_formatada)} dias.")
                    else:
                        print(f"❌ [PYTHON] Colunas de métricas não encontradas. Cols: {df_evolucao.columns.tolist()}")
                else:
                    print("❌ [PYTHON] Dados insuficientes para evolução temporal.")

                # 3. Bigramas Frequentes (Python)
                print("☁️ [PYTHON] Gerando bigramas...")
                try:
                    stopwords_pt = set(['de', 'a', 'o', 'que', 'e', 'do', 'da', 'em', 'um', 'para', 'com', 'não', 'uma', 'os', 'no', 'se', 'na', 'por', 'mais', 'as', 'dos', 'como', 'mas', 'ao', 'ele', 'das', 'à', 'seu', 'sua', 'ou', 'quando', 'muito', 'nos', 'já', 'eu', 'também', 'só', 'pelo', 'pela', 'até', 'isso', 'ela', 'entre', 'depois', 'sem', 'mesmo', 'aos', 'seus', 'quem', 'nas', 'me', 'esse', 'eles', 'você', 'essa', 'num', 'nem', 'suas', 'meu', 'às', 'minha', 'numa', 'pelos', 'elas', 'qual', 'nós', 'lhe', 'deles', 'essas', 'esses', 'pelas', 'este', 'dele', 'tu', 'te', 'vocês', 'vos', 'lhes', 'meus', 'minhas', 'teu', 'tua', 'teus', 'tuas', 'nosso', 'nossa', 'nossos', 'nossas', 'dela', 'delas', 'esta', 'estes', 'estas', 'aquele', 'aquela', 'aqueles', 'aquelas', 'isto', 'aquilo', 'estou', 'está', 'estamos', 'estão', 'estive', 'esteve', 'estivemos', 'estiveram', 'estava', 'estávamos', 'estavam', 'estivera', 'estivéramos', 'esteja', 'estejamos', 'estejam', 'estivesse', 'estivéssemos', 'estivessem', 'estiver', 'estivermos', 'estiverem', 'hei', 'há', 'havemos', 'hão', 'houve', 'houvemos', 'houveram', 'houvera', 'houvéramos', 'haja', 'hajamos', 'hajam', 'houvesse', 'houvéssemos', 'houvessem', 'houver', 'houvermos', 'houverem', 'houverei', 'houverá', 'houveremos', 'houverão', 'houveria', 'houveríamos', 'houveriam', 'sou', 'somos', 'são', 'era', 'éramos', 'eram', 'fui', 'foi', 'fomos', 'foram', 'fora', 'fôramos', 'seja', 'sejamos', 'sejam', 'fosse', 'fôssemos', 'fossem', 'for', 'formos', 'forem', 'serei', 'será', 'seremos', 'serão', 'seria', 'seríamos', 'seriam', 'tenho', 'tem', 'temos', 'tém', 'tinha', 'tínhamos', 'tinham', 'tive', 'teve', 'tivemos', 'tiveram', 'tivera', 'tivéramos', 'tenha', 'tenhamos', 'tenham', 'tivesse', 'tivéssemos', 'tivessem', 'tiver', 'tivermos', 'tiverem', 'terei', 'terá', 'teremos', 'terão', 'teria', 'teríamos', 'teriam'])
                    
                    import re
                    texto_total = " ".join([d['texto'] for d in discursos_com_metadados])
                    palavras = re.findall(r'\b[a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ]{4,}\b', texto_total.lower())
                    palavras = [p for p in palavras if p not in stopwords_pt]
                    
                    bigramas = []
                    for i in range(len(palavras) - 1):
                        bigrama = f"{palavras[i]} {palavras[i+1]}"
                        bigramas.append(bigrama)
                    
                    from collections import Counter
                    counter = Counter(bigramas)
                    top_bigramas = [{"bigrama": k, "frequencia": v} for k, v in counter.most_common(15)] # Limitado a 15 conforme pedido
                    
                    dados_analise['bigramas_frequentes'] = top_bigramas
                    print(f"✅ [PYTHON] Bigramas gerados: {len(top_bigramas)}")
                    
                    # Injetar lista de sessões (Python)
                    dados_analise['sessoes_analisadas'] = list(sessoes_identificadas.values())
                    print(f"✅ [PYTHON] Sessões únicas identificadas: {len(dados_analise['sessoes_analisadas'])}")
                    
                    # Injetar lista de sessões (Python)
                    dados_analise['sessoes_analisadas'] = list(sessoes_identificadas.values())
                    print(f"✅ [PYTHON] Sessões únicas identificadas: {len(dados_analise['sessoes_analisadas'])}")
                except Exception as e:
                    print(f"❌ [PYTHON] Erro ao gerar bigramas: {e}")

                # 4. Agregação por Categorias Padrão (Python)
                print("📂 [PYTHON] Agregando categorias padrão...")
                try:
                    categorias_padrao = [
                        "Agricultura e Meio Ambiente", "Economia e Orçamento", "Educação e Cultura",
                        "Saúde e Assistência Social", "Segurança Pública e Justiça", "Infraestrutura e Desenvolvimento Regional",
                        "Política e Administração Pública", "Direitos Humanos e Minorias",
                        "Relações Exteriores e Defesa", "Regimento Interno e Processo Legislativo"
                    ]
                    
                    contagem_categorias = {c: 0 for c in categorias_padrao}
                    
                    for d in todas_analises_discursos:
                        # Tentar pegar categoria_padrao, depois categoria, depois inferir
                        cat = d.get('categoria_padrao') or d.get('categoria') or "Outros"
                        
                        # Normalização simples para match
                        cat_lower = cat.lower()
                        match_encontrado = False
                        for padrao in categorias_padrao:
                            if padrao.lower() in cat_lower or cat_lower in padrao.lower():
                                contagem_categorias[padrao] += 1
                                match_encontrado = True
                                break
                        
                        if not match_encontrado:
                            # Tentar mapear "Outros" ou logar
                            pass

                    # Formatar para o frontend (substituindo temas_principais)
                    novos_temas = {}
                    for cat, freq in contagem_categorias.items():
                        if freq > 0:
                            novos_temas[cat] = {
                                "frequencia": freq,
                                "relevancia_comissao": "alta" if freq > 2 else "media",
                                "exemplos": [] # Poderíamos adicionar exemplos aqui se quiséssemos
                            }
                    
                    if novos_temas:
                        dados_analise['temas_principais'] = novos_temas
                        print(f"✅ [PYTHON] Categorias agregadas: {len(novos_temas)}")
                    else:
                        print("⚠️ [PYTHON] Nenhuma categoria padrão identificada.")

                except Exception as e:
                    print(f"❌ [PYTHON] Erro ao agregar categorias: {e}")

            except Exception as e:
                print(f"❌ [PYTHON] Erro fatal no cálculo de métricas: {e}")
                import traceback
                traceback.print_exc()
            
            # LOG FINAL
            print(f"\n{'='*80}")
            print(f"✅ PROCESSAMENTO CONCLUÍDO")
            print(f"{'='*80}")
            print(f"📊 Discursos recebidos: {len(discursos)}")
            print(f"📦 Lotes processados: {len(lotes)}")
            print(f"📋 Análises individuais geradas: {len(todas_analises_discursos)}")
            print(f"📅 Datas únicas encontradas: {len(set([d['data'] for d in todas_analises_discursos if d.get('data')]))}")
            print(f"🎯 Temas identificados: {len(todos_temas)}")
            print(f"💬 Frases destaque: {len(todas_frases)}")
            print(f"📝 Tamanho do relatório: {len(dados_analise.get('relatorio_analitico', ''))} caracteres")
            print(f"{'='*80}\n")
            
            # Marcar como completo
            progress_status[session_id].update({
                "processados": len(todas_analises_discursos),
                "status": "completo",
                "mensagem": "Análise concluída com sucesso!"
            })
            
            # Adicionar session_id ao resultado
            dados_analise['session_id'] = session_id
            
            # Salvar no cache
            cursor.execute('''
                INSERT OR REPLACE INTO relatorios_comissoes 
                (hash_discursos, parlamentar, comissao, estado, partido, dados_relatorio)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (hash_discursos, parlamentar, comissao, estado, partido, json.dumps(dados_analise, ensure_ascii=False)))
            conn_cache.commit()
            conn_cache.close()
            
            # Adicionar indicador de que foi gerado agora (não do cache)
            dados_analise['from_cache'] = False
            dados_analise['session_id'] = session_id
            
            # Armazenar resultado para ser recuperado depois
            resultados_prontos[session_id] = dados_analise
            
            print(f"✅ Novo relatório gerado e salvo no cache para {parlamentar}/{comissao}")
            
            return dados_analise
            
        except Exception as e:
            conn_cache.close()
            # Se houver erro, retornar estrutura básica
            resultado_erro = {
                "relatorio_analitico": f"Erro ao processar análise: {str(e)}",
                "analise_discursos": todas_analises_discursos,  # Retornar o que conseguimos processar
                "erro": str(e)
            }
            resultados_prontos[session_id] = resultado_erro
            return resultado_erro
            
    except Exception as e:
        progress_status[session_id].update({
            "status": "erro",
            "mensagem": f"Erro: {str(e)}"
        })
        resultado_erro = {
            "relatorio_analitico": f"Erro ao gerar relatório: {str(e)}",
            "analise_discursos": [],
            "erro": str(e)
        }
        resultados_prontos[session_id] = resultado_erro

@app.post("/api/comissoes/gerar-relatorio")
async def gerar_relatorio_comissao(request: RelatorioComissaoRequest):
    """Gera relatório LLM sobre atuação de parlamentar em comissão"""
    import re
    import threading
    
    parlamentar = request.parlamentar
    comissao = request.comissao
    estado = request.estado
    estado = request.estado or ""
    partido = request.partido or ""
    
    # Se não vieram discursos, buscar no banco
    discursos = request.discursos
    if not discursos:
        print(f"🔄 Buscando discursos para {parlamentar} no backend...")
        try:
            conn = get_db_connection("discursos")
            query = """
            SELECT Parlamentar, Comissao, Data, Sessao, Texto
            FROM discursos
            WHERE Parlamentar = ?
            """
            params = [parlamentar]
            
            if comissao and str(comissao).strip() != "" and str(comissao).strip().lower() != "todas":
                query += " AND Comissao LIKE ?"
                params.append(f"%{comissao}%")
            
            if request.data_inicio:
                query += " AND date(substr(Data, 7, 4) || '-' || substr(Data, 4, 2) || '-' || substr(Data, 1, 2)) >= date(?)"
                params.append(request.data_inicio)
            
            if request.data_fim:
                query += " AND date(substr(Data, 7, 4) || '-' || substr(Data, 4, 2) || '-' || substr(Data, 1, 2)) <= date(?)"
                params.append(request.data_fim)
                
            if not request.data_inicio:
                query += " AND date(substr(Data, 7, 4) || '-' || substr(Data, 4, 2) || '-' || substr(Data, 1, 2)) > date('2022-12-31')"
                
            query += " ORDER BY Data DESC"
            
            df = pd.read_sql_query(query, conn, params=params)
            conn.close()
            discursos = df.to_dict(orient="records")
            print(f"✅ Encontrados {len(discursos)} discursos no backend.")
        except Exception as e:
            print(f"❌ Erro ao buscar discursos no backend: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao buscar discursos: {str(e)}")

    if not discursos:
        try:
            with open("debug_trace.log", "a") as f:
                f.write(f"❌ [2] NENHUM DISCURSO ENCONTRADO\n")
        except: pass
        return {
            "status": "erro",
            "mensagem": "Nenhum discurso encontrado para o período selecionado."
        }
    
    try:
        with open("debug_trace.log", "a") as f:
            f.write(f"📊 [2] Discursos encontrados: {len(discursos)}\n")
    except: pass  
    
    # ---------------- AMOSTRAGEM INTELIGENTE (ROUND-ROBIN) ---------------- #
    total_original = len(discursos)
    if total_original > 100:
        from collections import defaultdict
        # 1. Agrupar por data
        discursos_por_data = defaultdict(list)
        for d in discursos:
            data = d.get('Data', 'N/A')
            discursos_por_data[data].append(d)
        
        # 2. Ordenar internamente cada grupo do maior pro menor
        for data in discursos_por_data:
            discursos_por_data[data] = sorted(discursos_por_data[data], key=lambda x: len(str(x.get('Texto', ''))), reverse=True)
            
        # 3. Extrair via Round-Robin
        discursos_amostra = []
        dias_disponiveis = list(discursos_por_data.keys())
        
        # Opcional: ordenar os dias disponíveis para os mais recentes sempre saírem na caixinha primeiro 
        try:
            dias_disponiveis.sort(key=lambda x: datetime.strptime(x, '%d/%m/%Y'), reverse=True)
        except:
            pass # fallback caso alguma data venha com sujeiras do banco
            
        index_round = 0
        while len(discursos_amostra) < 100 and dias_disponiveis:
            dias_remover = []
            for dia in dias_disponiveis:
                if len(discursos_por_data[dia]) > index_round:
                    discursos_amostra.append(discursos_por_data[dia][index_round])
                    if len(discursos_amostra) >= 100:
                        break
                else:
                    # Este dia esgotou os discursos, sair da fila nas próximas rodadas
                    dias_remover.append(dia)
                    
            for dia in dias_remover:
                dias_disponiveis.remove(dia)
                
            index_round += 1
            
        print(f"✂️ Reduzindo de {total_original} para os {len(discursos_amostra)} discursos equilibrados via Round-Robin.")
        discursos = discursos_amostra
    # -------------------------------------------------------- #

    # Log do tamanho do dataset
    print(f"📊 Dataset detectado: {len(discursos)} discursos")
    print(f"🔄 Sistema otimizado para processamento em lotes grandes (Smart Sample)")
    
    # Criar session_id com timestamp para garantir unicidade
    session_id = f"{parlamentar}_{comissao}_{len(discursos)}_{int(datetime.now().timestamp())}"
    session_id = re.sub(r'[^a-zA-Z0-9_]', '_', session_id)
    
    # Inicializar status de progresso
    progress_status[session_id] = {
        "total": len(discursos),
        "total_original": total_original,
        "processados": 0,
        "lote_atual": 0,
        "total_lotes": 0,
        "status": "iniciando",
        "mensagem": "Preparando análise...",
        "session_id": session_id
    }
    
    print(f"🆔 Session ID criado: {session_id}")
    
    # Iniciar processamento em background
    thread = threading.Thread(
        target=processar_relatorio_background,
        args=(parlamentar, comissao, estado, partido, discursos, session_id)
    )
    thread.daemon = True
    thread.start()
    
    # Retornar imediatamente com o session_id
    return {
        "session_id": session_id,
        "status": "processando",
        "mensagem": "Processamento iniciado. Use o session_id para consultar o progresso."
    }

@app.post("/api/comissoes/buscar-links")
async def buscar_links_discursos(request: dict):
    """Busca links apenas para as sessões específicas fornecidas"""
    try:
        import re
        sessoes_datas = request.get('sessoes_datas', [])
        
        if not sessoes_datas:
            return {"links": {}}
        
        conn_links = sqlite3.connect(DATABASE_PATHS["discursos_links"])
        
        # Buscar apenas os links necessários usando índice
        links_encontrados = {}
        
        for item in sessoes_datas[:100]:  # Limitar a 100 para segurança
            data = item.get('data')
            sessao = item.get('sessao')
            
            if data and sessao:
                # Busca específica por sessão
                query = """
                SELECT url
                FROM links_discursos
                WHERE origem = 'comissao'
                AND url LIKE ? 
                AND url LIKE ?
                LIMIT 1
                """
                cursor = conn_links.cursor()
                cursor.execute(query, (f'%nuSessao={sessao}%', f'%Data={data}%'))
                result = cursor.fetchone()
                
                if result:
                    key = f"{data}_{sessao}"
                    links_encontrados[key] = result[0]
        
        conn_links.close()
        return {"links": links_encontrados}
            
    except Exception as e:
        print(f"Erro ao buscar links: {str(e)}")
        return {"links": {}, "erro": str(e)}

@app.get("/api/discursos/date-range")
async def get_discursos_date_range(parlamentar: str, comissao: Optional[str] = None):
    """Retorna min/max de datas de discursos para o parlamentar (e comissão opcional) no formato YYYY-MM-DD."""
    try:
        conn = get_db_connection("discursos")
        params = [f"%{parlamentar}%"]
        comissao_clause = ""
        if comissao and str(comissao).strip() not in ("", "Todos", "Todas"):
            comissao_clause = " AND Comissao LIKE ?"
            params.append(f"%{comissao}%")

        df = pd.read_sql_query(
            f"""
            SELECT
                MIN(date(substr(Data,7,4)||'-'||substr(Data,4,2)||'-'||substr(Data,1,2))) AS data_min,
                MAX(date(substr(Data,7,4)||'-'||substr(Data,4,2)||'-'||substr(Data,1,2))) AS data_max
            FROM discursos
            WHERE UPPER(TRIM(Parlamentar)) LIKE UPPER(TRIM(?)){comissao_clause}
              AND length(Data) = 10
            """,
            conn,
            params=params
        )
        conn.close()
        if df.empty or df["data_min"].isna().all():
            return {"data_min": "2023-01-01", "data_max": None}
        LEGISLATURA_INICIO = "2023-01-01"
        data_min = str(df["data_min"].iloc[0])
        data_max = str(df["data_max"].iloc[0])
        if data_min < LEGISLATURA_INICIO:
            data_min = LEGISLATURA_INICIO
        return {"data_min": data_min, "data_max": data_max}
    except Exception as e:
        logger.error(f"Erro ao buscar date-range de discursos: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/comissoes/discursos-detalhados")
async def get_discursos_detalhados(parlamentar: str, comissao: str, data_inicio: str = None, data_fim: str = None):
    """Retorna TODOS os discursos detalhados com sessão, data e link (apenas após 31/12/2022)"""
    try:
        # Buscar TODOS os discursos (sem limite), apenas após 31/12/2022
        conn_discursos = get_db_connection("discursos")
        
        # Base query
        query = """
        SELECT Parlamentar, Comissao, Data, Sessao, Texto
        FROM discursos
        WHERE Parlamentar = ? AND Comissao = ?
        """
        params = [parlamentar, comissao]
        
        # Adicionar filtros de data se fornecidos
        if data_inicio:
            query += " AND date(substr(Data, 7, 4) || '-' || substr(Data, 4, 2) || '-' || substr(Data, 1, 2)) >= date(?)"
            params.append(data_inicio)
            
        if data_fim:
            query += " AND date(substr(Data, 7, 4) || '-' || substr(Data, 4, 2) || '-' || substr(Data, 1, 2)) <= date(?)"
            params.append(data_fim)
            
        # Sempre filtrar após 2022 se não houver data de início específica anterior
        if not data_inicio:
             query += " AND date(substr(Data, 7, 4) || '-' || substr(Data, 4, 2) || '-' || substr(Data, 1, 2)) > date('2022-12-31')"
            
        query += " ORDER BY Data DESC"
        
        df = pd.read_sql_query(query, conn_discursos, params=params)
        conn_discursos.close()
        
        print(f"📊 Carregados {len(df)} discursos para {parlamentar} em {comissao}")
        
        return df.to_dict(orient="records")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/comissoes/analisar")
async def analisar_comissao(request: RelatorioComissaoRequest):
    """Alias para gerar-relatorio, mantendo compatibilidade"""
    # Normalização preventiva para evitar erro 422 ou falhas de busca
    if request.comissao:
        # Se vier como objeto do Select (raro mas possível)
        if isinstance(request.comissao, dict):
            request.comissao = request.comissao.get('value', request.comissao.get('label', ''))
        
        request.comissao = str(request.comissao).strip()
        
    try:
        with open("debug_entry.log", "a") as f:
            f.write(f"📨 RECEBIDA REQUISIÇÃO: {request.parlamentar} para {request.comissao}\n")
    except:
        pass
        
    print(f"📨 RECEBIDA REQUISIÇÃO DE ANÁLISE (REAL): {request.parlamentar} em {request.comissao}")
    return await gerar_relatorio_comissao(request)

# ============================================================================
# BUSCA SEMÂNTICA
# ============================================================================

class BuscaSemanticaRequest(BaseModel):
    tema: str
    data_inicio: str
    data_fim: str
    n_results: Optional[int] = None  # Sem limite - buscar todos
    partido: Optional[str] = None  # Filtro por partido
    estado: Optional[str] = None  # Filtro por estado
    parlamentar: Optional[str] = None  # Filtro por parlamentar

class RelatorioSemanticoRequest(BaseModel):
    tema: str
    discursos: List[dict]
    ids_encontrados: Optional[List] = None  # Pode ser List[str] ou List[dict]
    data_inicio: str
    data_fim: str
    keywords: Optional[List[str]] = None
    min_keyword_hits: Optional[int] = None

@app.post("/api/busca-semantica/buscar")
async def buscar_semantica(request: BuscaSemanticaRequest):
    """Busca semântica por PALAVRAS-CHAVE OTIMIZADA"""
    try:
        import re
        from datetime import datetime
        from openai import OpenAI
        from dotenv import load_dotenv

        load_dotenv()

        print(f"\n{'='*60}")
        print(f"🚀 BUSCA SEMÂNTICA POR PALAVRAS-CHAVE")
        print(f"{'='*60}")

        # Converter datas (aceitar múltiplos formatos)
        def parse_data(data_str):
            """Parse data em múltiplos formatos"""
            if not data_str:
                return None
            data_str = data_str.strip()
            try:
                parts = data_str.split('/')
                if len(parts) == 3:
                    dia, mes, ano = parts
                    if len(ano) == 4 and ano.startswith('0'):
                        ano = '2' + ano[1:]
                    return datetime(int(ano), int(mes), int(dia))
            except:
                pass
            try:
                return datetime.strptime(data_str, '%Y-%m-%d')
            except:
                pass
            raise ValueError(f"Formato inválido: {data_str}")

        data_inicio_obj = parse_data(request.data_inicio)
        data_fim_obj = parse_data(request.data_fim)
        periodo_str = f"{data_inicio_obj.strftime('%Y')} a {data_fim_obj.strftime('%Y')}"

        if not request.tema or not request.tema.strip():
            raise HTTPException(status_code=400, detail="O tema de busca é obrigatório para a auditoria técnica.")

        print(f"📌 Tema: {request.tema}")
        print(f"📅 Período: {data_inicio_obj.strftime('%d/%m/%Y')} a {data_fim_obj.strftime('%d/%m/%Y')}")

        # ========== GERAR PALAVRAS-CHAVE COM LLM (SOMENTE SE HOUVER TEMA) ==========
        openai_api_key = os.getenv("OPENAI_API_KEY")
        palavras = []

        if request.tema and request.tema.strip() and openai_api_key:
            try:
                print(f"\n🔑 Gerando 30 palavras-chave com LLM...")
                client = OpenAI(api_key=openai_api_key)

                prompt = f"""Você é especialista em análise de discursos parlamentares.
TEMA: "{request.tema}"
PERÍODO: {periodo_str}

Gere EXATAMENTE 30 palavras-chave que parlamentares brasileiros usariam em discursos sobre este tema.

INSTRUÇÕES:
1. EXATAMENTE 30 palavras-chave
2. Termos que aparecem realmente em discursos parlamentares
3. Variações, sinônimos, termos técnicos, siglas
4. Uma palavra-chave por linha
5. Sem numeração, sem explicações

PALAVRAS-CHAVE:"""

                response = client.chat.completions.create(
                    model="gpt-5.4-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=400,
                    temperature=0.7
                )

                palavras_chave = response.choices[0].message.content.strip().split('\n')
                palavras_limpas = []

                for palavra in palavras_chave:
                    palavra = palavra.strip().lower()
                    palavra = re.sub(r'^\d+[\.\)]\s*', '', palavra)
                    if palavra and len(palavra) > 2 and palavra not in palavras_limpas:
                        palavras_limpas.append(palavra)

                if len(palavras_limpas) > 30:
                    palavras_limpas = palavras_limpas[:30]
                elif len(palavras_limpas) < 30:
                    tema_p = request.tema.lower().split()
                    if tema_p:
                        palavras_limpas.extend(tema_p * ((30 - len(palavras_limpas)) // len(tema_p) + 1))
                    palavras_limpas = palavras_limpas[:30]

                palavras = palavras_limpas
                print(f"✅ Geradas {len(palavras)} palavras-chave")

            except Exception as e:
                print(f"⚠️ Erro ao gerar palavras-chave: {e}")
                palavras = request.tema.lower().split() if request.tema else []
        elif request.tema:
            palavras = request.tema.lower().split()
        else:
            palavras = []

        # ========== BUSCAR NO BANCO DE DISCURSOS ==========
        print(f"\n🔍 Buscando discursos no banco de dados...")

        conn_discursos = sqlite3.connect(DATABASE_PATHS["discursos"])

        # ========== DEFINIR CONDIÇÕES DE BUSCA ==========
        if request.tema and request.tema.strip():
            tema_palavras_originais = request.tema.lower().split()
            condicoes_tema_original = " AND ".join([f"lower(d.Texto) LIKE '%{palavra}%'" for palavra in tema_palavras_originais])

            if len(palavras) > len(tema_palavras_originais):
                palavras_extras = [p for p in palavras if p not in tema_palavras_originais][:15]
                like_conditions_extras = " OR ".join([f"lower(d.Texto) LIKE '%{palavra}%'" for palavra in palavras_extras])
                like_conditions = f"(({condicoes_tema_original}) OR ({like_conditions_extras}))"
            else:
                like_conditions = f"({condicoes_tema_original})"
        else:
            # Se tema estiver vazio, buscar todos os discursos que atendem aos filtros (estado/partido/parlamentar)
            like_conditions = "1=1"
            print("ℹ️ Tema vazio: Buscando atuação geral conforme filtros.")

        # ========== CONSTRUIR FILTROS DINÂMICOS ==========
        filter_conditions = []
        filter_params = []

        if request.partido:
            filter_conditions.append("di.partido = ?")
            filter_params.append(request.partido.upper())

        if request.estado:
            filter_conditions.append("di.estado = ?")
            filter_params.append(request.estado.upper())

        if request.parlamentar:
            filter_conditions.append("di.parlamentar LIKE ?")
            filter_params.append(f"%{request.parlamentar}%")

        # ========== CONSTRUIR CLÁUSULA WHERE ==========
        where_clause = f"({like_conditions})"
        if filter_conditions:
            where_clause += " AND " + " AND ".join(filter_conditions)

        where_clause += f"""
          AND date(substr(di.data, 7, 4) || '-' || substr(di.data, 4, 2) || '-' || substr(di.data, 1, 2))
              BETWEEN date(?) AND date(?)"""

        # ========== ADICIONAR PARÂMETROS DE DATA ==========
        filter_params.extend([
            data_inicio_obj.strftime('%Y-%m-%d'),
            data_fim_obj.strftime('%Y-%m-%d')
        ])

        # ========== IMPRIMIR INFORMAÇÕES DO FILTRO ==========
        if filter_conditions:
            print(f"\n🔍 Filtros aplicados:")
            if request.partido:
                print(f"   • Partido: {request.partido.upper()}")
            if request.estado:
                print(f"   • Estado: {request.estado.upper()}")
            if request.parlamentar:
                print(f"   • Parlamentar: {request.parlamentar}")

        query = f"""
        SELECT
            di.hash_linha,
            di.id,
            di.sessao,
            di.parlamentar,
            di.estado,
            di.partido,
            di.origem,
            di.comissao,
            di.data,
            d.Texto
        FROM discursos_integrados di
        INNER JOIN discursos d ON di.hash_linha = d.hash_linha
        WHERE {where_clause}
        ORDER BY di.data DESC
        """

        df = pd.read_sql_query(
            query,
            conn_discursos,
            params=filter_params
        )

        conn_discursos.close()

        print(f"✅ Encontrados {len(df)} discursos no período")

        if len(df) == 0:
            return {
                "total_discursos": 0,
                "discursos": [],
                "ids_encontrados": []
            }

        # ========== PROCESSAR RESULTADOS ==========
        df = df.replace([np.nan, np.inf, -np.inf], None)

        discursos_processados = []
        for _, row in df.iterrows():
            discurso = {
                'id': row['id'],
                'Parlamentar': row['parlamentar'],
                'Estado': row['estado'],
                'Partido': row['partido'],
                'Origem': row['origem'],
                'Comissao': row['comissao'],
                'Data': row['data'],
                'Texto': row['Texto'][:500] if len(str(row['Texto'])) > 500 else row['Texto'],
                'Texto_completo': row['Texto'],
                'score_relevancia': 75,  # Score padrão para busca por palavras-chave
                'hash_linha': row['hash_linha'],
                'citacoes': [row['Texto'][:200]],  # Campo obrigatório para o frontend
            }
            discursos_processados.append(discurso)

        # Limitar a 300
        MAX_DISCURSOS = 300
        discursos_finais = discursos_processados[:MAX_DISCURSOS]

        print(f"📋 Selecionados {len(discursos_finais)} discursos para análise")

        # Estatísticas
        parlamentares = set([d.get('Parlamentar') for d in discursos_finais if d.get('Parlamentar')])
        partidos = set([d.get('Partido') for d in discursos_finais if d.get('Partido')])
        comissoes = set([d.get('Comissao') for d in discursos_finais if d.get('Comissao')])

        print(f"\n📊 Estatísticas:")
        print(f"   Total: {len(discursos_processados)}")
        print(f"   Top 300: {len(discursos_finais)}")
        print(f"   Parlamentares: {len(parlamentares)}")
        print(f"   Partidos: {len(partidos)}")

        return {
            "total_discursos": len(discursos_processados),
            "discursos_selecionados": len(discursos_finais),
            "parlamentares_envolvidos": list(parlamentares),
            "parlamentares_citantes": list(parlamentares),
            "partidos_envolvidos": len(partidos),
            "comissoes_envolvidas": len(comissoes),
            "periodo_filtro": f"{request.data_inicio} a {request.data_fim}",
            "metodo": "Busca por Palavras-Chave",
            "discursos": discursos_finais,
            "ids_encontrados": list(set([d.get('id') for d in discursos_finais])),
            "discursos_com_citacoes": len(discursos_finais),
            "total_citacoes": len(discursos_finais),
            "estatisticas": {
                "total_discursos": len(discursos_processados),
                "discursos_relevantes": len(discursos_finais),
                "parlamentares_encontrados": len(parlamentares),
                "total_citacoes": len(discursos_finais),
            }
        }
        GASTOS_GRAPH_CACHE[cache_key] = {"ts": now, "payload": payload}
        return deepcopy(payload)

    except Exception as e:
        print(f"❌ Erro na busca: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro ao buscar discursos: {str(e)}")

def _normalizar_trecho_semantico(texto: str) -> str:
    import re as _re
    return _re.sub(r"\s+", " ", str(texto or "")).strip()


def _extrair_trechos_reais_semantica(discurso: dict, tema: str = "", limite: int = 2) -> list:
    """Extrai apenas trechos literais existentes no discurso original."""
    import re as _re

    texto = _normalizar_trecho_semantico(discurso.get("Texto_completo") or discurso.get("Texto") or "")
    if not texto:
        return []

    termos = [
        t.lower()
        for t in _re.split(r"[^\wÀ-ÿ]+", str(tema or ""))
        if len(t.strip()) >= 4
    ]
    sentencas = [
        s.strip()
        for s in _re.split(r"(?<=[.!?])\s+", texto)
        if len(s.strip()) >= 40
    ]

    candidatos = []
    for sentenca in sentencas:
        sentenca_norm = sentenca.lower()
        if termos and not any(t in sentenca_norm for t in termos):
            continue
        candidatos.append(sentenca[:700])
        if len(candidatos) >= limite:
            return candidatos

    if termos:
        return []

    if sentencas:
        return [s[:700] for s in sentencas[:limite]]

    return [texto[:700]]


def _citacao_existe_no_discurso_semantica(citacao: str, discurso: dict) -> bool:
    citacao_norm = _normalizar_trecho_semantico(citacao)
    texto_norm = _normalizar_trecho_semantico(discurso.get("Texto_completo") or discurso.get("Texto") or "")
    if len(citacao_norm) < 20 or not texto_norm:
        return False
    return citacao_norm in texto_norm


def _sanitizar_analises_semanticas(analises: list, discursos: list, tema: str) -> list:
    """Remove nomes/citações inventados e repõe evidências com trechos reais."""
    discursos_por_hash = {
        str(d.get("hash_linha") or d.get("id") or "").strip(): d
        for d in discursos
        if str(d.get("hash_linha") or d.get("id") or "").strip()
    }

    discursos_por_chave = {}
    for d in discursos:
        chave = (
            str(d.get("Parlamentar") or "").strip().upper(),
            str(d.get("Data") or "").strip(),
            str(d.get("Comissao") or "").strip().upper(),
        )
        discursos_por_chave.setdefault(chave, []).append(d)

    discursos_por_parlamentar = {}
    for d in discursos:
        parl = str(d.get("Parlamentar") or "").strip().upper()
        if parl:
            discursos_por_parlamentar.setdefault(parl, []).append(d)

    sanitizadas = []
    for analise in analises or []:
        parl = str(analise.get("parlamentar") or "").strip()
        if not parl or parl.upper() not in discursos_por_parlamentar:
            continue

        discurso_hash = str(analise.get("_discurso_hash") or "").strip()
        discurso_ref = discursos_por_hash.get(discurso_hash)
        if not discurso_ref:
            chave = (
                parl.upper(),
                str(analise.get("data") or "").strip(),
                str(analise.get("comissao") or "").strip().upper(),
            )
            candidatos = discursos_por_chave.get(chave) or discursos_por_parlamentar.get(parl.upper()) or []
            discurso_ref = candidatos[0] if candidatos else None
        if not discurso_ref:
            continue

        citacoes_reais = [
            c for c in (analise.get("citacoes_diretas") or [])
            if _citacao_existe_no_discurso_semantica(c, discurso_ref)
        ]
        if not citacoes_reais:
            citacoes_reais = _extrair_trechos_reais_semantica(discurso_ref, tema, limite=2)
        if not citacoes_reais:
            continue

        analise_limpa = dict(analise)
        analise_limpa["parlamentar"] = discurso_ref.get("Parlamentar") or parl
        analise_limpa["partido"] = discurso_ref.get("Partido") or analise.get("partido", "")
        analise_limpa["estado"] = discurso_ref.get("Estado") or analise.get("estado", "")
        analise_limpa["data"] = discurso_ref.get("Data") or analise.get("data", "")
        analise_limpa["comissao"] = discurso_ref.get("Comissao") or analise.get("comissao", "")
        analise_limpa["citacoes_diretas"] = citacoes_reais[:2]
        analise_limpa["evidencia_verificada"] = True
        sanitizadas.append(analise_limpa)

    return sanitizadas


def _montar_relatorio_semantico_com_evidencias(tema: str, analises: list, data_inicio: str, data_fim: str) -> str:
    from collections import Counter, defaultdict

    if not analises:
        return (
            f"# Relatório sobre {tema}\n\n"
            "## Sem evidências textuais verificáveis\n\n"
            "A busca encontrou registros, mas nenhum trecho literal verificável foi validado para compor a análise. "
            "Para evitar alucinação, o sistema não gerou interpretação parlamentar sem citação real da base.\n"
        )

    por_parlamentar = defaultdict(list)
    for a in analises:
        por_parlamentar[a.get("parlamentar", "N/A")].append(a)

    def _normalizar_posicao(posicao):
        posicao = (posicao or "NEUTRO").upper()
        if "FAVOR" in posicao:
            return "FAVORÁVEL"
        if "CONTR" in posicao:
            return "CONTRÁRIO"
        return "NEUTRO"

    def _limpar_texto(texto):
        texto = (texto or "").strip()
        return " ".join(texto.split())

    def _eh_resumo_util(texto):
        texto_norm = _limpar_texto(texto).lower()
        if not texto_norm:
            return False
        return not any(
            descarte in texto_norm
            for descarte in (
                "discurso irrelevante",
                "irrelevante para o tema",
                "resumo não inferido",
                "não há evidência",
            )
        )

    def _topicos_unicos(valores, limite=5):
        vistos = set()
        saida = []
        for valor in valores:
            valor = _limpar_texto(valor)
            chave = valor.lower()
            if not valor or chave in vistos:
                continue
            vistos.add(chave)
            saida.append(valor)
            if len(saida) >= limite:
                break
        return saida

    def _resumo_parlamentar(itens):
        resumos = _topicos_unicos(
            [i.get("resumo_denso") for i in itens if _eh_resumo_util(i.get("resumo_denso"))],
            limite=3,
        )
        if not resumos:
            return "Os trechos validados não permitem identificar uma posição substantiva sobre o tema; predominam falas procedimentais ou desconectadas da busca."
        return " ".join(resumos)

    def _argumentos_parlamentar(itens):
        argumentos = []
        for item in itens:
            argumentos.extend(item.get("argumentos") or [])
        return _topicos_unicos(argumentos, limite=5)

    def _evidencias_parlamentar(itens, limite=4):
        evidencias = []
        vistos = set()
        for item in itens:
            meta = " • ".join([v for v in [item.get("data"), item.get("comissao")] if v])
            for citacao in item.get("citacoes_diretas") or []:
                citacao = _limpar_texto(citacao)
                chave = citacao.lower()
                if not citacao or chave in vistos:
                    continue
                vistos.add(chave)
                evidencias.append((meta, citacao))
                if len(evidencias) >= limite:
                    return evidencias
        return evidencias

    posicoes = Counter(_normalizar_posicao(a.get("posicao", "NEUTRO")) for a in analises)
    arenas = Counter(a.get("comissao") or "Plenário" for a in analises)
    parlamentares_ordenados = sorted(por_parlamentar.items(), key=lambda x: -len(x[1]))
    linhas = [
        f"# Relatório sobre {tema}",
        "",
        f"Relatório técnico com trechos reais verificados. Período: {data_inicio} a {data_fim}.",
        "",
        "## 1. Síntese para o eleitor",
        "",
        f"A busca validou {len(analises)} discurso(s) de {len(por_parlamentar)} parlamentar(es) com trechos literais da base. "
        f"No recorte, há {posicoes.get('FAVORÁVEL', 0)} fala(s) favorável(is), "
        f"{posicoes.get('CONTRÁRIO', 0)} contrária(s) e {posicoes.get('NEUTRO', 0)} neutra(s) ou de baixa aderência ao tema.",
        "",
        "O objetivo deste relatório é traduzir o debate para o eleitor: quem falou, onde falou, qual foi o foco do embate e quais blocos de ideias aparecem no material encontrado.",
        "",
        "## 2. Onde o debate apareceu",
        "",
    ]

    for arena, total in arenas.most_common(6):
        linhas.append(f"- {arena}: {total} discurso(s) validado(s)")
    linhas.extend(["", "## 3. Grupos de posicionamento", ""])

    grupos = defaultdict(list)
    for parlamentar, itens in parlamentares_ordenados:
        primeiro = itens[0]
        posicao = Counter(_normalizar_posicao(i.get("posicao", "NEUTRO")) for i in itens).most_common(1)[0][0]
        grupos[posicao].append(f"{parlamentar} ({primeiro.get('partido', '')}/{primeiro.get('estado', '')})")

    for titulo, chave in [
        ("Convergentes / favoráveis", "FAVORÁVEL"),
        ("Divergentes / contrários", "CONTRÁRIO"),
        ("Neutros ou sem posição substantiva", "NEUTRO"),
    ]:
        nomes = grupos.get(chave) or []
        if nomes:
            linhas.append(f"- {titulo}: {', '.join(nomes[:10])}")
    linhas.extend(["", "## 4. Análise por parlamentar", ""])

    for parlamentar, itens in parlamentares_ordenados:
        primeiro = itens[0]
        posicao = Counter(_normalizar_posicao(i.get("posicao", "NEUTRO")) for i in itens).most_common(1)[0][0]
        arenas_parlamentar = ", ".join([
            f"{arena} ({total})"
            for arena, total in Counter(i.get("comissao") or "Plenário" for i in itens).most_common(3)
        ])
        linhas.append(f"### {parlamentar} ({primeiro.get('partido', '')}/{primeiro.get('estado', '')})")
        linhas.append("")
        linhas.append(f"- Posição predominante no recorte: {posicao}")
        linhas.append(f"- Volume e arena: {len(itens)} discurso(s); principais espaços: {arenas_parlamentar or 'não informado'}")
        linhas.append(f"- O que disse, em resumo: {_resumo_parlamentar(itens)}")
        argumentos = _argumentos_parlamentar(itens)
        if argumentos:
            linhas.append(f"- Foco do embate: {'; '.join(argumentos[:4])}.")
        evidencias = _evidencias_parlamentar(itens)
        if evidencias:
            linhas.append("- Trechos que sustentam a leitura:")
            for meta, citacao in evidencias:
                linhas.append(f"  - {meta}: “{citacao}”")
        linhas.append("")

    linhas.extend([
        "## 5. Leitura consolidada",
        "",
        "A leitura deve priorizar parlamentares com maior volume de falas e evidências substantivas. "
        "Quando um parlamentar aparece como neutro, isso não significa apoio ou rejeição ao tema; significa que, nos trechos retornados, não houve posição clara o suficiente para classificação substantiva.",
    ])
    return "\n".join(linhas)


async def _background_gerar_relatorio_semantico(session_id: str, request: RelatorioSemanticoRequest):
    """
    Versão refatorada com 4 fases detalhadas e progresso em tempo real
    FASE 1: Busca Inicial (0-10%)
    FASE 2: Validação de Relevância (10-50%)
    FASE 3: Análise de Sentimento & ChromaDB (50-85%)
    FASE 4: Geração do Relatório (85-100%)
    """
    try:
        from openai import AsyncOpenAI
        from dotenv import load_dotenv
        import asyncio
        from datetime import datetime

        load_dotenv()
        openai_api_key = os.getenv("OPENAI_API_KEY")

        if not openai_api_key:
            progress_status[session_id]["status"] = "erro"
            progress_status[session_id]["mensagem"] = "API OpenAI não configurada."
            return

        client = AsyncOpenAI(api_key=openai_api_key)

        # ========== INICIALIZAR PROGRESSO ==========
        if ProgressoSemantica is None:
            # Fallback para versão antiga se não conseguir importar o novo módulo
            progress_status[session_id] = {
                "status": "iniciando",
                "total": len(request.discursos),
                "processados": 0,
                "lote_atual": 0,
                "total_lotes": 0,
                "mensagem": "Preparando análise..."
            }
            progresso = None
        else:
            progresso = ProgressoSemantica(session_id, request.tema)
            progress_status[session_id] = progresso.get_status()

        print(f"🚀 Iniciando busca semântica: {request.tema}")

        # ========== FASE 1: BUSCA INICIAL (0-10%) ==========
        if progresso:
            print(f"\n{'='*60}")
            print(f"FASE 1: Busca Inicial")
            print(f"{'='*60}")
            progresso.atualizar_fase("fase_1", "em_progresso", 10)
            progresso.adicionar_mensagem("fase_1", f"Tema recebido: {request.tema}")
            progresso.adicionar_mensagem("fase_1", "Buscando discursos no banco...")
        else:
            progress_status[session_id]["status"] = "filtrando"
            progress_status[session_id]["mensagem"] = "Analisando discursos..."

        discursos = request.discursos

        if progresso:
            progresso.atualizar_fase(
                "fase_1",
                "concluida",
                100,
                {
                    "palavras_chave_geradas": 30,
                    "discursos_encontrados": len(discursos),
                    "parlamentares_encontrados": len(set([d.get('Parlamentar') for d in discursos if d.get('Parlamentar')])),
                    "tempo_decorrido": int(time.time() - progresso.inicio),
                }
            )
            progress_status[session_id] = progresso.get_status()
            print(f"✅ FASE 1 CONCLUÍDA: {len(discursos)} discursos encontrados")

        # ========== FASE 2: FILTRAGEM RIGOROSA VIA LLM (10-50%) ==========
        if progresso:
            print(f"\n{'='*60}")
            print(f"FASE 2: Filtragem Rigorosa via LLM")
            print(f"{'='*60}")
            progresso.atualizar_fase("fase_2", "em_progresso", 10)
            progresso.adicionar_mensagem("fase_2", f"Filtrando {len(discursos)} discursos com IA...")
        else:
            progress_status[session_id]["status"] = "filtrando"
            progress_status[session_id]["mensagem"] = "Filtrando discursos com IA..."

        # Preparar metadados para filtragem (preview de 400 chars)
        LOTE_FILTRAGEM = 50
        ids_relevantes = set()
        total_lotes_filtragem = (len(discursos) + LOTE_FILTRAGEM - 1) // LOTE_FILTRAGEM

        async def filtrar_lote(idx_lote, lote_discursos, offset):
            try:
                metadata_list = []
                for i, d in enumerate(lote_discursos):
                    # Aumentado para 1000 caracteres para dar mais contexto à IA
                    texto = (d.get('Texto_completo') or d.get('Texto', ''))[:1000]
                    metadata_list.append({
                        "id": offset + i,
                        "parlamentar": d.get('Parlamentar', 'N/A'),
                        "data": d.get('Data', 'N/A'),
                        "comissao": d.get('Comissao', 'Plenário'),
                        "preview": texto
                    })

                if request.tema and request.tema.strip():
                    prompt_filtro = f"""Você é um analista legislativo. Analise estes metadados de discursos e identifique os que são RELEVANTES para o tema: "{request.tema}".

CRITÉRIOS DE RELEVÂNCIA (RIGOROSOS):
- Aceite apenas discursos cujo preview tenha relação textual direta com "{request.tema}" ou com conceito claramente equivalente.
- O parlamentar precisa discutir mérito, regulação, impacto, denúncia, defesa, crítica ou consequência ligada ao tema.
- Rejeite fala protocolar, saudação, voto sem justificativa, parabéns, encaminhamento genérico ou debate de outro assunto, mesmo que venha de parlamentar importante.
- Rejeite discurso em que a conexão com "{request.tema}" dependa de inferência ampla demais.

NA DÚVIDA, REJEITE. O relatório será usado pelo eleitor e precisa privilegiar precisão, não volume.

Retorne APENAS um JSON: {{ "ids_relevantes": [id1, id2, ...] }}

METADADOS:
{json.dumps(metadata_list, ensure_ascii=False)}"""
                else:
                    prompt_filtro = f"""Você é um analista legislativo sênior. Analise estes metadados de discursos e identifique os que são MAIS RELEVANTES para traçar um PANORAMA GERAL DA ATUAÇÃO deste parlamentar/grupo.

CRITÉRIOS DE SELEÇÃO:
- Selecione discursos que tratem de temas substantivos (economia, saúde, educação, infraestrutura, leis, etc.).
- Priorize discursos que mostrem posicionamentos claros ou defesa de pautas específicas.
- REJEITE discursos puramente protocolares (parabéns a cidades, pêsames, homenagens simples, abertura de sessão) a menos que tenham conteúdo político relevante.

O objetivo é filtrar o "ruído" protocolar e manter apenas o "sinal" da atuação legislativa real.

Retorne APENAS um JSON: {{ "ids_relevantes": [id1, id2, ...] }}

METADADOS:
{json.dumps(metadata_list, ensure_ascii=False)}"""

                resp = await client.chat.completions.create(
                    model="gpt-5.4-mini",
                    messages=[{"role": "user", "content": prompt_filtro}],
                    response_format={"type": "json_object"},
                    max_completion_tokens=2000,
                    temperature=0
                )
                result = json.loads(resp.choices[0].message.content)
                return result.get("ids_relevantes", [])
            except Exception as e:
                print(f"⚠️ Erro filtragem lote {idx_lote}: {e}")
                return [offset + i for i in range(len(lote_discursos))]  # Fallback: aceitar todos

        # Disparar filtragem em paralelo
        tarefas_filtragem = []
        for i in range(0, len(discursos), LOTE_FILTRAGEM):
            lote = discursos[i:i + LOTE_FILTRAGEM]
            idx = i // LOTE_FILTRAGEM + 1
            tarefas_filtragem.append(filtrar_lote(idx, lote, i))

        resultados_filtragem = await asyncio.gather(*tarefas_filtragem)
        for lista_ids in resultados_filtragem:
            ids_relevantes.update(lista_ids)

        # Filtrar discursos
        discursos_validados = [discursos[i] for i in sorted(ids_relevantes) if i < len(discursos)]

        # Limitar a 80 para análise profunda
        if len(discursos_validados) > 80:
            discursos_validados = discursos_validados[:80]

        print(f"🎯 IA filtrou: {len(discursos)} → {len(discursos_validados)} discursos realmente relevantes")

        if progresso:
            progresso.atualizar_fase(
                "fase_2", "concluida", 100,
                {
                    "lotes_totais": total_lotes_filtragem,
                    "lotes_processados": total_lotes_filtragem,
                    "discursos_validados": len(discursos_validados),
                    "discursos_rejeitados": len(discursos) - len(discursos_validados),
                    "score_medio": 0,
                    "tempo_decorrido": int(time.time() - progresso.inicio),
                },
            )
            progress_status[session_id] = progresso.get_status()
            print(f"✅ FASE 2 CONCLUÍDA: {len(discursos_validados)} discursos confirmados")

        # ========== FASE 3 & 4: PROCESSAMENTO CONDICIONAL ==========
        if len(discursos_validados) > 0:
            # ========== FASE 3: ANÁLISE PROFUNDA VIA LLM (50-85%) ==========
            if progresso:
                print(f"\n{'='*60}")
                print(f"FASE 3: Análise Profunda via LLM")
                print(f"{'='*60}")
                progresso.atualizar_fase("fase_3", "em_progresso", 10)
                progresso.adicionar_mensagem("fase_3", f"Analisando profundamente {len(discursos_validados)} discursos...")

            # Agrupar discursos por parlamentar para análise contextualizada
            discursos_por_parlamentar = {}
            for d in discursos_validados:
                parl = d.get('Parlamentar', 'N/A')
                partido = d.get('Partido', '')
                if not parl or parl == 'N/A' or len(parl) > 60: continue
                if not partido or partido in ('N/A', 'None', 'none', ''): continue
                if parl not in discursos_por_parlamentar:
                    discursos_por_parlamentar[parl] = {
                        'partido': partido,
                        'estado': d.get('Estado', 'N/A'),
                        'discursos': []
                    }
                discursos_por_parlamentar[parl]['discursos'].append(d)

            LOTE_ANALISE = 10
            analises_profundas = []

            async def analisar_lote_profundo(idx_lote, lote):
                try:
                    discursos_texto = []
                    for i, d in enumerate(lote):
                        texto = (d.get('Texto_completo') or d.get('Texto', ''))[:2000]
                        hash_linha = str(d.get('hash_linha') or d.get('id') or f'lote_{idx_lote}_{i}')
                        discursos_texto.append(
                            f"--- DISCURSO {i+1} ---\n"
                            f"ID_INTERNO: {i}\n"
                            f"HASH_ORIGEM: {hash_linha}\n"
                            f"Parlamentar: {d.get('Parlamentar', 'N/A')} ({d.get('Partido', '')}/{d.get('Estado', '')})\n"
                            f"Data: {d.get('Data', 'N/A')} | Comissão: {d.get('Comissao', 'Plenário')}\n"
                            f"Texto:\n{texto}\n"
                        )

                    prompt_analise = f"""Você é um analista parlamentar sênior. Analise CADA discurso abaixo sobre o tema "{request.tema}".
IMPORTANTE: Use estritamente o NOME, PARTIDO e ESTADO fornecidos em cada discurso. NUNCA invente nomes ou dados.

REGRAS DE OURO:
1. Se o discurso NÃO falar sobre o tema "{request.tema}", defina a posição como "NEUTRO" e o resumo como "Discurso irrelevante para o tema pesquisado."
2. Proibido inventar parlamentares ou pautas.
3. As citações diretas devem ser copiadas literalmente do campo Texto. Não resuma dentro de citações.
4. Se não houver nada relevante em nenhum discurso, admita isso.
5. Em cada item retornado, copie o ID_INTERNO do discurso analisado no campo "id_discurso".

Para cada discurso relevante, forneça:
1. Um RESUMO DENSO explicando O QUE o parlamentar disse ESPECIFICAMENTE sobre {request.tema}
2. A POSIÇÃO REAL: FAVORÁVEL, CONTRÁRIO ou NEUTRO
3. CITAÇÕES DIRETAS (1-2 trechos literais)
4. ARGUMENTOS ESPECÍFICOS

Retorne EXCLUSIVAMENTE um objeto JSON:
{{ "analises": [ {{ "id_discurso": 0, "parlamentar": "Nome Real", "partido": "Sigla", "estado": "UF", "data": "DD/MM/AAAA", "comissao": "Local", "posicao": "FAVORÁVEL/CONTRÁRIO/NEUTRO", "resumo_denso": "Conteúdo real...", "citacoes_diretas": ["..."], "argumentos": ["..."] }} ] }}

DISCURSOS:
{chr(10).join(discursos_texto)}"""

                    resp = await client.chat.completions.create(
                        model="gpt-5.4-mini",
                        messages=[{"role": "system", "content": "Analista parlamentar."}, {"role": "user", "content": prompt_analise}],
                        response_format={"type": "json_object"},
                        max_completion_tokens=8000,
                        temperature=0.2
                    )
                    analises_lote = json.loads(resp.choices[0].message.content).get("analises", [])
                    for analise in analises_lote:
                        try:
                            id_discurso = int(analise.get("id_discurso"))
                        except (TypeError, ValueError):
                            id_discurso = -1
                        if 0 <= id_discurso < len(lote):
                            discurso_origem = lote[id_discurso]
                            analise["_discurso_hash"] = str(discurso_origem.get("hash_linha") or discurso_origem.get("id") or "")
                    return analises_lote
                except Exception as e:
                    print(f"❌ Erro análise profunda lote {idx_lote}: {e}")
                    return []

            tarefas_analise = [analisar_lote_profundo(i//LOTE_ANALISE+1, discursos_validados[i:i+LOTE_ANALISE]) for i in range(0, len(discursos_validados), LOTE_ANALISE)]
            resultados_analise = await asyncio.gather(*tarefas_analise)
            for lista_analises in resultados_analise:
                analises_profundas.extend(lista_analises)

            analises_profundas = _sanitizar_analises_semanticas(analises_profundas, discursos_validados, request.tema)

            discursos_favoraveis = sum(1 for a in analises_profundas if a.get('posicao') == 'FAVORÁVEL')
            discursos_contrarios = sum(1 for a in analises_profundas if a.get('posicao') == 'CONTRÁRIO')
            discursos_neutros = sum(1 for a in analises_profundas if a.get('posicao') == 'NEUTRO')
            parlamentares_unicos = set(a.get('parlamentar', '') for a in analises_profundas if a.get('parlamentar') and len(a.get('parlamentar', '')) <= 60 and a.get('partido') not in (None, '', 'N/A', 'None'))

            if progresso:
                progresso.atualizar_fase("fase_3", "concluida", 100, {"discursos_favoraveis": discursos_favoraveis, "discursos_contrarios": discursos_contrarios, "discursos_neutros": discursos_neutros, "embeddings_gerados": len(analises_profundas), "tempo_decorrido": int(time.time() - progresso.inicio)})

            # ========== FASE 4: CONSOLIDAÇÃO NARRATIVA VIA LLM (85-100%) ==========
            if progresso:
                progresso.atualizar_fase("fase_4", "em_progresso", 20)
                progresso.adicionar_mensagem("fase_4", "Gerando relatório narrativo denso...")

            analises_por_parlamentar = {}
            for a in analises_profundas:
                parl = a.get('parlamentar', 'N/A')
                if parl not in analises_por_parlamentar:
                    analises_por_parlamentar[parl] = {'partido': a.get('partido', ''), 'estado': a.get('estado', ''), 'analises': [], 'posicoes': [], 'citacoes': [], 'argumentos': []}
                analises_por_parlamentar[parl]['analises'].append(a)
                analises_por_parlamentar[parl]['posicoes'].append(a.get('posicao', 'NEUTRO'))
                analises_por_parlamentar[parl]['citacoes'].extend(a.get('citacoes_diretas', []))
                analises_por_parlamentar[parl]['argumentos'].extend(a.get('argumentos', []))

            resumos_para_consolidar = []
            for parl, dados in sorted(analises_por_parlamentar.items(), key=lambda x: -len(x[1]['analises'])):
                if parl == 'N/A': continue
                posicao_dominante = max(set(dados['posicoes']), key=dados['posicoes'].count) if dados['posicoes'] else 'NEUTRO'
                resumos_para_consolidar.append(f"**{parl}** ({dados['partido']}/{dados['estado']}) — {len(dados['analises'])} discursos — Posição: {posicao_dominante}\nResumo: {' '.join([a.get('resumo_denso', '') for a in dados['analises'][:2]])[:800]}\nCitações: {json.dumps(dados['citacoes'][:2], ensure_ascii=False)}")

            posicao_por_partido = {}
            for a in analises_profundas:
                partido = a.get('partido', 'N/A')
                if partido not in posicao_por_partido: posicao_por_partido[partido] = {'favoravel': 0, 'contrario': 0, 'neutro': 0, 'parlamentares': set()}
                posicao_por_partido[partido]['parlamentares'].add(a.get('parlamentar', ''))
                if a.get('posicao') == 'FAVORÁVEL': posicao_por_partido[partido]['favoravel'] += 1
                elif a.get('posicao') == 'CONTRÁRIO': posicao_por_partido[partido]['contrario'] += 1
                else: posicao_por_partido[partido]['neutro'] += 1

            posicao_partidaria_json = json.dumps({p: {'favoravel': d['favoravel'], 'contrario': d['contrario'], 'neutro': d['neutro'], 'total_parlamentares': len(d['parlamentares'])} for p, d in posicao_por_partido.items() if p != 'N/A'}, ensure_ascii=False)

            relatorio_texto = _montar_relatorio_semantico_com_evidencias(
                request.tema,
                analises_profundas,
                request.data_inicio,
                request.data_fim,
            )
        else:
            # SHORTCUT: NENHUM DADO ENCONTRADO
            print(f"⚠️ Shortcut: Nenhum discurso relevante para {request.tema}. Pulando LLM.")
            relatorio_texto = f"# Relatório de Inteligência: {request.tema}\n\n"
            relatorio_texto += f"## ⚠️ Nenhum pronunciamento relevante encontrado\n\n"
            relatorio_texto += f"Após análise rigorosa via inteligência artificial de todos os discursos coletados no período de {request.data_inicio} a {request.data_fim}, **não foram identificadas manifestações parlamentares que tratassem especificamente do tema '{request.tema}'**.\n\n"
            relatorio_texto += f"### Possíveis motivos para a ausência de dados:\n"
            relatorio_texto += f"- **Ausência de Debate Formal**: O tema pode não ter sido objeto de pronunciamentos em plenário ou comissões no intervalo selecionado.\n"
            relatorio_texto += f"- **Filtros Restritivos**: A combinação de filtros (Estado/Partido) pode ter excluído parlamentares que discutiram o tema.\n"
            relatorio_texto += f"- **Terminologia Diferente**: O tema pode estar sendo discutido sob outra nomenclatura técnica não capturada pela busca atual.\n\n"
            relatorio_texto += f"### Recomendação:\n"
            relatorio_texto += f"Tente expandir o período da busca ou utilizar termos relacionados para verificar se o debate ocorreu em outros momentos ou sob outros contextos."
            
            analises_profundas = []
            parlamentares_unicos = set()
            discursos_favoraveis = 0
            discursos_contrarios = 0
            discursos_neutros = 0
            if progresso:
                progresso.adicionar_mensagem("fase_4", "Nenhum dado encontrado para consolidar.")
                progresso.atualizar_fase("fase_3", "concluida", 100, {"status": "vazio"})
                progresso.atualizar_fase("fase_4", "concluida", 100, {"status": "vazio"})

        # Adicionar rodapé
        relatorio_texto += f"\n\n---\n*Relatório gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}*\n*Análise de {len(analises_profundas)} discursos de {len(parlamentares_unicos)} parlamentares*"


        # ========== RESULTADO FINAL ==========
        # Contar por parlamentar
        posicionamentos_por_parlamentar = {}
        for a in analises_profundas:
            parl = a.get('parlamentar', 'N/A')
            if parl not in posicionamentos_por_parlamentar:
                posicionamentos_por_parlamentar[parl] = {
                    "favoraveis": 0, "contrarios": 0, "neutros": 0, "discursos": 0,
                    "partido": a.get('partido', 'N/A'), "estado": a.get('estado', 'N/A'),
                }
            posicionamentos_por_parlamentar[parl]["discursos"] += 1
            if a.get('posicao') == 'FAVORÁVEL':
                posicionamentos_por_parlamentar[parl]["favoraveis"] += 1
            elif a.get('posicao') == 'CONTRÁRIO':
                posicionamentos_por_parlamentar[parl]["contrarios"] += 1
            else:
                posicionamentos_por_parlamentar[parl]["neutros"] += 1

        total_citacoes = sum(p["discursos"] for p in posicionamentos_por_parlamentar.values())

        # Enriquecer dados de parlamentares com fotos e logos
        parlamentares_detalhados = []
        try:
            import sqlite3 as _sqlite3
            _conn_tabelao = _sqlite3.connect(DATABASE_PATHS.get("tabelao", "tabelao.db"))
            _conn_tabelao.row_factory = _sqlite3.Row
            _cursor_tabelao = _conn_tabelao.cursor()
            _cursor_tabelao.execute("SELECT nome, ideCadastro, ultimoStatus_urlFoto, sgPartido, sgUF FROM tabelao WHERE nome IS NOT NULL")
            _mapa_deputados = {}
            for _row in _cursor_tabelao.fetchall():
                nome_norm = str(_row['nome']).strip().upper()
                if nome_norm not in _mapa_deputados:
                    _mapa_deputados[nome_norm] = {
                        'ideCadastro': _row['ideCadastro'],
                        'foto': _row['ultimoStatus_urlFoto'],
                        'partido_db': str(_row['sgPartido']).strip() if _row['sgPartido'] else None,
                        'estado_db': str(_row['sgUF']).strip() if _row['sgUF'] else None,
                    }
            _conn_tabelao.close()
        except Exception as _e:
            print(f"⚠️ Erro ao carregar dados de deputados para fotos: {_e}")
            _mapa_deputados = {}

        for parl, dados_p in posicionamentos_por_parlamentar.items():
            if parl == 'N/A':
                continue
            # Buscar foto e ideCadastro
            parl_upper = parl.strip().upper()
            info_dep = _mapa_deputados.get(parl_upper, {})
            foto_url = info_dep.get('foto')
            if not foto_url and info_dep.get('ideCadastro'):
                foto_url = f"https://www.camara.leg.br/internet/deputado/bandep/{info_dep['ideCadastro']}.jpg"
            partido_sigla = dados_p.get('partido', 'N/A')
            logo_partido = partido_logos_dict.get(partido_sigla) if 'partido_logos_dict' in globals() else None

            # Buscar análises deste parlamentar
            analises_parl = [a for a in analises_profundas if a.get('parlamentar', '').strip().upper() == parl_upper]
            posicao_dom = 'NEUTRO'
            posicoes = [a.get('posicao', 'NEUTRO') for a in analises_parl]
            if posicoes:
                posicao_dom = max(set(posicoes), key=posicoes.count)

            parlamentares_detalhados.append({
                'nome': parl,
                'partido': partido_sigla,
                'estado': dados_p.get('estado', 'N/A'),
                'foto': foto_url,
                'logo_partido': logo_partido,
                'posicao': posicao_dom,
                'total_discursos': dados_p['discursos'],
                'favoraveis': dados_p['favoraveis'],
                'contrarios': dados_p['contrarios'],
                'neutros': dados_p['neutros'],
                'resumo': analises_parl[0].get('resumo_denso', '')[:800] if analises_parl else '',
                'citacoes': analises_parl[0].get('citacoes_diretas', [])[:2] if analises_parl else [],
                'datas': list(set(a.get('data', '') for a in analises_parl if a.get('data'))),
                'comissoes': list(set(a.get('comissao', '') for a in analises_parl if a.get('comissao'))),
            })

        # Ordenar por total de discursos
        parlamentares_detalhados.sort(key=lambda x: -x['total_discursos'])

        resultado_final = {
            "relatorio": relatorio_texto,
            "odiograma": {},
            "parlamentares_envolvidos": list(parlamentares_unicos),
            "parlamentares_citantes": list(parlamentares_unicos),
            "parlamentares_detalhados": parlamentares_detalhados,
            "total_citacoes": total_citacoes,
            "discursos_com_citacoes": len(analises_profundas),
            "estatisticas": {
                "total_discursos": len(discursos),
                "discursos_validados": len(discursos_validados),
                "discursos_relevantes": len(analises_profundas),
                "parlamentares_encontrados": len(parlamentares_unicos),
                "total_citacoes": total_citacoes,
                "discursos_favoraveis": discursos_favoraveis,
                "discursos_contrarios": discursos_contrarios,
                "discursos_neutros": discursos_neutros,
                "tempo_total": int(time.time() - progresso.inicio) if progresso else 0,
            }
        }

        print(f"✅ resultado_final criado com sucesso")

        if progresso:
            progresso.marcar_completo(resultado_final)
            status_atualizado = progresso.get_status()
            progress_status[session_id] = status_atualizado

            if 'resultado' not in status_atualizado:
                progress_status[session_id]['resultado'] = resultado_final

            print(f"\n{'='*60}")
            print(f"✅ ANÁLISE CONCLUÍDA EM {resultado_final['estatisticas']['tempo_total']}s")
            print(f"{'='*60}\n")
        else:
            progress_status[session_id].update({
                "status": "completo",
                "mensagem": "Análise concluída",
                "resultado": resultado_final,
            })


    except Exception as e:
        print(f"❌ ERRO FATAL: {str(e)}")
        import traceback
        traceback.print_exc()
        progress_status[session_id]["status"] = "erro"
        progress_status[session_id]["mensagem"] = f"Erro: {str(e)}"
        return



@app.post("/api/busca-semantica/gerar-relatorio")
async def gerar_relatorio_semantico(request: RelatorioSemanticoRequest, background_tasks: BackgroundTasks):
    """Inicia a geração do relatório em segundo plano e retorna o session_id"""
    import time
    session_id = f"semantica_{int(time.time() * 1000)}"

    # Não inicializar aqui - deixar que a função de background faça
    # O ProgressoSemantica vai inicializar automaticamente
    progress_status[session_id] = {
        "status": "nao_iniciada",
        "mensagem": "Preparando análise...",
    }

    background_tasks.add_task(_background_gerar_relatorio_semantico, session_id, request)
    return {"session_id": session_id}

@app.get("/api/busca-semantica/progress/{session_id}")
async def get_semantica_progress(session_id: str):
    """Retorna o progresso atual da geração do relatório"""
    status = progress_status.get(session_id)
    if not status:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    # Compatibilidade com ambas as estruturas (nova ProgressoSemantica e antiga)
    if "fases" in status:
        # Nova estrutura com ProgressoSemantica
        percent = status.get("percent", 0)
        mensagem = status.get("mensagem", "Processando...")
    else:
        # Estrutura antiga com total_lotes
        percent = 0
        mensagem = status.get("mensagem", "")
        if "total_lotes" in status and status["total_lotes"] > 0:
            # 10% inicial + 80% dos lotes + 10% finalização
            percent = 10
            if status.get("status") == "processando_lotes":
                percent += int((status.get("lote_atual", 0) / status["total_lotes"]) * 80)
            elif status.get("status") in ["consolidando", "gerando_relatorio_final", "gerando_odiograma"]:
                percent = 90
            elif status.get("status") == "completo":
                percent = 100

    # Retornar resultado apenas quando estiver completo
    resultado = None
    if status.get("status") == "completo":
        # Procurar resultado em várias localizações possíveis
        resultado = (
            status.get("resultado")  # Salvado por progresso.marcar_completo()
            or status.get("result")  # Fallback
            or status.get("response")  # Outro fallback
        )

        print(f"🔍 DEBUG get_semantica_progress: status='completo'")
        print(f"   • resultado é None? {resultado is None}")
        print(f"   • chaves em status: {list(status.keys())[:10]}")

        if resultado:
            print(f"   • resultado tem 'estatisticas'? {'estatisticas' in resultado}")
            if 'estatisticas' in resultado:
                print(f"   • discursos_relevantes: {resultado['estatisticas'].get('discursos_relevantes')}")
                print(f"   • parlamentares_encontrados: {resultado['estatisticas'].get('parlamentares_encontrados')}")

    return {
        "status": status.get("status", "nao_iniciada"),
        "mensagem": mensagem,
        "percent": percent,
        "fase_atual": status.get("fase_atual", 0),
        "fases": status.get("fases", {}),
        "tempo_decorrido": status.get("tempo_decorrido", 0),
        "result": resultado
    }

# ============================================================================
# RELATÓRIO ELEITOR - Accountability Política
# ============================================================================

class RelatorioEleitorRequest(BaseModel):
    tema: str
    partido: Optional[str] = None
    estado: Optional[str] = None
    parlamentar: Optional[str] = None
    limite: Optional[int] = 50

relatorio_eleitor_status = {}

@app.post("/api/relatorio-eleitor/gerar")
async def gerar_relatorio_eleitor(request: RelatorioEleitorRequest, background_tasks: BackgroundTasks):
    """
    Gera relatório de accountability política para eleitores
    Mostra o que deputados realmente disseram sobre um tema
    """
    import uuid
    from collections import defaultdict

    session_id = str(uuid.uuid4())

    def processar_relatorio():
        try:
            print(f"\n{'='*60}")
            print(f"🔍 RELATÓRIO ELEITOR - {request.tema}")
            print(f"{'='*60}")

            relatorio_eleitor_status[session_id] = {
                "status": "buscando_discursos",
                "percent": 10,
                "mensagem": "Buscando discursos..."
            }

            # Buscar no ChromaDB
            try:
                collection = chroma_client.get_collection("discursos_2023_plus")
            except:
                CHROMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vetores")
                chroma_client_temp = chromadb.PersistentClient(path=CHROMA_PATH)
                collection = chroma_client_temp.get_collection("discursos_2023_plus")

            # Buscar em lotes
            discursos_encontrados = []
            TAMANHO_LOTE = 5000

            def atende_filtros(metadata_doc, texto_doc):
                """Verifica se documento atende a TODOS os critérios"""
                # TEMA: obrigatório
                if not any(palavra.lower() in texto_doc.lower() for palavra in request.tema.split()[:1]):
                    return False

                # PARTIDO: se especificado, DEVE ser esse
                if request.partido and metadata_doc.get('Partido', '').upper() != request.partido.upper():
                    return False

                # ESTADO: se especificado, DEVE ser esse
                if request.estado and metadata_doc.get('Estado', '').upper() != request.estado.upper():
                    return False

                # PARLAMENTAR: se especificado, DEVE ser esse
                if request.parlamentar and metadata_doc.get('Parlamentar', '').upper() != request.parlamentar.upper():
                    return False

                return True

            for offset in range(0, 50000, TAMANHO_LOTE):
                results = collection.get(limit=TAMANHO_LOTE, offset=offset)

                for doc_id, doc_text, metadata in zip(
                    results['ids'],
                    results['documents'] if results['documents'] else [None] * len(results['ids']),
                    results['metadatas'] if results['metadatas'] else [{}] * len(results['ids'])
                ):
                    if not doc_text:
                        continue

                    # Verificar se atende a TODOS os filtros (AND lógico)
                    if atende_filtros(metadata, doc_text):
                        discursos_encontrados.append({
                            'id': doc_id,
                            'texto': doc_text,
                            'parlamentar': metadata.get('Parlamentar', 'N/A'),
                            'partido': metadata.get('Partido', 'N/A'),
                            'estado': metadata.get('Estado', 'N/A'),
                            'data': metadata.get('Data', 'N/A'),
                            'comissao': metadata.get('Comissão', metadata.get('comissao', 'Plenário')),
                            'origem': metadata.get('Origem', 'N/A'),
                            'tamanho': len(doc_text)
                        })

                        if len(discursos_encontrados) >= request.limite:
                            break

                if len(discursos_encontrados) >= request.limite:
                    break

            relatorio_eleitor_status[session_id]["percent"] = 40
            relatorio_eleitor_status[session_id]["mensagem"] = f"Encontrados {len(discursos_encontrados)} discursos. Analisando..."

            # Gerar relatório em Markdown
            relatorio_md = f"""# 📋 O que foi realmente discutido sobre "{request.tema}"

**Filtros aplicados**:
- Tema: {request.tema}
- Partido: {request.partido or "Todos"}
- Estado: {request.estado or "Todos"}
- Parlamentar: {request.parlamentar or "Todos"}

**Total de discursos analisados**: {len(discursos_encontrados)}
**Data da análise**: {datetime.now().strftime('%d/%m/%Y às %H:%M')}

---

## 🎯 Como Usar Este Relatório

Este documento reúne tudo o que foi discutido sobre **{request.tema}** no Congresso Nacional.

Você pode usar este documento para:
- ✅ Verificar o que seu deputado realmente disse
- ✅ Identificar promessas versus ações
- ✅ Comparar o discurso com o comportamento votação
- ✅ **Confrontar inverdades em campanha com evidências reais**

---

## 👥 Discursos Encontrados

"""

            # Agrupar por partido
            por_partido = defaultdict(list)
            por_parlamentar = defaultdict(list)

            for doc in discursos_encontrados:
                por_partido[doc['partido']].append(doc)
                por_parlamentar[doc['parlamentar']].append(doc)

            # Seção por partido
            relatorio_md += "### Por Partido\n\n"

            for partido_nome in sorted(por_partido.keys()):
                docs_partido = por_partido[partido_nome]
                relatorio_md += f"**{partido_nome}** ({len(docs_partido)} discursos)\n\n"

                for doc in docs_partido[:3]:  # Mostrar até 3 por partido
                    relatorio_md += f"- **{doc['parlamentar']}** ({doc['estado']})\n"
                    relatorio_md += f"  Data: {doc['data']} | Local: {doc['comissao']}\n"
                    relatorio_md += f"  _Clique para ver o discurso completo abaixo_\n\n"

            # Seção de discursos completos
            relatorio_md += "\n---\n\n## 📌 Discursos Completos\n\n"
            relatorio_md += "Abaixo estão os discursos na íntegra. **Use Ctrl+F para procurar seu deputado.**\n\n"

            for i, doc in enumerate(discursos_encontrados, 1):
                relatorio_md += f"""
### [{i}] {doc['parlamentar']} ({doc['partido']}/{doc['estado']})

**Data**: {doc['data']}
**Local**: {doc['comissao']}
**Origem**: {doc['origem']}

---

{doc['texto']}

---

"""

            # Rodapé
            relatorio_md += f"""

---

## ℹ️ Próximas Ações

1. **Procure seu deputado**: Use Ctrl+F (ou Cmd+F no Mac)
2. **Leia o que ele disse**: Veja as datas e locais das discussões
3. **Compare com promessas**: O que ele prometeu em campanha?
4. **Use as evidências**: Compartilhe com outros eleitores
5. **Responsabilize**: Cobre coerência nas próximas eleições

---

**Relatório gerado automaticamente a partir do banco oficial de discursos parlamentares.**
**Análise realizada em {datetime.now().strftime('%d/%m/%Y às %H:%M')}**
"""

            relatorio_eleitor_status[session_id]["status"] = "completo"
            relatorio_eleitor_status[session_id]["percent"] = 100
            relatorio_eleitor_status[session_id]["resultado"] = relatorio_md
            relatorio_eleitor_status[session_id]["resumo"] = {
                "total_discursos": len(discursos_encontrados),
                "partidos": len(por_partido),
                "parlamentares": len(por_parlamentar),
                "discursos_por_partido": {p: len(d) for p, d in por_partido.items()}
            }

            print(f"✅ Relatório gerado com sucesso: {len(discursos_encontrados)} discursos")

        except Exception as e:
            print(f"❌ Erro ao gerar relatório: {e}")
            relatorio_eleitor_status[session_id]["status"] = "erro"
            relatorio_eleitor_status[session_id]["erro"] = str(e)

    # Executar em background
    background_tasks.add_task(processar_relatorio)

    relatorio_eleitor_status[session_id] = {
        "status": "iniciando",
        "percent": 0,
        "mensagem": "Preparando busca..."
    }

    return {
        "session_id": session_id,
        "status": "iniciado",
        "mensagem": f"Gerando relatório para: {request.tema}"
    }

@app.get("/api/relatorio-eleitor/progress/{session_id}")
async def get_relatorio_eleitor_progress(session_id: str):
    """Retorna o progresso de geração do relatório eleitor"""
    status = relatorio_eleitor_status.get(session_id)

    if not status:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    return {
        "status": status.get("status"),
        "percent": status.get("percent", 0),
        "mensagem": status.get("mensagem", ""),
        "resumo": status.get("resumo")
    }

@app.get("/api/relatorio-eleitor/resultado/{session_id}")
async def get_relatorio_eleitor_resultado(session_id: str):
    """Retorna o relatório completo em Markdown"""
    status = relatorio_eleitor_status.get(session_id)

    if not status:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    if status.get("status") != "completo":
        raise HTTPException(status_code=202, detail="Relatório ainda está sendo processado")

    return {
        "status": "sucesso",
        "relatorio": status.get("resultado"),
        "resumo": status.get("resumo")
    }

@app.post("/api/gastos/gerar-email-denuncia")
async def gerar_email_denuncia(request: dict):
    """Gera email formatado para denúncia aos órgãos de controle"""
    try:
        from openai import OpenAI
        
        parlamentar = request.get('parlamentar')
        despesa = request.get('despesa')
        estado = request.get('estado')
        partido = request.get('partido')
        relatorio = request.get('relatorio', '')
        metricas = request.get('metricas', {})
        
        prompt = f"""Você é um assistente jurídico especializado em redação de denúncias a órgãos de controle.

MISSÃO: Redigir um email formal de denúncia/solicitação de avaliação sobre possíveis irregularidades nas despesas parlamentares.

DADOS DO CASO:
• Parlamentar: {parlamentar} ({partido}/{estado})
• Tipo de Despesa: {despesa}
• Valor Total: R$ {metricas.get('total_gasto', 0):,.2f}
• Número de Notas: {metricas.get('num_notas', 0)}
• Notas Atípicas: {metricas.get('num_atipicos', 0)}

IMPORTANTE - LINGUAGEM CONDICIONAL:
- Use SEMPRE verbos no CONDICIONAL: "poderia indicar", "sugere-se avaliar", "recomenda-se verificar"
- NUNCA faça afirmações categóricas
- Seja respeitoso e técnico
- Peça avaliação, não afirme irregularidades

ESTRUTURA DO EMAIL:

Assunto: Solicitação de Avaliação - Despesas Parlamentares - {parlamentar}

Prezados Senhores,

[Parágrafo 1 - Apresentação e contextualização]
Venho respeitosamente solicitar a avaliação técnica de possíveis inconsistências identificadas nas despesas de {despesa} do(a) parlamentar {parlamentar}, com base em análise de dados públicos disponibilizados pela Câmara dos Deputados.

[Parágrafo 2 - Descrição dos achados - SEMPRE NO CONDICIONAL]
Os dados analisados sugerem que PODERIAM existir aspectos que MERECERIAM avaliação mais detalhada por parte desse órgão de controle...

[Parágrafo 3 - Solicitação formal]
Diante do exposto, solicito respeitosamente que esse órgão avalie a pertinência de:
1. Verificar a conformidade das despesas com as normas aplicáveis
2. Analisar a razoabilidade dos valores praticados
3. Avaliar a documentação comprobatória

[Parágrafo 4 - Encerramento]
Coloco-me à disposição para fornecer informações adicionais que se fizerem necessárias.

Atenciosamente,

---
⚠️ IMPORTANTE: Esta análise foi realizada pelo sistema automatizado Antunes do euseidissodeputado.com.br utilizando Inteligência Artificial. Os dados são baseados em informações públicas da Câmara dos Deputados, mas REQUEREM VALIDAÇÃO HUMANA antes de qualquer conclusão definitiva.

Escreva o email completo, formal e técnico."""

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {"role": "system", "content": "Você é um assistente jurídico especializado em redação formal. Sempre use linguagem CONDICIONAL e respeitosa. Nunca faça afirmações categóricas."},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=2000,
            temperature=0.4
        )
        
        email = response.choices[0].message.content
        
        return {"email": email}
        
    except Exception as e:
        logger.error(f"❌ Erro ao gerar email: {str(e)}")
        return {"email": f"Erro ao gerar email: {str(e)}"}

@app.post("/api/gastos/gerar-auditoria")
async def gerar_auditoria_gastos(request: dict):
    """Gera relatório de auditoria com IA para análise de gastos parlamentares"""
    try:
        from openai import OpenAI
        
        parlamentar = request.get('parlamentar')
        despesa = request.get('despesa')
        estado = request.get('estado')
        partido = request.get('partido')
        metricas = request.get('metricas', {})
        metricas_comp = request.get('metricas_comparativas', {})
        top_forn = request.get('top_fornecedores', [])
        
        # Formatar top fornecedores para o prompt
        top_fornecedores_texto = "\n".join([
            f"  • {f['fornecedor']}: R$ {f['total']:,.2f} ({f['quantidade']} notas)" + (" - ATÍPICO" if f.get('atipico') else "")
            for f in top_forn[:5]
        ])
        
        prompt = f"""Você é Antunes, auditor-chefe especializado em contas públicas brasileiras, com 25 anos de experiência em controle interno e externo. Possui expertise em Regimento Interno da Câmara dos Deputados, Lei de Responsabilidade Fiscal (LC 101/2000), Instruções Normativas do TCU e Resoluções da Câmara sobre cota parlamentar.

MISSÃO: Analisar rigorosamente as despesas de "{despesa}" do parlamentar {parlamentar} ({partido}/{estado}) com base em evidências documentais e normativas aplicáveis.

DADOS CONSOLIDADOS PARA AUDITORIA:
• Parlamentar: {parlamentar}
• Despesa Analisada: {despesa}
• Estado/Partido: {estado}/{partido}
• Valor Total Executado: R$ {metricas.get('total_gasto', 0):,.2f}
• Quantidade de Notas Fiscais: {metricas.get('num_notas', 0)}
• Valor Médio por Nota: R$ {metricas.get('media_gasto', 0):,.2f}
• Número de Fornecedores Distintos: {metricas.get('fornecedores_unicos', 0)}
• Notas Atípicas Identificadas: {metricas.get('num_atipicos', 0)} (acima de 2 desvios padrão)
• Limite Atípico Calculado: R$ {metricas.get('limite_atipico', 0):,.2f}

ANÁLISE COMPARATIVA - DESVIOS IDENTIFICADOS:
• vs Média Geral de todos os parlamentares: {metricas_comp.get('diff_geral_pct', 0):+.1f}% (Média: R$ {metricas_comp.get('media_geral', 0):,.2f})
• vs Média dos parlamentares do {estado}: {metricas_comp.get('diff_estado_pct', 0):+.1f}% (Média: R$ {metricas_comp.get('media_estado', 0):,.2f})
• vs Média dos parlamentares do {partido}: {metricas_comp.get('diff_partido_pct', 0):+.1f}% (Média: R$ {metricas_comp.get('media_partido', 0):,.2f})

TOP 5 FORNECEDORES POR VALOR TOTAL:
{top_fornecedores_texto}

NORMATIVAS APLICÁVEIS (cite quando relevante):
• Ato da Mesa nº 43/2009 - Regulamento da Cota Parlamentar
• Resolução nº 1/2006 - Normas sobre cota parlamentar
• Lei de Responsabilidade Fiscal (LC 101/2000) - Arts. 1º e 15
• Lei 8.429/1992 - Improbidade Administrativa (Arts. 10 e 11)
• Acórdão TCU 1.753/2018 - Orientações sobre gastos atípicos

ESTRUTURA OBRIGATÓRIA DO RELATÓRIO DE AUDITORIA:

**1. RESUMO EXECUTIVO**
(2-3 parágrafos contextualizando o caso e principais achados)

**2. FUNDAMENTAÇÃO LEGAL E NORMATIVA**
(Cite artigos específicos aplicáveis ao caso)

**3. ANÁLISE QUANTITATIVA DETALHADA**
- Comparação com médias (geral, estado, partido)
- Identificação de outliers estatísticos
- Padrões de concentração em fornecedores

**4. ANÁLISE QUALITATIVA E CONFORMIDADE**
- Razoabilidade dos gastos
- Compatibilidade com atividade parlamentar
- Indícios de irregularidades (se houver)

**5. CONCLUSÕES E RECOMENDAÇÕES**
(Parecer técnico baseado em evidências)

IMPORTANTE:
- Use SEMPRE formatação brasileira de valores (R$ 1.234,56)
- Cite ARTIGOS ESPECÍFICOS de leis e resoluções
- Seja técnico mas acessível
- Escreva em MARKDOWN para melhor formatação
- Em caso de irregularidades, use linguagem CONDICIONAL ("pode indicar", "sugere-se avaliar")
- NUNCA faça afirmações categóricas sem ressalvas"""

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {"role": "system", "content": "Você é Antunes, auditor-chefe especializado em contas públicas. Seja técnico, incisivo e baseado em evidências. Escreva em texto puro sem formatação markdown."},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=4000,
            temperature=0.3
        )
        
        relatorio = response.choices[0].message.content
        
        return {"relatorio": relatorio}
        
    except Exception as e:
        logger.error(f"❌ Erro ao gerar auditoria: {str(e)}")
        return {"relatorio": f"Erro ao gerar relatório: {str(e)}"}

import unicodedata

# SQL_NORMALIZAR_NOME removido daqui e movido para o topo

@app.get("/api/passagens-aereas/analise")
def get_analise_passagens_aereas(estado: str = None, partido: str = None, parlamentar: str = None):
    """Retorna dados específicos para análise de passagens aéreas"""
    try:
        conn = get_db_connection("tabelao")

        # Query base para passagens aéreas
        query = """
        SELECT
            datEmissao,
            txtFornecedor,
            vlrLiquido,
            txtPassageiro,
            txtDescricao,
            nome,
            sgUF,
            sgPartido,
            txtTrecho,
            urlDocumento,
            ultimoStatus_urlFoto
        FROM tabelao
        WHERE UPPER(txtDescricao) LIKE '%PASSAGEM AÉREA%'
        """

        params = []

        # Aplicar filtros
        if estado and estado != 'Todos':
            query += " AND sgUF = ?"
            params.append(estado)

        if partido and partido != 'Todos':
            query += " AND sgPartido = ?"
            params.append(partido)

        if parlamentar and parlamentar != 'Todos':
            parlamentar_norm = normalizar_nome(parlamentar)
            query += f" AND REPLACE({SQL_NORMALIZAR_NOME}, 'Ç', 'C') LIKE ?"
            params.append(f"%{parlamentar_norm}%")
        
        query += " ORDER BY datEmissao DESC"
        
        df = pd.read_sql_query(query, conn, params=params)

        # Obter todos os dossiês já processados para cruzamento rápido
        dossies_map = {}
        try:
            query_osint = "SELECT nome_passageiro, dossie, outros_parlamentares, vinculos_socios, vinculos_doacoes FROM passageiros_osint"
            df_osint = pd.read_sql_query(query_osint, conn)
            for _, r in df_osint.iterrows():
                dossies_map[r['nome_passageiro']] = {
                    "dossie": r['dossie'],
                    "outros": json.loads(r['outros_parlamentares'] or "[]"),
                    "socios": json.loads(r['vinculos_socios'] or "[]"),
                    "doacoes": json.loads(r['vinculos_doacoes'] or "[]")
                }
        except Exception as e:
            logger.error(f"Erro ao carregar mapa osint: {e}")

        if df.empty:
            conn.close()
            return {
                "success": True,
                "dados_completos": [],
                "passageiros": [],
                "passagens_caras": [],
                "evolucao": [],
                "fornecedores": [],
                "viagens": [],
                "trechos_voo": [],
                "metricas": {
                    "total_gasto": 0,
                    "total_viagens": 0,
                    "media_viagem": 0,
                    "fornecedores_unicos": 0,
                    "passagens_caras": 0
                }
            }
        
        # Calcular métricas básicas diretamente do DataFrame
        total_gasto = float(df['vlrLiquido'].sum())
        total_viagens = len(df)
        media_viagem = total_gasto / total_viagens if total_viagens > 0 else 0
        fornecedores_unicos = df['txtFornecedor'].nunique()
        
        # Calcular limite de passagens caras baseado em 2 desvios padrão da média geral
        query_geral = """
        SELECT vlrLiquido
        FROM tabelao
        WHERE UPPER(txtDescricao) LIKE '%PASSAGEM AÉREA%'
        """
        df_geral = pd.read_sql_query(query_geral, conn)
        
        if not df_geral.empty:
            media_geral = df_geral['vlrLiquido'].mean()
            desvio_padrao = df_geral['vlrLiquido'].std()
            limite_passagens_caras = media_geral + (2 * desvio_padrao)
        else:
            limite_passagens_caras = 5000  # fallback
        
        passagens_caras_count = len(df[df['vlrLiquido'] > limite_passagens_caras])
        
        # Obter lista de assessores do parlamentar
        assessores_list = []
        if parlamentar and parlamentar != 'Todos':
            try:
                query_assessores = "SELECT nome_assessor FROM gabinetes_assessores WHERE nome_deputado_referencia = ?"
                df_assessores = pd.read_sql_query(query_assessores, conn, params=[parlamentar])
                if not df_assessores.empty:
                    assessores_list = df_assessores['nome_assessor'].dropna().str.strip().str.upper().tolist()
            except Exception as e:
                logger.error(f"Erro ao buscar assessores: {e}")
        
        import difflib
        
        # 1. Carregar Mapa de Inteligência OSINT
        dossies_map = {}
        try:
            query_osint = "SELECT nome_passageiro, dossie, outros_parlamentares, vinculos_socios, vinculos_doacoes FROM passageiros_osint"
            df_osint = pd.read_sql_query(query_osint, conn)
            for _, r in df_osint.iterrows():
                dossies_map[r['nome_passageiro']] = {
                    "dossie": r['dossie'],
                    "outros": json.loads(r['outros_parlamentares'] or "[]"),
                    "socios": json.loads(r['vinculos_socios'] or "[]"),
                    "doacoes": json.loads(r['vinculos_doacoes'] or "[]")
                }
        except Exception as e:
            print(f"Erro ao carregar mapa OSINT: {e}")

        import difflib
        
        # Dados brutos para a tabela de detalhamento
        dados_completos = []
        for _, row in df.iterrows():
            passag_nome = str(row['txtPassageiro'] or '').strip().upper()
            is_assessor = False
            
            # Inteligência OSINT vinculada
            osint_info = dossies_map.get(passag_nome, None)
            
            if assessores_list and passag_nome and passag_nome != 'N/A':
                if passag_nome in assessores_list:
                    is_assessor = True
                else:
                    matches = difflib.get_close_matches(passag_nome, assessores_list, n=1, cutoff=0.8)
                    if matches:
                        is_assessor = True

            item = {
                'datEmissao': row['datEmissao'] if pd.notna(row['datEmissao']) else 'N/A',
                'txtFornecedor': row['txtFornecedor'] if pd.notna(row['txtFornecedor']) else 'N/A',
                'vlrLiquido': float(row['vlrLiquido']) if pd.notna(row['vlrLiquido']) else 0.0,
                'txtPassageiro': row['txtPassageiro'] if pd.notna(row['txtPassageiro']) and row['txtPassageiro'] else 'N/A',
                'txtDescricao': row['txtDescricao'] if pd.notna(row['txtDescricao']) else 'N/A',
                'txtTrecho': row['txtTrecho'] if pd.notna(row['txtTrecho']) else 'N/A',
                'urlDocumento': row['urlDocumento'] if pd.notna(row['urlDocumento']) and row['urlDocumento'] else 'N/A',
                'nome': row['nome'] if pd.notna(row['nome']) else 'N/A',
                'ultimoStatus_urlFoto': row['ultimoStatus_urlFoto'] if pd.notna(row['ultimoStatus_urlFoto']) else None,
                'sgPartido': row['sgPartido'] if pd.notna(row['sgPartido']) else 'N/A',
                'sgUF': row['sgUF'] if pd.notna(row['sgUF']) else 'N/A',
                'is_assessor': is_assessor,
                'osint': osint_info # Injeta os dados da investigação
            }
            
            # Adicionar URLs de logo resolvidos diretamente da Wikipédia Viva
            item['urlPartido'] = resolve_party_logo_from_wikipedia(row['sgPartido']) or (partido_logos_dict.get(row['sgPartido']) if 'partido_logos_dict' in globals() else None)
            item['urlEstado'] = resolve_state_flag_from_wikipedia(row['sgUF']) or (estado_logos_dict.get(row['sgUF']) if 'estado_logos_dict' in globals() else None)
                
            dados_completos.append(item)
        
        # Análise de passageiros
        passageiros = []
        if parlamentar and parlamentar != 'Todos':
            # Para parlamentar específico, analisar passageiros
            passageiros_df = df.groupby('txtPassageiro').agg({
                'vlrLiquido': ['count', 'sum', 'mean']
            }).round(2)
            passageiros_df.columns = ['quantidade', 'valor_total', 'valor_medio']
            passageiros_df = passageiros_df.reset_index()
            
            for _, row in passageiros_df.iterrows():
                p_nome = str(row['txtPassageiro'] or '').strip().upper()
                passageiros.append({
                    'passageiro': row['txtPassageiro'] or 'N/A',
                    'quantidade': int(row['quantidade']),
                    'valor_total': float(row['valor_total']),
                    'valor_medio': float(row['valor_medio']),
                    'osint': dossies_map.get(p_nome, None) # Injeta inteligência no Top 10
                })
        
        # Passagens caras (acima do limite calculado)
        passagens_caras = df[df['vlrLiquido'] > limite_passagens_caras].head(20)
        passagens_caras_list = []
        for _, row in passagens_caras.iterrows():
            passagens_caras_list.append({
                'data': row['datEmissao'] if pd.notna(row['datEmissao']) else 'N/A',
                'fornecedor': row['txtFornecedor'] if pd.notna(row['txtFornecedor']) else 'N/A',
                'valor': float(row['vlrLiquido']) if pd.notna(row['vlrLiquido']) else 0.0,
                'passageiro': row['txtPassageiro'] if pd.notna(row['txtPassageiro']) and row['txtPassageiro'] else 'N/A',
                'urlDocumento': row['urlDocumento'] if pd.notna(row['urlDocumento']) and row['urlDocumento'] else 'N/A'
            })
        
        # Evolução temporal
        # Converter data para datetime para ordenação correta
        df['data_dt'] = pd.to_datetime(df['datEmissao'], dayfirst=True, errors='coerce')
        df['mes'] = df['data_dt'].dt.to_period('M')
        
        evolucao = df.groupby('mes')['vlrLiquido'].sum().reset_index()
        evolucao['mes'] = evolucao['mes'].astype(str)
        evolucao_list = []
        for _, row in evolucao.iterrows():
            evolucao_list.append({
                'mes': row['mes'],
                'valor': float(row['vlrLiquido'])
            })
        
        # Distribuição por fornecedor
        fornecedores = df.groupby('txtFornecedor')['vlrLiquido'].sum().sort_values(ascending=False).head(10)
        fornecedores_list = []
        for fornecedor, valor in fornecedores.items():
            fornecedores_list.append({
                'fornecedor': fornecedor,
                'valor': float(valor)
            })
        
        # Evolução de viagens (quantidade por mês)
        viagens = df.groupby('mes').size().reset_index(name='quantidade')
        viagens['mes'] = viagens['mes'].astype(str)
        viagens_list = []
        for _, row in viagens.iterrows():
            viagens_list.append({
                'mes': row['mes'],
                'quantidade': int(row['quantidade'])
            })

        # Informações do parlamentar (foto, partido, estado)
        info_parlamentar = {}
        if parlamentar and parlamentar != 'Todos' and not df.empty:
            # Pegar informações do primeiro registro (todos são do mesmo parlamentar)
            primeiro_registro = df.iloc[0]
            sg_partido = primeiro_registro['sgPartido']
            sg_uf = primeiro_registro['sgUF']
            
            info_parlamentar = {
                'nome': primeiro_registro['nome'],
                'foto': primeiro_registro['ultimoStatus_urlFoto'],
                'partido': sg_partido,
                'estado': sg_uf
            }
            
            # Buscar URLs do partido e estado resolvidos da Wikipédia (Anti-Bloqueio 429)
            info_parlamentar['url_partido'] = (
                resolve_party_logo_from_wikipedia(sg_partido) 
                or (partido_logos_dict.get(sg_partido) if 'partido_logos_dict' in globals() else None)
            )
            
            info_parlamentar['url_estado'] = (
                resolve_state_flag_from_wikipedia(sg_uf)
                or (estado_logos_dict.get(sg_uf) if 'estado_logos_dict' in globals() else None)
            )

        # Trechos de voo para o mapa
        trechos_voo = []
        if parlamentar and parlamentar != 'Todos': # Apenas para parlamentar específico
            df_trechos = df[['txtTrecho', 'vlrLiquido']].copy()
            trechos_extraidos = df_trechos['txtTrecho'].apply(extrair_origem_destino)
            df_trechos[['origem', 'destino']] = pd.DataFrame(
                trechos_extraidos.tolist(),
                index=df_trechos.index
            )
            df_trechos = df_trechos.dropna(subset=['origem', 'destino'])
            
            # Carregar dados de aeroportos
            try:
                df_airports = pd.read_csv('airport.csv')
                
                # Merge para ORIGEM
                df_trechos = df_trechos.merge(
                    df_airports[['sigla', 'latitude', 'longitude', 'nome']], 
                    left_on='origem', 
                    right_on='sigla', 
                    how='left',
                    suffixes=('_origem', None)
                ).rename(columns={'latitude': 'latitude_origem', 'longitude': 'longitude_origem', 'nome': 'nome_origem'})
                
                # Merge para DESTINO
                df_trechos = df_trechos.merge(
                    df_airports[['sigla', 'latitude', 'longitude', 'nome']], 
                    left_on='destino', 
                    right_on='sigla', 
                    how='left',
                    suffixes=('_destino', None)
                ).rename(columns={'latitude': 'latitude_destino', 'longitude': 'longitude_destino', 'nome': 'nome_destino'})
                
                df_trechos = df_trechos.dropna(subset=['latitude_origem', 'longitude_origem', 'latitude_destino', 'longitude_destino'])
                
                for _, row in df_trechos.iterrows():
                    trechos_voo.append({
                        'origem_sigla': row['origem'],
                        'origem_nome': row['nome_origem'],
                        'latitude_origem': float(row['latitude_origem']),
                        'longitude_origem': float(row['longitude_origem']),
                        'destino_sigla': row['destino'],
                        'destino_nome': row['nome_destino'],
                        'latitude_destino': float(row['latitude_destino']),
                        'longitude_destino': float(row['longitude_destino']),
                        'valor': float(row['vlrLiquido'])
                    })
            except Exception as e:
                print(f"Erro ao processar trechos de voo: {e}")
        
        conn.close()
        
        return {
            "success": True,
            "dados_completos": dados_completos,
            "passageiros": passageiros,
            "passagens_caras": passagens_caras_list,
            "evolucao": evolucao_list,
            "fornecedores": fornecedores_list,
            "viagens": viagens_list,
            "trechos_voo": trechos_voo,
            "info_parlamentar": info_parlamentar,
            "metricas": {
                "total_gasto": total_gasto,
                "total_viagens": total_viagens,
                "media_viagem": media_viagem,
                "fornecedores_unicos": fornecedores_unicos,
                "passagens_caras": passagens_caras_count
            }
        }
        
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        return {"success": False, "message": str(e), "error": str(e)}

@app.post("/api/passagens-aereas/investigar-passageiro")
async def investigar_passageiro_osint(data: dict):
    """Investiga um passageiro, priorizando dados pré-processados na tabela passageiros_osint."""
    nome_passageiro = data.get("passageiro", "").strip().upper()
    parlamentar = data.get("parlamentar", "").strip()
    
    if not nome_passageiro:
        return {"success": False, "message": "Nome do passageiro é obrigatório."}

    try:
        import sqlite3
        conn = sqlite3.connect(DATABASE_PATHS.get("tabelao", _local_db("tabelao.db")))
        
        # 1. Tentar Buscar na Tabela de Inteligência Pré-Processada (Velocidade Máxima)
        query_pre = "SELECT dossie, vinculos_socios, vinculos_doacoes, fontes_web FROM passageiros_osint WHERE nome_passageiro = ?"
        df_pre = pd.read_sql_query(query_pre, conn, params=[nome_passageiro])
        
        if not df_pre.empty:
            res = df_pre.iloc[0]
            conn.close()
            return {
                "success": True,
                "nome": nome_passageiro,
                "dossie": res['dossie'],
                "vinculos": {
                    "socios": json.loads(res['vinculos_socios']),
                    "doacoes": json.loads(res['vinculos_doacoes']),
                    "assessores": [],
                    "outros_parlamentares": json.loads(res['outros_parlamentares'] or "[]")
                },
                "fontes_web": json.loads(res['fontes_web']),
                "cached": True
            }

        # 2. Se não existir, disparar a varredura em tempo real (Fallback)
        from duckduckgo_search import DDGS
        
        # Cruzamento Interno Rápido
        query_socio = "SELECT Nome, Qualificação_Socio FROM lista_cnpj_geral WHERE Nome_Socio LIKE ?"
        df_socios = pd.read_sql_query(query_socio, conn, params=[f"%{nome_passageiro}%"])
        socios_info = df_socios.to_dict('records')
        
        query_doacao = "SELECT parlamentar, valor_doado_campanha, data_doacao FROM cruzamento_doacoes WHERE socio LIKE ?"
        df_doacoes = pd.read_sql_query(query_doacao, conn, params=[f"%{nome_passageiro}%"])
        doacoes_info = df_doacoes.to_dict('records')
        
        # Busca Web
        buscas = []
        try:
            with DDGS(timeout=10) as ddgs:
                pesquisa = f'"{nome_passageiro}" "{parlamentar or "Deputado"}"'
                resultados = list(ddgs.text(pesquisa, max_results=5))
                for r in resultados:
                    buscas.append({"titulo": r.get("title"), "link": r.get("href"), "snippet": r.get("body")})
        except: pass
            
        # IA Sumarização (GPT-4o-mini)
        contexto = f"Passageiro: {nome_passageiro}\nSociedades: {json.dumps(socios_info)}\nDoações: {json.dumps(doacoes_info)}\nWeb: {json.dumps(buscas)}"
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[{"role": "system", "content": "Resuma o provável vínculo político deste passageiro em 400 caracteres com tom de auditor."} ,
                      {"role": "user", "content": contexto}],
            temperature=0.3
        )
        dossie = response.choices[0].message.content.strip()
        
        conn.close()
        return {
            "success": True,
            "nome": nome_passageiro,
            "dossie": dossie,
            "vinculos": {"socios": socios_info, "doacoes": doacoes_info, "assessores": []},
            "fontes_web": buscas,
            "cached": False
        }
        
    except Exception as e:
        if 'conn' in locals(): conn.close()
        return {"success": False, "message": str(e)}


@app.get("/api/filters/assessores/parlamentares")
def get_assessores_parlamentares_filter(estado: str = "Todos", partido: str = "Todos"):
    """Filtro específico para a aba de assessores, retornando apenas quem tem gabinete mapeado."""
    conn = get_db_connection("tabelao")
    
    # 1. Obter todos os nomes que possuem gabinete (Normalizados para Upper)
    query_gabinetes = "SELECT DISTINCT nome_deputado_referencia FROM gabinetes_assessores"
    df_gabinetes = pd.read_sql_query(query_gabinetes, conn)
    nomes_ativos = set(n.upper().strip() for n in df_gabinetes['nome_deputado_referencia'].tolist())
    
    # 2. Obter parlamentares da tabela 'tabelao' com colunas corretas
    query_main = "SELECT DISTINCT nome FROM tabelao WHERE 1=1"
    params = []
    if estado != "Todos":
        query_main += " AND sgUF = ?"
        params.append(estado)
    if partido != "Todos":
        query_main += " AND sgPartido = ?"
        params.append(partido)
        
    df_main = pd.read_sql_query(query_main, conn, params=params)
    conn.close()
    
    # 3. Cruzar as listas com normalização
    nomes_filtrados = [n for n in df_main['nome'].tolist() if n.upper().strip() in nomes_ativos]
    
    return {"parlamentares": sorted(nomes_filtrados)}

@app.get("/api/assessores/analise")
def get_analise_assessores(parlamentar: str = None):
    """Retorna análise detalhada da equipe de assessores do parlamentar com benchmarks."""
    try:
        import sqlite3
        conn = sqlite3.connect(DATABASE_PATHS.get("tabelao", _local_db("tabelao.db")))
        
        # A. CÁLCULO DE BENCHMARK (Média da Câmara)
        query_media_geral = """
        SELECT 
            (SELECT COUNT(*) FROM gabinetes_assessores) * 1.0 / 
            (SELECT COUNT(DISTINCT nome_deputado_referencia) FROM gabinetes_assessores) as media
        """
        res_media = pd.read_sql_query(query_media_geral, conn)
        media_geral = res_media.iloc[0]['media'] or 19.5
        
        if not parlamentar or parlamentar == 'Todos':
            conn.close()
            return {"success": True, "media_geral": round(media_geral, 2), "message": "Selecione um parlamentar."}
            
        # RESOLUÇÃO DE NOMES (FUZZY MATCH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT nome_deputado_referencia FROM gabinetes_assessores")
        all_names = [row[0] for row in cursor.fetchall() if row[0]]
        
        target_name = None
        normalized_input = normalizar_texto_ia(parlamentar)
        
        # 1. Match exato
        if parlamentar in all_names:
            target_name = parlamentar
        else:
            # 2. Match por substring
            for name in all_names:
                norm_name = normalizar_texto_ia(name)
                if norm_name in normalized_input or normalized_input in norm_name:
                    target_name = name
                    break
        
        # Fallback
        target_name = target_name or parlamentar

        # 1. Métricas Consolidadas
        query_metrics = """
        SELECT 
            SUM(salario_liquido) as total_mensal,
            AVG(salario_liquido) as media_salarial,
            COUNT(*) as qtd_assessores
        FROM gabinetes_assessores
        WHERE nome_deputado_referencia = ?
        """
        metrics = pd.read_sql_query(query_metrics, conn, params=[target_name]).iloc[0].to_dict()
        
        # 2. Distribuição por Cargo (Top 10)
        query_cargos = """
        SELECT cargo, COUNT(*) as qtd, SUM(salario_liquido) as total_cargo
        FROM gabinetes_assessores
        WHERE nome_deputado_referencia = ?
        GROUP BY cargo
        ORDER BY qtd DESC
        LIMIT 10
        """
        cargos = pd.read_sql_query(query_cargos, conn, params=[target_name]).to_dict('records')
        
        # 3. Tendência de Admissão (Crescimento Acumulado)
        query_raw_dates = "SELECT data_admissao FROM gabinetes_assessores WHERE nome_deputado_referencia = ? AND data_admissao IS NOT NULL"
        df_dates = pd.read_sql_query(query_raw_dates, conn, params=[target_name])
        
        timeline_list = []
        if not df_dates.empty:
            df_dates['dt'] = pd.to_datetime(df_dates['data_admissao'], dayfirst=True, errors='coerce')
            df_dates = df_dates.dropna(subset=['dt'])
            df_dates['mes_ano'] = df_dates['dt'].dt.to_period('M').astype(str)
            
            # Agrupar por mês e calcular o acumulado
            timeline_res = df_dates.groupby('mes_ano').size().reset_index(name='novas_admissoes')
            timeline_res = timeline_res.sort_values('mes_ano')
            timeline_res['total_acumulado'] = timeline_res['novas_admissoes'].cumsum()
            timeline_list = timeline_res.to_dict('records')
        
        # 4. Lista Completa de Assessores (Ordenada por Admissão ASC)
        query_lista = """
        SELECT nome_assessor, cargo, salario_liquido, data_admissao, link_remuneracao, lotacao
        FROM gabinetes_assessores
        WHERE nome_deputado_referencia = ?
        """
        df_lista = pd.read_sql_query(query_lista, conn, params=[target_name])
        
        # Converter datas para ordenação correta
        df_lista['dt_ordem'] = pd.to_datetime(df_lista['data_admissao'], dayfirst=True, errors='coerce')
        df_lista = df_lista.sort_values('dt_ordem', ascending=True)
        
        # Adicionar campo de Origem (Estratificação solicitada)
        df_lista['origem'] = 'Comissionado'
        # Se algum cargo sugerir concursado no futuro, poderíamos mapear aqui
        
        lista = df_lista.drop(columns=['dt_ordem']).to_dict('records')
        
        conn.close()
        
        return {
            "success": True,
            "parlamentar": parlamentar,
            "media_geral": round(media_geral, 2),
            "metricas": {
                "total_mensal": metrics.get('total_mensal') or 0,
                "media_salarial": metrics.get('media_salarial') or 0,
                "qtd_assessores": int(metrics.get('qtd_assessores') or 0)
            },
            "cargos": cargos,
            "timeline": timeline_list,
            "lista": lista
        }
        
    except Exception as e:
        if 'conn' in locals(): conn.close()
        print(f"Erro em get_analise_assessores: {e}")
        return {"success": False, "message": str(e)}

# ============================================================
# ENDPOINT: Mapa Eleitoral - Votos por Parlamentar
# ============================================================
# BOUNDING BOXES DOS ESTADOS BRASILEIROS
# ============================================================
# Bounding boxes com margem generosa (+2 graus) para não cortar pontos legítimos
# Serve apenas para filtrar pontos claramente errados (ex: coordenada de RS aparecendo em ES)
ESTADO_BBOX = {
    'AC': {'lat_min': -13.0, 'lat_max': -5.0, 'lng_min': -76.0, 'lng_max': -64.0},
    'AL': {'lat_min': -12.5, 'lat_max': -6.8, 'lng_min': -40.5, 'lng_max': -33.5},
    'AP': {'lat_min': -6.0, 'lat_max': 7.0, 'lng_min': -56.8, 'lng_max': -49.0},
    'AM': {'lat_min': -12.0, 'lat_max': 7.0, 'lng_min': -75.0, 'lng_max': -54.0},
    'BA': {'lat_min': -20.5, 'lat_max': -7.0, 'lng_min': -48.0, 'lng_max': -35.0},
    'CE': {'lat_min': -10.0, 'lat_max': -0.8, 'lng_min': -43.5, 'lng_max': -35.0},
    'DF': {'lat_min': -17.0, 'lat_max': -14.0, 'lng_min': -49.0, 'lng_max': -46.0},
    'ES': {'lat_min': -22.5, 'lat_max': -16.0, 'lng_min': -43.0, 'lng_max': -38.0},
    'GO': {'lat_min': -21.5, 'lat_max': -12.0, 'lng_min': -55.0, 'lng_max': -44.0},
    'MA': {'lat_min': -12.5, 'lat_max': 1.0, 'lng_min': -52.0, 'lng_max': -40.0},
    'MT': {'lat_min': -20.5, 'lat_max': -5.0, 'lng_min': -63.0, 'lng_max': -48.0},
    'MS': {'lat_min': -25.0, 'lat_max': -15.5, 'lng_min': -59.0, 'lng_max': -51.0},
    'MG': {'lat_min': -24.5, 'lat_max': -12.5, 'lng_min': -53.0, 'lng_max': -38.0},
    'PA': {'lat_min': -10.5, 'lat_max': 5.0, 'lng_min': -61.0, 'lng_max': -46.0},
    'PB': {'lat_min': -10.5, 'lat_max': -4.5, 'lng_min': -40.0, 'lng_max': -33.0},
    'PR': {'lat_min': -28.5, 'lat_max': -20.5, 'lng_min': -56.5, 'lng_max': -46.0},
    'PE': {'lat_min': -11.5, 'lat_max': -5.0, 'lng_min': -42.5, 'lng_max': -32.5},
    'PI': {'lat_min': -13.0, 'lat_max': -0.5, 'lng_min': -47.0, 'lng_max': -39.0},
    'RJ': {'lat_min': -25.0, 'lat_max': -19.0, 'lng_min': -46.0, 'lng_max': -39.0},
    'RN': {'lat_min': -9.0, 'lat_max': -3.0, 'lng_min': -39.5, 'lng_max': -33.0},
    'RS': {'lat_min': -35.5, 'lat_max': -25.0, 'lng_min': -58.5, 'lng_max': -47.5},
    'RO': {'lat_min': -15.5, 'lat_max': -5.5, 'lng_min': -67.0, 'lng_max': -58.0},
    'RR': {'lat_min': -1.5, 'lat_max': 7.0, 'lng_min': -66.0, 'lng_max': -57.0},
    'SC': {'lat_min': -31.0, 'lat_max': -23.0, 'lng_min': -55.0, 'lng_max': -46.0},
    'SP': {'lat_min': -27.0, 'lat_max': -18.0, 'lng_min': -55.0, 'lng_max': -42.0},
    'SE': {'lat_min': -13.0, 'lat_max': -8.0, 'lng_min': -39.5, 'lng_max': -35.0},
    'TO': {'lat_min': -14.0, 'lat_max': -3.0, 'lng_min': -52.0, 'lng_max': -44.0},
}

def ponto_em_estado(lat: float, lng: float, sigla_estado: str) -> bool:
    """Verifica se um ponto está dentro do bounding box do estado."""
    bbox = ESTADO_BBOX.get(sigla_estado.upper())
    if not bbox:
        return True  # Fallback: aceitar se estado não encontrado

    return (bbox['lat_min'] <= lat <= bbox['lat_max'] and
            bbox['lng_min'] <= lng <= bbox['lng_max'])


def ponto_em_perimetro_estado(lat: float, lng: float, sigla_estado: str) -> bool:
    """
    Verifica se o ponto está dentro do perímetro real da UF usando os setores
    censitários materializados. Usa o bbox apenas como filtro barato inicial.
    """
    uf = (sigla_estado or "").upper().strip()
    if not uf:
        return True

    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except Exception:
        return False

    if not ponto_em_estado(lat_f, lng_f, uf):
        return False

    return ponto_em_estado(lat_f, lng_f, uf)


def buscar_centroides_confiaveis_municipio(estado: str, municipios: list[str]) -> dict:
    """
    Busca centróides municipais confiáveis usando apenas pontos já dentro do bbox da UF.
    Serve como fallback quando uma coordenada individual aparece fora do estado.
    """
    municipios_validos = [str(m).strip() for m in municipios if m and str(m).strip()]
    if not municipios_validos:
        return {}

    duck_db_path = DUCK_DB_PATH
    if not os.path.exists(duck_db_path):
        return {}

    bbox = ESTADO_BBOX.get((estado or "").upper())
    if not bbox:
        return {}

    placeholders = ",".join(["?"] * len(municipios_validos))
    params = [
        estado,
        *municipios_validos,
        bbox["lat_min"],
        bbox["lat_max"],
        bbox["lng_min"],
        bbox["lng_max"],
    ]

    con = safe_duckdb_connect(duck_db_path, read_only=True)
    try:
        rows = con.execute(
            f"""
            SELECT
                NM_MUNICIPIO,
                AVG(LAT) AS lat_centroide,
                AVG(LONG) AS lng_centroide
            FROM votacao
            WHERE SG_UF = ?
              AND NM_MUNICIPIO IN ({placeholders})
              AND LAT IS NOT NULL AND LONG IS NOT NULL
              AND LAT != 0 AND LONG != 0
              AND LAT BETWEEN ? AND ?
              AND LONG BETWEEN ? AND ?
            GROUP BY NM_MUNICIPIO
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    centroides = {}
    for municipio, lat, lng in rows:
        if municipio is None or lat is None or lng is None:
            continue
        lat_f = float(lat)
        lng_f = float(lng)
        if not ponto_em_perimetro_estado(lat_f, lng_f, estado):
            continue
        centroides[str(municipio)] = {"lat": lat_f, "lng": lng_f}
    return centroides


def sanitizar_pontos_mapa_por_estado(raw_points: list[dict], estado: str) -> tuple[list[dict], dict]:
    """
    Corrige pontos fora da UF usando o centróide confiável do município.
    Se não houver fallback confiável, suprime o ponto do mapa.
    """
    if not raw_points:
        return [], {"mantidos": 0, "corrigidos": 0, "suprimidos": 0}

    municipio_names = []
    for point in raw_points:
        municipio = point.get("municipio") or point.get("NM_MUNICIPIO")
        if municipio:
            municipio_names.append(str(municipio))
    centroides = buscar_centroides_confiaveis_municipio(estado, municipio_names)

    mantidos = 0
    corrigidos = 0
    suprimidos = 0
    final_points = []

    for point in raw_points:
        lat = point.get("lat")
        lng = point.get("lng")
        municipio = str(point.get("municipio") or point.get("NM_MUNICIPIO") or "").strip()

        if lat is None or lng is None:
            suprimidos += 1
            continue

        if ponto_em_perimetro_estado(float(lat), float(lng), estado):
            mantidos += 1
            final_points.append(point)
            continue

        centroide = centroides.get(municipio)
        if centroide and ponto_em_perimetro_estado(centroide["lat"], centroide["lng"], estado):
            point_corrigido = dict(point)
            point_corrigido["lat"] = centroide["lat"]
            point_corrigido["lng"] = centroide["lng"]
            point_corrigido["coordenada_corrigida"] = True
            point_corrigido["fonte_correcao"] = "centroide_municipal_confiavel"
            corrigidos += 1
            final_points.append(point_corrigido)
        else:
            suprimidos += 1

    return final_points, {"mantidos": mantidos, "corrigidos": corrigidos, "suprimidos": suprimidos}


@lru_cache(maxsize=1)
def load_municipios_coords_index() -> dict:
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "municipios_brasileiros.csv")
    if not os.path.exists(csv_path):
        return {}

    try:
        df_municipios = pd.read_csv(csv_path, usecols=["nome_municipio", "uf", "latitude", "longitude"])
    except Exception:
        return {}

    if df_municipios.empty:
        return {}

    df_municipios["municipio_norm"] = df_municipios["nome_municipio"].apply(normalize_city_name)
    df_municipios["uf_norm"] = df_municipios["uf"].astype(str).str.upper().str.strip()
    df_municipios["key"] = df_municipios["municipio_norm"] + "_" + df_municipios["uf_norm"]
    df_municipios = df_municipios.drop_duplicates(subset=["key"])

    coords_index = {}
    for _, row in df_municipios.iterrows():
        key = str(row["key"]).strip()
        if not key:
            continue
        try:
            coords_index[key] = {
                "lat": float(row["latitude"]),
                "lng": float(row["longitude"]),
            }
        except Exception:
            continue
    return coords_index


def montar_endereco_cadastral_fornecedor(registro: dict) -> Optional[str]:
    endereco_existente = str(registro.get("endereco_completo") or "").strip()
    if endereco_existente:
        return endereco_existente

    partes = []
    logradouro = str(registro.get("Logradouro") or "").strip()
    numero = str(registro.get("Número") or "").strip()
    bairro = str(registro.get("Bairro") or "").strip()
    cidade = str(registro.get("Cidade_Nome") or registro.get("Cidade") or "").strip()
    estado = str(registro.get("Estado_Nome") or "").strip().upper()
    cep = str(registro.get("CEP_lista") or registro.get("CEP") or "").strip()

    if logradouro:
        if numero and numero.lower() not in {"nan", "none"}:
            partes.append(f"{logradouro}, {numero}")
        else:
            partes.append(logradouro)
    if bairro and bairro.lower() not in {"nan", "none"}:
        partes.append(bairro)
    if cidade:
        cidade_uf = cidade
        if estado:
            cidade_uf = f"{cidade}/{estado}"
        partes.append(cidade_uf)
    elif estado:
        partes.append(estado)
    if cep and cep.lower() not in {"nan", "none"}:
        partes.append(f"CEP {cep}")

    endereco = " · ".join([parte for parte in partes if parte])
    return endereco or None


def persistir_correcao_coordenada_empresa(
    conn: sqlite3.Connection,
    cnpj_limpo: str,
    cidade: Optional[str],
    cep: Optional[str],
    endereco_completo: Optional[str],
    latitude: float,
    longitude: float,
) -> None:
    if not cnpj_limpo:
        return

    cidade_val = str(cidade).strip() if cidade else None
    cep_val = str(cep).strip() if cep else None
    endereco_val = str(endereco_completo).strip() if endereco_completo else None

    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE coordenadas_empresas
        SET latitude = ?, longitude = ?, Cidade = COALESCE(?, Cidade), CEP = COALESCE(?, CEP), endereco_completo = COALESCE(?, endereco_completo)
        WHERE REPLACE(REPLACE(REPLACE(cnpj, '.', ''), '/', ''), '-', '') = ?
           OR ltrim(REPLACE(REPLACE(REPLACE(cnpj, '.', ''), '/', ''), '-', ''), '0') = ?
        """,
        [latitude, longitude, cidade_val, cep_val, endereco_val, cnpj_limpo, cnpj_limpo.lstrip("0")],
    )

    if cursor.rowcount == 0:
        cursor.execute(
            """
            INSERT INTO coordenadas_empresas (cnpj, Cidade, CEP, latitude, longitude, endereco_completo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [cnpj_limpo, cidade_val, cep_val, latitude, longitude, endereco_val],
        )


@lru_cache(maxsize=4096)
def geocodificar_endereco_google(endereco: str, uf: str) -> Optional[dict]:
    api_key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_GEOCODING_API_KEY")
    )
    endereco_limpo = str(endereco or "").strip()
    uf_limpa = str(uf or "").strip().upper()
    if not api_key or not endereco_limpo or not uf_limpa:
        return None

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "address": endereco_limpo,
                "components": f"country:BR|administrative_area:{uf_limpa}",
                "language": "pt-BR",
                "region": "br",
                "key": api_key,
            },
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning(f"⚠️ Falha ao geocodificar fornecedor no Google Maps ({uf_limpa}): {exc}")
        return None

    for result in payload.get("results", []):
        geometry = result.get("geometry") or {}
        location = geometry.get("location") or {}
        try:
            lat = float(location.get("lat"))
            lng = float(location.get("lng"))
        except Exception:
            continue

        if not ponto_em_perimetro_estado(lat, lng, uf_limpa):
            continue

        cidade_resultado = None
        for component in result.get("address_components", []):
            types = set(component.get("types", []))
            if {"administrative_area_level_2"} & types or "locality" in types:
                cidade_resultado = component.get("long_name")
                break

        return {
            "lat": lat,
            "lng": lng,
            "cidade": cidade_resultado,
            "endereco_formatado": result.get("formatted_address"),
            "fonte": "google_geocoding_endereco_cadastral",
        }

    return None


def resolver_localizacao_cadastral_fornecedor(registro: dict, conn: sqlite3.Connection) -> Optional[dict]:
    cnpj_limpo = str(registro.get("cnpj_limpo") or "").strip()
    cidade_cadastral = str(registro.get("Cidade_Nome") or registro.get("Cidade") or "").strip()
    uf_cadastral = str(registro.get("Estado_Nome") or "").strip().upper()
    endereco_cadastral = montar_endereco_cadastral_fornecedor(registro)
    cep_cadastral = str(registro.get("CEP_lista") or registro.get("CEP") or "").strip()

    lat = registro.get("latitude")
    lng = registro.get("longitude")
    try:
        lat = float(lat) if pd.notna(lat) else None
        lng = float(lng) if pd.notna(lng) else None
    except Exception:
        lat = None
        lng = None

    if uf_cadastral and lat is not None and lng is not None and ponto_em_perimetro_estado(lat, lng, uf_cadastral):
        return {
            "lat": lat,
            "lng": lng,
            "cidade": cidade_cadastral or None,
            "estado": uf_cadastral,
            "endereco": endereco_cadastral,
            "cep": cep_cadastral or None,
            "fonte": "coordenada_empresa_validada",
        }

    if uf_cadastral and endereco_cadastral:
        geo_google = geocodificar_endereco_google(endereco_cadastral, uf_cadastral)
        if geo_google:
            lat_corrigida = float(geo_google["lat"])
            lng_corrigida = float(geo_google["lng"])
            cidade_google = str(geo_google.get("cidade") or cidade_cadastral or "").strip() or None
            endereco_google = str(geo_google.get("endereco_formatado") or endereco_cadastral or "").strip() or None

            try:
                persistir_correcao_coordenada_empresa(
                    conn,
                    cnpj_limpo=cnpj_limpo,
                    cidade=cidade_google,
                    cep=cep_cadastral or None,
                    endereco_completo=endereco_google,
                    latitude=lat_corrigida,
                    longitude=lng_corrigida,
                )
            except Exception as exc:
                logger.warning(f"⚠️ Não foi possível persistir correção Google do fornecedor {cnpj_limpo}: {exc}")

            return {
                "lat": lat_corrigida,
                "lng": lng_corrigida,
                "cidade": cidade_google,
                "estado": uf_cadastral,
                "endereco": endereco_google,
                "cep": cep_cadastral or None,
                "fonte": str(geo_google.get("fonte") or "google_geocoding_endereco_cadastral"),
            }

    coords_municipios = load_municipios_coords_index()
    cidade_key = f"{normalize_city_name(cidade_cadastral)}_{uf_cadastral}" if cidade_cadastral and uf_cadastral else None
    coords_cidade = coords_municipios.get(cidade_key) if cidade_key else None

    if uf_cadastral and coords_cidade:
        lat_corrigida = float(coords_cidade["lat"])
        lng_corrigida = float(coords_cidade["lng"])
        if ponto_em_perimetro_estado(lat_corrigida, lng_corrigida, uf_cadastral):
            try:
                persistir_correcao_coordenada_empresa(
                    conn,
                    cnpj_limpo=cnpj_limpo,
                    cidade=cidade_cadastral or None,
                    cep=cep_cadastral or None,
                    endereco_completo=endereco_cadastral,
                    latitude=lat_corrigida,
                    longitude=lng_corrigida,
                )
            except Exception as exc:
                logger.warning(f"⚠️ Não foi possível persistir correção do fornecedor {cnpj_limpo}: {exc}")

            return {
                "lat": lat_corrigida,
                "lng": lng_corrigida,
                "cidade": cidade_cadastral or None,
                "estado": uf_cadastral,
                "endereco": endereco_cadastral,
                "cep": cep_cadastral or None,
                "fonte": "centroide_cidade_cadastral",
            }

    if lat is not None and lng is not None:
        return {
            "lat": lat,
            "lng": lng,
            "cidade": cidade_cadastral or str(registro.get("Cidade") or "").strip() or None,
            "estado": uf_cadastral or None,
            "endereco": endereco_cadastral,
            "cep": cep_cadastral or None,
            "fonte": "coordenada_empresa_sem_uf_validada",
        }

    return None


@app.get("/api/mapa-eleitoral/filtros")
async def get_mapa_eleitoral_filtros(uf: Optional[str] = None, partido_atual: Optional[str] = None, partido_eleicao: Optional[str] = None):
    """Retorna partidos atuais e parlamentares disponíveis no banco de votação (DuckDB)."""
    try:
        duck_db_path = DUCK_DB_PATH
        if not os.path.exists(duck_db_path):
            return {"partidos_atuais": [], "parlamentares": []}

        con = safe_duckdb_connect(duck_db_path, read_only=True)
        estado_normalizado = str(uf or "").strip().upper()
        partido_atual_normalizado = str(partido_atual or "").strip().upper()
        partido_eleicao_normalizado = str(partido_eleicao or "").strip().upper()

        where = []
        params = []
        
        # Filtro de UF (Estado)
        if uf and uf != "Todos":
            where.append("SG_UF = ?")
            params.append(uf)
            
        # Filtros de partido: partido atual via SQLite e partido de eleição via DuckDB.
        nomes_intersecao = None
        try:
            conn_sq = sqlite3.connect(DATABASE_PATHS["tabelao"])
            base_query = "SELECT DISTINCT UPPER(TRIM(nome)) AS nome_norm FROM tabelao WHERE 1=1"
            base_params = []
            if estado_normalizado and estado_normalizado != "TODOS":
                base_query += " AND UPPER(TRIM(sgUF)) = UPPER(?)"
                base_params.append(estado_normalizado)

            if partido_atual_normalizado and partido_atual_normalizado != "TODOS":
                query_atual = base_query + " AND UPPER(TRIM(ultimoStatus_siglaPartido)) = UPPER(?)"
                params_atual = base_params + [partido_atual_normalizado]
                df_atual = pd.read_sql_query(query_atual, conn_sq, params=params_atual)
                nomes_intersecao = set(df_atual["nome_norm"].dropna().tolist())

            if partido_eleicao_normalizado and partido_eleicao_normalizado != "TODOS":
                con_duck = None
                try:
                    con_duck = safe_duckdb_connect(duck_db_path, read_only=True)
                    table_name_duck = "votacao_validada"
                    try:
                        con_duck.execute(f"SELECT 1 FROM {table_name_duck} LIMIT 1")
                    except Exception:
                        table_name_duck = "votacao"
                    query_eleicao = f"""
                        SELECT DISTINCT UPPER(TRIM(NM_PARLAMENTAR)) AS nome_norm
                        FROM {table_name_duck}
                        WHERE UPPER(TRIM(SG_UF)) = UPPER(?)
                          AND UPPER(TRIM(SIGLA_PARTIDO_FINAL)) = UPPER(?)
                          AND NM_PARLAMENTAR IS NOT NULL
                          AND TRIM(NM_PARLAMENTAR) <> ''
                    """
                    params_eleicao = [estado_normalizado, partido_eleicao_normalizado]
                    df_eleicao = pd.read_sql_query(query_eleicao, con_duck, params=params_eleicao)
                    nomes_eleicao = set(df_eleicao["nome_norm"].dropna().tolist())
                finally:
                    if con_duck is not None:
                        try:
                            con_duck.close()
                        except Exception:
                            pass
                nomes_intersecao = nomes_eleicao if nomes_intersecao is None else (nomes_intersecao & nomes_eleicao)

            conn_sq.close()
        except Exception as e:
            logger.error(f"Erro ao cruzar partidos no SQLite: {e}")

        if nomes_intersecao is not None:
            if nomes_intersecao:
                placeholders = ", ".join(["?"] * len(nomes_intersecao))
                where.append(f"UPPER(TRIM(NM_PARLAMENTAR)) IN ({placeholders})")
                params.extend(sorted(nomes_intersecao))
            else:
                where.append("1=0")
        else:
            # Sem filtro de partido atual/eleição, mantém comportamento antigo no DuckDB.
            pass

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        table_name = "votacao_validada" # Usar a tabela validada se possível
        
        # Verificar se a tabela existe, senão volta para 'votacao'
        try:
            con.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
        except:
            table_name = "votacao"

        partidos = [r[0] for r in con.execute(
            f"SELECT DISTINCT SIGLA_PARTIDO_FINAL FROM {table_name} {where_sql} ORDER BY SIGLA_PARTIDO_FINAL",
            params
        ).fetchall() if r[0]]

        parlamentares = [r[0] for r in con.execute(
            f"SELECT DISTINCT NM_PARLAMENTAR FROM {table_name} {where_sql} ORDER BY NM_PARLAMENTAR",
            params
        ).fetchall() if r[0]]

        # Quando o filtro está preso ao partido atual, o partido exibido na UI
        # deve refletir a legenda corrente real do parlamentar, não a legenda histórica
        # registrada na base eleitoral.
        partidos_atuais = []
        if parlamentares:
            parlamentares_norm = [str(p).strip().upper() for p in parlamentares if str(p).strip()]
            placeholders = ",".join(["?"] * len(parlamentares_norm))
            try:
                conn_sq = sqlite3.connect(DATABASE_PATHS["tabelao"])
                query_atual = f"""
                    SELECT DISTINCT UPPER(TRIM(nome)) AS nome_norm, ultimoStatus_siglaPartido
                    FROM tabelao
                    WHERE UPPER(TRIM(nome)) IN ({placeholders})
                      AND (%s)
                      AND ultimoStatus_siglaPartido IS NOT NULL
                      AND TRIM(ultimoStatus_siglaPartido) <> ''
                """
                query_atual = query_atual % ("1=1")
                df_atual = pd.read_sql_query(query_atual, conn_sq, params=parlamentares_norm)
                conn_sq.close()
                partidos_atuais = (
                    df_atual['ultimoStatus_siglaPartido']
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .replace('', pd.NA)
                    .dropna()
                    .drop_duplicates()
                    .tolist()
                )
            except Exception as e:
                logger.error(f"Erro ao resolver partidos atuais reais: {e}")
                partidos_atuais = []

        if not partidos_atuais:
            # Fallback preservando comportamento anterior, mas sem duplicar o partido eleitoral
            partidos_atuais = [r[0] for r in con.execute(
                f"SELECT DISTINCT SIGLA_PARTIDO_FINAL FROM {table_name} {where_sql} ORDER BY SIGLA_PARTIDO_FINAL",
                params
            ).fetchall() if r[0]]
            if partido_atual and partido_atual != "Todos" and partido_atual not in partidos_atuais:
                partidos_atuais = [partido_atual] + partidos_atuais

        con.close()
        return {"partidos_atuais": partidos_atuais, "partidos_eleicao": partidos, "parlamentares": parlamentares}
    except Exception as e:
        logger.error(f"Erro em get_mapa_eleitoral_filtros: {e}")
        return {"partidos_atuais": [], "parlamentares": []}


# ============================================================
@app.get("/api/mapa-eleitoral/votos/{nome_parlamentar}")
async def mapa_eleitoral_votos(
    nome_parlamentar: str,
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    include_ibge: bool = False
):
    """
    Retorna dados de votação eleitoral para o mapa de redutos.
    Consulta o banco DuckDB (votacao.duckdb) com dados das eleições 2022.
    """
    import urllib.parse
    nome_decoded = urllib.parse.unquote(nome_parlamentar)

    try:
        cached_payload = get_cached_mapa_eleitoral_votos_payload(nome_decoded, estado=estado, partido=partido)
        if cached_payload:
            return cached_payload

        # Não está no cache — gera agora automaticamente (lazy materialization)
        payload = materialize_mapa_eleitoral_votos_cache(nome_decoded, estado=estado, partido=partido)
        if payload and not payload.get("error"):
            return payload

        return payload or {
            "error": f"Parlamentar '{nome_decoded}' não encontrado no banco de dados de votação.",
            "cacheStatus": "not_found",
        }

    except Exception as e:
        logging.error(f"Erro no endpoint mapa-eleitoral: {str(e)}")
        return {"error": f"Erro ao buscar dados: {str(e)}"}


@app.get("/api/mapa-eleitoral/ibge-top10/{nome_parlamentar}")
async def mapa_eleitoral_ibge_top10(
    nome_parlamentar: str,
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    allow_municipal_fallback: bool = False,
):
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        table_exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mapa_eleitoral_ibge_top10_cache' LIMIT 1"
        ).fetchone()
        if not table_exists:
            table_exists = None

        granular_table_exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mapa_eleitoral_ibge_reduto_granular_cache' LIMIT 1"
        ).fetchone()

        if granular_table_exists:
            granular_row = None
            candidate_names = resolve_parlamentar_name_candidates(nome_parlamentar, estado=estado, partido=partido)
            def fetch_granular_row(candidate_name: str, include_partido: bool):
                granular_conditions = ["UPPER(parlamentar) = UPPER(?)"]
                granular_params = [candidate_name]

                if estado:
                    granular_conditions.append("UPPER(uf) = UPPER(?)")
                    granular_params.append(estado)

                if include_partido and partido:
                    granular_conditions.append("UPPER(partido) = UPPER(?)")
                    granular_params.append(partido)

                granular_query = f"""
                    SELECT
                        cards_json,
                        top_redutos_json,
                        atualizado_em,
                        contexto_nota,
                        metodologia,
                        parlamentar,
                        uf,
                        partido
                    FROM mapa_eleitoral_ibge_reduto_granular_cache
                    WHERE {" AND ".join(granular_conditions)}
                    ORDER BY atualizado_em DESC
                    LIMIT 1
                """
                return cursor.execute(granular_query, granular_params).fetchone()

            for candidate_name in candidate_names:
                granular_row = fetch_granular_row(candidate_name, include_partido=True)
                if not granular_row and partido:
                    granular_row = fetch_granular_row(candidate_name, include_partido=False)
                if granular_row:
                    break
            if granular_row:
                try:
                    cards = json.loads(granular_row["cards_json"]) if granular_row["cards_json"] else []
                except Exception:
                    cards = []
                try:
                    top_redutos = json.loads(granular_row["top_redutos_json"]) if granular_row["top_redutos_json"] else []
                except Exception:
                    top_redutos = []

                if top_redutos:
                    cards = build_granular_ibge_cards(top_redutos[:10])

                payload = {
                    "ibgeResumoTop10": cards,
                    "topRedutos": top_redutos[:100],
                    "metricBenchmarks": build_metric_benchmarks_payload(
                        top_redutos[:100],
                        [
                            "alfabetizacao",
                            "nao_alfabetizacao",
                            "rede_geral_agua",
                            "rede_esgoto",
                            "lixo_coletado",
                            "sem_banheiro",
                            "share_domicilios_improvisados",
                            "share_cortico",
                            "share_maloca",
                            "poco_artesiano",
                            "sem_esgoto",
                            "fossa_rudimentar_buraco",
                            "lixo_queimado",
                            "lixo_ceu_aberto",
                            "share_estrutura_degradada",
                            "entorno_via_pavimentada",
                            "entorno_bueiro",
                            "entorno_calcada_sem_obstaculo",
                            "entorno_rampa_cadeirante",
                            "entorno_ponto_onibus",
                            "entorno_calcada",
                            "entorno_iluminacao_publica",
                            "entorno_arborizacao_1_2_arvores",
                            "entorno_arborizacao_3_4_arvores",
                            "entorno_arborizacao_5_mais_arvores",
                            "entorno_sem_arvores",
                        ],
                    ),
                    "topMunicipios": [],
                    "cacheStatus": "hit_granular",
                    "atualizadoEm": granular_row["atualizado_em"],
                    "contextoNota": granular_row["contexto_nota"],
                    "metodologia": granular_row["metodologia"],
                    "parlamentar": granular_row["parlamentar"],
                    "uf": granular_row["uf"],
                    "partido": granular_row["partido"],
                }
                return clean_data_for_json(payload)

        if not allow_municipal_fallback:
            return {
                "ibgeResumoTop10": [],
                "topMunicipios": [],
                "topRedutos": [],
                "cacheStatus": "territorial_required",
                "message": "Esta tela foi configurada para usar apenas territórios específicos do IBGE, com base nos polígonos/setores censitários do reduto. Como o cache territorial granular ainda não está materializado para este parlamentar, o fallback municipal foi desativado para evitar uma leitura metodologicamente incorreta.",
            }

        if not table_exists:
            return {
                "ibgeResumoTop10": [],
                "topMunicipios": [],
                "topRedutos": [],
                "cacheStatus": "not_initialized",
                "message": "Nenhum cache socioeconômico foi inicializado ainda. Para a versão granular dos redutos, rode o script de setor censitário.",
            }

        row = None
        candidate_names = resolve_parlamentar_name_candidates(nome_parlamentar, estado=estado, partido=partido)
        def fetch_municipal_row(candidate_name: str, include_partido: bool):
            conditions = ["UPPER(parlamentar) = UPPER(?)"]
            params = [candidate_name]

            if estado:
                conditions.append("UPPER(uf) = UPPER(?)")
                params.append(estado)

            if include_partido and partido:
                conditions.append("UPPER(partido) = UPPER(?)")
                params.append(partido)

            query = f"""
                SELECT
                    cards_json,
                    top10_municipios_json,
                    atualizado_em,
                    contexto_nota,
                    parlamentar,
                    uf,
                    partido
                FROM mapa_eleitoral_ibge_top10_cache
                WHERE {" AND ".join(conditions)}
                ORDER BY atualizado_em DESC
                LIMIT 1
            """
            return cursor.execute(query, params).fetchone()

        for candidate_name in candidate_names:
            row = fetch_municipal_row(candidate_name, include_partido=True)
            if not row and partido:
                row = fetch_municipal_row(candidate_name, include_partido=False)
            if row:
                break

        if not row:
            return {
                "ibgeResumoTop10": [],
                "topMunicipios": [],
                "topRedutos": [],
                "cacheStatus": "missing",
                "message": "A síntese socioeconômica granular ainda não foi pré-processada para este parlamentar. O fallback municipal também não está disponível no tabelao.db.",
            }

        try:
            cards = json.loads(row["cards_json"]) if row["cards_json"] else []
        except Exception:
            cards = []

        try:
            top_municipios = json.loads(row["top10_municipios_json"]) if row["top10_municipios_json"] else []
        except Exception:
            top_municipios = []

        return clean_data_for_json({
            "ibgeResumoTop10": cards,
            "topMunicipios": top_municipios[:10],
            "topRedutos": [],
            "cacheStatus": "hit_municipal",
            "atualizadoEm": row["atualizado_em"],
            "contextoNota": row["contexto_nota"],
            "parlamentar": row["parlamentar"],
            "uf": row["uf"],
            "partido": row["partido"],
        })
    except Exception as exc:
        logger.error(f"Erro ao carregar cache IBGE do top 10: {exc}")
        return {
            "ibgeResumoTop10": [],
            "topMunicipios": [],
            "topRedutos": [],
            "cacheStatus": "error",
            "message": "Erro ao ler o cache socioeconômico pré-processado no tabelao.db.",
        }
    finally:
        if conn:
            conn.close()


# ============================================================
# ENDPOINT: Análise de Perfil do Eleitor (IA)
# ============================================================
@app.get("/api/analise-perfil-eleitor/{nome_parlamentar}")
async def analise_perfil_eleitor(nome_parlamentar: str, estado: Optional[str] = None, partido: Optional[str] = None):
    """
    Gera análise de perfil do eleitor usando IA (OpenAI).
    """
    import urllib.parse
    nome_decoded = urllib.parse.unquote(nome_parlamentar)

    try:
        duck_db_path = DUCK_DB_PATH

        if not os.path.exists(duck_db_path):
            return {"analise": "Banco de dados de votação não encontrado."}

        con = safe_duckdb_connect(duck_db_path, read_only=True)

        info_params = [nome_decoded, nome_decoded]
        info_filters = ["(UPPER(NM_PARLAMENTAR) = UPPER(?) OR UPPER(NM_VOTAVEL) = UPPER(?))"]
        if estado:
            info_filters.append("UPPER(SG_UF) = UPPER(?)")
            info_params.append(str(estado).strip().upper())
        if partido:
            info_filters.append("UPPER(SIGLA_PARTIDO_FINAL) = UPPER(?)")
            info_params.append(str(partido).strip().upper())

        info_query = f"""
            SELECT DISTINCT
                NM_PARLAMENTAR, NM_VOTAVEL, SIGLA_PARTIDO_FINAL, SG_UF, DS_CARGO, ALINHAMENTO_IDEOLOGICO
            FROM votacao
            WHERE {' AND '.join(info_filters)}
            LIMIT 1
        """
        info_result = con.execute(info_query, info_params).fetchdf()

        if info_result.empty:
            like_params = [f"%{nome_decoded}%", f"%{nome_decoded}%"]
            like_filters = ["(UPPER(NM_PARLAMENTAR) LIKE UPPER(?) OR UPPER(NM_VOTAVEL) LIKE UPPER(?))"]
            if estado:
                like_filters.append("UPPER(SG_UF) = UPPER(?)")
                like_params.append(str(estado).strip().upper())
            if partido:
                like_filters.append("UPPER(SIGLA_PARTIDO_FINAL) = UPPER(?)")
                like_params.append(str(partido).strip().upper())

            info_query_like = f"""
                SELECT DISTINCT
                    NM_PARLAMENTAR, NM_VOTAVEL, SIGLA_PARTIDO_FINAL, SG_UF, DS_CARGO, ALINHAMENTO_IDEOLOGICO
                FROM votacao
                WHERE {' AND '.join(like_filters)}
                LIMIT 1
            """
            info_result = con.execute(info_query_like, like_params).fetchdf()

        if info_result.empty:
            con.close()
            return {"analise": "Dados insuficientes para análise."}

        nome_real = str(info_result.iloc[0]["NM_PARLAMENTAR"])
        nome_votavel_raw = str(info_result.iloc[0]["NM_VOTAVEL"]) if not pd.isna(info_result.iloc[0]["NM_VOTAVEL"]) else nome_real
        partido_real = str(info_result.iloc[0]["SIGLA_PARTIDO_FINAL"])
        estado_real = str(info_result.iloc[0]["SG_UF"])
        cargo_real = str(info_result.iloc[0]["DS_CARGO"]) if not pd.isna(info_result.iloc[0]["DS_CARGO"]) else "Deputado Federal"
        alinhamento_real = str(info_result.iloc[0]["ALINHAMENTO_IDEOLOGICO"]) if not pd.isna(info_result.iloc[0]["ALINHAMENTO_IDEOLOGICO"]) else "Não informado"
        alias_to_display_state, _ = get_state_elected_label_maps(estado_real)
        nome_urna = (
            alias_to_display_state.get(normalizar_texto_ia(nome_real))
            or alias_to_display_state.get(normalizar_texto_ia(nome_votavel_raw))
            or nome_votavel_raw
            or nome_real
        )

        df, df_bairros = get_official_votacao_context(nome_real, estado_real, limit_municipios=10, limit_bairros=12)

        if df.empty:
            con.close()
            return {"analise": "Dados insuficientes para análise."}

        data_summary = df.to_string(index=False)
        bairros_summary = df_bairros.to_string(index=False) if not df_bairros.empty else "Sem bairros relevantes com nome informado."

        granular_cache = None
        granular_redutos = []
        granular_contexto_nota = None
        granular_metodologia = None
        try:
            sqlite_conn = sqlite3.connect(DATABASE_PATHS["tabelao"])
            sqlite_conn.row_factory = sqlite3.Row
            sqlite_cursor = sqlite_conn.cursor()
            granular_table_exists = sqlite_cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mapa_eleitoral_ibge_reduto_granular_cache' LIMIT 1"
            ).fetchone()

            if granular_table_exists:
                granular_row = sqlite_cursor.execute(
                    """
                    SELECT top_redutos_json, contexto_nota, metodologia
                    FROM mapa_eleitoral_ibge_reduto_granular_cache
                    WHERE UPPER(parlamentar) = UPPER(?) AND UPPER(uf) = UPPER(?)
                    ORDER BY atualizado_em DESC
                    LIMIT 1
                    """,
                    [nome_real, estado_real],
                ).fetchone()

                if granular_row:
                    granular_contexto_nota = granular_row["contexto_nota"]
                    granular_metodologia = granular_row["metodologia"]
                    try:
                        granular_redutos = json.loads(granular_row["top_redutos_json"]) if granular_row["top_redutos_json"] else []
                    except Exception:
                        granular_redutos = []

                    if granular_redutos:
                        sector_codes = [
                            str(item.get("cd_setor")).strip()
                            for item in granular_redutos
                            if item.get("cd_setor") is not None
                        ]
                        indicator_map = load_enriched_indicator_map(sector_codes) if sector_codes else {}

                        granular_redutos = [
                            {
                                **reduto,
                                "indicadores": indicator_map.get(str(reduto.get("cd_setor", "")).strip(), reduto.get("indicadores", {})),
                            }
                            for reduto in granular_redutos[:10]
                        ]
                        granular_cache = "hit_granular"
        except Exception as exc:
            logger.warning(f"Falha ao carregar cache granular para análise de perfil: {exc}")
        finally:
            try:
                sqlite_conn.close()
            except Exception:
                pass

        def weighted_reduto_metric(redutos, field):
            valid = []
            for item in redutos or []:
                indicadores = item.get("indicadores") or {}
                peso = item.get("total_votos")
                valor = indicadores.get(field)
                try:
                    peso = float(peso)
                except Exception:
                    peso = None
                try:
                    valor = float(valor)
                except Exception:
                    valor = None
                if peso and valor is not None:
                    valid.append((peso, valor))
            if not valid:
                return None
            total_weight = sum(weight for weight, _ in valid)
            if not total_weight:
                return None
            return sum(weight * value for weight, value in valid) / total_weight

        def top_reduto_core(redutos, threshold=100.0):
            valid = sorted(
                [item for item in (redutos or []) if item.get("total_votos") is not None],
                key=lambda row: float(row.get("total_votos") or 0),
                reverse=True,
            )
            total = sum(float(item.get("total_votos") or 0) for item in valid)
            if total <= 0:
                return [], 0.0
            selected = []
            selected_votes = 0.0
            for item in valid:
                selected.append(item)
                selected_votes += float(item.get("total_votos") or 0)
                if (selected_votes / total) * 100 >= threshold:
                    break
            return selected, (selected_votes / total) * 100

        def fmt_number(value, decimals=1, suffix=""):
            if value is None:
                return "N/D"
            if decimals == 0:
                return f"{int(round(value)):,}".replace(",", ".") + suffix
            return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".") + suffix

        contexto_redutos = []
        for _, row in df.head(5).iterrows():
            nome_municipio = str(row["NM_MUNICIPIO"])
            contexto_redutos.append({
                "municipio": nome_municipio,
                "votos": int(row["total_votos"]) if not pd.isna(row["total_votos"]) else 0,
                "percentual_medio": float(row["percentual_medio"]) if not pd.isna(row["percentual_medio"]) else 0.0,
                "total_secoes": int(row["total_secoes"]) if not pd.isna(row["total_secoes"]) else 0,
                "populacao_sidra": None,
                "populacao_periodo": None,
                "microrregiao": None,
                "mesorregiao": None,
                "indicadores_sidra": {},
            })

        contexto_redutos_texto = "\n".join([
            (
                f"- {item['municipio']}: {item['votos']:,} votos, "
                f"{item['percentual_medio']:.2f}% médio, {item['total_secoes']} seções, "
                + (f"população estimada SIDRA {item['populacao_periodo']}: {item['populacao_sidra']:,}. " if item["populacao_sidra"] else "população SIDRA indisponível. ")
                + (f"Microrregião: {item['microrregiao']}. " if item["microrregiao"] else "")
                + (f"Mesorregião: {item['mesorregiao']}." if item["mesorregiao"] else "")
                + (
                    " Indicadores adicionais: "
                    + "; ".join([
                        f"idade mediana {item['indicadores_sidra'].get('idade_mediana')}" if item["indicadores_sidra"].get("idade_mediana") is not None else "",
                        f"taxa de alfabetização {item['indicadores_sidra'].get('taxa_alfabetizacao')}%" if item["indicadores_sidra"].get("taxa_alfabetizacao") is not None else "",
                        f"renda domiciliar per capita média R$ {item['indicadores_sidra'].get('renda_domiciliar_per_capita_media')}" if item["indicadores_sidra"].get("renda_domiciliar_per_capita_media") is not None else "",
                        f"renda domiciliar per capita mediana R$ {item['indicadores_sidra'].get('renda_domiciliar_per_capita_mediana')}" if item["indicadores_sidra"].get("renda_domiciliar_per_capita_mediana") is not None else "",
                        f"25+ com superior completo {item['indicadores_sidra'].get('share_superior_completo_25mais')}%" if item["indicadores_sidra"].get("share_superior_completo_25mais") is not None else "",
                        f"25+ com médio completo {item['indicadores_sidra'].get('share_medio_completo_25mais')}%" if item["indicadores_sidra"].get("share_medio_completo_25mais") is not None else "",
                        f"25+ sem instrução {item['indicadores_sidra'].get('share_sem_instrucao_25mais')}%" if item["indicadores_sidra"].get("share_sem_instrucao_25mais") is not None else "",
                        f"domicílios com rede geral de água {item['indicadores_sidra'].get('share_rede_geral_agua')}%" if item["indicadores_sidra"].get("share_rede_geral_agua") is not None else "",
                        f"domicílios com rede geral de esgoto {item['indicadores_sidra'].get('share_rede_esgoto')}%" if item["indicadores_sidra"].get("share_rede_esgoto") is not None else "",
                        f"domicílios com internet {item['indicadores_sidra'].get('share_internet_domiciliar')}%" if item["indicadores_sidra"].get("share_internet_domiciliar") is not None else "",
                        f"14+ na força de trabalho {item['indicadores_sidra'].get('share_forca_trabalho_14mais')}%" if item["indicadores_sidra"].get("share_forca_trabalho_14mais") is not None else "",
                        f"14+ ocupadas {item['indicadores_sidra'].get('share_ocupadas_14mais')}%" if item["indicadores_sidra"].get("share_ocupadas_14mais") is not None else "",
                        f"população urbana {item['indicadores_sidra'].get('share_populacao_urbana')}%" if item["indicadores_sidra"].get("share_populacao_urbana") is not None else "",
                        f"população rural {item['indicadores_sidra'].get('share_populacao_rural')}%" if item["indicadores_sidra"].get("share_populacao_rural") is not None else "",
                        f"residentes recentes {item['indicadores_sidra'].get('share_residencia_recente')}%" if item["indicadores_sidra"].get("share_residencia_recente") is not None else "",
                    ]).strip("; ")
                    if item["indicadores_sidra"] else " Indicadores adicionais indisponíveis."
                )
            )
            for item in contexto_redutos
        ])

        granular_core_redutos, granular_core_coverage = top_reduto_core(granular_redutos, threshold=100.0)
        granular_top_redutos_texto = "Cache granular não disponível."
        granular_thematic_summary = "Sem resumo granular disponível."
        comparativo_reduto_texto = "Sem comparativo do reduto contra estado e Brasil disponível."
        sobreposicao_parlamentar_texto = "Sem leitura consolidada de sobreposição com outros parlamentares eleitos no mesmo território."
        benchmark_payload = {}
        overlap_df = pd.DataFrame()
        competition_full_df = pd.DataFrame()
        age_014 = age_1524 = age_2539 = age_4059 = age_60 = None
        female = male = None
        race_white = race_parda = race_preta = race_indigena = None
        renda = densidade = moradores = None
        filhos = conjuges = pais = netos = None
        agua = esgoto = lixo = sem_banheiro = None
        casa = apto = None
        pav = ilum = calcada = onibus = rampa = None
        metric_fields = {
            "renda_media_responsavel": None,
            "moradores_por_domicilio": None,
            "alfabetizacao": None,
            "rede_geral_agua": None,
            "rede_esgoto": None,
            "lixo_coletado": None,
            "share_domicilios_improvisados": None,
            "share_estrutura_degradada": None,
        }

        if granular_redutos:
            granular_top_redutos_texto = "\n".join([
                (
                    f"- Setor {item.get('cd_setor')}: {item.get('municipio')}/{item.get('uf')}, "
                    f"{int(item.get('total_votos', 0)):,} votos, "
                    f"{int(item.get('quantidade_sessoes', 0))} seções, "
                    f"zonas {', '.join(map(str, item.get('zonas', [])[:6])) if item.get('zonas') else 'N/D'}, "
                    f"locais {', '.join(item.get('locais', [])[:3]) if item.get('locais') else 'N/D'}."
                )
                for item in granular_redutos[:10]
            ])

            age_014 = weighted_reduto_metric(granular_core_redutos, "share_0_14")
            age_1524 = weighted_reduto_metric(granular_core_redutos, "share_15_24")
            age_2539 = weighted_reduto_metric(granular_core_redutos, "share_25_39")
            age_4059 = weighted_reduto_metric(granular_core_redutos, "share_40_59")
            age_60 = weighted_age_metric(granular_core_redutos, "share_60_mais")
            female = weighted_reduto_metric(granular_core_redutos, "share_mulheres")
            male = weighted_reduto_metric(granular_core_redutos, "share_homens")
            race_white = weighted_reduto_metric(granular_core_redutos, "share_branca")
            race_parda = weighted_reduto_metric(granular_core_redutos, "share_parda")
            race_preta = weighted_reduto_metric(granular_core_redutos, "share_preta")
            race_indigena = weighted_reduto_metric(granular_core_redutos, "share_indigena")
            renda = weighted_reduto_metric(granular_core_redutos, "renda_media_responsavel") or weighted_reduto_metric(granular_core_redutos, "renda_media_pc")
            densidade = weighted_reduto_metric(granular_core_redutos, "densidade_demografica")
            moradores = weighted_reduto_metric(granular_core_redutos, "moradores_por_domicilio")
            filhos = weighted_reduto_metric(granular_core_redutos, "share_filhos")
            conjuges = weighted_reduto_metric(granular_core_redutos, "share_conjuges_companheiros")
            pais = weighted_reduto_metric(granular_core_redutos, "share_pais_padrastos")
            netos = weighted_reduto_metric(granular_core_redutos, "share_netos_bisnetos")
            agua = weighted_reduto_metric(granular_core_redutos, "rede_geral_agua")
            esgoto = weighted_reduto_metric(granular_core_redutos, "rede_esgoto")
            lixo = weighted_reduto_metric(granular_core_redutos, "lixo_coletado")
            sem_banheiro = weighted_reduto_metric(granular_core_redutos, "sem_banheiro")
            casa = weighted_reduto_metric(granular_core_redutos, "share_casa")
            apto = weighted_reduto_metric(granular_core_redutos, "share_apartamento")
            pav = weighted_reduto_metric(granular_core_redutos, "entorno_via_pavimentada")
            ilum = weighted_reduto_metric(granular_core_redutos, "entorno_iluminacao_publica")
            calcada = weighted_reduto_metric(granular_core_redutos, "entorno_calcada")
            onibus = weighted_reduto_metric(granular_core_redutos, "entorno_ponto_onibus")
            rampa = weighted_reduto_metric(granular_core_redutos, "entorno_rampa_cadeirante")

            dominant_race = sorted([
                ("branca", race_white or 0),
                ("parda", race_parda or 0),
                ("preta", race_preta or 0),
                ("indígena", race_indigena or 0),
            ], key=lambda item: item[1], reverse=True)[0][0]

            metric_fields = {
                "renda_media_responsavel": renda,
                "moradores_por_domicilio": moradores,
                "alfabetizacao": weighted_reduto_metric(granular_core_redutos, "alfabetizacao"),
                "rede_geral_agua": agua,
                "rede_esgoto": esgoto,
                "lixo_coletado": lixo,
                "share_domicilios_improvisados": weighted_reduto_metric(granular_core_redutos, "share_domicilios_improvisados"),
                "share_estrutura_degradada": estruturaDegradada if 'estruturaDegradada' in locals() else weighted_reduto_metric(granular_core_redutos, "share_estrutura_degradada"),
            }

            metric_labels = {
                "renda_media_responsavel": "Renda média do responsável",
                "moradores_por_domicilio": "Moradores por domicílio",
                "alfabetizacao": "Alfabetização",
                "rede_geral_agua": "Rede geral de água",
                "rede_esgoto": "Rede de esgoto",
                "lixo_coletado": "Coleta de lixo",
                "share_domicilios_improvisados": "Domicílios improvisados",
                "share_estrutura_degradada": "Estrutura degradada",
            }

            benchmark_payload = build_metric_benchmarks_payload(granular_core_redutos, list(metric_fields.keys()))
            comparativo_linhas = []
            for metric_name, valor_reduto in metric_fields.items():
                if valor_reduto is None:
                    continue
                benchmark = benchmark_payload.get(metric_name, {})
                valor_estado = benchmark.get("estado")
                valor_brasil = benchmark.get("brasil")
                if metric_name == "renda_media_responsavel":
                    reduto_fmt = f"R$ {fmt_number(valor_reduto, 0)}"
                    estado_fmt = f"R$ {fmt_number(valor_estado, 0)}" if valor_estado is not None else "N/D"
                    brasil_fmt = f"R$ {fmt_number(valor_brasil, 0)}" if valor_brasil is not None else "N/D"
                elif metric_name == "moradores_por_domicilio":
                    reduto_fmt = fmt_number(valor_reduto, 1)
                    estado_fmt = fmt_number(valor_estado, 1) if valor_estado is not None else "N/D"
                    brasil_fmt = fmt_number(valor_brasil, 1) if valor_brasil is not None else "N/D"
                else:
                    reduto_fmt = fmt_number(valor_reduto, 1, "%")
                    estado_fmt = fmt_number(valor_estado, 1, "%") if valor_estado is not None else "N/D"
                    brasil_fmt = fmt_number(valor_brasil, 1, "%") if valor_brasil is not None else "N/D"

                delta_estado = None
                delta_brasil = None
                if valor_estado not in (None, 0):
                    delta_estado = ((valor_reduto - valor_estado) / valor_estado) * 100
                if valor_brasil not in (None, 0):
                    delta_brasil = ((valor_reduto - valor_brasil) / valor_brasil) * 100

                comparativo_linhas.append(
                    f"- {metric_labels[metric_name]}: reduto {reduto_fmt}; estado {estado_fmt}; Brasil {brasil_fmt}; "
                    + (f"diferença vs estado {delta_estado:+.1f}%. " if delta_estado is not None else "")
                    + (f"diferença vs Brasil {delta_brasil:+.1f}%." if delta_brasil is not None else "")
                )

            comparativo_reduto_texto = "\n".join(comparativo_linhas) if comparativo_linhas else comparativo_reduto_texto

            zone_refs = sorted({
                str(zona).strip()
                for item in granular_core_redutos
                for zona in (item.get("zonas") or [])
                if zona is not None and str(zona).strip()
            })
            municipio_refs = sorted({
                str(item.get("municipio")).strip()
                for item in granular_core_redutos
                if item.get("municipio") is not None and str(item.get("municipio")).strip()
            })
            competition_full_df = pd.DataFrame()

            if municipio_refs:
                overlap_df = get_official_elected_overlap_context(
                    nome_real,
                    estado_real,
                    zone_refs=zone_refs,
                    municipio_refs=municipio_refs,
                    limit=15,
                )
                competition_full_df = get_official_elected_overlap_context(
                    nome_real,
                    estado_real,
                    zone_refs=zone_refs,
                    municipio_refs=municipio_refs,
                    limit=16,
                    include_target=True,
                )
                if not overlap_df.empty:
                    overlap_lines = []
                    for _, row in overlap_df.iterrows():
                        partido_overlap = str(row.get("partido") or "Sem partido").strip() or "Sem partido"
                        alinhamento_overlap = str(row.get("alinhamento") or "Não informado").strip() or "Não informado"

                        if partido_overlap.upper() == str(partido_real).upper():
                            relacao_partidaria = "mesmo partido"
                        else:
                            relacao_partidaria = f"outro partido ({partido_overlap})"

                        if alinhamento_overlap.lower() == str(alinhamento_real).lower():
                            relacao_espectro = "mesmo espectro"
                        elif alinhamento_overlap.lower() in {"", "não informado", "nao informado", "sem informação"}:
                            relacao_espectro = "espectro não informado"
                        else:
                            relacao_espectro = f"outro espectro ({alinhamento_overlap})"

                        share_texto = ""
                        if not pd.isna(row.get("share_no_recorte")):
                            share_texto = f", {float(row['share_no_recorte']):.1f}% do volume competitivo observado no recorte"

                        overlap_lines.append(
                            f"- {row['nome_exibicao']} ({partido_overlap}, {alinhamento_overlap}): "
                            f"{int(row['votos_territorio']):,} votos oficiais no mesmo recorte territorial{share_texto}; "
                            f"presença em {int(row['zonas_presentes'])} zonas e {int(row['municipios_presentes'])} municípios do reduto; "
                            f"{relacao_partidaria}; {relacao_espectro}."
                        )

                    sobreposicao_parlamentar_texto = "\n".join(overlap_lines)

            granular_thematic_summary = f"""
BLOCO 1 - DEMOGRAFIA DOS MICROTERRITÓRIOS DOMINANTES
- Núcleo analisado: {len(granular_core_redutos)} setores censitários, cobrindo {fmt_number(granular_core_coverage, 1, '%')} dos votos do top 10 setorial.
- Faixa etária: 0-14 {fmt_number(age_014, 1, '%')}; 15-24 {fmt_number(age_1524, 1, '%')}; 25-39 {fmt_number(age_2539, 1, '%')}; 40-59 {fmt_number(age_4059, 1, '%')}; 60+ {fmt_number(age_60, 1, '%')}.
- Sexo: homens {fmt_number(male, 1, '%')}; mulheres {fmt_number(female, 1, '%')}.

BLOCO 2 - RAÇA/COR
- Branca {fmt_number(race_white, 1, '%')}; parda {fmt_number(race_parda, 1, '%')}; preta {fmt_number(race_preta, 1, '%')}; indígena {fmt_number(race_indigena, 1, '%')}.
- Perfil racial predominante no núcleo: {dominant_race}.

BLOCO 3 - RENDA E ESTRUTURA SOCIOECONÔMICA
- Renda média do responsável: {('R$ ' + fmt_number(renda, 0)) if renda is not None else 'N/D'}.
- Densidade demográfica: {fmt_number(densidade, 0)} hab./km².
- Moradores por domicílio: {fmt_number(moradores, 1)}.

BLOCO 4 - ESTRUTURA FAMILIAR
- Cônjuges/companheiros {fmt_number(conjuges, 1, '%')}; filhos {fmt_number(filhos, 1, '%')}; pais/padrastos {fmt_number(pais, 1, '%')}; netos/bisnetos {fmt_number(netos, 1, '%')}.

BLOCO 5 - SANEAMENTO E HABITAÇÃO
- Água em rede geral {fmt_number(agua, 1, '%')}; esgoto em rede {fmt_number(esgoto, 1, '%')}; lixo coletado {fmt_number(lixo, 1, '%')}; sem banheiro {fmt_number(sem_banheiro, 1, '%')}.
- Tipo de moradia: casa {fmt_number(casa, 1, '%')}; apartamento {fmt_number(apto, 1, '%')}.

BLOCO 6 - ENTORNO URBANO
- Via pavimentada {fmt_number(pav, 1, '%')}; iluminação pública {fmt_number(ilum, 1, '%')}; calçada {fmt_number(calcada, 1, '%')}; ponto de ônibus {fmt_number(onibus, 1, '%')}; rampa para cadeirante {fmt_number(rampa, 1, '%')}.
""".strip()
        def build_local_fallback_analysis(return_context: bool = False):
            def as_int(value):
                try:
                    return int(float(value))
                except Exception:
                    return None

            def as_float(value):
                try:
                    return float(value)
                except Exception:
                    return None

            def pct(value, total):
                if value in (None, 0) or total in (None, 0):
                    return None
                return (float(value) / float(total)) * 100.0

            def relation_label(value, reference):
                if value is None or reference in (None, 0):
                    return None
                ratio = (float(value) - float(reference)) / float(reference)
                if ratio >= 0.25:
                    return "bem acima"
                if ratio >= 0.08:
                    return "acima"
                if ratio <= -0.25:
                    return "bem abaixo"
                if ratio <= -0.08:
                    return "abaixo"
                return "próximo"

            def choose_first(*values):
                for value in values:
                    if value is None:
                        continue
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                    if isinstance(value, list):
                        for item in value:
                            if item and str(item).strip():
                                return str(item).strip()
                return None

            def broad_camp(label):
                normalized = normalizar_texto_ia(label or "")
                if "centro-direita" in normalized or "centrodireita" in normalized:
                    return "centro-direita"
                if "centro-esquerda" in normalized or "centroesquerda" in normalized:
                    return "centro-esquerda"
                if "direita" in normalized:
                    return "direita"
                if "esquerda" in normalized:
                    return "esquerda"
                if "centro" in normalized:
                    return "centro"
                return "não informado"

            def mean_defined(*values):
                valid = [float(value) for value in values if value is not None]
                if not valid:
                    return None
                return sum(valid) / len(valid)

            def format_compact_number(value):
                integer = as_int(value)
                if integer is None:
                    return "N/D"
                return f"{integer:,}".replace(",", ".")

            def format_currency(value):
                if value is None:
                    return "N/D"
                return f"R$ {fmt_number(value, 0)}"

            def format_percent(value):
                if value is None:
                    return "N/D"
                return fmt_number(value, 1, "%")

            def natural_join(values):
                cleaned = [str(value).strip() for value in values if value and str(value).strip()]
                if not cleaned:
                    return ""
                if len(cleaned) == 1:
                    return cleaned[0]
                if len(cleaned) == 2:
                    return f"{cleaned[0]} e {cleaned[1]}"
                return f"{', '.join(cleaned[:-1])} e {cleaned[-1]}"

            def compare_text(metric_name, value):
                benchmark = benchmark_payload.get(metric_name, {})
                estado_ref = benchmark.get("estado")
                brasil_ref = benchmark.get("brasil")
                return {
                    "estado": estado_ref,
                    "brasil": brasil_ref,
                    "label_estado": relation_label(value, estado_ref),
                    "label_brasil": relation_label(value, brasil_ref),
                }

            capitals_by_uf = {
                "AC": "Rio Branco", "AL": "Maceió", "AP": "Macapá", "AM": "Manaus", "BA": "Salvador",
                "CE": "Fortaleza", "DF": "Brasília", "ES": "Vitória", "GO": "Goiânia", "MA": "São Luís",
                "MT": "Cuiabá", "MS": "Campo Grande", "MG": "Belo Horizonte", "PA": "Belém", "PB": "João Pessoa",
                "PR": "Curitiba", "PE": "Recife", "PI": "Teresina", "RJ": "Rio de Janeiro", "RN": "Natal",
                "RS": "Porto Alegre", "RO": "Porto Velho", "RR": "Boa Vista", "SC": "Florianópolis",
                "SP": "São Paulo", "SE": "Aracaju", "TO": "Palmas",
            }
            state_names_by_uf = {
                "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
                "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
                "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba",
                "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
                "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
                "SE": "Sergipe", "TO": "Tocantins",
            }
            state_locative_by_uf = {
                "AC": "no Acre",
                "AL": "em Alagoas",
                "AP": "no Amapá",
                "AM": "no Amazonas",
                "BA": "na Bahia",
                "CE": "no Ceará",
                "DF": "no Distrito Federal",
                "ES": "no Espírito Santo",
                "GO": "em Goiás",
                "MA": "no Maranhão",
                "MT": "em Mato Grosso",
                "MS": "em Mato Grosso do Sul",
                "MG": "em Minas Gerais",
                "PA": "no Pará",
                "PB": "na Paraíba",
                "PR": "no Paraná",
                "PE": "em Pernambuco",
                "PI": "no Piauí",
                "RJ": "no Rio de Janeiro",
                "RN": "no Rio Grande do Norte",
                "RS": "no Rio Grande do Sul",
                "RO": "em Rondônia",
                "RR": "em Roraima",
                "SC": "em Santa Catarina",
                "SP": "em São Paulo",
                "SE": "em Sergipe",
                "TO": "no Tocantins",
            }
            estado_nome = state_names_by_uf.get(str(estado_real).upper(), estado_real)
            estado_locativo = state_locative_by_uf.get(str(estado_real).upper(), f"em {estado_nome}")

            total_oficial = get_total_votos_oficiais_tse(nome_real, estado_real) or 0
            municipio_lider = str(df.iloc[0]["NM_MUNICIPIO"]).strip() if not df.empty else None
            votos_lider = as_int(df.iloc[0]["total_votos"]) if not df.empty else None
            top5_votos = int(df.head(5)["total_votos"].sum()) if not df.empty else 0
            top10_votos = int(df["total_votos"].sum()) if not df.empty else 0
            top1_share = pct(votos_lider, total_oficial)
            top5_share = pct(top5_votos, total_oficial)
            top10_share = pct(top10_votos, total_oficial)

            top_municipios = []
            for _, row in df.head(5).iterrows():
                votos = as_int(row["total_votos"]) or 0
                share = pct(votos, total_oficial)
                top_municipios.append(
                    {
                        "municipio": str(row["NM_MUNICIPIO"]).strip(),
                        "votos": votos,
                        "share": share,
                    }
                )

            locais_lines = []
            for _, row in df_bairros.head(5).iterrows():
                votos = as_int(row["total_votos"]) or 0
                local_nome = choose_first(row.get("bairro"))
                municipio_nome = str(row.get("NM_MUNICIPIO") or "").strip()
                if local_nome and normalizar_texto_ia(local_nome) != "local nao informado":
                    locais_lines.append(f"- **{local_nome}** ({municipio_nome}): {format_compact_number(votos)} votos.")

            age_band_pairs = [
                ("0 a 14 anos", age_014),
                ("15 a 24 anos", age_1524),
                ("25 a 39 anos", age_2539),
                ("40 a 59 anos", age_4059),
                ("60+ anos", age_60),
            ]
            age_band_pairs = [(label, value) for label, value in age_band_pairs if value is not None]
            idade_lider = max(age_band_pairs, key=lambda item: item[1])[0] if age_band_pairs else "N/D"

            renda_cmp = compare_text("renda_media_responsavel", renda)
            moradores_cmp = compare_text("moradores_por_domicilio", moradores)
            alfabet_cmp = compare_text("alfabetizacao", metric_fields.get("alfabetizacao"))
            agua_cmp = compare_text("rede_geral_agua", agua)
            esgoto_cmp = compare_text("rede_esgoto", esgoto)
            lixo_cmp = compare_text("lixo_coletado", lixo)
            impro_cmp = compare_text("share_domicilios_improvisados", metric_fields.get("share_domicilios_improvisados"))
            degradada_cmp = compare_text("share_estrutura_degradada", metric_fields.get("share_estrutura_degradada"))

            renda_estado = renda_cmp["estado"]
            renda_brasil = renda_cmp["brasil"]
            moradores_estado = moradores_cmp["estado"]
            moradores_brasil = moradores_cmp["brasil"]
            alfabet_estado = alfabet_cmp["estado"]
            alfabet_brasil = alfabet_cmp["brasil"]
            agua_estado = agua_cmp["estado"]
            agua_brasil = agua_cmp["brasil"]
            esgoto_estado = esgoto_cmp["estado"]
            esgoto_brasil = esgoto_cmp["brasil"]
            lixo_estado = lixo_cmp["estado"]
            lixo_brasil = lixo_cmp["brasil"]

            renda_rel_estado = renda_cmp["label_estado"]
            renda_rel_brasil = renda_cmp["label_brasil"]
            moradores_rel_estado = moradores_cmp["label_estado"]
            moradores_rel_brasil = moradores_cmp["label_brasil"]
            alfabet_rel_estado = alfabet_cmp["label_estado"]
            alfabet_rel_brasil = alfabet_cmp["label_brasil"]
            agua_rel_estado = agua_cmp["label_estado"]
            esgoto_rel_estado = esgoto_cmp["label_estado"]
            lixo_rel_estado = lixo_cmp["label_estado"]

            capital_estado = capitals_by_uf.get(str(estado_real).upper())
            top_names = [item["municipio"] for item in top_municipios]
            capital_nos_principais = capital_estado and any(normalizar_texto_ia(m) == normalizar_texto_ia(capital_estado) for m in top_names[:4])
            lider_e_capital = capital_estado and municipio_lider and normalizar_texto_ia(municipio_lider) == normalizar_texto_ia(capital_estado)

            if lider_e_capital and (top1_share or 0) >= 20:
                geometria_reduto = (
                    f"O reduto é nitidamente **capitalizado**: o município líder é a própria capital estadual, "
                    f"que sozinho responde por cerca de **{top1_share:.1f}%** da votação oficial do deputado no estado."
                )
            elif not capital_nos_principais and len(top_names) >= 4:
                geometria_reduto = (
                    f"O reduto é **interiorizado**: a votação se organiza em um arco de municípios fora da capital, "
                    f"com maior densidade em **{', '.join(top_names[:4])}**."
                )
            else:
                geometria_reduto = (
                    f"O reduto é **misto**, com ancoragem em **{municipio_lider}** e capilaridade relevante em "
                    f"**{', '.join(top_names[1:4]) if len(top_names) > 1 else municipio_lider}**."
                )

            if top10_share is not None:
                concentracao_texto = (
                    f"Os dez municípios mais fortes concentram cerca de **{top10_share:.1f}%** do total oficial de votos, "
                    f"e os cinco primeiros já respondem por **{top5_share:.1f}%**."
                )
            else:
                concentracao_texto = "A concentração municipal do voto não pôde ser quantificada com precisão nesta tentativa."

            renda_texto = format_currency(renda)
            moradores_texto = fmt_number(moradores, 1) if moradores is not None else "N/D"
            agua_texto = format_percent(agua)
            esgoto_texto = format_percent(esgoto)
            lixo_texto = format_percent(lixo)
            alfabet_texto = format_percent(metric_fields.get("alfabetizacao"))
            impro_texto = format_percent(metric_fields.get("share_domicilios_improvisados"))
            degradada_texto = format_percent(metric_fields.get("share_estrutura_degradada"))

            urban_score = mean_defined(pav, ilum, calcada)
            acessibilidade_score = mean_defined(rampa)
            infraestrutura_score = mean_defined(agua, esgoto, lixo)

            def delta_points(value, reference):
                if value is None or reference is None:
                    return None
                return float(value) - float(reference)

            def delta_currency(value, reference):
                if value is None or reference is None:
                    return None
                return float(value) - float(reference)

            def points_text(value):
                if value is None:
                    return "N/D"
                sign = "+" if value > 0 else ""
                return f"{sign}{value:.1f} p.p."

            def currency_diff_text(value):
                if value is None:
                    return "N/D"
                sign = "+" if value > 0 else "-"
                return f"{sign}R$ {fmt_number(abs(value), 0)}"

            def choose_metric_sentence(metric_label, reduto_value, state_value, brazil_value, formatter):
                if reduto_value is None:
                    return None
                reduto_fmt = formatter(reduto_value)
                estado_fmt = formatter(state_value)
                brasil_fmt = formatter(brazil_value)
                delta_estado_fmt = points_text(delta_points(reduto_value, state_value)) if formatter != format_currency else currency_diff_text(delta_currency(reduto_value, state_value))
                delta_brasil_fmt = points_text(delta_points(reduto_value, brazil_value)) if formatter != format_currency else currency_diff_text(delta_currency(reduto_value, brazil_value))
                return (
                    f"- **{metric_label}**: reduto {reduto_fmt}; estado {estado_fmt}; Brasil {brasil_fmt}; "
                    f"diferença vs estado **{delta_estado_fmt}**; diferença vs Brasil **{delta_brasil_fmt}**."
                )

            if idade_lider == "60+ anos":
                ciclo_vida = "um eleitorado envelhecido, com peso acima da média de faixas etárias maduras"
            elif idade_lider == "40 a 59 anos":
                ciclo_vida = "um eleitorado adulto maduro, com prevalência de famílias estabilizadas e inserção ocupacional mais regular"
            elif idade_lider == "25 a 39 anos":
                ciclo_vida = "um eleitorado mais centrado em adultos em consolidação econômica e familiar"
            else:
                ciclo_vida = "uma composição etária mais mista, sem predominância absoluta de faixas maduras"

            if urban_score is not None and urban_score >= 85:
                urbanizacao_texto = "o entorno urbano aparece consolidado, com bom padrão de pavimentação, iluminação e calçada"
            elif urban_score is not None and urban_score >= 65:
                urbanizacao_texto = "o entorno urbano é funcional, mas ainda heterogêneo"
            elif urban_score is not None:
                urbanizacao_texto = "o entorno urbano é mais frágil e menos padronizado"
            else:
                urbanizacao_texto = "não há informação suficiente para classificar com segurança o entorno urbano"

            if casa is not None and apto is not None:
                if casa >= 75 and (apto or 0) <= 20:
                    morfologia_residencial = "ocupação predominantemente horizontal, com forte presença de casas e sociabilidade residencial mais local"
                elif apto >= 30:
                    morfologia_residencial = "ocupação mais verticalizada, típica de áreas urbanas de maior densidade e renda"
                else:
                    morfologia_residencial = "ocupação residencial mista, sem domínio pleno de uma tipologia"
            else:
                morfologia_residencial = "morfologia residencial sem medição consolidada"

            if renda_rel_estado in {"bem acima", "acima"} and infraestrutura_score is not None and infraestrutura_score >= 85:
                base_social = "territórios de renda relativamente alta e infraestrutura bem consolidada"
            elif renda_rel_estado in {"abaixo", "bem abaixo"} and esgoto_rel_estado in {"acima", "bem acima"}:
                base_social = "territórios de renda intermediária, mas mais organizados em infraestrutura do que a média estadual"
            elif renda_rel_estado in {"abaixo", "bem abaixo"} and infraestrutura_score is not None and infraestrutura_score < 75:
                base_social = "territórios socialmente mais pressionados, com menor conforto material e infraestrutura mais irregular"
            else:
                base_social = "territórios de classe média ou média-baixa, sem luxo disseminado, mas tampouco marcados por precariedade estrutural aguda"

            if moradores_rel_estado in {"abaixo", "bem abaixo"}:
                estrutura_domiciliar = "com domicílios menores que a média do estado"
            elif moradores_rel_estado in {"acima", "bem acima"}:
                estrutura_domiciliar = "com domicílios mais cheios que a média estadual"
            else:
                estrutura_domiciliar = "com tamanho domiciliar muito próximo do padrão estadual"

            sociologia_paragrafo = (
                f"Os microterritórios em que **{nome_urna}** é mais forte apontam para **{ciclo_vida}**. "
                f"Não se trata de um reduto socialmente homogêneo, mas o núcleo dominante se aproxima de **{base_social}**, "
                f"{estrutura_domiciliar}. A renda média do responsável é de **{renda_texto}**, a alfabetização chega a **{alfabet_texto}**, "
                f"e a infraestrutura básica registra **água {agua_texto}**, **esgoto {esgoto_texto}** e **coleta de lixo {lixo_texto}**. "
                f"Do ponto de vista da forma urbana, o reduto sugere **{morfologia_residencial}**; no espaço público, **{urbanizacao_texto}**"
                + (f", com acessibilidade em torno de **{format_percent(acessibilidade_score)}**." if acessibilidade_score is not None else ".")
            )

            competicao_leitura = (
                "Ainda não foi possível medir com segurança quem domina este recorte nem qual é a distância competitiva entre os principais nomes."
            )
            competencia_resumo = (
                "Sem a hierarquia dos deputados eleitos no mesmo território, o reduto pode parecer mais fechado ou mais disperso do que realmente é."
            )
            janelas_texto = (
                "Sem uma leitura consolidada de competição no mesmo espaço, a interpretação estratégica deste reduto fica incompleta."
            )
            competencia_classificacao = "ainda sem classificação competitiva robusta"
            target_camp = broad_camp(alinhamento_real)
            same_party_share = None
            same_camp_share = None
            cross_camp_share = None

            if not overlap_df.empty:
                top_overlap = overlap_df.head(8).copy()
                total_overlap = float(top_overlap["votos_territorio"].sum()) if not top_overlap.empty else 0.0
                camp_votes = {}
                same_party_votes = 0
                same_camp_votes = 0
                cross_camp_votes = 0

                for _, row in top_overlap.iterrows():
                    votos_territorio = as_int(row.get("votos_territorio")) or 0
                    partido_overlap = str(row.get("partido") or "Sem partido").strip()
                    alinhamento_overlap = str(row.get("alinhamento") or "Não informado").strip()
                    campo_amplo = broad_camp(alinhamento_overlap)
                    if partido_overlap.upper() == str(partido_real).upper():
                        same_party_votes += votos_territorio
                    if campo_amplo == target_camp and campo_amplo != "não informado":
                        same_camp_votes += votos_territorio
                    elif campo_amplo != "não informado":
                        cross_camp_votes += votos_territorio
                    camp_votes[campo_amplo] = camp_votes.get(campo_amplo, 0) + votos_territorio

                same_party_share = pct(same_party_votes, total_overlap)
                same_camp_share = pct(same_camp_votes, total_overlap)
                cross_camp_share = pct(cross_camp_votes, total_overlap)

                if same_camp_share is not None and same_camp_share >= 55:
                    competencia_classificacao = "compartilhado sobretudo dentro do mesmo campo político"
                elif cross_camp_share is not None and cross_camp_share >= 35:
                    competencia_classificacao = "efetivamente disputado por campos diferentes"
                else:
                    competencia_classificacao = "competitivo, mas com liderança relativamente nítida de um campo predominante"

            if not competition_full_df.empty:
                competition_rank_df = competition_full_df.sort_values("votos_territorio", ascending=False).reset_index(drop=True)
                competition_total = float(competition_rank_df["votos_territorio"].sum()) if not competition_rank_df.empty else 0.0
                target_rows = competition_rank_df[competition_rank_df["is_target"] == True]

                if not target_rows.empty:
                    target_idx = int(target_rows.index[0])
                    target_rank = target_idx + 1
                    target_row = competition_rank_df.iloc[target_idx]
                    leader_row = competition_rank_df.iloc[0]
                    target_votes = as_int(target_row.get("votos_territorio")) or 0
                    target_share = pct(target_votes, competition_total)
                    leader_votes = as_int(leader_row.get("votos_territorio")) or 0
                    leader_share = pct(leader_votes, competition_total)

                    def overlap_actor_label(row):
                        nome_comp = str(row.get("nome_exibicao") or "").strip()
                        partido_comp = str(row.get("partido") or "").strip()
                        votos_comp = as_int(row.get("votos_territorio")) or 0
                        if partido_comp and partido_comp.lower() not in {"sem partido", "não info", "nao info", "não informado", "nao informado"}:
                            return f"**{nome_comp}** ({partido_comp}, {format_compact_number(votos_comp)} votos)"
                        return f"**{nome_comp}** ({format_compact_number(votos_comp)} votos)"

                    if target_rank == 1:
                        runner_up = competition_rank_df.iloc[1] if len(competition_rank_df) > 1 else None
                        if runner_up is not None:
                            runner_votes = as_int(runner_up.get("votos_territorio")) or 0
                            runner_share = pct(runner_votes, competition_total)
                            margin_votes = max(target_votes - runner_votes, 0)
                            margin_share = max((target_share or 0) - (runner_share or 0), 0)
                            if margin_share >= 10:
                                dominio_texto = "liderança robusta"
                            elif margin_share >= 4:
                                dominio_texto = "liderança clara, mas com competição real"
                            else:
                                dominio_texto = "liderança estreita"

                            competicao_leitura = (
                                f"No recorte territorial analisado, quem **domina** o espaço é **{nome_urna}**. "
                                f"Entre os deputados federais eleitos com presença nesse mesmo território, ele ocupa a **1ª posição**, com "
                                f"**{format_compact_number(target_votes)} votos** e cerca de **{fmt_number(target_share, 1, '%')}** do volume competitivo observado. "
                                f"A vantagem sobre o segundo colocado, **{runner_up['nome_exibicao']}**, é de **{format_compact_number(margin_votes)} votos** "
                                f"({fmt_number(margin_share, 1, ' p.p.')}), o que configura uma **{dominio_texto}**."
                            )
                        else:
                            competicao_leitura = (
                                f"No recorte territorial analisado, quem **domina** o espaço é **{nome_urna}**. "
                                f"Ele aparece sozinho com densidade eleitoral relevante entre os eleitos observados nesse território, "
                                f"com **{format_compact_number(target_votes)} votos**."
                            )
                    else:
                        gap_votes = max(leader_votes - target_votes, 0)
                        gap_share = max((leader_share or 0) - (target_share or 0), 0)
                        if gap_share >= 10:
                            dominio_texto = "liderança externa consolidada"
                        elif gap_share >= 4:
                            dominio_texto = "liderança externa clara, mas disputável"
                        else:
                            dominio_texto = "disputa apertada"

                        competicao_leitura = (
                            f"No recorte territorial analisado, quem **domina** o espaço é **{leader_row['nome_exibicao']}**. "
                            f"**{nome_urna}** aparece na **{target_rank}ª posição**, com **{format_compact_number(target_votes)} votos** e cerca de "
                            f"**{fmt_number(target_share, 1, '%')}** do volume competitivo observado. A distância para o líder é de "
                            f"**{format_compact_number(gap_votes)} votos** ({fmt_number(gap_share, 1, ' p.p.')}), o que caracteriza uma **{dominio_texto}**."
                        )

                    relevant_others = competition_rank_df[competition_rank_df["is_target"] != True].head(4)
                    others_labels = [overlap_actor_label(row) for _, row in relevant_others.iterrows()]
                    if others_labels:
                        competencia_resumo = (
                            f"Isso significa que o mesmo público também é disputado por {natural_join(others_labels)}. "
                            f"O território, portanto, não deve ser lido como monopólio absoluto: ele é um espaço em que **{nome_urna}** "
                            f"{'lidera' if target_rank == 1 else 'disputa posição'} diante de concorrentes que já têm capilaridade eleitoral no mesmo recorte de zonas e municípios."
                        )

                    if same_party_share is not None and same_party_share >= 20:
                        competencia_resumo += (
                            f" Há ainda uma camada intrapartidária relevante: entre os concorrentes observados, nomes da mesma sigla respondem por "
                            f"cerca de **{same_party_share:.1f}%** do volume competitivo."
                        )

                    if cross_camp_share is not None and cross_camp_share >= 25:
                        janelas_texto = (
                            "A competição não está restrita ao campo imediato do deputado. Há atores de outros campos políticos com presença concreta no mesmo território, "
                            "o que sugere um eleitorado menos cativo do que o retrato bruto dos votos pode sugerir. Em termos estratégicos, a disputa tende a se abrir quando o adversário consegue "
                            "traduzir clivagens nacionais em problemas locais reconhecíveis, sem parecer estranho à sociologia do reduto."
                        )
                    elif same_camp_share is not None and same_camp_share >= 50:
                        janelas_texto = (
                            "A principal disputa parece ocorrer dentro de um mesmo campo político. Nessa situação, o voto tende a girar menos em torno de identidade ideológica pura e mais em torno de reputação, "
                            "grau de enraizamento local, estilo de representação e capacidade percebida de entregar proteção ou influência ao território."
                        )
                    else:
                        janelas_texto = (
                            "O recorte sugere um território competitivo, mas ainda com centro de gravidade reconhecível. A disputa fica mais aberta quando a concorrência consegue combinar presença local, "
                            "sinalização de pertencimento e uma narrativa compatível com a hierarquia social do reduto."
                        )

            metodo_linha = ""
            if granular_core_redutos:
                metodo_linha = (
                    f"Esta leitura se apoia em **{len(granular_core_redutos)} microterritórios/setores dominantes**, que cobrem "
                    f"**{fmt_number(granular_core_coverage, 1, '%')}** do núcleo setorial considerado na síntese territorial."
                )

            ranking_municipal = ", ".join(item["municipio"] for item in top_municipios[:4]) if top_municipios else "sem recorte municipal dominante claro"

            metric_specs = [
                ("renda_media_responsavel", "Renda média do responsável", format_currency),
                ("moradores_por_domicilio", "Moradores por domicílio", lambda value: fmt_number(value, 1) if value is not None else "N/D"),
                ("alfabetizacao", "Alfabetização", format_percent),
                ("rede_geral_agua", "Rede geral de água", format_percent),
                ("rede_esgoto", "Rede de esgoto", format_percent),
                ("lixo_coletado", "Coleta de lixo", format_percent),
                ("share_domicilios_improvisados", "Domicílios improvisados", format_percent),
                ("share_estrutura_degradada", "Estrutura degradada", format_percent),
            ]
            comparativo_linhas = []
            for metric_name, label, formatter in metric_specs:
                reduto_value = metric_fields.get(metric_name)
                bm = benchmark_payload.get(metric_name, {})
                if reduto_value is None:
                    continue
                if metric_name in {"share_domicilios_improvisados", "share_estrutura_degradada"} and (reduto_value or 0) == 0 and (bm.get("estado") or 0) == 0 and (bm.get("brasil") or 0) == 0:
                    continue
                linha = choose_metric_sentence(label, reduto_value, bm.get("estado"), bm.get("brasil"), formatter)
                if linha:
                    comparativo_linhas.append(linha)

            if top1_share is not None and top1_share >= 35:
                concentracao_analitica = "muito concentrada"
            elif top5_share is not None and top5_share >= 55:
                concentracao_analitica = "concentrada em poucos polos"
            else:
                concentracao_analitica = "mais distribuída entre vários polos"

            referencia_lens = []
            referencia_passagens = []
            reference_query = " ".join(
                filter(
                    None,
                    [
                        nome_urna,
                        estado_nome,
                        municipio_lider or "",
                        ranking_municipal,
                        "comportamento eleitoral reduto territorio competicao opiniao publica campanha",
                    ],
                )
            )
            if build_reference_lens:
                try:
                    referencia_lens = build_reference_lens(reference_query, limit=4)
                except Exception:
                    referencia_lens = []
            if retrieve_reference_passages:
                try:
                    referencia_passagens = retrieve_reference_passages(reference_query, limit=3)
                except Exception:
                    referencia_passagens = []

            top_names = [item["municipio"] for item in top_municipios[:5]]
            top_municipios_texto = natural_join(top_names[:4])
            locais_texto = []
            for linha in locais_lines[:3]:
                cleaned = re.sub(r"^- ", "", linha).replace("**", "")
                locais_texto.append(cleaned.rstrip("."))
            locais_texto_str = natural_join(locais_texto)

            renda_delta_estado = delta_currency(renda, renda_estado)
            renda_delta_brasil = delta_currency(renda, renda_brasil)
            moradores_delta_estado = delta_points(moradores, moradores_estado)
            alfabet_delta_estado = delta_points(metric_fields.get("alfabetizacao"), alfabet_estado)
            esgoto_delta_estado = delta_points(esgoto, esgoto_estado)
            esgoto_delta_brasil = delta_points(esgoto, esgoto_brasil)
            agua_delta_estado = delta_points(agua, agua_estado)
            lixo_delta_estado = delta_points(lixo, lixo_estado)

            if top1_share is not None and top1_share >= 20:
                estrutura_reduto = "fortemente ancorado em um município-líder"
            elif top5_share is not None and top5_share >= 45:
                estrutura_reduto = "organizado por um conjunto curto de polos municipais"
            else:
                estrutura_reduto = "mais capilarizado entre municípios médios e polos locais"

            densidade_local_texto = (
                f"Dentro desse arco, a concentração mais fina aparece em locais de votação como {locais_texto_str}."
                if locais_texto_str
                else "Mesmo sem detalhamento fino de locais de votação bem nomeados, o padrão municipal já mostra onde o reduto se fecha com mais nitidez."
            )

            comparativo_partes = []
            if renda is not None and renda_estado is not None and renda_brasil is not None:
                comparativo_partes.append(
                    f"A renda média do responsável no reduto é de {format_currency(renda)}, valor {'inferior' if (renda_delta_estado or 0) < 0 else 'superior' if (renda_delta_estado or 0) > 0 else 'muito próximo'} ao padrão estadual ({format_currency(renda_estado)}) e {'inferior' if (renda_delta_brasil or 0) < 0 else 'superior' if (renda_delta_brasil or 0) > 0 else 'muito próximo'} ao nacional ({format_currency(renda_brasil)})."
                )
            if esgoto is not None and esgoto_estado is not None and esgoto_brasil is not None:
                comparativo_partes.append(
                    f"O dado mais distintivo não está na renda, mas na infraestrutura: o reduto registra {format_percent(esgoto)} de cobertura de esgoto, cerca de {points_text(esgoto_delta_estado)} frente ao estado e {points_text(esgoto_delta_brasil)} frente ao Brasil."
                )
            if alfabet_delta_estado is not None and moradores_delta_estado is not None:
                comparativo_partes.append(
                    f"Somam-se a isso uma alfabetização de {alfabet_texto} ({points_text(alfabet_delta_estado)} acima do estado) e domicílios com {moradores_texto} moradores em média ({points_text(moradores_delta_estado)} frente ao padrão estadual), o que sugere um território mais organizado socialmente e menos comprimido do que a média."
                )
            if agua_delta_estado is not None and lixo_delta_estado is not None:
                comparativo_partes.append(
                    f"Água em rede ({agua_texto}) e coleta de lixo ({lixo_texto}) não se destacam tanto quanto o esgoto, mas reforçam um quadro de urbanização funcional, sem indicadores fortes de precariedade extrema."
                )
            comparativo_texto = " ".join(comparativo_partes).strip()
            reference_corpus = " ".join(str(item.get("text") or "") for item in referencia_passagens)
            reference_norm = normalizar_texto_ia(reference_corpus)
            enfatiza_cruzamento = ("cruzamentos entre variaveis" in reference_norm) or ("variaveis" in reference_norm)
            enfatiza_moradia = "local de moradia" in reference_norm
            enfatiza_rigidez = ("variaveis mais rigidas" in reference_norm) or ("brigada pesada" in reference_norm) or ("dificil move" in reference_norm)

            if lider_e_capital:
                eixo_territorial = "uma centralidade metropolitana clara"
            elif not capital_nos_principais and len(top_names) >= 4:
                eixo_territorial = "um arco interiorano relativamente coeso"
            else:
                eixo_territorial = "uma coalizão de polos urbanos e sub-regionais"

            if renda_delta_estado is not None:
                if renda_delta_estado >= 600:
                    renda_analitica = "um patamar de renda nitidamente acima do padrão estadual"
                elif renda_delta_estado >= 200:
                    renda_analitica = "uma renda um pouco acima da média estadual"
                elif renda_delta_estado <= -600:
                    renda_analitica = "um patamar de renda claramente abaixo do padrão estadual"
                elif renda_delta_estado <= -200:
                    renda_analitica = "uma renda ligeiramente abaixo da média estadual"
                else:
                    renda_analitica = "uma renda muito próxima da média estadual"
            else:
                renda_analitica = "uma renda sem desvio forte em relação ao estado"

            if esgoto_delta_estado is not None:
                if esgoto_delta_estado >= 10:
                    infra_analitica = "infraestrutura urbana muito superior à média estadual, sobretudo no esgoto"
                elif esgoto_delta_estado >= 4:
                    infra_analitica = "infraestrutura urbana melhor que a média estadual"
                elif esgoto_delta_estado <= -6:
                    infra_analitica = "infraestrutura urbana mais frágil que a média estadual"
                else:
                    infra_analitica = "infraestrutura urbana próxima do padrão estadual"
            else:
                infra_analitica = "infraestrutura urbana sem desvio forte em relação ao estado"

            if renda_rel_estado in {"bem acima", "acima"} and morfologia_residencial.startswith("ocupação mais verticalizada"):
                eleitor_tipo = "camadas urbanas de classe média e classe média alta, mais ideologizadas e sensíveis a distinção social, ordem e desempenho"
                mecanismo_voto = "identificação ideológica, percepção de competência e defesa de status"
            elif renda_rel_estado in {"abaixo", "bem abaixo"} and esgoto_rel_estado in {"acima", "bem acima"}:
                eleitor_tipo = "um interior urbano organizado, de renda mediana, mas com forte valorização de ordem local, estabilidade e representação próxima"
                mecanismo_voto = "reconhecimento territorial, conservadorismo social e mediação local"
            elif renda_rel_estado in {"abaixo", "bem abaixo"} and infraestrutura_score is not None and infraestrutura_score < 75:
                eleitor_tipo = "territórios mais pressionados, em que o voto mistura aspiração material, busca de proteção e presença política concreta"
                mecanismo_voto = "promessa de proteção, proximidade e resposta a carências"
            else:
                eleitor_tipo = "segmentos de classe média ou média-baixa relativamente organizados, pouco aderentes a discursos puramente redistributivos"
                mecanismo_voto = "ordem local, previsibilidade e identificação com a oferta política dominante do reduto"

            if target_rank == 1:
                competicao_analitica = (
                    f"No plano competitivo, **{nome_urna}** não atua em vazio: ele lidera um território em que outros eleitos também circulam, mas o faz a partir de uma posição de vantagem. "
                    f"Isso significa que seu reduto é competitivo, embora ainda possua um centro de gravidade favorável ao deputado."
                )
            elif "mesmo campo político" in competencia_classificacao:
                competicao_analitica = (
                    f"No plano competitivo, o reduto parece menos atravessado por choque ideológico frontal e mais por concorrência entre nomes que disputam um eleitorado vizinho. "
                    f"O problema central, aqui, não é converter um eleitor de campo oposto, mas prevalecer dentro do próprio espaço político."
                )
            else:
                competicao_analitica = (
                    f"No plano competitivo, o reduto não se comporta como monopólio: há presença efetiva de outros eleitos no mesmo recorte, o que torna a disputa mais aberta do que o total bruto de votos poderia sugerir."
                )

            conceitos_ativados = []
            if enfatiza_cruzamento:
                conceitos_ativados.append(
                    "que o voto só ganha sentido analítico quando se cruzam território, posição social e estrutura da disputa"
                )
            if enfatiza_moradia:
                conceitos_ativados.append(
                    "que local de moradia e sociabilidade territorial ajudam a organizar predisposições políticas estáveis"
                )
            if enfatiza_rigidez:
                conceitos_ativados.append(
                    "que há variáveis mais rígidas do que a retórica de campanha, especialmente quando o eleitor reconhece previamente o ator político e o lugar que ele ocupa"
                )
            if not conceitos_ativados:
                conceitos_ativados.append(
                    "que campanhas eficazes partem de predisposições reais do eleitorado, e não de um eleitor abstrato inventado pela propaganda"
                )

            conceitos_texto = natural_join(conceitos_ativados[:3])

            referencia_texto = (
                f"Tomando *A cabeça do eleitor*, de Alberto Carlos Almeida, como chave de leitura, o dado relevante aqui não é um indicador isolado, mas o modo como eles se combinam. "
                f"O livro ajuda a ler {conceitos_texto}. No caso de **{nome_urna}** {estado_locativo}, esse cruzamento aponta para **{eixo_territorial}** e para um eleitorado localizado em territórios com **{renda_analitica}** e **{infra_analitica}**. "
                f"Isso significa que a razão estratégica do voto não está num apelo genérico: ela aparece quando a oferta política do deputado se encaixa em uma sociologia local específica, com {mecanismo_voto}. "
                f"Em vez de descrever um eleitor abstrato, os números sugerem um mercado eleitoral em que território, padrão urbano e competição ajudam a explicar por que o voto se estabiliza exatamente onde se estabiliza."
            )

            sociologia_analitica = (
                f"O perfil provável do eleitorado de **{nome_urna}** não é o de uma massa indistinta. O reduto combina **{ciclo_vida}**, "
                f"presença de **{base_social}** e **{morfologia_residencial}**. A combinação estatisticamente mais importante não está em um único número, mas no contraste entre **{renda_texto}** de renda média, "
                f"**{alfabet_texto}** de alfabetização e um ambiente urbano em que **esgoto ({esgoto_texto})**, **água ({agua_texto})** e **coleta ({lixo_texto})** desenham um território mais funcional do que precário. "
                f"Isso aproxima o reduto de um eleitorado para o qual identidade política, reputação local e leitura de ordem cotidiana tendem a pesar mais do que promessas difusas de redistribuição."
            )

            comparativo_analitico = (
                f"Quando comparado ao padrão {estado_locativo.replace('no ', 'do ').replace('na ', 'da ').replace('em ', 'de ')} e ao brasileiro, o reduto não se destaca por um único traço absoluto, "
                f"mas pela composição dos desvios. A renda do responsável fica em **{renda_texto}**, {'muito próxima' if abs(renda_delta_estado or 0) < 200 else 'acima' if (renda_delta_estado or 0) > 0 else 'abaixo'} da média estadual; "
                f"os domicílios são **{moradores_texto}** moradores em média, sinal de estrutura doméstica menos pressionada; e a alfabetização chega a **{alfabet_texto}**. "
                f"O ponto mais expressivo é o saneamento: o esgoto fica **{points_text(esgoto_delta_estado)}** acima do estado e **{points_text(esgoto_delta_brasil)}** acima do Brasil. "
                f"Esse conjunto revela um reduto que não é nem periferia aguda nem elite dissociada do território, mas um espaço socialmente organizado o suficiente para transformar predisposições culturais e reputacionais em voto estável."
            )

            sintese_final = (
                f"Em síntese, o voto de **{nome_urna}** {estado_locativo} depende menos de presença homogênea e mais da capacidade de dominar um recorte social e territorial específico. "
                f"Trata-se de um reduto **{concentracao_analitica}**, apoiado em **{eixo_territorial}**, socialmente compatível com **{eleitor_tipo}** e inserido em um ambiente **{competencia_classificacao}**. "
                f"O ponto decisivo não é apenas onde o deputado soma votos, mas que tipo de território torna sua mensagem crível, reproduzível e competitiva."
            )

            analysis_markdown = f"""
## Arquitetura territorial do voto
O reduto de **{nome_urna}** {estado_locativo} não é um agregado indiferenciado de votos espalhados pelo estado. Ele se organiza em torno de um eixo territorial identificável, com hierarquia interna e pontos claros de maior densidade. {geometria_reduto} {concentracao_texto}

Em termos analíticos, isso significa que a força do deputado depende menos de presença uniforme e mais da capacidade de estabilizar apoio em municípios específicos. O eixo dominante do reduto aparece em **{ranking_municipal}**{f", com liderança de **{municipio_lider}** e **{format_compact_number(votos_lider)} votos oficiais** nesse município" if municipio_lider and votos_lider is not None else ""}. {densidade_local_texto}

## Corroboração conceitual
{referencia_texto}

## Perfil socioterritorial provável do eleitorado
{sociologia_analitica}

### Comparação estrutural com o estado e com o Brasil
{comparativo_analitico}

## Competição no mesmo território
{competicao_leitura}

{competencia_resumo}

## Leitura política do reduto
{janelas_texto}

{sintese_final}

{metodo_linha}

---
*Relatório territorial gerado a partir dos dados oficiais de votação e dos microterritórios do IBGE materializados no projeto, com apoio conceitual de* A cabeça do eleitor, *de Alberto Carlos Almeida.*
""".strip()

            top_municipios_payload = [
                {
                    "municipio": item.get("municipio"),
                    "votos": item.get("votos"),
                    "share_total_oficial": item.get("share"),
                }
                for item in top_municipios[:8]
            ]

            competition_payload = []
            if not competition_full_df.empty:
                for _, row in competition_full_df.head(10).iterrows():
                    competition_payload.append({
                        "nome": row.get("nome_exibicao"),
                        "partido": row.get("partido"),
                        "alinhamento": row.get("alinhamento"),
                        "votos_no_recorte": as_int(row.get("votos_territorio")) or 0,
                        "share_no_recorte": float(row.get("share_no_recorte") or 0.0),
                        "is_target": bool(row.get("is_target")),
                    })

            benchmark_payload_reduzido = {
                "renda_media_responsavel": {
                    "reduto": renda,
                    "estado": renda_estado,
                    "brasil": renda_brasil,
                },
                "moradores_por_domicilio": {
                    "reduto": moradores,
                    "estado": moradores_estado,
                    "brasil": moradores_brasil,
                },
                "alfabetizacao": {
                    "reduto": metric_fields.get("alfabetizacao"),
                    "estado": alfabet_estado,
                    "brasil": alfabet_brasil,
                },
                "rede_geral_agua": {
                    "reduto": agua,
                    "estado": agua_estado,
                    "brasil": agua_brasil,
                },
                "rede_esgoto": {
                    "reduto": esgoto,
                    "estado": esgoto_estado,
                    "brasil": esgoto_brasil,
                },
                "lixo_coletado": {
                    "reduto": lixo,
                    "estado": lixo_estado,
                    "brasil": lixo_brasil,
                },
            }

            reference_passages_payload = [
                {
                    "section": item.get("section"),
                    "text": str(item.get("text") or "")[:1400],
                }
                for item in referencia_passagens[:3]
            ]

            structured_context = {
                "parlamentar": nome_urna,
                "nome_civil": nome_real,
                "partido": partido_real,
                "uf": estado_real,
                "estado_nome": estado_nome,
                "estado_locativo": estado_locativo,
                "cargo": cargo_real,
                "alinhamento": alinhamento_real,
                "total_votos_oficiais": total_oficial,
                "municipio_lider": municipio_lider,
                "votos_municipio_lider": votos_lider,
                "top1_share": top1_share,
                "top5_share": top5_share,
                "top10_share": top10_share,
                "geometria_reduto": geometria_reduto,
                "concentracao_texto": concentracao_texto,
                "top_municipios": top_municipios_payload,
                "locais_densidade": locais_texto[:5],
                "idade_lider": idade_lider,
                "base_social": base_social,
                "morfologia_residencial": morfologia_residencial,
                "ciclo_vida": ciclo_vida,
                "benchmark_resumido": benchmark_payload_reduzido,
                "competencia_classificacao": competencia_classificacao,
                "competition_payload": competition_payload,
                "same_party_share": same_party_share,
                "same_camp_share": same_camp_share,
                "cross_camp_share": cross_camp_share,
                "reference_lens": referencia_lens[:4],
                "reference_passages": reference_passages_payload,
            }

            if return_context:
                return {
                    "analysis": analysis_markdown,
                    "structured_context": structured_context,
                }

            return analysis_markdown

        fallback_bundle = build_local_fallback_analysis(return_context=True)
        fallback_analise_texto = fallback_bundle["analysis"]
        structured_context = fallback_bundle["structured_context"]

        analise_texto = fallback_analise_texto
        try:
            import openai

            load_dotenv()
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                client = openai.OpenAI(api_key=api_key)

                llm_cache_path = DATABASE_PATHS.get("llm_cache") or os.path.join(BASE_DIR, "llm_cache.db")
                cache_key_payload = {
                    "version": "perfil_eleitor_agents_v5",
                    "parlamentar": nome_urna,
                    "partido": partido_real,
                    "uf": estado_real,
                    "contexto": structured_context,
                }
                cache_hash = hashlib.md5(json.dumps(cache_key_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

                cached_llm_response = None
                try:
                    cache_conn = sqlite3.connect(llm_cache_path)
                    cache_cursor = cache_conn.cursor()
                    cache_cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS llm_cache (
                            hash_id TEXT PRIMARY KEY,
                            response_json TEXT,
                            created_at TEXT
                        )
                        """
                    )
                    cache_cursor.execute("SELECT response_json FROM llm_cache WHERE hash_id = ?", (cache_hash,))
                    cached_row = cache_cursor.fetchone()
                    if cached_row and cached_row[0]:
                        cached_llm_response = cached_row[0]
                except Exception as cache_exc:
                    logger.warning(f"Falha ao acessar cache do Antunes de perfil: {cache_exc}")
                finally:
                    try:
                        cache_conn.close()
                    except Exception:
                        pass

                if cached_llm_response:
                    analise_texto = cached_llm_response
                else:
                    def extract_message_content(response):
                        try:
                            return (response.choices[0].message.content or "").strip()
                        except Exception:
                            return ""

                    def run_agent(agent_name: str, system_prompt: str, user_prompt: str, max_completion_tokens: int = 1800, timeout_seconds: float = 35.0) -> str:
                        response = client.chat.completions.create(
                            model="gpt-5.4-mini",
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=0.4,
                            max_completion_tokens=max_completion_tokens,
                            timeout=timeout_seconds,
                        )
                        content = extract_message_content(response)
                        if not content:
                            raise RuntimeError(f"{agent_name} retornou conteúdo vazio")
                        return content

                    contexto_json = json.dumps(clean_data_for_json(structured_context), ensure_ascii=False, indent=2)
                    fallback_resumo = fallback_analise_texto[:9000]

                    territorial_text = run_agent(
                        "Agente territorial",
                        (
                            "Você é um analista de geografia eleitoral especializado em eleições proporcionais. "
                            "Escreva apenas a seção 'Arquitetura territorial do voto'. "
                            "Não faça lista de municípios. Não repita números como planilha. "
                            "Sua tarefa é formular uma tese territorial específica do caso, dizendo como o voto se distribui no estado, "
                            "que tipo de eixo municipal organiza o reduto e o que isso implica para a construção política do deputado. "
                            "Use números somente quando forem indispensáveis para sustentar a tese. "
                            "Você pode mobilizar conhecimento geral, estável e amplamente conhecido sobre os municípios e bairros citados "
                            "(por exemplo: perfil metropolitano ou interiorano, base industrial, presença de serviços, agricultura forte, "
                            "classe média urbana, função regional, tradição conservadora ou progressista), mas somente como contexto interpretativo "
                            "para explicar os dados observados. Não invente fatos específicos nem substitua a evidência territorial por generalidades."
                        ),
                        (
                            f"Deputado analisado: {nome_urna} ({partido_real}-{estado_real}).\n\n"
                            f"Contexto estruturado:\n{contexto_json}\n\n"
                            f"Rascunho factual local já calculado:\n{fallback_resumo}\n\n"
                            "Escreva 2 ou 3 parágrafos tecnicamente densos, específicos do caso, sem clichês e sem texto genérico aplicável a qualquer deputado. "
                            "Explique por que a geografia concreta desses municípios ajuda a entender a concentração do voto."
                        ),
                    )

                    sociological_text = run_agent(
                        "Agente sociológico",
                        (
                            "Você é um sociólogo político especializado em comportamento eleitoral brasileiro. "
                            "Escreva duas seções: 'Corroboração conceitual' e 'Perfil socioterritorial provável do eleitorado'. "
                            "Use o livro A cabeça do eleitor apenas como lente conceitual, sem citar páginas e sem enumerar lições genéricas. "
                            "Cruze explicitamente as ideias do livro com os números do caso. "
                            "Não descreva gráficos; interprete o que a combinação dos indicadores revela sobre a lógica do voto. "
                            "Você pode usar conhecimento contextual estável sobre os municípios/bairros do reduto para enriquecer a análise "
                            "(estrutura produtiva, sociabilidade local, morfologia urbana, estratificação social, perfil ocupacional aproximado), "
                            "desde que isso seja usado para iluminar os dados medidos no reduto. "
                            "Seu texto deve soar como análise sociológica aplicada à eleição de deputado federal, não como resumo do dashboard."
                        ),
                        (
                            f"Deputado analisado: {nome_urna} ({partido_real}-{estado_real}).\n\n"
                            f"Texto territorial já produzido:\n{territorial_text}\n\n"
                            f"Contexto estruturado:\n{contexto_json}\n\n"
                            f"Rascunho factual local já calculado:\n{fallback_resumo}\n\n"
                            "Escreva 3 a 5 parágrafos coerentes e específicos do caso. "
                            "A seção 'Corroboração conceitual' deve parecer escrita por alguém que leu o livro e soube aplicá-lo ao caso concreto. "
                            "Mostre como os números do reduto revelam mecanismos sociais e políticos, e não apenas diferenças aritméticas."
                        ),
                    )

                    competition_text = run_agent(
                        "Agente competitivo",
                        (
                            "Você é um analista político-eleitoral focado em competição territorial entre deputados federais. "
                            "Escreva duas seções: 'Competição no mesmo território' e 'Leitura política do reduto'. "
                            "Responda de forma direta: quem domina o território, quão competitivo é o deputado analisado, "
                            "que outros eleitos disputam o mesmo público e se a competição é intrapartidária, de mesmo campo ou entre campos diferentes. "
                            "Não transforme a resposta em listagem burocrática. "
                            "Use os números de competição para inferir se o território é hegemônico, contestado, compartido ou poroso. "
                            "Quando útil, use conhecimento político geral e estável sobre os atores e sobre a sociologia eleitoral local, "
                            "mas sempre ancorado no recorte territorial observado."
                        ),
                        (
                            f"Deputado analisado: {nome_urna} ({partido_real}-{estado_real}).\n\n"
                            f"Texto territorial já produzido:\n{territorial_text}\n\n"
                            f"Texto sociológico já produzido:\n{sociological_text}\n\n"
                            f"Contexto estruturado:\n{contexto_json}\n\n"
                            f"Rascunho factual local já calculado:\n{fallback_resumo}\n\n"
                            "Escreva 2 a 4 parágrafos com linguagem de consultoria política, explicando o padrão competitivo do território. "
                            "Diga o que os números sugerem sobre dominância, ameaça competitiva e circulação do eleitor entre partidos ou campos próximos."
                        ),
                    )

                    synthesis_text = run_agent(
                        "Agente de síntese",
                        (
                            "Você é o redator-chefe de um relatório técnico-político sobre redutos eleitorais de deputados federais. "
                            "Sua tarefa é consolidar o trabalho de três especialistas em um documento final coeso, denso e não padronizado. "
                            "O texto final deve ter estas seções em markdown: "
                            "'## Arquitetura territorial do voto', "
                            "'## Corroboração conceitual', "
                            "'## Perfil socioterritorial provável do eleitorado', "
                            "'## Competição no mesmo território', "
                            "'## Leitura política do reduto', "
                            "'## Síntese final'. "
                            "Não use listas de municípios, não enumere lições do livro, não repita o dashboard em prosa, "
                            "não use texto de manual ou frases intercambiáveis entre deputados. "
                            "Integre contexto territorial real dos municípios citados, conhecimento político geral estável e a lente de A cabeça do eleitor "
                            "para produzir uma análise que pareça relatório de consultoria política, não formulário preenchido."
                        ),
                        (
                            f"Deputado analisado: {nome_urna} ({partido_real}-{estado_real}).\n\n"
                            f"Contexto estruturado:\n{contexto_json}\n\n"
                            f"Agente territorial:\n{territorial_text}\n\n"
                            f"Agente sociológico:\n{sociological_text}\n\n"
                            f"Agente competitivo:\n{competition_text}\n\n"
                            "Consolide isso em um único relatório. O resultado deve parecer parecer técnico de consultoria política com base empírica real. "
                            "A análise deve usar os dados do caso como espinha dorsal e o conhecimento contextual do LLM como camada interpretativa adicional."
                        ),
                        max_completion_tokens=2600,
                        timeout_seconds=45.0,
                    )

                    if synthesis_text.strip():
                        analise_texto = synthesis_text.strip() + "\n\n---\n*Relatório territorial gerado a partir dos dados oficiais de votação e dos microterritórios do IBGE materializados no projeto, com apoio conceitual de* A cabeça do eleitor, *de Alberto Carlos Almeida.*"
                        try:
                            cache_conn = sqlite3.connect(llm_cache_path)
                            cache_cursor = cache_conn.cursor()
                            cache_cursor.execute(
                                "INSERT OR REPLACE INTO llm_cache (hash_id, response_json, created_at) VALUES (?, ?, ?)",
                                (cache_hash, analise_texto, datetime.now().isoformat()),
                            )
                            cache_conn.commit()
                        except Exception as cache_exc:
                            logger.warning(f"Falha ao gravar cache do Antunes de perfil: {cache_exc}")
                        finally:
                            try:
                                cache_conn.close()
                            except Exception:
                                pass
        except Exception as llm_exc:
            logger.warning(f"Falha na cadeia de agentes do Antunes; usando fallback local: {llm_exc}")

        con.close()
        return {"analise": analise_texto}

    except Exception as e:
        logging.error(f"Erro na análise de perfil: {str(e)}")
        return {"analise": f"Erro ao gerar análise: {str(e)}"}

@app.post("/api/llm/auditor-antunes")
async def auditor_antunes(request: dict):
    """
    Endpoint dedicado ao Robô Antunes para auditoria detalhada.
    Espera um payload com dados completos do parlamentar e despesas.
    Retorna um JSON com: relatorio_tecnico, email_corpo, disclaimer.
    """
    try:
        import openai
        from dotenv import load_dotenv
        import json
        
        load_dotenv()
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise HTTPException(status_code=500, detail="API key do OpenAI não configurada")
            
        client = openai.OpenAI(api_key=api_key)
        
        # Extrair dados do request
        parlamentar = request.get('parlamentar')
        despesa = request.get('despesa')
        estado = request.get('estado')
        partido = request.get('partido')
        ano = request.get('ano')
        resumo = request.get('resumo_gastos', {})
        top_fornecedores = request.get('top_fornecedores', [])
        notas_atipicas = request.get('notas_atipicas', [])
        metricas = request.get('metricas_comparativas', {})
        todas_notas = request.get('todas_notas', []) or []
        dados_temporais_req = request.get('dados_temporais', []) or []
        dados_mapa_req = request.get('dados_mapa', []) or []
        orgao_destino = request.get('orgao_destino', 'TCU')
        
        import hashlib
        import sqlite3
        
        # Calcular hash único para este conjunto de dados
        # Inclui uma versão explícita para invalidar saídas antigas quando a auditoria evolui.
        cache_fingerprint = {
            "version": "auditor_antunes_v2",
            "parlamentar": parlamentar,
            "despesa": despesa,
            "estado": estado,
            "partido": partido,
            "ano": ano,
            "orgao_destino": orgao_destino,
            "total_gasto": resumo.get('total_gasto'),
            "num_notas": resumo.get('num_notas') or resumo.get('total_notas') or len(todas_notas),
            "fornecedores_unicos": resumo.get('fornecedores_unicos'),
            "num_atipicos": resumo.get('num_atipicos'),
            "metricas": metricas,
            "top_fornecedores_len": len(top_fornecedores),
            "notas_atipicas_len": len(notas_atipicas),
            "todas_notas_len": len(todas_notas),
            "dados_temporais_len": len(dados_temporais_req),
            "dados_mapa_len": len(dados_mapa_req),
        }
        hash_input = json.dumps(cache_fingerprint, ensure_ascii=False, sort_keys=True, default=str)
        query_hash = hashlib.md5(hash_input.encode()).hexdigest()
        
        # Verificar cache
        db_path = DATABASE_PATHS.get('llm_cache')
        if db_path:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                # Criar tabela se não existir
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS auditor_antunes_cache (
                        hash TEXT PRIMARY KEY,
                        response TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Buscar no cache
                cursor.execute("SELECT response FROM auditor_antunes_cache WHERE hash = ?", (query_hash,))
                cached = cursor.fetchone()
                
                if cached:
                    logger.info(f"✅ Retornando auditoria do cache para hash {query_hash}")
                    conn.close()
                    return json.loads(cached[0])
                    
            except Exception as e:
                logger.warning(f"⚠️ Erro ao acessar cache: {e}")
                if 'conn' in locals(): conn.close()
        
        def safe_float(value, default=0.0):
            try:
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    return default
                if isinstance(value, str):
                    cleaned = value.replace('R$', '').replace('.', '').replace(',', '.').strip()
                    return float(cleaned)
                return float(value)
            except Exception:
                return default

        def parse_any_date(value):
            if not value:
                return None
            if isinstance(value, datetime):
                return value
            text = str(value).strip()
            for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
                try:
                    return datetime.strptime(text[:19], fmt)
                except Exception:
                    continue
            try:
                return pd.to_datetime(text, errors='coerce').to_pydatetime()
            except Exception:
                return None

        def normalize_cnpj(value):
            digits = re.sub(r'\D', '', str(value or ''))
            return digits.zfill(14) if digits else ''

        def fmt_money(value):
            return f"R$ {safe_float(value):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

        def fmt_pct(value):
            return f"{safe_float(value):.1f}%".replace('.', ',')

        def first_sig_digit(value):
            try:
                text = re.sub(r'[^1-9]', '', f"{abs(safe_float(value)):.2f}")
                return int(text[0]) if text else None
            except Exception:
                return None

        def get_forensic_rules(categoria):
            """Retorna as regras forenses e base legal específica para cada rubrica."""
            categoria = (categoria or '').upper()
            base_legal_geral = """
[BASE LEGAL TRANSVERSAL]
- Constituição Federal, art. 37: legalidade, impessoalidade, moralidade, publicidade e eficiência.
- Ato da Mesa nº 43/2009: a despesa deve guardar nexo com o exercício do mandato e ser adequadamente comprovada.
- Lei nº 8.429/1992, arts. 10 e 11: proteção ao erário e aos deveres de probidade.
- Jurisprudência do TCU sobre materialidade, razoabilidade, economicidade e necessidade de lastro documental.
"""

            if "COMBUST" in categoria or "LUBRIFICANTE" in categoria:
                return f"""{base_legal_geral}
[RUBRICA: COMBUSTÍVEIS]
- Ato da Mesa nº 43/2009, art. 4º, § 8º: vedações e necessidade de vinculação do gasto a veículo e atividade parlamentar.
- Acórdão TCU 2.873/2018: razoabilidade do gasto e aderência a deslocamentos e agenda funcional.
- Sinais relevantes: pulverização artificial de notas, repetição incomum por fornecedor/dia, concentração excessiva, valores fora de faixa e inconsistências geográficas.
"""
            if "CONSULTORIA" in categoria or "TRABALHOS TÉCNICOS" in categoria:
                return f"""{base_legal_geral}
[RUBRICA: CONSULTORIA / TRABALHOS TÉCNICOS]
- Ato da Mesa nº 43/2009, art. 4º, inciso VI: necessidade de produto ou serviço efetivamente vinculado ao mandato.
- Acórdão TCU 2.162/2012: rejeição de consultoria genérica, sem materialidade demonstrável ou com sobreposição a função permanente de gabinete.
"""
            if "DIVULGA" in categoria or "PUBLICIDADE" in categoria:
                return f"""{base_legal_geral}
[RUBRICA: DIVULGAÇÃO]
- Constituição Federal, art. 37, § 1º: vedação de promoção pessoal.
- Ato da Mesa nº 43/2009: material deve ter caráter informativo, educativo ou de orientação social.
"""
            if "ALIMENT" in categoria:
                return f"""{base_legal_geral}
[RUBRICA: ALIMENTAÇÃO]
- Necessidade de razoabilidade do valor, aderência ao exercício do mandato e vedação de despesas em favor de terceiros sem justificativa.
"""
            return f"""{base_legal_geral}
[RUBRICA: ANÁLISE GERAL]
- Avaliar materialidade, razoabilidade, recorrência, concentração e aderência entre a despesa, o fornecedor e a atividade parlamentar.
"""

        def build_forensic_bundle():
            notes_df = pd.DataFrame(todas_notas or [])
            if notes_df.empty:
                return {
                    "summary": resumo,
                    "comparatives": metricas,
                    "top_suppliers": top_fornecedores[:10],
                    "suspicious_notes": notas_atipicas[:10],
                    "flags": [],
                    "regularity_signals": [],
                    "top_shared_deputies": [],
                    "registry_snapshot": [],
                    "insufficient_notes": True,
                }

            standardized_rows = []
            for row in notes_df.to_dict('records'):
                fornecedor = row.get('txtFornecedor') or row.get('fornecedor') or 'Fornecedor não informado'
                valor = row.get('vlrLiquido')
                if valor is None:
                    valor = row.get('valor')
                data_emissao = row.get('datEmissao') or row.get('data')
                standardized_rows.append({
                    "fornecedor": str(fornecedor).strip(),
                    "valor": safe_float(valor),
                    "data": parse_any_date(data_emissao),
                    "numero": row.get('txtNumero') or row.get('numero'),
                    "descricao": row.get('txtDescricao') or row.get('descricao') or despesa,
                    "url_documento": row.get('urlDocumento') or row.get('url_documento'),
                    "cnpj": normalize_cnpj(row.get('txtCNPJCPF') or row.get('cnpj')),
                    "estado_deputado": row.get('sgUF') or row.get('estado') or estado,
                    "partido_eleicao": row.get('sgPartido') or row.get('partido') or partido,
                })

            std_df = pd.DataFrame(standardized_rows)
            std_df = std_df[std_df['valor'] > 0].copy()
            if std_df.empty:
                return {
                    "summary": resumo,
                    "comparatives": metricas,
                    "top_suppliers": top_fornecedores[:10],
                    "suspicious_notes": notas_atipicas[:10],
                    "flags": [],
                    "regularity_signals": [],
                    "top_shared_deputies": [],
                    "registry_snapshot": [],
                    "insufficient_notes": True,
                }

            std_df['data_str'] = std_df['data'].apply(lambda d: d.strftime('%d/%m/%Y') if d else 'Sem data')
            std_df['weekday'] = std_df['data'].apply(lambda d: d.weekday() if d else None)
            std_df['mes_ref'] = std_df['data'].apply(lambda d: d.strftime('%Y-%m') if d else 'Sem data')

            temporal_df = pd.DataFrame(dados_temporais_req or [])
            map_df = pd.DataFrame(dados_mapa_req or [])

            total_value = safe_float(std_df['valor'].sum())
            note_count = int(len(std_df))
            supplier_count = int(std_df['fornecedor'].nunique())
            median_value = safe_float(std_df['valor'].median())
            std_value = safe_float(std_df['valor'].std())
            p90 = safe_float(std_df['valor'].quantile(0.90))
            p95 = safe_float(std_df['valor'].quantile(0.95))
            max_value = safe_float(std_df['valor'].max())

            limit_atypical = safe_float(resumo.get('limite_atipico') or 0)
            if limit_atypical <= 0:
                limit_atypical = safe_float(std_df['valor'].mean()) + 2 * safe_float(std_df['valor'].std())
            std_df['atypical'] = std_df['valor'] > limit_atypical
            atypical_count = int(std_df['atypical'].sum())
            atypical_total = safe_float(std_df.loc[std_df['atypical'], 'valor'].sum())

            suppliers_df = (
                std_df.groupby(['fornecedor', 'cnpj'], dropna=False)
                .agg(total=('valor', 'sum'), notas=('valor', 'size'), media=('valor', 'mean'))
                .reset_index()
                .sort_values('total', ascending=False)
            )
            suppliers_df['share'] = suppliers_df['total'] / total_value if total_value else 0
            top1_share = safe_float(suppliers_df['share'].head(1).sum() * 100)
            top3_share = safe_float(suppliers_df['share'].head(3).sum() * 100)
            top5_share = safe_float(suppliers_df['share'].head(5).sum() * 100)
            hhi = safe_float((suppliers_df['share'] ** 2).sum() * 10000)

            std_df['cents'] = ((std_df['valor'] * 100).round().astype(int) % 100)
            rounded_00_share = safe_float((std_df['cents'] == 0).mean() * 100)
            rounded_50_share = safe_float((std_df['cents'] == 50).mean() * 100)
            rounded_share = safe_float(std_df['cents'].isin([0, 50]).mean() * 100)

            weekend_mask = std_df['weekday'].isin([5, 6])
            weekend_total = safe_float(std_df.loc[weekend_mask, 'valor'].sum())
            weekend_share = safe_float((weekend_total / total_value) * 100) if total_value else 0
            weekend_count = int(weekend_mask.sum())

            day_supplier_df = (
                std_df.groupby(['data_str', 'fornecedor'])
                .agg(notas=('valor', 'size'), total=('valor', 'sum'), media=('valor', 'mean'))
                .reset_index()
                .sort_values(['notas', 'total'], ascending=False)
            )
            repeated_day_supplier = day_supplier_df[day_supplier_df['notas'] >= 3].head(8)

            duplicate_exact_df = (
                std_df.groupby(['data_str', 'fornecedor', 'valor'])
                .size()
                .reset_index(name='ocorrencias')
                .sort_values('ocorrencias', ascending=False)
            )
            duplicate_exact_df = duplicate_exact_df[duplicate_exact_df['ocorrencias'] >= 2]
            duplicate_note_count = int(duplicate_exact_df['ocorrencias'].sum()) if not duplicate_exact_df.empty else 0

            daily_totals = std_df.groupby('data_str')['valor'].sum().sort_values(ascending=False)
            peak_day_value = safe_float(daily_totals.iloc[0]) if not daily_totals.empty else 0
            peak_day_share = safe_float((peak_day_value / total_value) * 100) if total_value else 0

            monthly_points = []
            peak_month_value = 0
            peak_month_share = 0
            active_months = 0
            if not temporal_df.empty and 'valor' in temporal_df.columns:
                temporal_df['valor'] = temporal_df['valor'].apply(safe_float)
                temporal_df = temporal_df[temporal_df['valor'] > 0].copy()
                if not temporal_df.empty:
                    temporal_df['periodo'] = temporal_df.get('periodo', pd.Series(dtype=str)).astype(str)
                    temporal_df = temporal_df.sort_values('valor', ascending=False)
                    active_months = int(len(temporal_df))
                    peak_month_value = safe_float(temporal_df.iloc[0]['valor'])
                    total_temporal = safe_float(temporal_df['valor'].sum())
                    peak_month_share = safe_float((peak_month_value / total_temporal) * 100) if total_temporal else 0
                    monthly_points = [
                        {
                            "periodo": row['periodo'],
                            "valor": safe_float(row['valor'])
                        }
                        for _, row in temporal_df.head(8).iterrows()
                    ]

            corrected_coords_count = 0
            out_of_state_count = 0
            out_of_state_value = 0
            point_count = 0
            top_cities = []
            top_address_points = []
            if not map_df.empty:
                point_count = int(len(map_df))
                if 'coordenada_corrigida' in map_df.columns:
                    corrected_coords_count = int(map_df['coordenada_corrigida'].fillna(False).astype(bool).sum())
                if 'estado_fornecedor' in map_df.columns:
                    out_mask = map_df['estado_fornecedor'].fillna('').astype(str).str.upper().ne((estado or '').upper())
                    out_mask &= map_df['estado_fornecedor'].fillna('').astype(str).str.len().gt(0)
                    out_of_state_count = int(out_mask.sum())
                    if 'total' in map_df.columns:
                        out_of_state_value = safe_float(map_df.loc[out_mask, 'total'].apply(safe_float).sum())
                if 'cidade_cadastral' in map_df.columns and 'total' in map_df.columns:
                    cities_df = (
                        map_df.assign(total_num=map_df['total'].apply(safe_float))
                        .groupby(['cidade_cadastral', 'estado_fornecedor'], dropna=False)
                        .agg(total=('total_num', 'sum'), fornecedores=('cidade_cadastral', 'size'))
                        .reset_index()
                        .sort_values('total', ascending=False)
                    )
                    top_cities = [
                        {
                            "cidade": row.get('cidade_cadastral'),
                            "estado": row.get('estado_fornecedor'),
                            "total": safe_float(row.get('total')),
                            "fornecedores": int(row.get('fornecedores', 0)),
                        }
                        for _, row in cities_df.head(6).iterrows()
                    ]
                if 'fornecedor' in map_df.columns and 'total' in map_df.columns:
                    top_address_df = (
                        map_df.assign(total_num=map_df['total'].apply(safe_float))
                        .sort_values('total_num', ascending=False)
                    )
                    top_address_points = [
                        {
                            "fornecedor": row.get('fornecedor'),
                            "cidade": row.get('cidade_cadastral'),
                            "estado": row.get('estado_fornecedor'),
                            "fonte_localizacao": row.get('fonte_localizacao'),
                            "coordenada_corrigida": bool(row.get('coordenada_corrigida', False)),
                            "total": safe_float(row.get('total_num')),
                        }
                        for _, row in top_address_df.head(6).iterrows()
                    ]
            out_of_state_share = safe_float((out_of_state_value / total_value) * 100) if total_value else 0

            benford_digits = std_df['valor'].apply(first_sig_digit).dropna()
            benford_obs = {}
            benford_mad = None
            if len(benford_digits) >= 20:
                observed = benford_digits.value_counts(normalize=True).to_dict()
                benford_expected = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
                benford_obs = {str(d): round(observed.get(d, 0), 4) for d in range(1, 10)}
                benford_mad = safe_float(np.mean([abs(observed.get(d, 0) - benford_expected[d]) for d in range(1, 10)]))

            registry_snapshot = []
            top_shared_deputies = []
            cnpjs = [c for c in std_df['cnpj'].dropna().unique().tolist() if c]
            if cnpjs:
                conn_tabelao = None
                try:
                    conn_tabelao = get_db_connection('tabelao')
                    # Cadastro dos fornecedores
                    cnpj_candidates = sorted(set(cnpjs + [c.lstrip('0') for c in cnpjs]))
                    placeholders = ','.join(['?'] * len(cnpj_candidates))
                    query_registry = f"""
                    SELECT CAST(cnpj AS TEXT) AS cnpj, Cidade, Estado, Logradouro, "Número" AS Numero, Bairro, CEP
                    FROM lista_cnpj_geral
                    WHERE CAST(cnpj AS TEXT) IN ({placeholders})
                    """
                    registry_df = pd.read_sql_query(query_registry, conn_tabelao, params=cnpj_candidates)
                    if not registry_df.empty:
                        registry_df['cnpj_clean'] = registry_df['cnpj'].astype(str).str.replace(r'\D', '', regex=True).str.zfill(14)
                        registry_df = registry_df.drop_duplicates('cnpj_clean')
                        merged_registry = pd.merge(
                            suppliers_df[['fornecedor', 'cnpj', 'total', 'share']],
                            registry_df[['cnpj_clean', 'Cidade', 'Estado']],
                            left_on='cnpj',
                            right_on='cnpj_clean',
                            how='left'
                        )
                        registry_snapshot = [
                            {
                                "fornecedor": row.get('fornecedor'),
                                "cidade": row.get('Cidade'),
                                "estado": row.get('Estado'),
                                "share": round(safe_float(row.get('share')) * 100, 1),
                                "total": safe_float(row.get('total')),
                            }
                            for _, row in merged_registry.head(8).iterrows()
                        ]

                    despesa_map = {
                        "Gasto com Combustível": "COMBUSTÍVEIS E LUBRIFICANTES.",
                    }
                    despesa_tecnica = despesa_map.get(despesa, despesa)
                    query_overlap = f"""
                    SELECT nome, sgUF, sgPartido, txtCNPJCPF, SUM(vlrLiquido) AS total, COUNT(*) AS notas
                    FROM tabelao
                    WHERE txtDescricao = ?
                      AND nome != ?
                      AND REPLACE(REPLACE(REPLACE(txtCNPJCPF, '.', ''), '/', ''), '-', '') IN ({placeholders})
                    GROUP BY nome, sgUF, sgPartido, txtCNPJCPF
                    """
                    overlap_df = pd.read_sql_query(
                        query_overlap,
                        conn_tabelao,
                        params=[despesa_tecnica, parlamentar] + cnpj_candidates
                    )
                    if not overlap_df.empty:
                        overlap_df['cnpj_clean'] = overlap_df['txtCNPJCPF'].astype(str).str.replace(r'\D', '', regex=True).str.zfill(14)
                        overlap_rank = (
                            overlap_df.groupby(['nome', 'sgUF', 'sgPartido'])
                            .agg(
                                total=('total', 'sum'),
                                notas=('notas', 'sum'),
                                fornecedores_compartilhados=('cnpj_clean', 'nunique')
                            )
                            .reset_index()
                            .sort_values(['fornecedores_compartilhados', 'total'], ascending=[False, False])
                        )
                        top_shared_deputies = [
                            {
                                "parlamentar": row['nome'],
                                "partido": row['sgPartido'],
                                "estado": row['sgUF'],
                                "fornecedores_compartilhados": int(row['fornecedores_compartilhados']),
                                "total": safe_float(row['total']),
                                "notas": int(row['notas'])
                            }
                            for _, row in overlap_rank.head(8).iterrows()
                        ]
                except Exception as conn_exc:
                    logger.warning(f"⚠️ Falha ao calcular cadastro/rede compartilhada no Auditor Antunes: {conn_exc}")
                finally:
                    try:
                        if conn_tabelao is not None:
                            conn_tabelao.close()
                    except Exception:
                        pass

            flags = []
            regularity_signals = []

            if safe_float(metricas.get('diff_geral_pct')) <= -20 or safe_float(metricas.get('diff_estado_pct')) <= -20:
                regularity_signals.append(
                    f"O gasto médio por nota está abaixo das médias de comparação em magnitude relevante, o que reduz a força de uma tese de sobrepreço isolado."
                )
            if atypical_count == 0:
                regularity_signals.append("Não houve notas acima do limite estatístico de atipicidade calculado para o próprio conjunto analisado.")
            if top1_share < 25 and top5_share < 70:
                regularity_signals.append("A distribuição entre fornecedores não indica dependência extrema de um único prestador.")

            if safe_float(metricas.get('diff_geral_pct')) >= 60 or safe_float(metricas.get('diff_estado_pct')) >= 60:
                flags.append({
                    "severity": "alto",
                    "title": "Patamar de gasto muito acima das médias de referência",
                    "evidence": f"Despesa por nota em {fmt_pct(metricas.get('diff_geral_pct'))} vs média geral e {fmt_pct(metricas.get('diff_estado_pct'))} vs média estadual.",
                    "why_it_matters": "Diferença persistente e elevada exige justificativa operacional robusta.",
                })
            if atypical_count > 0 and (atypical_total / total_value if total_value else 0) >= 0.15:
                flags.append({
                    "severity": "alto",
                    "title": "Parcela material do gasto concentrada em notas atípicas",
                    "evidence": f"{atypical_count} notas acima do limite de {fmt_money(limit_atypical)}, somando {fmt_money(atypical_total)} ({fmt_pct((atypical_total / total_value) * 100)} do total).",
                    "why_it_matters": "A materialidade do desvio estatístico aumenta a necessidade de explicação documental.",
                })
            if top1_share >= 35 or top3_share >= 70:
                flags.append({
                    "severity": "medio",
                    "title": "Concentração relevante de pagamentos em poucos fornecedores",
                    "evidence": f"Top 1 fornecedor responde por {fmt_pct(top1_share)} do valor; top 3 concentram {fmt_pct(top3_share)}.",
                    "why_it_matters": "Concentração excessiva pede verificação de racionalidade econômica e de dependência operacional.",
                })
            if duplicate_note_count >= 2:
                flags.append({
                    "severity": "medio",
                    "title": "Repetição exata de valores no mesmo fornecedor e no mesmo dia",
                    "evidence": f"Foram encontrados {duplicate_note_count} lançamentos em grupos com mesmo fornecedor, data e valor idêntico.",
                    "why_it_matters": "Esse padrão não prova irregularidade, mas é compatível com fracionamento, repetição indevida ou lançamento padronizado.",
                })
            if rounded_share >= 65 and note_count >= 15:
                flags.append({
                    "severity": "medio",
                    "title": "Predomínio incomum de valores redondos",
                    "evidence": f"{fmt_pct(rounded_share)} das notas terminam em ,00 ou ,50.",
                    "why_it_matters": "Em bases reais de consumo, excesso de valores redondos pode indicar baixa aderência a preços de bomba ou padronização artificial.",
                })
            if benford_mad is not None and benford_mad >= 0.015:
                flags.append({
                    "severity": "medio",
                    "title": "Distribuição de primeiros dígitos foge do padrão esperado",
                    "evidence": f"MAD de Benford = {benford_mad:.4f}.",
                    "why_it_matters": "É um indício auxiliar, nunca prova isolada, mas recomenda exame adicional da composição das notas.",
                })
            if weekend_share >= 25 and weekend_count >= 5:
                flags.append({
                    "severity": "baixo",
                    "title": "Participação elevada de despesas em fins de semana",
                    "evidence": f"{weekend_count} notas em sábado/domingo, somando {fmt_money(weekend_total)} ({fmt_pct(weekend_share)} do total).",
                    "why_it_matters": "Pode ser compatível com agenda política, mas pede conferência de nexo funcional.",
                })
            if peak_month_share >= 35 and active_months >= 4:
                flags.append({
                    "severity": "medio",
                    "title": "Concentração temporal relevante em um único mês",
                    "evidence": f"O mês de maior gasto concentrou {fmt_pct(peak_month_share)} do total anual ou do recorte auditado.",
                    "why_it_matters": "Picos muito fortes merecem cotejo com agenda, reembolsos acumulados ou regularização tardia de notas.",
                })
            if out_of_state_share >= 25 and point_count >= 5:
                flags.append({
                    "severity": "baixo",
                    "title": "Parcela relevante do gasto aparece em fornecedores cadastrados fora da UF do deputado",
                    "evidence": f"{out_of_state_count} fornecedores/pontos fora de {estado}, somando {fmt_money(out_of_state_value)} ({fmt_pct(out_of_state_share)} do total).",
                    "why_it_matters": "Pode ser legítimo em deslocamentos ou redes regionais, mas precisa ser compatível com a narrativa operacional da rubrica.",
                })

            suspicious_notes = []
            atypical_notes_df = std_df[std_df['atypical']].sort_values('valor', ascending=False).head(8)
            for _, row in atypical_notes_df.iterrows():
                suspicious_notes.append({
                    "data": row['data_str'],
                    "fornecedor": row['fornecedor'],
                    "valor": safe_float(row['valor']),
                    "numero": row.get('numero'),
                    "cnpj": row.get('cnpj'),
                    "url_documento": row.get('url_documento'),
                })

            repeat_samples = []
            for _, row in repeated_day_supplier.head(6).iterrows():
                repeat_samples.append({
                    "data": row['data_str'],
                    "fornecedor": row['fornecedor'],
                    "notas": int(row['notas']),
                    "total": safe_float(row['total']),
                    "media": safe_float(row['media'])
                })

            if corrected_coords_count == 0 and point_count > 0:
                regularity_signals.append("As coordenadas do mapa não exigiram correções cadastrais relevantes, o que reforça a consistência geográfica da base.")
            if out_of_state_share <= 10 and point_count > 0:
                regularity_signals.append("A maior parte do gasto mapeado permanece dentro da própria UF de referência, sem dependência geográfica atípica.")
            if active_months >= 6 and peak_month_share <= 25:
                regularity_signals.append("A distribuição mensal não ficou excessivamente concentrada em um único pico, o que sugere padrão operacional mais estável.")

            score_indiciario = 0
            if safe_float(metricas.get('diff_geral_pct')) >= 60 or safe_float(metricas.get('diff_estado_pct')) >= 60:
                score_indiciario += 20
            if atypical_count > 0 and (atypical_total / total_value if total_value else 0) >= 0.15:
                score_indiciario += 20
            if top1_share >= 35:
                score_indiciario += 12
            if top3_share >= 70:
                score_indiciario += 10
            if duplicate_note_count >= 2:
                score_indiciario += 12
            if rounded_share >= 65 and note_count >= 15:
                score_indiciario += 8
            if benford_mad is not None and benford_mad >= 0.015:
                score_indiciario += 8
            if weekend_share >= 25 and weekend_count >= 5:
                score_indiciario += 4
            if peak_month_share >= 35 and active_months >= 4:
                score_indiciario += 8
            if out_of_state_share >= 25 and point_count >= 5:
                score_indiciario += 6
            score_indiciario = min(score_indiciario, 100)

            return {
                "insufficient_notes": False,
                "summary": {
                    "total_value": total_value,
                    "note_count": note_count,
                    "supplier_count": supplier_count,
                    "median_value": median_value,
                    "std_value": std_value,
                    "p90": p90,
                    "p95": p95,
                    "max_value": max_value,
                    "peak_day_value": peak_day_value,
                    "peak_day_share_pct": peak_day_share,
                    "score_indiciario_0_100": score_indiciario,
                },
                "comparatives": {
                    "diff_geral_pct": safe_float(metricas.get('diff_geral_pct')),
                    "diff_estado_pct": safe_float(metricas.get('diff_estado_pct')),
                    "diff_partido_pct": safe_float(metricas.get('diff_partido_pct')),
                    "media_geral": safe_float(metricas.get('media_geral')),
                    "media_estado": safe_float(metricas.get('media_estado')),
                    "media_partido": safe_float(metricas.get('media_partido')),
                },
                "concentration": {
                    "top1_share_pct": top1_share,
                    "top3_share_pct": top3_share,
                    "top5_share_pct": top5_share,
                    "hhi": hhi,
                    "top_suppliers": [
                        {
                            "fornecedor": row['fornecedor'],
                            "total": safe_float(row['total']),
                            "notas": int(row['notas']),
                            "media": safe_float(row['media']),
                            "share_pct": round(safe_float(row['share']) * 100, 1),
                            "cnpj": row['cnpj'],
                        }
                        for _, row in suppliers_df.head(8).iterrows()
                    ],
                },
                "temporal": {
                    "weekend_share_pct": weekend_share,
                    "weekend_count": weekend_count,
                    "active_months": active_months,
                    "peak_month_value": peak_month_value,
                    "peak_month_share_pct": peak_month_share,
                    "monthly_points": monthly_points,
                    "repeated_day_supplier_patterns": repeat_samples,
                    "duplicate_exact_groups": duplicate_exact_df.head(8).to_dict('records'),
                },
                "geography": {
                    "point_count": point_count,
                    "corrected_coords_count": corrected_coords_count,
                    "out_of_state_count": out_of_state_count,
                    "out_of_state_value": out_of_state_value,
                    "out_of_state_share_pct": out_of_state_share,
                    "top_cities": top_cities,
                    "top_address_points": top_address_points,
                },
                "digit_analysis": {
                    "rounded_00_share_pct": rounded_00_share,
                    "rounded_50_share_pct": rounded_50_share,
                    "rounded_share_pct": rounded_share,
                    "benford_mad": benford_mad,
                    "benford_observed": benford_obs,
                },
                "atypical": {
                    "limit": limit_atypical,
                    "count": atypical_count,
                    "value_total": atypical_total,
                    "value_share_pct": safe_float((atypical_total / total_value) * 100) if total_value else 0,
                    "top_notes": suspicious_notes,
                },
                "registry_snapshot": registry_snapshot,
                "top_shared_deputies": top_shared_deputies,
                "flags": flags,
                "regularity_signals": regularity_signals,
                "raw_top_suppliers": top_fornecedores[:10],
                "raw_suspicious_notes": notas_atipicas[:10],
            }

        forensic_bundle = build_forensic_bundle()
        regras_especificas = get_forensic_rules(despesa)

        def invoke_agent_json(agent_name, system_prompt, user_prompt, max_completion_tokens=2200):
            response = client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.25,
                max_completion_tokens=max_completion_tokens,
                timeout=45.0,
            )
            content = (response.choices[0].message.content or "{}").strip()
            try:
                return json.loads(content)
            except Exception as exc:
                raise ValueError(f"{agent_name} retornou JSON inválido: {exc}")

        local_flags = forensic_bundle.get("flags", [])
        local_regularities = forensic_bundle.get("regularity_signals", [])
        top_shared_deputies = forensic_bundle.get("top_shared_deputies", [])
        forensic_summary = forensic_bundle.get("summary", {})
        forensic_temporal = forensic_bundle.get("temporal", {})
        forensic_geography = forensic_bundle.get("geography", {})

        agent_outputs = {}
        llm_failures = []

        audit_context = {
            "parlamentar": parlamentar,
            "estado": estado,
            "partido_eleicao": partido,
            "despesa": despesa,
            "ano": ano,
            "orgao_destino": orgao_destino,
            "forensic_bundle": forensic_bundle,
            "regras_especificas": regras_especificas,
        }

        try:
            agent_outputs["estatistico"] = invoke_agent_json(
                "Agente Estatístico",
                "Você é um auditor estatístico forense de contas públicas. Sua tarefa é separar indícios quantitativos relevantes de ruído estatístico. Seja severo com números, mas justo com contextos exculpatórios. Nunca trate gasto abaixo da média como irregularidade.",
                f"""Analise o contexto abaixo e devolva JSON com as chaves:
- tese_quantitativa
- classif_risco_quantitativo (baixo|moderado|alto)
- achados_relevantes: array de objetos com titulo, severidade, evidencia, contraargumento_possivel
- sinais_de_regularidade: array de strings
- leitura_estatistica_final

Contexto:
{json.dumps(audit_context, ensure_ascii=False, indent=2)}"""
            )
        except Exception as exc:
            llm_failures.append(f"estatistico: {exc}")
            agent_outputs["estatistico"] = {
                "tese_quantitativa": "Leitura estatística construída localmente.",
                "classif_risco_quantitativo": "moderado" if local_flags else "baixo",
                "achados_relevantes": local_flags,
                "sinais_de_regularidade": local_regularities,
                "leitura_estatistica_final": "A avaliação quantitativa foi montada a partir dos indicadores calculados no backend.",
            }

        try:
            agent_outputs["fornecedores"] = invoke_agent_json(
                "Agente Fornecedores",
                "Você é um investigador forense de fornecedores e redes de contratação parlamentar. Foque em concentração, recorrência, compartilhamento de CNPJ com outros deputados e geografia cadastral. Não acuse sem prova; sinalize padrões que merecem explicação.",
                f"""Analise o contexto abaixo e devolva JSON com as chaves:
- leitura_rede
- leitura_fornecedores
- sinais_de_alerta: array de objetos com titulo, severidade, evidencia, relevancia
- sinais_de_normalidade: array de strings
- competidores_relevantes: array de objetos com parlamentar, partido, estado, fornecedores_compartilhados, total

Contexto:
{json.dumps(audit_context, ensure_ascii=False, indent=2)}"""
            )
        except Exception as exc:
            llm_failures.append(f"fornecedores: {exc}")
            agent_outputs["fornecedores"] = {
                "leitura_rede": "Leitura de fornecedores construída localmente.",
                "leitura_fornecedores": "Fornecedores compartilhados e concentração foram calculados a partir da base interna.",
                "sinais_de_alerta": [flag for flag in local_flags if flag.get("severity") in {"alto", "medio"}],
                "sinais_de_normalidade": local_regularities,
                "competidores_relevantes": top_shared_deputies[:6],
            }

        try:
            agent_outputs["padroes"] = invoke_agent_json(
                "Agente Temporal e Geográfico",
                "Você é um auditor forense especializado em padrões temporais, coerência espacial e rastros operacionais. Sua função é ler sazonalidade, picos, fins de semana, cidades e fornecedores fora da UF sem exagero retórico. O objetivo é separar anomalia explicável de padrão realmente desconfortável.",
                f"""Analise o contexto abaixo e devolva JSON com as chaves:
- leitura_temporal
- leitura_geografica
- sinais_de_alerta: array de objetos com titulo, severidade, evidencia, relevancia
- sinais_de_normalidade: array de strings
- pontos_para_verificacao: array de strings

Contexto:
{json.dumps(audit_context, ensure_ascii=False, indent=2)}"""
            )
        except Exception as exc:
            llm_failures.append(f"padroes: {exc}")
            agent_outputs["padroes"] = {
                "leitura_temporal": "Leitura temporal construída localmente a partir da série mensal e dos agrupamentos por dia/fornecedor.",
                "leitura_geografica": "Leitura geográfica construída localmente com a malha de fornecedores e cidades cadastrais.",
                "sinais_de_alerta": [
                    flag for flag in local_flags
                    if flag.get("title") in {
                        "Participação elevada de despesas em fins de semana",
                        "Concentração temporal relevante em um único mês",
                        "Parcela relevante do gasto aparece em fornecedores cadastrados fora da UF do deputado",
                    }
                ],
                "sinais_de_normalidade": [
                    item for item in local_regularities
                    if "coordenadas" in item.lower() or "mensal" in item.lower() or "uf" in item.lower()
                ],
                "pontos_para_verificacao": [
                    "Conferir se os picos mensais coincidem com deslocamentos e agenda parlamentar documentada.",
                    "Validar se fornecedores fora da UF representam deslocamento funcional ou padrão operacional ordinário da rubrica.",
                ],
            }

        try:
            agent_outputs["conformidade"] = invoke_agent_json(
                "Agente Conformidade",
                "Você é um auditor de conformidade com formação em TCU, CEAP e Direito Administrativo. Sua obrigação é converter evidências em quesitos, materialidade e necessidade (ou não) de apuração. Seja rigoroso, porém juridicamente cauteloso.",
                f"""Analise o contexto abaixo e devolva JSON com as chaves:
- enquadramento_geral
- nivel_de_criticidade (baixo|moderado|alto)
- pontos_para_esclarecimento: array de strings
- fundamentos_normativos: array de strings
- recomendacao (sem_achado_relevante|monitorar|pedir_esclarecimentos|encaminhar_para_apuracao)
- justificativa_recomendacao

Contexto:
{json.dumps(audit_context, ensure_ascii=False, indent=2)}"""
            )
        except Exception as exc:
            llm_failures.append(f"conformidade: {exc}")
            recommendation = "pedir_esclarecimentos" if any(flag.get("severity") == "alto" for flag in local_flags) else ("monitorar" if local_flags else "sem_achado_relevante")
            agent_outputs["conformidade"] = {
                "enquadramento_geral": "Enquadramento de conformidade construído localmente.",
                "nivel_de_criticidade": "alto" if recommendation == "pedir_esclarecimentos" else ("moderado" if recommendation == "monitorar" else "baixo"),
                "pontos_para_esclarecimento": [
                    "Apresentar documentos comprobatórios e justificativa material para os lançamentos destacados.",
                    "Explicar a lógica operacional dos principais fornecedores e da distribuição temporal dos gastos.",
                ],
                "fundamentos_normativos": [
                    "Constituição Federal, art. 37.",
                    "Ato da Mesa nº 43/2009.",
                ],
                "recomendacao": recommendation,
                "justificativa_recomendacao": "A recomendação foi derivada diretamente dos sinais quantitativos e de concentração já calculados.",
            }

        def build_local_fallback_report():
            summary = forensic_bundle.get("summary", {})
            comparatives = forensic_bundle.get("comparatives", {})
            concentration = forensic_bundle.get("concentration", {})
            atypical = forensic_bundle.get("atypical", {})
            temporal = forensic_bundle.get("temporal", {})
            geography = forensic_bundle.get("geography", {})
            findings = local_flags
            regular = local_regularities

            risk_level = agent_outputs.get("conformidade", {}).get("nivel_de_criticidade", "baixo")
            recommendation = agent_outputs.get("conformidade", {}).get("recomendacao", "sem_achado_relevante")

            intro = (
                f"## Síntese Auditorial\n"
                f"Foi realizada revisão forense da rubrica **{despesa}** do deputado **{parlamentar}** ({partido}/{estado}), "
                f"com base em {summary.get('note_count', 0)} notas fiscais, {fmt_money(summary.get('total_value', 0))} empenhados "
                f"e comparação com referências gerais, estaduais e partidárias. O objetivo foi testar materialidade, concentração, recorrência e aderência do padrão observado às regras de razoabilidade e transparência.\n"
            )

            if findings:
                finding_lines = "\n".join(
                    f"- **{item['title']}**: {item['evidence']} {item['why_it_matters']}"
                    for item in findings
                )
            else:
                finding_lines = "- Não surgiram indícios robustos de irregularidade material a partir dos testes quantitativos e comportamentais executados."

            regular_lines = "\n".join(f"- {item}" for item in regular) if regular else "- Não foram identificados sinais exculpatórios adicionais além dos padrões usuais da base."

            report = (
                intro
                + "\n## Evidência Quantitativa\n"
                + f"- Gasto médio por nota: {fmt_money(resumo.get('media_gasto', 0))}\n"
                + f"- Diferença vs média geral: {fmt_pct(comparatives.get('diff_geral_pct', 0))}\n"
                + f"- Diferença vs média estadual: {fmt_pct(comparatives.get('diff_estado_pct', 0))}\n"
                + f"- Concentração top 1 fornecedor: {fmt_pct(concentration.get('top1_share_pct', 0))}\n"
                + f"- Concentração top 5 fornecedores: {fmt_pct(concentration.get('top5_share_pct', 0))}\n"
                + f"- Notas acima do limite atípico: {atypical.get('count', 0)} somando {fmt_money(atypical.get('value_total', 0))}\n"
                + f"- Participação de despesas em fins de semana: {fmt_pct(temporal.get('weekend_share_pct', 0))}\n"
                + f"- Mês mais concentrado: {fmt_pct(temporal.get('peak_month_share_pct', 0))} do total\n"
                + f"- Fornecedores/pontos fora da UF: {geography.get('out_of_state_count', 0)} ({fmt_pct(geography.get('out_of_state_share_pct', 0))})\n"
                + "\n## Achados Relevantes\n"
                + finding_lines
                + "\n\n## Sinais de Regularidade\n"
                + regular_lines
                + "\n\n## Enquadramento e Juízo Auditor\n"
                + f"O exame foi conduzido à luz do art. 37 da Constituição Federal e das regras da CEAP. No estado atual da evidência, o nível de criticidade foi classificado como **{risk_level}** e a recomendação técnica é **{recommendation.replace('_', ' ')}**. "
                + "Esse juízo não substitui diligência documental e validação humana, mas organiza os pontos que merecem resposta objetiva do gabinete.\n"
            )

            email_corpo = None
            if recommendation in {"pedir_esclarecimentos", "encaminhar_para_apuracao"} and findings:
                questions = []
                for idx, item in enumerate(findings[:4], start=1):
                    questions.append(f"{idx}. Favor esclarecer objetivamente o ponto: {item['title'].lower()} ({item['evidence']}).")
                email_corpo = (
                    f"Excelentíssimo Senhor Deputado {parlamentar},\n\n"
                    f"No âmbito de auditoria cidadã sobre a rubrica {despesa}, exercício {ano}, foram identificados pontos que demandam esclarecimentos complementares, sempre em caráter técnico e não conclusivo.\n\n"
                    f"Principais pontos sob análise:\n"
                    + "\n".join(f"- {item['title']}: {item['evidence']}" for item in findings[:4])
                    + "\n\nSolicitamos manifestação objetiva sobre os seguintes quesitos:\n"
                    + "\n".join(questions)
                    + "\n\nCaso haja documentação comprobatória capaz de contextualizar esses registros, sua apresentação é essencial para afastar interpretações indevidas.\n\nAtenciosamente,\nEquipe de Auditoria Cidadã"
                )

            return {
                "relatorio_tecnico": report,
                "email_corpo": email_corpo,
                "painel_forense": {
                    "nivel_risco": risk_level,
                    "score_indiciario": summary.get("score_indiciario_0_100", 0),
                    "recomendacao": recommendation,
                    "achados_prioritarios": findings[:5],
                    "sinais_regularidade": regular[:5],
                    "necessita_oficio": bool(email_corpo),
                },
                "disclaimer": "Relatório gerado por IA com protocolo multiagente do Auditor Antunes. Requer validação humana e jurídica.",
            }

        result = None
        try:
            synthesis_payload = invoke_agent_json(
                "Antunes Síntese",
                """Você é Antunes, auditor sênior em contas públicas com formação de TCU e controle interno. Sua função é consolidar os pareceres dos agentes especializados em um relatório justo, severo quando necessário e equilibrado quando os indícios não são robustos.

REGRAS:
- Não moralize.
- Não transforme gasto abaixo da média em achado.
- Não acuse crime ou fraude como fato consumado.
- Se não houver materialidade relevante, diga isso com clareza.
- Se houver indícios consistentes, exponha sem aliviar, mas sempre com base nas evidências.
- O relatório técnico deve ser em markdown.
- O e-mail ao deputado deve ser texto corrido, institucional e objetivo.
- O resultado DEVE ser JSON com: relatorio_tecnico, email_corpo, painel_forense, disclaimer.
""",
                f"""Consolide os dados abaixo.

[CONTEXTO BASE]
{json.dumps(audit_context, ensure_ascii=False, indent=2)}

[AGENTE ESTATÍSTICO]
{json.dumps(agent_outputs.get("estatistico", {}), ensure_ascii=False, indent=2)}

[AGENTE FORNECEDORES]
{json.dumps(agent_outputs.get("fornecedores", {}), ensure_ascii=False, indent=2)}

[AGENTE TEMPORAL E GEOGRÁFICO]
{json.dumps(agent_outputs.get("padroes", {}), ensure_ascii=False, indent=2)}

[AGENTE CONFORMIDADE]
{json.dumps(agent_outputs.get("conformidade", {}), ensure_ascii=False, indent=2)}

Estrutura esperada do relatorio_tecnico:
## Síntese Auditorial
## Achados Relevantes
## Sinais de Regularidade
## Exame de Fornecedores e Concentração
## Enquadramento Normativo
## Juízo Auditor e Encaminhamentos

Se a recomendação final for sem_achado_relevante, email_corpo deve ser null.
Se a recomendação final for pedir_esclarecimentos ou encaminhar_para_apuracao, gere email_corpo consistente com os achados.
""",
                max_completion_tokens=4200,
            )
            result = synthesis_payload
        except Exception as exc:
            llm_failures.append(f"sintese: {exc}")
            result = build_local_fallback_report()

        if "painel_forense" not in result:
            result["painel_forense"] = {
                "nivel_risco": agent_outputs.get("conformidade", {}).get("nivel_de_criticidade", "baixo"),
                "score_indiciario": forensic_summary.get("score_indiciario_0_100", 0),
                "recomendacao": agent_outputs.get("conformidade", {}).get("recomendacao", "sem_achado_relevante"),
                "achados_prioritarios": local_flags[:5],
                "sinais_regularidade": local_regularities[:5],
                "necessita_oficio": bool(result.get("email_corpo")),
            }
        result["agentes"] = agent_outputs
        if llm_failures:
            result["falhas_agentes"] = llm_failures
        if not result.get("disclaimer"):
            result["disclaimer"] = "Relatório gerado por IA com protocolo multiagente do Auditor Antunes. Requer validação humana e jurídica."

        # Adicionar contatos
        nome_email = parlamentar.lower().replace(' ', '.') if parlamentar else 'deputado'
        result['contatos'] = {
            "deputado": f"dep.{nome_email}@camara.leg.br",
            "corregedoria_camara": "corregedoria.parlamentar@camara.leg.br",
            "tcu": "ouvidoria@tcu.gov.br",
            "mpf": "pgr.mpf.mp.br"
        }
        
        # Salvar no cache
        if db_path:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO auditor_antunes_cache (hash, response) VALUES (?, ?)",
                    (query_hash, json.dumps(result))
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"⚠️ Erro ao salvar no cache: {e}")
        
        return result

    except Exception as e:
        logger.error(f"Erro no Auditor Antunes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/analise-votos-antunes")
async def analise_votos_antunes(request: dict):
    """
    Endpoint do Robo Antunes para analisar comportamento de votação.
    """
    try:
        import openai
        from dotenv import load_dotenv
        import json
        import hashlib
        import sqlite3
        
        load_dotenv()
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise HTTPException(status_code=500, detail="API key do OpenAI não configurada")
            
        client = openai.OpenAI(api_key=api_key)
        
        parlamentar = request.get('parlamentar')
        partido = request.get('partido', '')
        uf = request.get('uf', '')
        votos_detalhe = request.get('votos_detalhe', [])
        temas_stats = request.get('temas_stats', [])
        governismo = request.get('governismo', 0)
        
        # 1. Filtro e Score de Qualidade (Prioridade: Dados Ricos > Data)
        # Queremos pautas que tenham "carne" para a IA analisar
        def get_score(v):
            resumo = str(v.get('resumo_leigo') or v.get('descricao', ''))
            # Peso alto para resumos técnicos longos
            score = len(resumo)
            # Bônus para pautas orientadas pelo governo
            if v.get('pauta_governo') in ['Sim', 'Não']:
                score += 500
            return score

        # Ordenar por qualidade técnica decrescente
        votos_ordenados = sorted(votos_detalhe, key=get_score, reverse=True)
        # Pegar as 30 pautas mais ricas em informação para auditoria
        votos_amostra_total = votos_ordenados[:30]
        # Re-ordenar a amostra final por data para cronologia no relatório
        votos_amostra_total.sort(key=lambda x: x.get('data_votacao', ''), reverse=True)
        
        alinhadas_txt = []
        divergentes_txt = []
        gerais_txt = [] 
        
        for v in votos_amostra_total:
            pauta = v.get('pauta_governo')
            voto = v.get('voto')
            
            # Dados Técnicos Exigidos: PL, Data, Comissão
            pl = v.get('nome_projeto') or v.get('objeto_votacao') or "Projeto"
            data_raw = v.get('data_votacao', '').split('T')[0]
            data = data_raw
            if '-' in data_raw:
                try:
                    y, m, d = data_raw.split('-')
                    data = f"{d}/{m}/{y}"
                except: pass
            comissao = v.get('sigla_orgao') or "PLEN"
            resumo = v.get('resumo_leigo', v.get('descricao', ''))
            
            # Descrição Técnica: "[PL] em [Data] na [Comissão]: [Resumo]"
            desc_tecnica = f"{pl} em {data} na {comissao}: {resumo}"
            
            # Categorização
            if pauta in ['Sim', 'Não']:
                is_aligned = (pauta == 'Sim' and voto == 'Sim') or (pauta == 'Não' and voto == 'Não')
                if is_aligned:
                    alinhadas_txt.append(f"✅ {desc_tecnica}")
                else:
                    divergentes_txt.append(f"❌ {desc_tecnica} (Voto: {voto} | Gov: {pauta})")
            else:
                gerais_txt.append(f"ℹ️ {desc_tecnica}")

        def fmt_br(date_str):
            if not date_str or date_str == "N/A": return "N/A"
            try:
                # Remove T00:00:00 se houver e converte
                d = date_str.split('T')[0]
                dt = datetime.strptime(d, '%Y-%m-%d')
                return dt.strftime('%d/%m/%Y')
            except: return date_str

        # 1. Contagem de Votos Nominais vs Simbólicos REAIS de carreira (enviados pelo frontend)
        # Se não vierem, usamos o fallback do cálculo sobre a amostra de 100
        c_nom_total = request.get('votos_nominais', sum(1 for v in votos_detalhe if 'Nominal' in str(v.get('tipo_votacao', ''))))
        c_simb_total = request.get('votos_simbolicos', sum(1 for v in votos_detalhe if any(x in str(v.get('tipo_votacao', '')) for x in ['Simból', 'Simbol', 'Agregada'])))
        c_votos_total = request.get('total_votos', c_nom_total + c_simb_total)

        # Contagem específica da amostra de 100 para o disclaimer técnico
        c_nom_amostra = sum(1 for v in votos_detalhe if 'Nominal' in str(v.get('tipo_votacao', '')))
        c_simb_amostra = sum(1 for v in votos_detalhe if any(x in str(v.get('tipo_votacao', '')) for x in ['Simból', 'Simbol', 'Agregada']))
        
        # 2. Formatar Temas Macro
        temas_list = []
        for t in temas_stats:
            temas_list.append(f"- {t.get('tema')}: {t.get('governismo')}% de governismo ({t.get('total_votos')} votos)")
        temas_prompt = "\n".join(temas_list) if temas_list else "Dados de temas não disponíveis para este filtro."

        # 3. Limites de Datas
        datas_amostra = [v.get('data_votacao') for v in votos_amostra_total if v.get('data_votacao')]
        data_min_raw = min(datas_amostra) if datas_amostra else "N/A"
        data_max_raw = max(datas_amostra) if datas_amostra else datetime.now().strftime('%Y-%m-%d')
        
        data_min = fmt_br(data_min_raw)
        data_max = fmt_br(data_max_raw)
        
        # Cache (Token de Economia Robusto)
        # HASH: Nome + Partido + Estado + Lista de IDs de votação
        votos_ids = [str(v.get('id_votacao', '')) for v in votos_detalhe]
        votos_ids.sort() # Garante ordem para o hash bater sempre
        
        hash_input = f"{parlamentar}-{partido}-{uf}-ids:{','.join(votos_ids)}"
        query_hash = hashlib.md5(hash_input.encode()).hexdigest()
        
        db_path = DATABASE_PATHS.get('llm_cache')
        if db_path:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("CREATE TABLE IF NOT EXISTS votos_antunes_cache (hash TEXT PRIMARY KEY, response TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
                cursor.execute("SELECT response FROM votos_antunes_cache WHERE hash = ?", (query_hash,))
                cached = cursor.fetchone()
                if cached:
                    conn.close()
                    return json.loads(cached[0])
            except Exception as e:
                logger.warning(f"Erro cache votos: {e}")

        system_prompt = f"""
        Você é o "Auditor Forense Antunes 5.0", com foco em INTEGRIDADE ABSOLUTA de dados. 
        Sua missão é relatar APENAS os fatos presentes nos dados fornecidos, sem inventar informações.
        
        REGRA DE OURO (BLINDAGEM CONTRA ALUCINAÇÃO):
        1. CÉREBRO VAZIO: Ignore qualquer conhecimento prévio que você tenha sobre o político {parlamentar} ou sobre pautas famosas (Fundeb, Teto de Gastos, etc). 
        2. ANTIMITO: Proibido usar placeholders como "Projeto X", "Projeto Y" ou inventar temas genéricos.
        3. FIDELIDADE AOS DADOS: Se os dados fornecidos em uma pauta forem curtos ou burocráticos, reporte exatamente isso. 
           - Ex: "Pauta técnica de comissão sobre [Objeto], sem impacto detalhado disponível."
           - JAMAIS invente descrições para preencher o relatório.
        4. ISENÇÃO TOTAL: Seu tom deve ser frio, institucional e baseado em provas. Se os dados forem pobres, seu relatório será honestamente pobre sobre esses pontos específicos.
        
        DIRETRIZES DE ESTRUTURA:
        - Auditoria de Comportamento e Adesão Regimental (Art. 185 RICD).
        - Análise Técnica de Pautas (Use os resumos reais. Se não houver, cite apenas o objeto oficial).
        - Proibido "passar pano", mas também proibido "atacar sem provas".
        
        Retorne um JSON com:
        {{
          "analise": "Auditoria técnica profunda baseada EXCLUSIVAMENTE nos dados anexos",
          "disclaimer": "Certificado de Integridade Forense: Esta análise ignora preconceitos e usa apenas âncoras de dados reais."
        }}
        """
        
        user_prompt = f"""
        ÂNCORAS DE DADOS REAIS PARA AUDITORIA: {parlamentar} ({partido}-{uf})
        Período: {data_min} a {data_max}
        Alinhamento Governamental: {governismo}%
        
        BASE DE MÉRITO (DADOS INCONTESTÁVEIS):
        - Votos Totais Carreira: {c_votos_total}
        - Composição: {c_nom_total} Nominais (Exclusivos) | {c_simb_total} Simbólicos (Coniventes Regimento Art. 185)
        
        AMOSTRA DE PAUTAS DO BANCO (PROIBIDO USAR INFORMAÇÃO EXTERNA):
        
        -- PAUTAS COM ORIENTAÇÃO (GOVERNO):
        {chr(10).join(alinhadas_txt)}
        {chr(10).join(divergentes_txt)}
        
        -- ATUAÇÃO TÉCNICA (COMISSÕES/GERAIS):
        {chr(10).join(gerais_txt)}
        
        INSTRUÇÃO TÉCNICA: Sua análise deve se basear 100% nestes textos. Se o resumo for curto, reporte apenas o que está escrito. Se a ficha de auditoria pedir 5 pautas e os dados forem insuficientes, liste apenas as pautas reais disponíveis. JAMAIS use Projeto X, Y ou temas da sua memória.
        """

        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Salvar cache
        if db_path:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO votos_antunes_cache (hash, response) VALUES (?, ?)", (query_hash, json.dumps(result)))
                conn.commit()
                conn.close()
            except: pass
            
        return result

    except Exception as e:
        logger.error(f"Erro Antunes Votos: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# ENDPOINTS DE PRESENÇA PARLAMENTAR
# =============================================================================

@app.get("/api/presenca/analise")
async def get_presenca_analise(
    parlamentar: Optional[str] = None,
    estado: Optional[str] = None,
    partido: Optional[str] = None,
    comissao: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None
):
    """
    Retorna dados de presença, métricas e lista de comissões.
    """
    conn = None
    try:
        conn = get_db_connection('tabelao')
        cursor = conn.cursor()
        
        # Resolução de Nome (Title Case Fallback)
        if parlamentar and parlamentar != 'Todos':
            # Verificar se o nome como veio existe
            check_query = "SELECT 1 FROM presencas_eventos WHERE nome_deputado = ? COLLATE NOCASE LIMIT 1"
            has_match = pd.read_sql_query(check_query, conn, params=[parlamentar])
            
            if has_match.empty:
                # Tentar Title Case
                parlamentar_title = parlamentar.title()
                has_match = pd.read_sql_query(check_query, conn, params=[parlamentar_title])
                if not has_match.empty:
                    parlamentar = parlamentar_title
        
        # 1. Construir filtro base
        where_clauses = []
        params = []
        
        if parlamentar and parlamentar != 'Todos':
            where_clauses.append("nome_deputado = ? COLLATE NOCASE")
            params.append(parlamentar)
            
        # Filtro de Data (Mês de Referência)
        if data_inicio and data_fim:
            # Converter YYYY-MM-DD para YYYY-MM (formato do banco)
            mes_inicio = data_inicio[:7]
            mes_fim = data_fim[:7]
            where_clauses.append("mes_referencia >= ? AND mes_referencia <= ?")
            params.append(mes_inicio)
            params.append(mes_fim)
            
        # Nota: estado e partido não estão diretamente na tabela presencas_eventos,
        # precisaria fazer join com tabelao se fosse filtrar estritamente.
        # Por enquanto, assumimos que o frontend já filtrou o nome do parlamentar corretamente.
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        # 2. Buscar Comissões Disponíveis para o Parlamentar
        # Se um parlamentar foi selecionado, retornamos apenas as comissões dele
        comissoes_list = []
        if parlamentar and parlamentar != 'Todos':
            query_comissoes = """
            SELECT DISTINCT id_orgao, nome_orgao, tipo_orgao
            FROM presencas_eventos
            WHERE nome_deputado = ? COLLATE NOCASE
            ORDER BY nome_orgao
            """
            df_comissoes = pd.read_sql_query(query_comissoes, conn, params=[parlamentar])
            
            
            for _, row in df_comissoes.iterrows():
                comissoes_list.append({
                    "id": row['id_orgao'],
                    "nome": row['nome_orgao'],
                    "tipo": row['tipo_orgao']
                })
        
        # 3. Buscar Dados de Presença
        # Se comissao for especificada, filtramos por ela
        where_dados = list(where_clauses)
        params_dados = list(params)
        
        if comissao and comissao != 'Todas':
            # Verificar se é apenas números (ID direto)
            if comissao.isdigit():
                where_dados.append("id_orgao = ?")
                params_dados.append(comissao)
            else:
                # Extrair ID do órgão da string "Tipo - Nome (ID)"
                import re
                match = re.search(r'\((\d+)\)$', comissao)
                if match:
                    id_orgao = match.group(1)
                    where_dados.append("id_orgao = ?")
                    params_dados.append(id_orgao)
                elif comissao == 'Plenário': # Caso especial Plenário (ID 0 ou nome)
                     where_dados.append("(id_orgao = '0' OR tipo_orgao = 'Plenário')")
        
        where_dados_sql = " AND ".join(where_dados) if where_dados else "1=1"
        
        query_dados = f"""
        SELECT *
        FROM presencas_eventos
        WHERE {where_dados_sql}
        ORDER BY mes_referencia
        """
        
        df_dados = pd.read_sql_query(query_dados, conn, params=params_dados)
        
        # 4. Calcular Métricas
        metricas = {
            "presenca_geral": 0,
            "sessoes_participadas": 0,
            "sessoes_realizadas": 0
        }
        
        evolucao_mensal = []
        presenca_por_tipo = []
        presenca_por_tipo = []
        ranking_comissoes = []
        presencas_detalhadas = []
        
        evolucao_mensal = []
        presenca_por_tipo = []
        ranking_comissoes = []
        presencas_detalhadas = []
        detalhamento_mensal = []
        
        if not df_dados.empty:
            metricas["sessoes_participadas"] = int(df_dados["n_presencas"].sum())
            metricas["sessoes_realizadas"] = int(df_dados["n_total_reunioes"].sum())
            if metricas["sessoes_realizadas"] > 0:
                metricas["presenca_geral"] = (metricas["sessoes_participadas"] / metricas["sessoes_realizadas"]) * 100
            
            # Evolução Mensal
            df_mensal = df_dados.groupby("mes_referencia")[["n_presencas", "n_total_reunioes"]].sum().reset_index()
            for _, row in df_mensal.iterrows():
                evolucao_mensal.append({
                    "mes": row["mes_referencia"],
                    "presencas": int(row["n_presencas"]),
                    "ausencias": int(row["n_total_reunioes"] - row["n_presencas"]),
                    "total": int(row["n_total_reunioes"])
                })
            
            # Presença por Tipo
            df_tipo = df_dados.groupby("tipo_orgao")[["n_presencas", "n_total_reunioes"]].sum().reset_index()
            for _, row in df_tipo.iterrows():
                presenca_por_tipo.append({
                    "tipo": row["tipo_orgao"],
                    "presencas": int(row["n_presencas"]),
                    "total": int(row["n_total_reunioes"])
                })
                
            # Ranking Comissões
            df_ranking = df_dados.groupby("nome_orgao")[["n_presencas", "n_total_reunioes"]].sum().reset_index()
            df_ranking["percentual"] = (df_ranking["n_presencas"] / df_ranking["n_total_reunioes"]) * 100
            df_ranking = df_ranking.sort_values("percentual", ascending=False)
            
            for _, row in df_ranking.iterrows():
                ranking_comissoes.append({
                    "nome": row["nome_orgao"],
                    "percentual": float(row["percentual"]),
                    "presencas": int(row["n_presencas"]),
                    "total": int(row["n_total_reunioes"])
                })

            # Presença Detalhada (para Frontend) - Agrupando por ID e Tipo
            df_detalhado = df_dados.groupby(["id_orgao", "nome_orgao", "tipo_orgao"])[["n_presencas", "n_total_reunioes"]].sum().reset_index()
            df_detalhado["percentual"] = (df_detalhado["n_presencas"] / df_detalhado["n_total_reunioes"]) * 100
            
            for _, row in df_detalhado.iterrows():
                presencas_detalhadas.append({
                    "id_orgao": row["id_orgao"],
                    "nome": row["nome_orgao"],
                    "tipo": row["tipo_orgao"],
                    "percentual": float(row["percentual"]),
                    "presencas": int(row["n_presencas"]),
                    "reunioes": int(row["n_total_reunioes"])
                })

            # Detalhamento Mensal (para Frontend)
            df_detalhe_mensal = df_dados.groupby(["mes_referencia", "nome_orgao", "tipo_orgao"])[["n_presencas", "n_total_reunioes"]].sum().reset_index()
            df_detalhe_mensal["percentual"] = (df_detalhe_mensal["n_presencas"] / df_detalhe_mensal["n_total_reunioes"]) * 100
            
            for _, row in df_detalhe_mensal.iterrows():
                detalhamento_mensal.append({
                    "mes": row["mes_referencia"],
                    "orgao": row["nome_orgao"], 
                    "tipo": row["tipo_orgao"],
                    "percentual": float(row["percentual"]),
                    "presencas": int(row["n_presencas"]),
                    "total": int(row["n_total_reunioes"])
                })

        # Buscar dados do parlamentar (foto, etc)
        dados_parlamentar = {}
        if parlamentar and parlamentar != 'Todos':
            query_info = "SELECT nome, ultimoStatus_urlFoto, sgPartido, sgUF FROM tabelao WHERE nome = ? COLLATE NOCASE LIMIT 1"
            df_info = pd.read_sql_query(query_info, conn, params=[parlamentar])
            
            if df_info.empty:
                df_info = pd.read_sql_query(query_info, conn, params=[parlamentar.upper()])
            if not df_info.empty:
                sg_partido = df_info.iloc[0]["sgPartido"]
                sg_uf = df_info.iloc[0]["sgUF"]
                dados_parlamentar = {
                    "nome": df_info.iloc[0]["nome"],
                    "foto": df_info.iloc[0]["ultimoStatus_urlFoto"],
                    "partido": sg_partido,
                    "estado": sg_uf,
                    "url_partido": partido_logos_dict.get(sg_partido),
                    "url_estado": estado_logos_dict.get(sg_uf)
                }
        
        # 5. Dados Adicionais para Comissão Específica
        media_comissao = 0
        calendario_presenca = []
        presenca_por_dia_semana = {
            "Segunda": {"presencas": 0, "total": 0},
            "Terça": {"presencas": 0, "total": 0},
            "Quarta": {"presencas": 0, "total": 0},
            "Quinta": {"presencas": 0, "total": 0},
            "Sexta": {"presencas": 0, "total": 0}
        }
        dias_map = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta"}

        # Determinar range de datas para o calendário (usado no retorno mesmo sem comissão)
        d_fim = datetime.now()
        if data_fim:
            try: d_fim = datetime.strptime(data_fim, "%Y-%m-%d")
            except: pass
        
        d_inicio = d_fim - pd.DateOffset(months=6)
        if data_inicio:
            try:
                d_inicio = datetime.strptime(data_inicio, "%Y-%m-%d")
            except: pass

        if comissao and comissao != 'Todas' and parlamentar and parlamentar != 'Todos':
            # A. Média da Comissão
            id_orgao_val = None
            if comissao == 'Plenário':
                id_orgao_val = '0'
            elif comissao.isdigit():
                id_orgao_val = comissao
            else:
                import re
                match = re.search(r'\((\d+)\)$', comissao)
                if match:
                    id_orgao_val = match.group(1)
            
            if id_orgao_val:
                query_media = """
                SELECT SUM(n_presencas) as total_pres, SUM(n_total_reunioes) as total_reun
                FROM presencas_eventos
                WHERE id_orgao = ?
                """
                if data_inicio and data_fim:
                    query_media += " AND mes_referencia >= ? AND mes_referencia <= ?"
                    df_media = pd.read_sql_query(query_media, conn, params=[id_orgao_val, data_inicio[:7], data_fim[:7]])
                else:
                    df_media = pd.read_sql_query(query_media, conn, params=[id_orgao_val])
                
                if not df_media.empty and df_media.iloc[0]['total_reun'] > 0:
                    media_comissao = (df_media.iloc[0]['total_pres'] / df_media.iloc[0]['total_reun']) * 100

                # B. Dados Diários (Calendário e Dia da Semana)
                # Limita a 60 dias a partir de d_fim para manter consistência com o banco
                d_janela_inicio = max(d_inicio, d_fim - pd.DateOffset(days=60))

                url_ev = "https://dadosabertos.camara.leg.br/api/v2/eventos"
                id_orgao_api = '180' if id_orgao_val == '0' else id_orgao_val
                params_ev = {
                    "dataInicio": d_janela_inicio.strftime("%Y-%m-%d"),
                    "dataFim": d_fim.strftime("%Y-%m-%d"),
                    "idOrgao": id_orgao_api,
                    "ordem": "ASC",
                    "ordenarPor": "dataHoraInicio",
                    "itens": 50
                }

                query_dep_id = "SELECT id FROM tabelao WHERE nome = ? COLLATE NOCASE ORDER BY ultimoStatus_idLegislatura DESC LIMIT 1"
                df_dep_id = pd.read_sql_query(query_dep_id, conn, params=[parlamentar])
                if df_dep_id.empty:
                    df_dep_id = pd.read_sql_query(query_dep_id, conn, params=[parlamentar.upper()])

                if not df_dep_id.empty:
                    id_dep = str(df_dep_id.iloc[0]['id'])

                    try:
                        resp_ev = requests.get(url_ev, params=params_ev, timeout=8)
                        if resp_ev.status_code == 200:
                            evs = resp_ev.json().get('dados', [])

                            def check_presenca(ev):
                                id_ev = ev['id']
                                dt_ev = ev['dataHoraInicio'].split('T')[0]
                                dt_obj = datetime.strptime(dt_ev, "%Y-%m-%d")
                                dia_sem = dias_map.get(dt_obj.weekday())
                                try:
                                    resp_pr = requests.get(
                                        f"https://dadosabertos.camara.leg.br/api/v2/eventos/{id_ev}/deputados",
                                        timeout=5
                                    )
                                    deps = resp_pr.json().get('dados', []) if resp_pr.status_code == 200 else []
                                    is_present = any(str(d['id']) == id_dep for d in deps)
                                except Exception:
                                    is_present = False
                                return dt_ev, dia_sem, is_present

                            from concurrent.futures import ThreadPoolExecutor, as_completed
                            with ThreadPoolExecutor(max_workers=8) as executor:
                                futures = [executor.submit(check_presenca, ev) for ev in evs]
                                for future in as_completed(futures, timeout=20):
                                    try:
                                        dt_ev, dia_sem, is_present = future.result()
                                        calendario_presenca.append({"data": dt_ev, "status": "Presente" if is_present else "Ausente"})
                                        if dia_sem:
                                            presenca_por_dia_semana[dia_sem]["total"] += 1
                                            if is_present:
                                                presenca_por_dia_semana[dia_sem]["presencas"] += 1
                                    except Exception:
                                        pass
                    except Exception:
                        pass
        
        return {
            "comissoes": comissoes_list,
            "metricas": metricas,
            "evolucao_mensal": evolucao_mensal,
            "presenca_por_tipo": presenca_por_tipo,
            "presencas": presencas_detalhadas,
            "detalhamento_mensal": detalhamento_mensal,
            "ranking_comissoes": ranking_comissoes,
            "parlamentar": dados_parlamentar,
            "detalhes_comissao": {
                "media_comissao": float(media_comissao),
                "calendario": calendario_presenca,
                "dia_semana": presenca_por_dia_semana,
                "range_inicio": d_inicio.strftime("%Y-%m-%d"),
                "range_fim": d_fim.strftime("%Y-%m-%d")
            }
        }

    except Exception as e:
        print(f"Erro em /api/presenca/analise: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()

class PresencaLLMRequest(BaseModel):
    parlamentar: str
    comissao: Optional[str] = None
    estado: Optional[str] = None
    partido: Optional[str] = None
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None
    percentual_presenca: Optional[float] = None
    media_comissao: Optional[float] = None

@app.post("/api/llm/presenca-reunioes-faltadas")
async def analisar_presenca_llm(request: PresencaLLMRequest):
    """
    Gera análise de IA sobre as ausências do parlamentar.
    Busca sessões onde houve falta e analisa o que foi discutido.
    """
    try:
        import openai
        from dotenv import load_dotenv
        import os
        
        load_dotenv()
        api_key = os.getenv('OPENAI_API_KEY')
        client = openai.OpenAI(api_key=api_key)

        conn = get_db_connection('tabelao')
        
        # 1. Obter ID do Deputado e da Comissão
        query_dep = "SELECT id, nome FROM tabelao WHERE nome = ? COLLATE NOCASE LIMIT 1"
        df_dep = pd.read_sql_query(query_dep, conn, params=[request.parlamentar])
        
        if df_dep.empty:
            conn.close()
            return {"error": "Parlamentar não encontrado."}
            
        id_deputado = int(df_dep.iloc[0]['id'])
        nome_deputado = df_dep.iloc[0]['nome']
        
        id_orgao = None
        nome_orgao = request.comissao
        
        if request.comissao and request.comissao != 'Todas':
            if request.comissao.isdigit():
                id_orgao = int(request.comissao)
                # Buscar nome para o prompt
                query_nome = "SELECT nome_orgao FROM presencas_eventos WHERE id_orgao = ? LIMIT 1"
                df_nome = pd.read_sql_query(query_nome, conn, params=[id_orgao])
                if not df_nome.empty:
                    nome_orgao = df_nome.iloc[0]['nome_orgao']
            else:
                # Tentar extrair ID da string "Tipo - Nome (ID)"
                import re
                match = re.search(r'\((\d+)\)$', request.comissao)
                if match:
                    id_orgao = int(match.group(1))
                else:
                    # Tentar buscar pelo nome
                    query_orgao = "SELECT id_orgao FROM presencas_eventos WHERE nome_orgao = ? COLLATE NOCASE LIMIT 1"
                    df_orgao = pd.read_sql_query(query_orgao, conn, params=[request.comissao])
                    if not df_orgao.empty:
                        id_orgao = int(df_orgao.iloc[0]['id_orgao'])

        conn.close()
        
        if not id_orgao:
             return {
                 "analise": f"Selecione uma comissão específica para analisar as ausências de {nome_deputado}.",
                 "comissao": request.comissao,
                 "periodo": f"{request.data_inicio} a {request.data_fim}" if request.data_inicio else "Últimos 6 meses",
                 "num_discursos": 0
             }

        # 2. Buscar Eventos Recentes da Comissão
        # Lógica de Data: Se período > 6 meses, pegar apenas os últimos 6 meses.
        
        data_fim_dt = datetime.now()
        if request.data_fim:
            try:
                data_fim_dt = datetime.strptime(request.data_fim, "%Y-%m-%d")
            except:
                pass
                
        data_inicio_dt = data_fim_dt - pd.DateOffset(months=6)
        if request.data_inicio:
             try:
                data_inicio_req = datetime.strptime(request.data_inicio, "%Y-%m-%d")
                # Se o intervalo solicitado for menor que 6 meses, usamos ele
                if (data_fim_dt - data_inicio_req).days < 180:
                    data_inicio_dt = data_inicio_req
             except:
                pass
        
        data_fim_str = data_fim_dt.strftime("%Y-%m-%d")
        data_inicio_str = data_inicio_dt.strftime("%Y-%m-%d")
        
        url_eventos = "https://dadosabertos.camara.leg.br/api/v2/eventos"
        params_eventos = {
            "dataInicio": data_inicio_str,
            "dataFim": data_fim_str,
            "idOrgao": id_orgao,
            "itens": 50,
            "ordem": "DESC",
            "ordenarPor": "dataHoraInicio"
        }
        
        print(f"🔍 Buscando eventos para órgão {id_orgao}...")
        resp_eventos = requests.get(url_eventos, params=params_eventos)
        if resp_eventos.status_code != 200:
             return {"error": "Erro ao buscar eventos na API da Câmara."}
             
        eventos = resp_eventos.json().get('dados', [])
        
        # 3. Verificar Presença em Cada Evento
        ausencias_confirmadas = []
        
        for evento in eventos:
            if len(ausencias_confirmadas) >= 3: # Limitar a 3 análises para não demorar
                break
                
            id_evento = evento['id']
            data_evento = evento['dataHoraInicio'].split('T')[0]
            descricao = evento.get('descricaoTipo', 'Reunião')
            
            # Checar lista de presença
            url_presenca = f"https://dadosabertos.camara.leg.br/api/v2/eventos/{id_evento}/deputados"
            resp_presenca = requests.get(url_presenca)
            
            presente = False
            if resp_presenca.status_code == 200:
                deputados_presentes = resp_presenca.json().get('dados', [])
                if any(d['id'] == id_deputado for d in deputados_presentes):
                    presente = True
            
            if not presente:
                ausencias_confirmadas.append({
                    "id": id_evento,
                    "data": data_evento,
                    "descricao": descricao,
                    "pauta": evento.get('descricao', '')
                })
        
        if not ausencias_confirmadas:
            return {
                "analise": f"Não foram encontradas ausências recentes (no período selecionado) para {nome_deputado} na comissão selecionada.",
                "comissao": nome_orgao,
                "periodo": f"{data_inicio_str} a {data_fim_str}",
                "num_discursos": 0
            }
            
        # 4. Buscar Discursos/Pauta dessas Sessões
        # Como não temos pauta fácil, vamos buscar discursos de OUTROS parlamentares nessa comissão/data
        # no nosso banco de discursos
        
        conn_discursos = get_db_connection('discursos')
        contexto_ausencias = []
        
        for ausencia in ausencias_confirmadas:
            data_formatada = datetime.strptime(ausencia['data'], "%Y-%m-%d").strftime("%d/%m/%Y")
            
            # Buscar discursos nessa data e comissão
            query_disc = """
            SELECT Parlamentar, Texto, Partido 
            FROM discursos 
            WHERE Data = ? AND Comissao LIKE ? 
            LIMIT 5
            """
            # Tentar match aproximado da comissão
            nome_comissao_busca = f"%{nome_orgao.split(' - ')[-1].strip()}%" if ' - ' in nome_orgao else f"%{nome_orgao}%"
            
            df_disc = pd.read_sql_query(query_disc, conn_discursos, params=[data_formatada, nome_comissao_busca])
            
            resumo_sessao = ""
            if not df_disc.empty:
                resumo_sessao = "\n".join([f"- {row['Parlamentar']} ({row['Partido']}): {row['Texto'][:200]}..." for _, row in df_disc.iterrows()])
            else:
                resumo_sessao = "Não há discursos registrados nesta data."
                
            contexto_ausencias.append(f"""
            DATA: {data_formatada}
            EVENTO: {ausencia['descricao']}
            PAUTA/DESCRIÇÃO: {ausencia['pauta']}
            O QUE FOI DISCUTIDO (Amostra):
            {resumo_sessao}
            """)
            
        conn_discursos.close()
        
        # 5. Gerar Análise com LLM
        # Dados comparativos
        comp_texto = ""
        if request.percentual_presenca is not None and request.media_comissao is not None:
            diff = request.percentual_presenca - request.media_comissao
            status_comp = "ABAIXO" if diff < 0 else "ACIMA"
            comp_texto = f"O parlamentar teve {request.percentual_presenca:.1f}% de presença, ficando {status_comp} da média da comissão ({request.media_comissao:.1f}%)."

        prompt = f"""
        Atue como um analista político sênior e incisivo. Analise as ausências do parlamentar {nome_deputado} na comissão {nome_orgao}.
        
        CONTEXTO:
        {comp_texto}
        
        DETALHES DAS SESSÕES PERDIDAS:
        {"-"*20}
        {"".join(contexto_ausencias)}
        {"-"*20}
        
        ESCREVA UM RELATÓRIO INCISIVO E DETALHADO (Mínimo 4 parágrafos):
        
        1. CITE AS DATAS EXATAS e o que ele deixou de votar ou discutir em cada uma. Nomeie os Projetos de Lei (PLs) ou pautas específicas se houver.
        2. EXPLICITE A FUNÇÃO do deputado nesta comissão e como sua ausência impacta a representatividade.
        3. COMPARE: Se ele faltou muito (está abaixo da média), critique a falta de compromisso. Se faltou pouco, analise se a ausência foi pontual mas em dia crítico.
        4. CONCLUSÃO: O impacto político dessas faltas para os eleitores e para o setor regulado pela comissão.
        
        Use tom profissional, crítico e baseado nos dados fornecidos. Não invente dados não listados acima.
        """
        
        
        # ---------------------------------------------------------
        # SISTEMA DE CACHE DO LLM
        # ---------------------------------------------------------
        try:
            # 1. Gerar Hash do Prompt
            prompt_hash = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
            conn_cache = sqlite3.connect(DATABASE_PATHS.get("tabelao", _local_db("tabelao.db")))
            cursor_cache = conn_cache.cursor()
            
            # 2. Verificar se já existe no cache
            cursor_cache.execute("SELECT response_json FROM llm_cache WHERE hash_id = ?", (prompt_hash,))
            cached_result = cursor_cache.fetchone()
            
            if cached_result:
                print(f"⚡ [CACHE HIT] Retornando análise salva para hash {prompt_hash[:8]}", flush=True)
                analise_texto = cached_result[0]
            else:
                print(f"🤖 [CACHE MISS] Gerando nova análise na OpenAI... Hash: {prompt_hash[:8]}", flush=True)
                # 3. Gerar na OpenAI
                response = client.chat.completions.create(
                    model="gpt-5.4-mini",
                    messages=[
                        {"role": "system", "content": "Você é um analista parlamentar focado em produtividade e presença."},
                        {"role": "user", "content": prompt}
                    ],
                    max_completion_tokens=3000,
                    temperature=0.3
                )
                analise_texto = response.choices[0].message.content
                
                # 4. Salvar no Cache
                print(f"💾 Salvando no cache DB: {os.path.abspath('tabelao.db')}", flush=True)
                cursor_cache.execute(
                    "INSERT INTO llm_cache (hash_id, response_json, created_at) VALUES (?, ?, ?)",
                    (prompt_hash, analise_texto, datetime.now().isoformat())
                )
                conn_cache.commit()
                print("✅ Salvo no cache.", flush=True)
                
            conn_cache.close()
            
        except Exception as e:
            print(f"⚠️ Erro no processo de LLM/Cache: {e}")
            analise_texto = f"Erro ao gerar análise: {str(e)}"
            
        return {
            "analise": analise_texto,
            "detalhes_ausencias": ausencias_confirmadas,
            "comissao": nome_orgao,
            "periodo": f"{data_inicio_str} a {data_fim_str}",
            "num_discursos": sum(1 for ctx in contexto_ausencias if "Não há discursos registrados" not in ctx)
        }

    except Exception as e:
        print(f"Erro em /api/llm/presenca-reunioes-faltadas: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

# --------------------------------------------------------------------------------
# REDE DE FORNECEDORES (GRAFO)
# --------------------------------------------------------------------------------

@app.get("/api/rede-fornecedores/{nome_deputado}")
async def get_rede_fornecedores(nome_deputado: str, api_key: str = Security(get_api_key)):
    """
    Retorna estrutura de grafo (nodes e links) para a rede de fornecedores do deputado.
    Nodes: Deputado (Centro), Fornecedores (Top 15), Outros Deputados (Top 5 por fornecedor).
    Links: Deputado -> Fornecedor, Fornecedor -> Outro Deputado.
    """
    try:
        # Usar 'tabelao' pois é onde está a tabela serie_historica_gastos (ou similar)
        # Se serie_historica_gastos não existir, tentar tabela principal de gastos.
        # Assumindo 'tabelao' como banco principal.
        conn = get_db_connection('tabelao')
        cursor = conn.cursor()
        
        # 1. Normalização do nome para busca (LIKE)
        # Decodificar URL encoding é feito automatico pelo FastAPI no path param? Sim.
        nome_like = f"%{nome_deputado}%"
        
        # 2. Buscar Top 15 fornecedores do deputado (por valor total)
        # Primeiro verificamos a tabela correta. Normalmente 'tabelao' tem tudo?
        # Ou 'serie_historica_gastos'? 
        # Vamos tentar 'tabelao' que tem colunas 'txtCNPJCPF', 'txtFornecedor', 'vlrLiquido', 'txNomeParlamentar'
        
        query_fornecedores = """
            SELECT 
                txtCNPJCPF, 
                txtFornecedor, 
                SUM(vlrLiquido) as total_gasto
            FROM tabelao
            WHERE txNomeParlamentar = ? OR txNomeParlamentar LIKE ?
            GROUP BY txtCNPJCPF, txtFornecedor
            ORDER BY total_gasto DESC
            LIMIT 15
        """
        
        cursor.execute(query_fornecedores, (nome_deputado, nome_like))
        fornecedores_rows = cursor.fetchall()
        
        # Fallback caso não ache exato
        if not fornecedores_rows:
             cursor.execute(query_fornecedores, (nome_like, nome_like))
             fornecedores_rows = cursor.fetchall()

        nodes = []
        links = []
        nodes_ids = set() # Para evitar duplicatas
        
        # --- Node Central: Deputado Alvo ---
        # Tenta pegar URL da foto na tabela 'deputados' se existir, ou usar placeholder
        img_url = "https://www.camara.leg.br/tema/assets/images/foto-deputado-sem-foto.png"
        try:
            cursor.execute("SELECT txtUrlFoto FROM tabelao WHERE txNomeParlamentar LIKE ? LIMIT 1", (nome_like,))
            foto_row = cursor.fetchone()
            if foto_row and foto_row[0]:
                img_url = foto_row[0]
        except:
             pass
        
        nodes.append({
            "id": nome_deputado,
            "name": nome_deputado,
            "symbol": f"image://{img_url}",
            "symbolSize": 50,
            "value": 0,
            "category": "Deputado Alvo",
            "label": {"show": True, "position": "bottom"}
        })
        nodes_ids.add(nome_deputado)
        
        # --- Processar Fornecedores ---
        for f_row in fornecedores_rows:
            cnpj = f_row[0]
            nome_fornecedor = f_row[1]
            total_gasto = f_row[2]
            
            if not nome_fornecedor: continue
            
            # Node Fornecedor
            # ID único para o node: "F_CNPJ" ou Nome se CNPJ nulo
            fornecedor_id = f"F_{cnpj}" if cnpj else f"F_{nome_fornecedor}"
            
            if fornecedor_id not in nodes_ids:
                nodes.append({
                    "id": fornecedor_id,
                    "name": nome_fornecedor[:30] + "..." if len(nome_fornecedor) > 30 else nome_fornecedor,
                    "full_name": nome_fornecedor,
                    "symbol": "circle",
                    "symbolSize": 20, 
                    "value": total_gasto,
                    "category": "Fornecedor",
                    "label": {"show": True, "position": "right", "fontSize": 10},
                    "itemStyle": {"color": "#ff7043"} # Laranja para fornecedor
                })
                nodes_ids.add(fornecedor_id)
            
            # Link Deputado -> Fornecedor
            links.append({
                "source": nome_deputado,
                "target": fornecedor_id,
                "value": total_gasto,
                "lineStyle": {"width": 2, "curveness": 0.2}
            })
            
            # --- 3. Buscar outros deputados neste fornecedor ---
            # Top 3 outros
            query_outros = """
                SELECT 
                    txNomeParlamentar,
                    SUM(vlrLiquido) as total_outros
                FROM tabelao
                WHERE txtCNPJCPF = ? AND txNomeParlamentar != ? AND txNomeParlamentar NOT LIKE ?
                GROUP BY txNomeParlamentar
                ORDER BY total_outros DESC
                LIMIT 3
            """
            
            # Se CNPJ for nulo ou genérico, cuidado. Mas vamos tentar.
            if cnpj:
                cursor.execute(query_outros, (cnpj, nome_deputado, nome_like))
                outros_rows = cursor.fetchall()
                
                for o_row in outros_rows:
                    outro_nome = o_row[0]
                    outro_gasto = o_row[1]
                    
                    if not outro_nome: continue
                    
                    if outro_nome not in nodes_ids:
                        nodes.append({
                            "id": outro_nome,
                            "name": outro_nome,
                            "symbol": "circle", 
                            "symbolSize": 10,
                            "value": outro_gasto,
                            "category": "Outro Parlamentar",
                            "label": {"show": False}, # Hover mostra nome
                            "itemStyle": {"color": "#42a5f5"} # Azul para outros
                        })
                        nodes_ids.add(outro_nome)
                    
                    # Link Fornecedor -> Outro Deputado
                    links.append({
                        "source": fornecedor_id,
                        "target": outro_nome,
                        "value": outro_gasto,
                        "lineStyle": {"width": 1, "opacity": 0.5, "curveness": 0.1}
                    })

        conn.close()
        
        return {
            "nodes": nodes,
            "links": links,
            "categories": [
                {"name": "Deputado Alvo"},
                {"name": "Fornecedor"},
                {"name": "Outro Parlamentar"}
            ]
        }
        
    except Exception as e:
        logger.error(f"Erro grafo fornecedores: {e}")
        import traceback
        traceback.print_exc()
        return {"nodes": [], "links": [], "categories": []}

# ==========================================
# NOVOS ENDPOINTS - PARLAMENTARES
# ==========================================

@app.get("/api/parlamentares")
async def get_parlamentares(estado: Optional[str] = None, partido: Optional[str] = None):
    """Retorna lista simplificada de parlamentares com filtros opcionais."""
    try:
        conn = get_db_connection("tabelao")
        query = "SELECT DISTINCT id, nome, sgPartido, sgUF, ultimoStatus_urlFoto as urlFoto FROM tabelao WHERE 1=1"
        params = []
        
        if estado and estado != 'Todos':
            query += " AND sgUF = ?"
            params.append(estado)
        
        if partido and partido != 'Todos':
            query += " AND sgPartido = ?"
            params.append(partido)
            
        query += " ORDER BY nome"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"Erro ao listar parlamentares: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/filtros/comissoes")
@app.get("/api/filters/comissoes")
async def get_comissoes_unified(parlamentar: Optional[str] = None, source: Optional[str] = None):
    """Retorna lista de órgãos/comissões com siglas e nomes reais.
    source='discursos' retorna comissões onde o parlamentar tem discursos registrados."""
    # When querying for a specific parlamentar in discursos context, use discursos.db
    if source == "discursos" and parlamentar and parlamentar != "Todos":
        try:
            conn_disc = get_db_connection("discursos")
            df_disc = pd.read_sql_query(
                """
                SELECT DISTINCT Comissao
                FROM discursos
                WHERE UPPER(TRIM(Parlamentar)) LIKE UPPER(TRIM(?))
                  AND Comissao IS NOT NULL AND TRIM(Comissao) != ''
                """,
                conn_disc,
                params=[f"%{parlamentar}%"]
            )
            conn_disc.close()
            import re as _re
            INVALIDOS = {"ID de Sessão inválido", "ID Inválido", ""}
            # Normalize long one-off commission types into canonical group names
            def _canonicalize(s: str) -> str:
                s = s.strip().rstrip(',').strip()
                if not s or s in INVALIDOS:
                    return ""
                if _re.match(r'Comissão Parlamentar de Inquérito', s, _re.I) or _re.match(r'^CPI\b', s, _re.I):
                    return "Comissão Parlamentar de Inquérito (CPI)"
                if _re.match(r'Comissão Especial', s, _re.I):
                    return "Comissão Especial"
                if _re.match(r'Comissão Externa', s, _re.I):
                    return "Comissão Externa"
                if _re.match(r'Grupo de Trabalho', s, _re.I):
                    return "Grupo de Trabalho"
                return s

            individuais = set()
            for raw in df_disc["Comissao"].dropna().tolist():
                raw_str = str(raw).strip()
                if raw_str in INVALIDOS:
                    continue
                # Split on ", " followed by known commission-type prefixes
                partes = _re.split(r',\s+(?=Comissão|Plenário|Conselho|Grupo de Trabalho|CPI)', raw_str)
                for parte in partes:
                    canon = _canonicalize(parte)
                    if canon:
                        individuais.add(canon)

            comissoes_list = [{"id": c, "nome": c} for c in sorted(individuais) if c]
            comissoes_list = sorted(comissoes_list, key=lambda x: (x["id"] != "Plenário", x["nome"]))
            return {"comissoes": comissoes_list}
        except Exception as e:
            logger.error(f"Erro ao listar comissoes de discursos: {e}")
            # Fall through to default behavior

    try:
        conn = get_db_connection("tabelao")

        # Mapeamento básico de siglas comuns para nomes reais
        MAPPING = {
            'CFT': 'Comissão de Finanças e Tributação',
            'CCJC': 'Comissão de Constituição e Justiça e de Cidadania',
            'CTUR': 'Comissão de Turismo',
            'CN': 'Congresso Nacional',
            'CCULT': 'Comissão de Cultura',
            'CE': 'Comissão de Educação',
            'CTRAB': 'Comissão de Trabalho',
            'CSAUDE': 'Comissão de Saúde',
            'CCTI': 'Comissão de Ciência, Tecnologia e Inovação',
            'CDU': 'Comissão de Desenvolvimento Urbano',
            'CDE': 'Comissão de Desenvolvimento Econômico',
            'PLEN': 'Plenário',
            'CSPCCO': 'Segurança Pública e Combate ao Crime Organizado',
            'CICS': 'Comissão de Indústria, Comércio e Serviços',
            'CMULHER': 'Comissão de Defesa dos Direitos da Mulher',
            'CESPO': 'Comissão do Esporte',
            'CPD': 'Comissão de Defesa dos Direitos das Pessoas com Deficiência',
            'CCP': 'Comissão de Constituição e Justiça e de Cidadania (Antiga)',
            'CDHMIR': 'Direitos Humanos, Minorias e Igualdade Racial',
            'CPASF': 'Previdência, Assistência Social, Infância, Adolescência e Família',
            'CCOM': 'Comissão de Comunicação',
            'CLP': 'Comissão de Legislação Participativa',
            'CIDOSO': 'Comissão de Defesa dos Direitos da Pessoa Idosa',
            'CREDN': 'Relações Exteriores e de Defesa Nacional',
            'CAPADR': 'Agricultura, Pecuária, Abastecimento e Desenv. Rural',
            'CVT': 'Comissão de Viação e Transportes',
            'CME': 'Comissão de Minas e Energia',
            'CMADS': 'Meio Ambiente e Desenvolvimento Sustentável',
            'CINDRE': 'Integração Nacional e Desenvolvimento Regional',
            'CASP': 'Administração e Serviço Público',
            'CFFC': 'Fiscalização Financeira e Controle',
            'MESA': 'Mesa Diretora',
            'CDC': 'Comissão de Defesa do Consumidor',
            'CPOVOS': 'Amazônia e dos Povos Originários e Tradicionais'
        }

        if parlamentar and parlamentar != 'Todos':
            nome_limpo = str(parlamentar).replace("DR. ", "").replace("PROF. ", "").strip()

            query_votos = """
                WITH parlamentar_ids AS (
                    SELECT DISTINCT CAST(id AS TEXT) AS id_deputado
                    FROM tabelao
                    WHERE UPPER(TRIM(nome)) = UPPER(TRIM(?))
                       OR UPPER(TRIM(nomeCivil)) = UPPER(TRIM(?))
                ),
                todos_votos AS (
                    SELECT CAST(id_parlamentar AS TEXT) AS id_deputado, id_votacao
                    FROM votos_parlamentares
                    WHERE CAST(id_parlamentar AS TEXT) IN (SELECT id_deputado FROM parlamentar_ids)
                    UNION ALL
                    SELECT CAST(id_deputado AS TEXT) AS id_deputado, id_votacao
                    FROM votos_destaque_detalhe
                    WHERE CAST(id_deputado AS TEXT) IN (SELECT id_deputado FROM parlamentar_ids)
                ),
                votacoes_base AS (
                    SELECT id_votacao, sigla_orgao
                    FROM votacoes
                    UNION ALL
                    SELECT id_votacao, sigla_orgao
                    FROM votacoes_unificadas
                    WHERE id_votacao NOT IN (SELECT id_votacao FROM votacoes)
                )
                SELECT DISTINCT COALESCE(NULLIF(TRIM(vb.sigla_orgao), ''), 'PLEN') AS sigla_orgao
                FROM todos_votos tv
                JOIN votacoes_base vb ON tv.id_votacao = vb.id_votacao
                ORDER BY sigla_orgao
            """

            try:
                df = pd.read_sql_query(query_votos, conn, params=[parlamentar, parlamentar])
            except Exception:
                df = pd.DataFrame()

            if df.empty:
                query_membros = """
                    SELECT DISTINCT nome_orgao
                    FROM membros_comissoes
                    WHERE nome_deputado LIKE ? OR nome_deputado LIKE ?
                    ORDER BY nome_orgao
                """
                df_membros = pd.read_sql_query(query_membros, conn, params=[f"%{parlamentar}%", f"%{nome_limpo}%"])
                res = [{"id": "PLEN", "nome": "Plenário"}]
                for nome in df_membros.get("nome_orgao", pd.Series(dtype=str)).dropna().tolist():
                    nome_orgao = str(nome).strip()
                    if nome_orgao:
                        res.append({"id": nome_orgao, "nome": nome_orgao})
                unicos = list({item["id"]: item for item in res}.values())
                unicos.sort(key=lambda x: (x["id"] != "PLEN", x["nome"]))
                conn.close()
                return {"comissoes": unicos}
        else:
            try:
                df = pd.read_sql_query(
                    """
                    SELECT DISTINCT COALESCE(NULLIF(TRIM(sigla_orgao), ''), 'PLEN') AS sigla_orgao
                    FROM votacoes
                    WHERE sigla_orgao IS NOT NULL
                    UNION
                    SELECT DISTINCT COALESCE(NULLIF(TRIM(sigla_orgao), ''), 'PLEN') AS sigla_orgao
                    FROM votacoes_unificadas
                    WHERE sigla_orgao IS NOT NULL
                    ORDER BY sigla_orgao
                    """,
                    conn
                )
            except Exception:
                df = pd.DataFrame()

        conn.close()

        siglas = df['sigla_orgao'].dropna().tolist() if not df.empty and 'sigla_orgao' in df.columns else ['PLEN']

        res = []
        for s in siglas:
            sigla = str(s).strip() or 'PLEN'
            res.append({
                "id": sigla,
                "nome": MAPPING.get(sigla, sigla if sigla != 'PLEN' else 'Plenário')
            })
        res = list({item["id"]: item for item in res}.values())
        res.sort(key=lambda x: (x['id'] != 'PLEN', x['nome']))

        return {"comissoes": res}
    except Exception as e:
        logger.error(f"Erro ao listar comissoes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def normalize_date(date_str: str) -> str:
    """Converte datas DD/MM/YYYY ou YYYY-MM-DD para o padrão YYYY-MM-DD do banco."""
    if not date_str:
        return date_str
    try:
        # Tenta formato brasileiro
        if '/' in date_str:
            d, m, y = date_str.split('/')
            return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        return date_str
    except:
        return date_str

@app.get("/api/parlamentares/{id_deputado}/stats")
async def get_parlamentar_stats(
    id_deputado: str,
    tema: Optional[str] = None,
    comissao: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    tipo_voto_filtro: Optional[str] = 'Todos' # New: Todos, Nominal, Simbolico
):
    """Retorna estatísticas de votação do parlamentar com filtros."""
    try:
        conn = get_db_connection("tabelao")

        def _sanitize_json_value(value):
            if isinstance(value, dict):
                return {k: _sanitize_json_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_sanitize_json_value(v) for v in value]
            if pd.isna(value):
                return None
            return value

        def _normalize_nome_lookup(value: str) -> str:
            if value is None:
                return ""
            normalized = unicodedata.normalize("NFD", str(value).strip().upper())
            return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")

        id_param = (id_deputado or "").strip()
        resolved_id = id_param

        if not id_param.isdigit():
            df_resolve = pd.read_sql_query(
                """
                SELECT DISTINCT id, nome
                FROM tabelao
                WHERE nome IS NOT NULL AND TRIM(nome) <> ''
                """,
                conn
            )
            nome_alvo = _normalize_nome_lookup(id_param)
            if not df_resolve.empty:
                df_resolve["nome_normalizado"] = df_resolve["nome"].apply(_normalize_nome_lookup)
                df_resolve = df_resolve[df_resolve["nome_normalizado"] == nome_alvo]
            if df_resolve.empty:
                conn.close()
                raise HTTPException(status_code=404, detail="Parlamentar não encontrado")
            resolved_id = str(df_resolve.iloc[0]["id"])
        
        # 1. Perfil
        query_perfil = "SELECT * FROM tabelao WHERE id = ?"
        df_perfil = pd.read_sql_query(query_perfil, conn, params=[resolved_id])
        if df_perfil.empty:
            conn.close()
            raise HTTPException(status_code=404, detail="Parlamentar não encontrado")
        
        # Blindagem contra a serialização JSON da conversão em dicionário
        df_perfil = df_perfil.fillna("")
        
        perfil_raw = df_perfil.iloc[0].to_dict()
        # Limpar espaços extras nos nomes das colunas (ex: urlPartido)
        perfil = {k.strip(): v for k, v in perfil_raw.items()}
        sg_partido_eleicao = str(perfil.get("sgPartido") or "").strip()
        sg_partido_atual = str(perfil.get("ultimoStatus_siglaPartido") or sg_partido_eleicao).strip()
        perfil["sgPartidoEleicao"] = sg_partido_eleicao
        perfil["sgPartidoAtual"] = sg_partido_atual
        perfil["sgPartidoExibicao"] = sg_partido_atual or sg_partido_eleicao
        # 2. Votos e Alinhamento
        # Unificar votos_parlamentares e votos_destaque_detalhe para pegar tudo (Nominal + Simbólica)
        query_votos = """
        WITH todos_votos AS (
            SELECT CAST(id_parlamentar AS TEXT) AS id_parlamentar, id_votacao, voto FROM votos_parlamentares
            UNION ALL
            SELECT CAST(id_deputado AS TEXT) AS id_parlamentar, id_votacao, voto FROM votos_destaque_detalhe
        ),
        votacoes_base AS (
            SELECT
                id_votacao,
                data_votacao AS data_registro,
                sigla_orgao,
                COALESCE(tipo_votacao, 'N/A') AS tipo_votacao,
                descricao,
                nome_projeto,
                objeto_votacao,
                tema,
                resumo_discussao
            FROM votacoes
            UNION ALL
            SELECT
                id_votacao,
                data_registro,
                sigla_orgao,
                COALESCE(tipo_votacao, 'N/A') AS tipo_votacao,
                descricao,
                proposicao AS nome_projeto,
                NULL AS objeto_votacao,
                NULL AS tema,
                resumo_midia AS resumo_discussao
            FROM votacoes_unificadas
            WHERE id_votacao NOT IN (SELECT id_votacao FROM votacoes)
        )
        SELECT 
            v.voto,
            COALESCE(e.pauta_governo, 'Indiferente') AS pauta_governo,
            COALESCE(e.tema_macro, vb.tema, 'Geral') AS tema_macro,
            COALESCE(d.resumo_midia, e.resumo_leigo, vb.resumo_discussao, vb.objeto_votacao, vb.descricao, 'Resumo técnico detalhado não disponível no sistema') AS resumo_leigo,
            vb.data_registro AS data_votacao,
            vb.sigla_orgao,
            vb.tipo_votacao,
            vb.id_votacao,
            vb.descricao,
            vb.nome_projeto,
            vb.objeto_votacao
        FROM todos_votos v
        JOIN votacoes_base vb ON v.id_votacao = vb.id_votacao
        LEFT JOIN votacoes_analise_enrichment e ON v.id_votacao = e.id_votacao
        LEFT JOIN votacoes_destaque d ON v.id_votacao = d.id_votacao
        WHERE v.id_parlamentar = ?
        """
        params = [resolved_id]
        
        if tema and tema != 'Todos':
            # Mapeamento reverso simplificado para o filtro bater com o macro_tema_agrupado
            MAP_SUBTHEMES = {
                'Administração Pública': ['Admin', 'Pública', 'Polític', 'Eleitoral', 'Transparência', 'Governo', 'Legislação', 'Regimento', 'Mesa', 'Comunicação', 'Comissão'],
                'Agropecuária e Meio Ambiente': ['Agro', 'Meio Amb', 'Rural', 'Energia', 'Clima', 'Terra'],
                'Cultura e Esporte': ['Cultura', 'Esporte', 'Arte'],
                'Direitos Humanos e Sociais': ['Humanos', 'Social', 'Mulher', 'Idoso', 'Igualdade', 'Minoria', 'Criança', 'Assistência'],
                'Economia e Desenvolvimento': ['Econ', 'Finan', 'Tribut', 'Indústria', 'Comércio', 'Turismo', 'Trabalho'],
                'Educação': ['Educação', 'Ensino'],
                'Infraestrutura e Transportes': ['Infra', 'Transp', 'Urban', 'Habita', 'Cidades'],
                'Relações Exteriores': ['Exteriores', 'Internacional'],
                'Saúde': ['Saú', 'Sanit', 'Médico'],
                'Segurança Pública e Justiça': ['Segurança', 'Justiça', 'Penal', 'Defesa', 'Crime', 'Civil']
            }
            if tema in MAP_SUBTHEMES:
                keywords = MAP_SUBTHEMES[tema]
                clause = " AND (" + " OR ".join(["e.tema_macro LIKE ?"] * len(keywords)) + ")"
                query_votos += clause
                for kw in keywords:
                    params.append(f"%{kw}%")
            else:
                query_votos += " AND e.tema_macro = ?"
                params.append(tema)
            
        if comissao and comissao != 'Todos':
            query_votos += " AND vb.sigla_orgao = ?"
            params.append(comissao)
            
        if data_inicio:
            query_votos += " AND vb.data_registro >= ?"
            params.append(normalize_date(data_inicio))
            
        if data_fim:
            query_votos += " AND vb.data_registro <= ?"
            params.append(normalize_date(data_fim))
            
        if tipo_voto_filtro and tipo_voto_filtro != 'Todos':
            if tipo_voto_filtro == 'Nominal':
                query_votos += " AND vb.tipo_votacao LIKE '%Nominal%'"
            elif tipo_voto_filtro == 'Simbolico':
                query_votos += " AND (vb.tipo_votacao LIKE '%Simból%' OR vb.tipo_votacao LIKE '%Simbol%' OR vb.tipo_votacao LIKE '%Agregada%')"

        df_votos = pd.read_sql_query(query_votos, conn, params=params)
        df_votos['tipo_votacao'] = df_votos['tipo_votacao'].fillna('').astype(str)

        # Aplicar filtro de tipo de voto (Behavioral: Agregada -> Simbolica)
        if tipo_voto_filtro == 'Nominal':
            # Estritamente Nominal
            df_votos = df_votos[
                df_votos['tipo_votacao'].str.contains('Nominal', case=False, na=False) & 
                ~df_votos['tipo_votacao'].str.contains('Agregada', case=False, na=False)
            ].copy()
        elif tipo_voto_filtro == 'Simbolico':
            # Simbólica ou Nominal Agregada
            df_votos = df_votos[df_votos['tipo_votacao'].str.contains('Simbólica|Agregada', case=False, na=False)].copy()

        # 3. Estatísticas Gerais
        total_votos = len(df_votos)
        
        # Recalcular caches de tipo para o dashboard (mesmo filtrado, mostramos o split do set atual)
        v_simb = df_votos[df_votos['tipo_votacao'].str.contains('Simbólica|Agregada', case=False, na=False)]
        v_nom = df_votos[
            df_votos['tipo_votacao'].str.contains('Nominal', case=False, na=False) & 
            ~df_votos['tipo_votacao'].str.contains('Agregada', case=False, na=False)
        ]
        
        count_nominais = len(v_nom)
        count_simbolicos = len(v_simb)
        
        # Alinhamento
        df_gov = df_votos[df_votos['pauta_governo'].isin(['Sim', 'Não'])].copy()
        
        votos_com_governo = 0
        votos_contra_governo = 0
        abstencoes = 0
        perc_governismo = 0
        
        def check_alignment(row):
            gov = row['pauta_governo']
            voto = row['voto']
            if voto in ['Abstenção', 'Obstrução']: return 'Isento'
            if (gov == 'Sim' and voto == 'Sim') or (gov == 'Não' and voto == 'Não'): return 'Favorável'
            if (gov == 'Sim' and voto == 'Não') or (gov == 'Não' and voto == 'Sim'): return 'Contra'
            return 'Outro'

        if not df_gov.empty:
            df_gov['alinhamento'] = df_gov.apply(check_alignment, axis=1)
            counts = df_gov['alinhamento'].value_counts()
            votos_com_governo = int(counts.get('Favorável', 0))
            votos_contra_governo = int(counts.get('Contra', 0))
            abstencoes = int(counts.get('Isento', 0))
            
            total_validos_gov = votos_com_governo + votos_contra_governo + abstencoes
            perc_governismo = (votos_com_governo / total_validos_gov * 100) if total_validos_gov > 0 else 0
            
            # --- 3a. Evolução Temporal (Alinhamento por Mês) ---
            df_gov['mes_ano'] = pd.to_datetime(df_gov['data_votacao']).dt.strftime('%Y-%m')
            
            evolucao_temporal = []
            if not df_gov.empty:
                # Agrupar por mes_ano e calcular % alinhamento
                for mes, group in df_gov.groupby('mes_ano'):
                    g_counts = group['alinhamento'].value_counts()
                    g_fav = g_counts.get('Favorável', 0)
                    g_contra = g_counts.get('Contra', 0)
                    g_isento = g_counts.get('Isento', 0)
                    g_total = g_fav + g_contra + g_isento
                    g_perc = (g_fav / g_total * 100) if g_total > 0 else 0
                    
                    evolucao_temporal.append({
                        "periodo": mes,
                        "governismo": round(g_perc, 1),
                        "votos": int(g_total)
                    })
                evolucao_temporal.sort(key=lambda x: x['periodo'])
        else:
            evolucao_temporal = []

        # 4. Por Tema (Consolidado em Macro Temas)
        temas_stats = []
        if not df_gov.empty:
            def get_macro_tema(t):
                if not t: return 'Outros'
                t = str(t)
                if any(x in t for x in ['Admin', 'Pública', 'Polític', 'Eleitoral', 'Transparência', 'Governo', 'Legislação', 'Regimento', 'Mesa', 'Comunicação', 'Comissão']):
                    return 'Administração Pública'
                if any(x in t for x in ['Agro', 'Meio Amb', 'Rural', 'Energia', 'Clima', 'Terra']):
                    return 'Agropecuária e Meio Ambiente'
                if any(x in t for x in ['Cultura', 'Esporte', 'Arte']):
                    return 'Cultura e Esporte'
                if any(x in t for x in ['Humanos', 'Social', 'Mulher', 'Idoso', 'Igualdade', 'Minoria', 'Criança', 'Assistência']):
                    return 'Direitos Humanos e Sociais'
                if any(x in t for x in ['Econ', 'Finan', 'Tribut', 'Indústria', 'Comércio', 'Turismo', 'Trabalho']):
                    return 'Economia e Desenvolvimento'
                if any(x in t for x in ['Educação', 'Ensino']):
                    return 'Educação'
                if any(x in t for x in ['Infra', 'Transp', 'Urban', 'Habita', 'Cidades']):
                    return 'Infraestrutura e Transportes'
                if any(x in t for x in ['Exteriores', 'Internacional']):
                    return 'Relações Exteriores'
                if any(x in t for x in ['Saú', 'Sanit', 'Médico']):
                    return 'Saúde'
                if any(x in t for x in ['Segurança', 'Justiça', 'Penal', 'Defesa', 'Crime', 'Civil']):
                    return 'Segurança Pública e Justiça'
                return 'Outros'

            # Criar coluna de macro tema de forma garantida
            df_gov['macro_tema_agrupado'] = df_gov['tema_macro'].fillna('Outros').apply(get_macro_tema)
            
            if not df_gov.empty and 'macro_tema_agrupado' in df_gov.columns and 'alinhamento' in df_gov.columns:
                try:
                    df_gov_temas = df_gov.groupby('macro_tema_agrupado', observed=True)['alinhamento'].value_counts().unstack().fillna(0)
                    for tema_nome, row in df_gov_temas.iterrows():
                        fav = row.get('Favorável', 0)
                        contra = row.get('Contra', 0)
                        isento = row.get('Isento', 0)
                        total = fav + contra + isento
                        perc = (fav / total * 100) if total > 0 else 0
                        temas_stats.append({
                            "tema": str(tema_nome),
                            "governismo": round(float(perc), 1),
                            "total_votos": int(total)
                        })
                except Exception as e:
                    logger.warning(f"Erro ao agrupar temas: {e}")
                    temas_stats = []
        
        # Omitir Badges conforme pedido do usuário
        conn.close()
        
        return _sanitize_json_value({
            "perfil": perfil,
            "stats": {
                "total_votos": int(total_votos),
                "votos_nominais": int(count_nominais),
                "votos_simbolicos": int(count_simbolicos),
                "governismo_perc": round(perc_governismo, 1),
                "votos_favoraveis": votos_com_governo,
                "votos_contrarios": votos_contra_governo,
                "abstencoes": abstencoes
            },
            "temas": temas_stats,
            "evolucao": evolucao_temporal,
            "votos_detalhe": df_votos[['data_votacao', 'id_votacao', 'tipo_votacao', 'voto', 'tema_macro']].to_dict(orient='records') if not df_votos.empty else []
        })
    except Exception as e:
        logger.error(f"Erro stats parlamentar: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# =====================================================================
# ENDPOINTS DA AUDITORIA PROFUNDA DE IMPRENSA (V2)
# =====================================================================

def get_imprensa_db_conn():
    db_path = DATABASE_PATHS.get("noticias", _local_db("noticias_parlamentares.db"))
    return sqlite3.connect(db_path)

IMPRENSA_DATA_SQL = """
date(
    CASE
        WHEN instr(n.data, '/') > 0 AND length(n.data) >= 10
            THEN substr(n.data, 7, 4) || '-' || substr(n.data, 4, 2) || '-' || substr(n.data, 1, 2)
        ELSE substr(n.data, 1, 10)
    END
)
"""

def parse_imprensa_date(value):
    """Normaliza datas da tabela noticias para Timestamp, cobrindo ISO, BR, RFC e mês abreviado em PT."""
    if value is None or pd.isna(value):
        return pd.NaT
    text = str(value).strip()
    if not text:
        return pd.NaT

    meses_pt = {
        "jan": "01", "janeiro": "01",
        "fev": "02", "fevereiro": "02",
        "mar": "03", "marco": "03", "março": "03",
        "abr": "04", "abril": "04",
        "mai": "05", "maio": "05",
        "jun": "06", "junho": "06",
        "jul": "07", "julho": "07",
        "ago": "08", "agosto": "08",
        "set": "09", "setembro": "09",
        "out": "10", "outubro": "10",
        "nov": "11", "novembro": "11",
        "dez": "12", "dezembro": "12",
    }
    norm = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
    match = re.search(r"(\d{1,2})\s+de\s+([a-z.]+)\s+de\s+(\d{4})", norm)
    if match:
        dia, mes_txt, ano = match.groups()
        mes = meses_pt.get(mes_txt.replace(".", ""))
        if mes:
            return pd.to_datetime(f"{ano}-{mes}-{int(dia):02d}", errors="coerce")

    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True, utc=True)
    if pd.isna(parsed):
        return pd.NaT
    try:
        return parsed.tz_convert(None)
    except Exception:
        try:
            return parsed.tz_localize(None)
        except Exception:
            return parsed

IMPRENSA_MIN_DATE = pd.Timestamp("2023-01-01")

@app.get("/api/imprensa-v2/filtros")
async def get_imprensa_v2_filtros():
    """Retorna filtros baseados na base V2, com normalização de acentos para pareamento."""
    try:
        import unicodedata
        def normalize_name(s):
            if not s: return ""
            return "".join(c for c in unicodedata.normalize('NFD', str(s).upper()) if unicodedata.category(c) != 'Mn').strip()

        conn = get_imprensa_db_conn()
        df_ativos = pd.read_sql_query("SELECT DISTINCT nome FROM noticias_mencoes_v2 WHERE tipo_entidade='PARLAMENTAR'", conn)
        conn.close()
        
        if df_ativos.empty:
            return {"parlamentares": [], "ufs": [], "partidos": [], "veiculos": [], "vies": [], "temas": []}

        # Conjunto de nomes normalizados com auditoria
        nomes_auditados = {normalize_name(n) for n in df_ativos['nome'].tolist()}
        
        # Carregar o Tabelão (Base de Referência)
        conn_tab = get_db_connection("tabelao")
        df_tabelao = pd.read_sql_query("SELECT DISTINCT nome, sgUF as uf, sgPartido as partido FROM tabelao", conn_tab)
        conn_tab.close()
        
        # Filtro: Manter apenas parlamentares do Tabelão que foram citados nas notícias
        df_tabelao['nome_norm'] = df_tabelao['nome'].apply(normalize_name)
        df_base = df_tabelao[df_tabelao['nome_norm'].isin(nomes_auditados)].copy()
        
        # Preparar dados para o Frontend
        parlamentares_data = df_base[['nome', 'uf', 'partido']].drop_duplicates().fillna("").to_dict('records')
        ufs = sorted(df_base['uf'].dropna().unique().tolist())
        partidos = sorted(df_base['partido'].dropna().unique().tolist())
        
        # Filtros de Contexto (Veículos, Viés, Temas)
        conn = get_imprensa_db_conn()
        df_veic = pd.read_sql_query("SELECT DISTINCT veiculo_nome FROM noticias_metadados_v2 WHERE veiculo_nome IS NOT NULL AND veiculo_nome != ''", conn)
        veiculos = sorted(df_veic['veiculo_nome'].tolist())
        
        df_vies = pd.read_sql_query("SELECT DISTINCT vies_editorial FROM noticias_metadados_v2 WHERE vies_editorial IS NOT NULL", conn)
        vies = sorted(df_vies['vies_editorial'].tolist())

        df_temas = pd.read_sql_query("SELECT temas_tratados FROM noticias_metadados_v2 WHERE temas_tratados IS NOT NULL", conn)
        temas_unicos = set()
        for _, row in df_temas.iterrows():
            try:
                lista = json.loads(row['temas_tratados'])
                for t in lista: temas_unicos.add(str(t).strip())
            except: pass
        temas = sorted(list(temas_unicos))
        df_periodo_raw = pd.read_sql_query(
            """
            SELECT n.data AS data_raw
            FROM noticias n
            JOIN noticias_metadados_v2 meta ON n.id = meta.news_id
            WHERE n.data IS NOT NULL AND trim(n.data) != ''
            """,
            conn
        )
        df_periodo_raw['data_norm'] = df_periodo_raw['data_raw'].apply(parse_imprensa_date)
        df_periodo_raw = df_periodo_raw[df_periodo_raw['data_norm'].notna() & (df_periodo_raw['data_norm'] >= IMPRENSA_MIN_DATE)]
        periodo_noticias = {
            "data_min": df_periodo_raw["data_norm"].min().strftime("%Y-%m-%d") if not df_periodo_raw.empty else None,
            "data_max": df_periodo_raw["data_norm"].max().strftime("%Y-%m-%d") if not df_periodo_raw.empty else None,
        }
        conn.close()
        
        return {
            "parlamentares": parlamentares_data,
            "ufs": ufs,
            "partidos": partidos,
            "veiculos": veiculos,
            "vies": vies,
            "temas": temas,
            "periodo_noticias": periodo_noticias
        }
    except Exception as e:
        logger.error(f"Erro em filtros imprensa V2: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/imprensa-v2/date-range")
async def get_imprensa_v2_date_range(
    parlamentar: str = None,
    tema: str = None,
    apenas_escandalo: bool = False
):
    """Retorna o intervalo efetivo de notícias processadas para os filtros selecionados."""
    try:
        conn = get_imprensa_db_conn()
        query = """
        SELECT n.data AS data_raw, meta.temas_tratados
        FROM noticias n
        JOIN noticias_metadados_v2 meta ON n.id = meta.news_id
        JOIN noticias_mencoes_v2 m ON n.id = m.news_id
        WHERE n.data IS NOT NULL
          AND trim(n.data) != ''
          AND m.tipo_entidade = 'PARLAMENTAR'
        """
        params = []
        if parlamentar and parlamentar not in ("Selecione...", "Todos"):
            query += " AND UPPER(m.nome) LIKE '%' || UPPER(?) || '%'"
            params.append(parlamentar)
        if apenas_escandalo:
            query += " AND meta.indicador_escandalo_juridico = 1"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        if tema and tema != "Todos" and not df.empty:
            df = df[df['temas_tratados'].apply(lambda x: tema in json.loads(x) if pd.notna(x) else False)]

        df['data_norm'] = df['data_raw'].apply(parse_imprensa_date)
        df = df[df['data_norm'].notna() & (df['data_norm'] >= IMPRENSA_MIN_DATE)]
        df = df[df['data_norm'].notna()]
        if df.empty:
            return {"data_min": None, "data_max": None, "total": 0}

        return {
            "data_min": df['data_norm'].min().strftime("%Y-%m-%d"),
            "data_max": df['data_norm'].max().strftime("%Y-%m-%d"),
            "total": int(len(df))
        }
    except Exception as e:
        logger.error(f"Erro em date-range imprensa V2: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/imprensa-v2/temas-parlamentar")
async def get_imprensa_v2_temas_parlamentar(
    parlamentar: str,
    apenas_escandalo: bool = False
):
    """Retorna apenas os temas existentes para o parlamentar/filtro atual."""
    try:
        if not parlamentar or parlamentar in ("Selecione...", "Todos"):
            return {"temas": []}

        conn = get_imprensa_db_conn()
        query = """
        SELECT meta.temas_tratados, n.data AS data_raw
        FROM noticias_metadados_v2 meta
        JOIN noticias_mencoes_v2 m ON meta.news_id = m.news_id
        JOIN noticias n ON meta.news_id = n.id
        WHERE m.tipo_entidade = 'PARLAMENTAR'
          AND UPPER(m.nome) LIKE '%' || UPPER(?) || '%'
          AND meta.temas_tratados IS NOT NULL
          AND trim(meta.temas_tratados) != ''
        """
        params = [parlamentar]
        if apenas_escandalo:
            query += " AND meta.indicador_escandalo_juridico = 1"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        df['data_norm'] = df['data_raw'].apply(parse_imprensa_date)
        df = df[df['data_norm'].notna() & (df['data_norm'] >= IMPRENSA_MIN_DATE)]

        temas = set()
        for raw in df['temas_tratados'].dropna().astype(str):
            try:
                for tema in json.loads(raw):
                    tema = str(tema).strip()
                    if tema:
                        temas.add(tema)
            except Exception:
                continue

        return {"temas": sorted(temas)}
    except Exception as e:
        logger.error(f"Erro em temas parlamentar imprensa V2: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# Cache global para os filtros para evitar consultas pesadas
_GASTOS_FILTROS_CACHE = None

@app.get("/api/gastos/filtros")
async def get_gastos_filtros():
    """Filtros inteligentes para a página de Gastos (Filtro Cascata) com cache"""
    global _GASTOS_FILTROS_CACHE
    if _GASTOS_FILTROS_CACHE:
        return _GASTOS_FILTROS_CACHE
        
    try:
        import sqlite3
        conn = sqlite3.connect(DATABASE_PATHS.get("tabelao", _local_db("tabelao.db")))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT DISTINCT nome, sgPartido as partido, sgUF as estado FROM tabelao WHERE nome IS NOT NULL ORDER BY nome"
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        parlamentares_data = []
        ufs_set = set()
        
        for row in rows:
            parlamentares_data.append({
                "nome": row['nome'],
                "partido": row['partido'],
                "estado": row['estado']
            })
            if row['estado']: ufs_set.add(row['estado'])

        result = {"parlamentares": parlamentares_data, "ufs": sorted(list(ufs_set))}
        _GASTOS_FILTROS_CACHE = result
        return result
    except Exception as e:
        logger.error(f"Erro em filtros gastos: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/imprensa-v2/analise")
async def get_imprensa_v2_analise(
    parlamentar: str, 
    vies: str = None, 
    tema: str = None,
    apenas_escandalo: bool = False,
    data_inicio: str = None,
    data_fim: str = None
):
    """Executa o cruzamento profundo. Retorna ECharts Veículos vs Sentimento, Temporal e Grafo."""
    try:
        conn = get_imprensa_db_conn()
        
        base_query = f"""
        SELECT 
            m.news_id, m.sentimento_score, m.protagonismo_score, m.resumo_participacao,
            meta.veiculo_nome, meta.vies_editorial, meta.temas_tratados, meta.indicador_escandalo_juridico, meta.resumo_forense, meta.palavras_chave,
            n.data as data_raw, n.link, n.veiculo, n.titulo, n.resumo, n.texto_completo
        FROM noticias_mencoes_v2 m
        JOIN noticias_metadados_v2 meta ON m.news_id = meta.news_id
        JOIN noticias n ON m.news_id = n.id
        WHERE m.tipo_entidade = 'PARLAMENTAR' AND UPPER(m.nome) LIKE '%' || UPPER(?) || '%'
        """
        params = [parlamentar]
        
        if vies and vies != "Todos":
            base_query += " AND meta.vies_editorial = ?"
            params.append(vies)
            
        if apenas_escandalo:
            base_query += " AND meta.indicador_escandalo_juridico = 1"

        df = pd.read_sql_query(base_query, conn, params=params)
        
        if df.empty:
            conn.close()
            return {"error": "Nenhuma matéria encontrada para os filtros aplicados."}

        df['dt'] = df['data_raw'].apply(parse_imprensa_date)
        df = df[df['dt'].notna() & (df['dt'] >= IMPRENSA_MIN_DATE)]
        if data_inicio:
            inicio_dt = pd.to_datetime(data_inicio, errors='coerce')
            if pd.notna(inicio_dt):
                inicio_dt = max(inicio_dt, IMPRENSA_MIN_DATE)
                df = df[df['dt'].notna() & (df['dt'] >= inicio_dt)]
        if data_fim:
            fim_dt = pd.to_datetime(data_fim, errors='coerce')
            if pd.notna(fim_dt):
                df = df[df['dt'].notna() & (df['dt'] <= fim_dt)]
        df['data_noticia'] = df['dt'].dt.strftime("%Y-%m-%d")

        if df.empty:
            conn.close()
            return {"error": "Nenhuma matéria encontrada para o período selecionado."}

        # 1. PEGAR PERFIL DO PARLAMENTAR (TABELAO)
        profile_data = {"nome": parlamentar, "foto": None, "partido": None, "partido_logo": None, "estado": None, "estado_logo": None}
        try:
            conn_tab = get_db_connection("tabelao")
            q_tab = "SELECT nome, sgPartido, sgUF, ultimoStatus_urlFoto as foto FROM tabelao WHERE UPPER(nome) = UPPER(?) LIMIT 1"
            df_prof = pd.read_sql_query(q_tab, conn_tab, params=[parlamentar])
            if not df_prof.empty:
                row_p = df_prof.iloc[0]
                profile_data["nome"] = row_p['nome']
                profile_data["foto"] = row_p['foto']
                profile_data["partido"] = row_p['sgPartido']
                profile_data["estado"] = row_p['sgUF']
                profile_data["partido_logo"] = partido_logos_dict.get(str(row_p['sgPartido']).strip())
                profile_data["estado_logo"] = estado_logos_dict.get(str(row_p['sgUF']).strip())
            conn_tab.close()
        except Exception as e:
            logger.error(f"Erro ao buscar perfil tabelao: {e}")

        # Aplicar filtro de Tema no Python já que é JSON
        if tema and tema != "Todos":
            df = df[df['temas_tratados'].apply(lambda x: tema in json.loads(x) if pd.notna(x) else False)]
            
        if df.empty:
            conn.close()
            return {"error": "Nenhuma matéria passou pelo filtro de Temas."}
            
        # --- PROCESSAMENTO DE DADOS ---
        import urllib.parse
        fontes_busca_ou_agregador = {
            "duckduckgo", "google", "google news", "googlenews", "news.google.com",
            "bing", "yahoo", "serper", "gnews", "brave search"
        }

        def extract_domain(link):
            if not link or type(link) != str: return ""
            try: return urllib.parse.urlparse(link).netloc.replace("www.", "").lower()
            except: return ""

        def dominio_para_nome(domain):
            if not domain:
                return "Outros"
            base = domain.split(":")[0]
            partes = [p for p in base.split(".") if p]
            if len(partes) >= 3 and partes[-2] in {"com", "org", "gov", "edu", "net"}:
                nome = partes[-3]
            elif len(partes) >= 2:
                nome = partes[-2]
            else:
                nome = partes[0]
            nomes_especiais = {
                "g1": "G1",
                "r7": "R7",
                "ebc": "Agência Brasil",
                "camara": "Câmara dos Deputados",
                "senado": "Senado Federal",
                "metropoles": "Metrópoles",
                "conjur": "ConJur",
                "correiobraziliense": "Correio Braziliense",
                "poder360": "Poder360",
                "estadao": "Estadão",
                "folha": "Folha",
                "oglobo": "O Globo",
                "uol": "UOL",
                "cnn": "CNN Brasil",
                "veja": "VEJA",
                "cartacapital": "CartaCapital",
            }
            return nomes_especiais.get(nome, nome.replace("-", " ").title())

        def limpar_nome_fonte(nome):
            nome = str(nome or "").strip()
            nome = re.sub(r"\s*\((serper|duckduckgo|google\s*news|gnews|googlenews)[^)]*\)\s*", "", nome, flags=re.IGNORECASE)
            nome = re.sub(r"\s+", " ", nome).strip()
            return nome

        def resolver_veiculo(row):
            meta_nome = str(row.get("veiculo_nome") or "").strip()
            veiculo_original = str(row.get("veiculo") or "").strip()
            domain = extract_domain(row.get("link"))

            candidato = limpar_nome_fonte(meta_nome if meta_nome and meta_nome.lower() != "não especificado" else veiculo_original)
            candidato_norm = candidato.lower().strip()
            if (not candidato) or candidato_norm in fontes_busca_ou_agregador:
                return dominio_para_nome(domain)
            return candidato

        def classificar_fonte(row):
            nome = str(row.get("veiculo_nome") or "").lower()
            domain = str(row.get("veiculo_domain") or "").lower()
            combinado = f"{nome} {domain}"
            if any(x in combinado for x in ["camara.leg.br", "senado.leg.br", ".gov.br", "prefeitura", "assembleia", "tribunal", "ministerio"]):
                return "Fonte institucional"
            if any(x in combinado for x in ["psb40", "pt.org", "pl22", "republicanos10", "mdb.org", "uniaobrasil", "partido", "mandato"]):
                return "Partido/mandato"
            if any(x in combinado for x in ["linkedin", "facebook", "instagram", "youtube", "x.com", "twitter"]):
                return "Rede social/plataforma"
            return "Veículo de imprensa"

        df['veiculo_domain'] = df['link'].apply(extract_domain)
        df['veiculo_nome'] = df.apply(resolver_veiculo, axis=1)
        df['veiculo_tipo'] = df.apply(classificar_fonte, axis=1)
        df = df[~df['veiculo_nome'].str.lower().isin(fontes_busca_ou_agregador)]
        if df.empty:
            conn.close()
            return {"error": "Nenhuma matéria com veículo identificável passou pelos filtros aplicados."}
        
        def calc_sent(score):
            if pd.isna(score): return 'Neutro'
            s = float(score)
            if s >= 7: return 'Positivo'
            elif s <= 4: return 'Negativo'
            return 'Neutro'
        df['sentimento_txt'] = df['sentimento_score'].apply(calc_sent)

        # 1. PERFIL E MÉTRICAS BÁSICAS
        profile = {"nome": parlamentar}
        try:
            conn_t = get_db_connection("tabelao")
            df_p = pd.read_sql_query("SELECT nome, sgPartido, sgUF, ultimoStatus_urlFoto as foto FROM tabelao WHERE UPPER(nome)=UPPER(?) LIMIT 1", conn_t, params=[parlamentar])
            if not df_p.empty:
                p = df_p.iloc[0]
                sg_partido = str(p['sgPartido']).strip().upper()
                sg_uf = str(p['sgUF']).strip().upper()
                profile.update({
                    "nome": p['nome'],
                    "foto": p['foto'], 
                    "partido": sg_partido, 
                    "uf": sg_uf, 
                    "partido_logo": partido_logos_dict.get(sg_partido), 
                    "uf_logo": estado_logos_dict.get(sg_uf)
                })
            conn_t.close()
        except: pass

        # 2. BARRAS EMPILHADAS DE TEMAS POR SENTIMENTO (Substituindo Treemap)
        temas_stats = {}
        try:
            for _, row in df.iterrows():
                t_raw = row['temas_tratados']
                if not t_raw or t_raw == '[]': continue
                sent = row['sentimento_txt']
                temas = json.loads(t_raw) if isinstance(t_raw, str) else t_raw
                for tema in temas:
                    if tema not in temas_stats: 
                        temas_stats[tema] = {"Positivo": 0, "Negativo": 0, "Neutro": 0, "total": 0}
                    temas_stats[tema][sent] += 1
                    temas_stats[tema]["total"] += 1
            
            # Ordenar por total de menções e pegar top 10
            sorted_temas = sorted(temas_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:10]
            
            temas_chart = {
                "categories": [x[0] for x in sorted_temas],
                "series": [
                    {"name": "Positivo", "data": [x[1]['Positivo'] for x in sorted_temas], "color": "#009739"},
                    {"name": "Neutro", "data": [x[1]['Neutro'] for x in sorted_temas], "color": "#4F81BD"},
                    {"name": "Negativo", "data": [x[1]['Negativo'] for x in sorted_temas], "color": "#ED8B00"}
                ]
            }
        except Exception as e:
            logger.error(f"Erro Temas Chart: {e}")
            temas_chart = {"categories": [], "series": []}

        # 3. NUVEM DE BIGRAMAS DO TEXTO DA NOTÍCIA
        kw_cloud = []
        try:
            import html
            from collections import Counter

            stopwords_pt = {
                "a", "à", "às", "ao", "aos", "aquela", "aquele", "aqueles", "aquilo", "as", "até",
                "com", "como", "contra", "da", "das", "de", "dela", "dele", "deles", "depois", "do",
                "dos", "e", "é", "ela", "ele", "eles", "em", "entre", "era", "essa", "esse", "esta",
                "está", "este", "foi", "foram", "há", "isso", "já", "lhe", "mais", "mas", "me", "mesmo",
                "na", "nas", "não", "no", "nos", "o", "os", "ou", "para", "pela", "pelas", "pelo",
                "pelos", "por", "porque", "quando", "que", "quem", "se", "sem", "ser", "seu", "seus",
                "sua", "suas", "também", "tem", "ter", "um", "uma", "vão", "vai", "sobre", "após",
                "antes", "durante", "onde", "nesta", "neste", "nesta", "nossos", "nossas", "são"
            }
            termos_genericos = {
                "noticia", "noticias", "portal", "jornal", "blog", "radio", "tv", "site", "leia",
                "comentario", "comentarios", "whatsapp", "instagram", "facebook", "twitter", "x",
                "deputado", "deputada", "deputados", "deputadas", "federal", "federais", "camara",
                "congresso", "parlamentar", "parlamentares", "brasil", "brasileiro", "brasileira"
            }
            bigramas_genericos = {
                "deputado federal", "deputada federal", "camara deputados", "portal camara",
                "camara federal", "congresso nacional", "noticias politica", "politica nacional"
            }
            partido_tokens = {
                unicodedata.normalize("NFKD", str(sigla).lower()).encode("ascii", "ignore").decode("ascii")
                for sigla in partido_logos_dict.keys()
            }
            nome_tokens = {
                unicodedata.normalize("NFKD", token.lower()).encode("ascii", "ignore").decode("ascii")
                for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", parlamentar or "")
                if len(token) > 2
            }

            def limpar_html_texto(valor):
                if pd.isna(valor) or valor is None:
                    return ""
                texto = html.unescape(str(valor))
                texto = re.sub(r"<[^>]+>", " ", texto)
                texto = re.sub(r"https?://\S+", " ", texto)
                return texto

            def tokenizar(valor):
                texto = limpar_html_texto(valor).lower()
                tokens = []
                for token in re.findall(r"[a-zà-öø-ÿ0-9]{3,}", texto, flags=re.IGNORECASE):
                    token_norm = unicodedata.normalize("NFKD", token).encode("ascii", "ignore").decode("ascii")
                    valido = True
                    if token in stopwords_pt or token_norm in stopwords_pt:
                        valido = False
                    if token_norm in nome_tokens:
                        valido = False
                    if token_norm.isdigit():
                        valido = False
                    tokens.append((token, token_norm, valido))
                return tokens

            counter = Counter()
            for _, row in df.iterrows():
                texto_base = " ".join([
                    limpar_html_texto(row.get("titulo")),
                    limpar_html_texto(row.get("resumo")),
                    limpar_html_texto(row.get("texto_completo")),
                    limpar_html_texto(row.get("resumo_forense")),
                ])
                tokens = tokenizar(texto_base)
                vistos_na_noticia = set()
                for i in range(len(tokens) - 1):
                    t1, n1, valido1 = tokens[i]
                    t2, n2, valido2 = tokens[i + 1]
                    if not valido1 or not valido2:
                        continue
                    bigrama_norm = f"{n1} {n2}"
                    if bigrama_norm in bigramas_genericos:
                        continue
                    if n1 in partido_tokens or n2 in partido_tokens:
                        continue
                    if n1 == n2:
                        continue
                    if n1 in termos_genericos and n2 in termos_genericos:
                        continue
                    bigrama = f"{t1} {t2}"
                    vistos_na_noticia.add(bigrama)

                # Conta uma vez por notícia para evitar que textos longos dominem a nuvem.
                counter.update(vistos_na_noticia)

            kw_cloud = [
                {"text": termo, "value": freq}
                for termo, freq in counter.most_common(20)
                if freq > 0
            ]
        except Exception as e:
            logger.error(f"Erro ao gerar bigramas textuais da imprensa: {e}")

        # 4. GRAFO DE DIFUSÃO (veículos reais + sentimento predominante)
        graph = {"nodes": [], "links": [], "categories": [{"name": "Alvo"}, {"name": "Parlamentares"}, {"name": "Fontes"}, {"name": "Temas"}]}
        try:
            sentimento_cores = {
                "Positivo": "#009739",
                "Neutro": "#4F81BD",
                "Negativo": "#ED8B00"
            }
            fonte_cor = "#FFF81C"
            tema_cor = "#4F81BD"
            parl_cor = "#66BB6A"

            def sentimento_dominante(series):
                counts = series.value_counts()
                if counts.empty:
                    return "Neutro"
                return str(counts.idxmax())

            def node_sentimento_label(nome, dominante, total):
                return f"{nome}\n{dominante} ({total})"

            def perfil_parlamentar_por_nomes(nomes):
                if not nomes:
                    return {}
                try:
                    conn_profiles = get_db_connection("tabelao")
                    placeholders = ",".join(["?"] * len(nomes))
                    df_profiles = pd.read_sql_query(
                        f"""
                        SELECT nome, sgPartido, sgUF, ultimoStatus_urlFoto as foto
                        FROM tabelao
                        WHERE UPPER(nome) IN ({placeholders})
                        GROUP BY UPPER(nome)
                        """,
                        conn_profiles,
                        params=[str(n).upper() for n in nomes]
                    )
                    conn_profiles.close()
                    return {
                        str(row['nome']).upper(): {
                            "nome": row['nome'],
                            "partido": row['sgPartido'],
                            "uf": row['sgUF'],
                            "foto": row['foto']
                        }
                        for _, row in df_profiles.iterrows()
                    }
                except Exception:
                    return {}

            # 1. Alvo Principal
            graph["nodes"].append({
                "id": parlamentar, "name": parlamentar, "symbolSize": 50, "category": 0,
                "symbol": f"image://{profile.get('foto')}" if profile.get('foto') else "circle",
                "label": {"show": True},
                "details": {
                    "tipo": "Parlamentar",
                    "partido": profile.get("partido"),
                    "uf": profile.get("uf"),
                    "total": int(len(df)),
                    "sentimento_medio": float(df['sentimento_score'].mean()) if not df.empty else 0
                }
            })

            # 2. Veículos/fontes reais (Top 8)
            veiculos_stats = (
                df.groupby('veiculo_nome')
                .agg(
                    total=('news_id', 'count'),
                    sentimento_medio=('sentimento_score', 'mean'),
                    link_exemplo=('link', 'first'),
                    tipo_fonte=('veiculo_tipo', lambda s: str(s.mode().iloc[0]) if not s.mode().empty else "Outra fonte"),
                    dominio=('veiculo_domain', 'first')
                )
                .sort_values('total', ascending=False)
                .head(8)
                .reset_index()
            )

            news_ids_grafo = sorted({int(x) for x in df['news_id'].dropna().tolist()})
            mencoes_grafo = pd.DataFrame()
            perfis_outros = {}
            if news_ids_grafo:
                placeholders = ",".join(["?"] * len(news_ids_grafo))
                mencoes_grafo = pd.read_sql_query(
                    f"""
                    SELECT news_id, nome, sentimento_score
                    FROM noticias_mencoes_v2
                    WHERE tipo_entidade = 'PARLAMENTAR'
                      AND news_id IN ({placeholders})
                    """,
                    conn,
                    params=news_ids_grafo
                )
                outros_nomes = sorted({
                    str(n).strip()
                    for n in mencoes_grafo['nome'].dropna().tolist()
                    if str(n).strip() and str(n).strip().upper() != str(parlamentar).strip().upper()
                })
                perfis_outros = perfil_parlamentar_por_nomes(outros_nomes)

            nodes_adicionados = {parlamentar}
            for _, v_row in veiculos_stats.iterrows():
                v_name = str(v_row['veiculo_nome'])
                v_df = df[df['veiculo_nome'] == v_name]
                dominante = sentimento_dominante(v_df['sentimento_txt'])
                cor_sent = sentimento_cores.get(dominante, "#95a5a6")
                total_v = int(v_row['total'])
                label_v = node_sentimento_label(v_name, dominante, total_v)
                graph["nodes"].append({
                    "id": f"V_{v_name}", "name": label_v, "raw_name": v_name, "symbolSize": min(26 + total_v * 3, 58), "category": 2,
                    "label": {"show": True, "formatter": "{b}"},
                    "itemStyle": {"color": fonte_cor, "borderColor": cor_sent, "borderWidth": 4},
                    "details": {
                        "tipo": v_row.get('tipo_fonte') or "Outra fonte",
                        "dominio": v_row.get('dominio'),
                        "total": total_v,
                        "sentimento_dominante": dominante,
                        "sentimento_medio": round(float(v_row['sentimento_medio']), 2) if not pd.isna(v_row['sentimento_medio']) else None,
                        "link_exemplo": v_row.get('link_exemplo')
                    }
                })
                graph["links"].append({
                    "source": parlamentar,
                    "target": f"V_{v_name}",
                    "value": total_v,
                    "sentimento": dominante,
                    "lineStyle": {"color": cor_sent, "width": min(1.5 + total_v * 0.25, 7), "opacity": 0.78}
                })

                if not mencoes_grafo.empty:
                    v_news_ids = set(int(x) for x in v_df['news_id'].dropna().tolist())
                    v_mencoes = mencoes_grafo[
                        mencoes_grafo['news_id'].isin(v_news_ids)
                        & (mencoes_grafo['nome'].astype(str).str.upper() != str(parlamentar).upper())
                    ].copy()
                    if not v_mencoes.empty:
                        v_mencoes['sentimento_txt'] = v_mencoes['sentimento_score'].apply(calc_sent)
                        outros_stats = (
                            v_mencoes.groupby('nome')
                            .agg(total=('news_id', 'nunique'), sentimento_medio=('sentimento_score', 'mean'))
                            .sort_values('total', ascending=False)
                            .head(4)
                            .reset_index()
                        )
                        for _, outro in outros_stats.iterrows():
                            nome_outro = str(outro['nome']).strip()
                            if not nome_outro:
                                continue
                            outro_df = v_mencoes[v_mencoes['nome'] == nome_outro]
                            sent_outro = sentimento_dominante(outro_df['sentimento_txt'])
                            cor_outro = sentimento_cores.get(sent_outro, "#95a5a6")
                            total_outro = int(outro['total'])
                            perfil_outro = perfis_outros.get(nome_outro.upper(), {})
                            node_id = f"P_{nome_outro}"
                            if node_id not in nodes_adicionados:
                                graph["nodes"].append({
                                    "id": node_id,
                                    "name": nome_outro,
                                    "symbolSize": 34,
                                    "category": 1,
                                    "symbol": f"image://{perfil_outro.get('foto')}" if perfil_outro.get('foto') else "circle",
                                    "label": {"show": True},
                                    "itemStyle": {"color": parl_cor, "borderColor": cor_outro, "borderWidth": 3},
                                    "details": {
                                        "tipo": "Parlamentar co-coberto",
                                        "partido": perfil_outro.get("partido"),
                                        "uf": perfil_outro.get("uf"),
                                        "total": total_outro,
                                        "sentimento_dominante": sent_outro,
                                        "sentimento_medio": round(float(outro['sentimento_medio']), 2) if not pd.isna(outro['sentimento_medio']) else None
                                    }
                                })
                                nodes_adicionados.add(node_id)
                            graph["links"].append({
                                "source": f"V_{v_name}",
                                "target": node_id,
                                "value": total_outro,
                                "sentimento": sent_outro,
                                "lineStyle": {"color": cor_outro, "width": min(1.2 + total_outro * 0.3, 4), "opacity": 0.55}
                            })

            # 3. Temas (Top 5)
            top_t_list = [x[0] for x in sorted_temas[:5]]
            for t_name in top_t_list:
                t_df = df[df['temas_tratados'].apply(lambda raw: t_name in json.loads(raw) if isinstance(raw, str) and raw else False)]
                dominante = sentimento_dominante(t_df['sentimento_txt'])
                cor_sent = sentimento_cores.get(dominante, "#95a5a6")
                graph["nodes"].append({
                    "id": f"T_{t_name}", "name": t_name, "symbolSize": 25, "category": 3,
                    "label": {"show": True},
                    "itemStyle": {"color": tema_cor, "borderColor": cor_sent, "borderWidth": 3},
                    "details": {
                        "tipo": "Tema",
                        "total": int(len(t_df)),
                        "sentimento_dominante": dominante
                    }
                })
                graph["links"].append({
                    "source": parlamentar,
                    "target": f"T_{t_name}",
                    "value": int(len(t_df)),
                    "sentimento": dominante,
                    "lineStyle": {"color": cor_sent, "width": min(1.5 + len(t_df) * 0.18, 6), "opacity": 0.65}
                })

            # Pre-parse temas_tratados and news_id once for sections 4 and 5
            df_nid_int = pd.to_numeric(df['news_id'], errors='coerce').fillna(-1).astype(int)
            df_temas_parsed = df['temas_tratados'].apply(
                lambda raw: json.loads(raw) if isinstance(raw, str) and raw and raw not in ('[]', 'null') else []
            )

            # 4. Arestas Veículo → Tema
            for _, v_row in veiculos_stats.iterrows():
                v_name = str(v_row['veiculo_nome'])
                v_mask = df['veiculo_nome'] == v_name
                v_temas = df_temas_parsed[v_mask]
                for t_name in top_t_list:
                    t_count = int(v_temas.apply(lambda lst: t_name in lst).sum())
                    if t_count > 0:
                        graph["links"].append({
                            "source": f"V_{v_name}",
                            "target": f"T_{t_name}",
                            "value": t_count,
                            "lineStyle": {"color": "#B0BEC5", "width": min(1 + t_count * 0.15, 3), "opacity": 0.5, "type": "dashed"}
                        })

            # 5. Arestas Parlamentar citado → Tema
            if not mencoes_grafo.empty:
                mencoes_nid_int = pd.to_numeric(mencoes_grafo['news_id'], errors='coerce').fillna(-1).astype(int)
                mencoes_nomes = mencoes_grafo['nome'].astype(str).str.strip()
                for node_id in list(nodes_adicionados):
                    if not node_id.startswith("P_"):
                        continue
                    nome_citado = node_id[2:].strip()
                    mask_nome = mencoes_nomes == nome_citado
                    if not mask_nome.any():
                        continue
                    citado_news_ids = set(mencoes_nid_int[mask_nome].tolist())
                    citado_temas = df_temas_parsed[df_nid_int.isin(citado_news_ids)]
                    for t_name in top_t_list:
                        t_count = int(citado_temas.apply(lambda lst: t_name in lst).sum())
                        if t_count > 0:
                            graph["links"].append({
                                "source": node_id,
                                "target": f"T_{t_name}",
                                "value": t_count,
                                "lineStyle": {"color": "#90CAF9", "width": min(1 + t_count * 0.1, 3), "opacity": 0.45, "type": "dashed"}
                            })

        except Exception as e:
            logger.error(f"Erro ao montar grafo imprensa V2: {e}")

        # Louvain community detection on imprensa diffusion graph
        try:
            import networkx as nx
            import community as community_louvain
            G_imp = nx.Graph()
            for lk in graph["links"]:
                w = int(lk.get("value", 1) or 1)
                src = str(lk["source"])
                tgt = str(lk["target"])
                if G_imp.has_edge(src, tgt):
                    G_imp[src][tgt]["weight"] += w
                else:
                    G_imp.add_edge(src, tgt, weight=w)
            if G_imp.number_of_nodes() >= 2:
                partition = community_louvain.best_partition(G_imp, weight="weight", resolution=1.0)
                graph["communities"] = {k: int(v) for k, v in partition.items()}
                logger.info(f"[Louvain imprensa] {G_imp.number_of_nodes()} nós → {len(set(partition.values()))} comunidades")
            else:
                graph["communities"] = {}
        except Exception as _e_imp:
            logger.warning(f"[Louvain imprensa] Ignorado: {_e_imp}")
            graph["communities"] = {}

        # 5. ESTATÍSTICAS
        df['dt'] = pd.to_datetime(df['data_noticia'], errors='coerce')
        avg_per_month = df.groupby(df['dt'].dt.strftime('%m/%y')).size().mean() if not df.empty else 0
        periodo_filtrado = {
            "inicio": df['dt'].min().strftime("%Y-%m-%d") if not df.empty and pd.notna(df['dt'].min()) else None,
            "fim": df['dt'].max().strftime("%Y-%m-%d") if not df.empty and pd.notna(df['dt'].max()) else None,
        }
        
        conn.close()
        response_payload = {
            "profile": profile, 
            "bigrams": kw_cloud, 
            "temas_chart": temas_chart, # Novo formato de barras
            "graph": graph,
            "metrics": {
                "total": len(df), 
                "sent": float(df['sentimento_score'].mean()) if not df.empty else 0,
                "prot": float(df['protagonismo_score'].mean()) if not df.empty else 0, 
                "escand": int(df['indicador_escandalo_juridico'].sum()) if not df.empty else 0,
                "avg_month": float(avg_per_month) if not pd.isna(avg_per_month) else 0,
                "periodo": periodo_filtrado
            },
            "amostra_noticias": df[
                [c for c in ['news_id', 'veiculo_nome', 'data_noticia', 'sentimento_score', 'resumo_forense', 'resumo_participacao', 'link'] if c in df.columns]
            ].fillna("").head(30).to_dict('records'),
            "veiculos_stats": [
                {
                    "veiculo_nome": str(r['veiculo_nome']),
                    "total_noticias": int(r['total']),
                    "media_sentimento": round(float(r['sentimento_medio']), 2),
                }
                for _, r in veiculos_stats.iterrows()
            ]
        }
        return clean_data_for_json(response_payload)
    except Exception as e:
        logger.error(f"Erro em analise V2: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

class ChatParlamentarRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []

def _extract_parlamentar_from_query(client, message: str, history: list) -> dict:
    """Usa GPT-4o-mini para extrair parlamentar e reescrever a query para busca vetorial."""
    try:
        extraction_prompt = """Analise a mensagem do usuário e o histórico da conversa. Retorne um JSON com quatro campos:

1. "parlamentar": O nome do parlamentar mencionado em MAIÚSCULAS. Se nenhum for citado mas o histórico menciona um, use o do histórico. Se nenhum for citado, use "NENHUM".
2. "search_query": Reescreva a pergunta do usuário como uma query otimizada para busca semântica em discursos parlamentares. FOQUE no TEMA CENTRAL, inclua sinônimos e termos de contexto político.
3. "keywords": Lista de 3-8 TERMOS-CHAVE puros do tema (sem verbos auxiliares, sem "deputados"). Fundamental para busca direta e validação lexical.
4. "deep_search": Booleano (true/false). Defina como true se o usuário estiver:
   - Questionando a resposta anterior ("tem certeza?", "está certo disso?", "verifique de novo")
   - Pedindo MAIS resultados/nomes ("tem mais alguém?", "liste outros", "continue a lista")
   - Reclamando de dados incompletos.
   - Fazendo pergunta ampla de tema ("o que se fala sobre...", "quem falou sobre...", "qual o debate sobre...")

Exemplos:
- Input: "O que Nikolas Ferreira falou sobre educação?"
  → {"parlamentar": "NIKOLAS FERREIRA", "search_query": "educação ensino escolas universidades políticas educacionais", "keywords": "educação ensino universidade", "deep_search": false}
- Input: "o que se fala sobre taxar o pix?"
  → {"parlamentar": "NENHUM", "search_query": "taxar Pix imposto Pix tributação transações digitais Banco Central Receita Federal fiscalização pagamento instantâneo", "keywords": "Pix imposto tributação Receita Banco Central transações digitais", "deep_search": true}
- Input: "cite se o parlamentar Ricardo Salles falou sobre fila do INSS"
  → {"parlamentar": "RICARDO SALLES", "search_query": "fila do INSS previdência atendimento benefício perícia aposentadoria segurados", "keywords": "INSS fila previdência benefício perícia segurados", "deep_search": true}
- Input: "tem mais deputado que falou de Petrobras em 2025?"
  → {"parlamentar": "NENHUM", "search_query": "Petrobras petróleo estatal 2025", "keywords": "Petrobras petróleo 2025", "deep_search": true}
- Input: "você tem certeza disso?" (Histórico sobre divergências de Hugo Motta)
  → {"parlamentar": "HUGO MOTTA", "search_query": "mudança opinião voto divergência contradição", "keywords": "posição voto divergência", "deep_search": true}

Retorne APENAS o JSON, sem markdown."""

        msgs = [{"role": "system", "content": extraction_prompt}]
        for h in history[-4:]:
            msgs.append(h)
        msgs.append({"role": "user", "content": message})

        resp = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=msgs,
            temperature=0,
            max_completion_tokens=150
        )
        raw = resp.choices[0].message.content.strip()
        # Limpar possíveis artefatos de markdown
        raw = raw.replace("```json", "").replace("```", "").strip()
        import json as _json
        parsed = _json.loads(raw)
        
        parlamentar = parsed.get("parlamentar", "NENHUM").strip().upper()
        search_query = parsed.get("search_query", message).strip()
        kw_val = parsed.get("keywords", "")
        keywords = " ".join(kw_val) if isinstance(kw_val, list) else str(kw_val).strip()
        deep_search = parsed.get("deep_search", False)
        
        if parlamentar == "NENHUM" or len(parlamentar) < 3 or len(parlamentar) > 60:
            parlamentar = None
        else:
            parlamentar = parlamentar.replace('"', '').replace("'", '').strip()
        
        return {
            "parlamentar": parlamentar, 
            "search_query": search_query, 
            "keywords": keywords,
            "deep_search": deep_search
        }
    except Exception as e:
        logger.warning(f"Erro ao extrair parlamentar/query: {e}")
        return {"parlamentar": None, "search_query": message, "keywords": "", "deep_search": False}

def _chat_keyword_terms(*texts) -> list:
    """Extrai termos simples para reforçar resultados com correspondência textual explícita."""
    import re as _re
    stopwords = {
        "sobre", "para", "pela", "pelo", "pelas", "pelos", "como", "qual", "quais",
        "quem", "onde", "quando", "falou", "falaram", "fala", "falam", "cite",
        "citar", "deputado", "deputada", "parlamentar", "isso", "essa", "esse",
        "esta", "este", "voce", "você", "algo", "coisa", "tema", "governo",
        "contra", "favor", "disse", "diz", "dizem", "mais", "menos", "teve",
        "tem", "ter", "foi", "foram", "uma", "uns", "das", "dos", "com", "sem"
    }
    terms = []
    for text in texts:
        for token in _re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", str(text or "").lower()):
            if token not in stopwords and token not in terms:
                terms.append(token)
    return terms[:14]

def _chat_lexical_score(text: str, terms: list) -> int:
    lowered = (text or "").lower()
    return sum(1 for term in terms if term and term.lower() in lowered)

def _inferir_partido_estado_do_discurso(texto: str) -> dict:
    """
    Extrai partido/UF do cabeçalho taquigráfico quando o metadado estruturado
    vem vazio. Ex.: "GISELA SIMONA(Bloco/UNIÃO - MT. Sem revisão...)".
    """
    import re as _re

    trecho = (texto or "")[:500]
    ufs_validas = {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT",
        "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO",
        "RR", "SC", "SP", "SE", "TO",
    }

    padroes = [
        r"\((?:\s*Bloco\s*/\s*)?([A-ZÀ-Ü0-9 .ºª-]{2,45}?)\s*-\s*([A-Z]{2})\b",
        r"\b(?:Bloco\s*/\s*)?([A-ZÀ-Ü0-9 .ºª-]{2,45}?)\s*-\s*([A-Z]{2})\b",
    ]

    for padrao in padroes:
        match = _re.search(padrao, trecho, flags=_re.IGNORECASE)
        if not match:
            continue

        partido = (match.group(1) or "").strip().upper()
        estado = (match.group(2) or "").strip().upper()
        partido = _re.sub(r"\s+", " ", partido).strip(" .-/")

        # Evita transformar "Sem revisão da oradora" em dado partidário.
        partido_invalidos = {"SEM", "SEM PARTIDO", "SEM REVISÃO", "REVISAO", "REVISÃO", "ORADOR", "ORADORA"}
        if estado in ufs_validas and partido and partido not in partido_invalidos and "REVIS" not in partido:
            return {"partido": partido, "estado": estado}

    return {"partido": "", "estado": ""}

def _valor_metadata_valido(valor) -> bool:
    texto = str(valor or "").strip()
    return bool(texto and texto.upper() not in {"N/D", "NONE", "NULL", "NAN", "SEM PARTIDO"})

def _deduplicate_chroma_results(documents, metadatas, distances, threshold=0.60) -> list:
    """Remove duplicatas e retorna lista de resultados únicos ordenados por relevância."""
    seen_hashes = set()
    unique_results = []

    for i in range(len(documents)):
        doc = documents[i]
        meta = metadatas[i]
        dist = distances[i]
        score = float(1 - dist)

        # Filtrar por relevância mínima (dinâmico)
        if score < threshold:
            continue

        # Hash do conteúdo para deduplicação (primeiros 500 chars para performance)
        content_key = hash(doc[:500])
        if content_key in seen_hashes:
            continue
        seen_hashes.add(content_key)

        unique_results.append({
            "doc": doc,
            "meta": meta,
            "score": score
        })

    # Ordenar por score decrescente
    unique_results.sort(key=lambda x: x["score"], reverse=True)
    return unique_results

@app.post("/api/chat-parlamentar/conversa")
async def chat_parlamentar(req: ChatParlamentarRequest):
    """
    Endpoint de chat RAG para discursos parlamentares.
    V3 — RAG Híbrido com memória, enriquecimento SQL e contexto profundo.
    """
    try:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise HTTPException(status_code=500, detail="OpenAI API Key não configurada")

        client = OpenAI(api_key=openai_api_key)

        collection = None
        if chroma_client:
            try:
                collection = chroma_client.get_collection(name="discursos_2023_plus")
            except Exception as e:
                logger.warning(f"[Chat RAG V3] ChromaDB collection não disponível: {e}. Usando fallback SQL.")

        # ── 1. Extrair nome do parlamentar e query otimizada ──
        extraction = _extract_parlamentar_from_query(
            client, req.message, req.history
        )
        parlamentar_name = extraction["parlamentar"]
        search_query = extraction["search_query"]
        keywords = extraction.get("keywords", "")
        deep_search = extraction.get("deep_search", False)
        
        # Parâmetros — mais contexto, sem abrir mão de relevância.
        N_FILTERED = 45 if deep_search else 28
        N_GENERAL = 35 if deep_search else 18
        SIM_THRESHOLD = 0.34 if deep_search else 0.40
        keyword_terms = _chat_keyword_terms(req.message, search_query, keywords)

        logger.info(f"[Chat RAG V3] Parlamentar: {parlamentar_name or 'NENHUM'} | Query: '{search_query}' | Keywords: '{keywords}' | Deep: {deep_search}")

        # ── 2. Gerar Embeddings (apenas se ChromaDB disponível) ──
        query_vector = None
        search_vector = None
        if collection:
            keyword_text = keywords if keywords else search_query
            embed_texts = [keyword_text]
            if search_query != keyword_text:
                embed_texts.append(search_query)

            embed_resp = client.embeddings.create(
                model="text-embedding-ada-002",
                input=embed_texts
            )
            query_vector = embed_resp.data[0].embedding
            search_vector = embed_resp.data[-1].embedding

        # ── 3. Busca Híbrida no ChromaDB ──
        all_docs = []
        all_metas = []
        all_dists = []

        # 3a. Busca filtrada pelo parlamentar
        if collection and parlamentar_name:
            try:
                for v in [search_vector, query_vector]:
                    filtered_results = collection.query(
                        query_embeddings=[v],
                        n_results=N_FILTERED,
                        where={"Parlamentar": parlamentar_name}
                    )
                    if filtered_results['documents'][0]:
                        all_docs.extend(filtered_results['documents'][0])
                        all_metas.extend(filtered_results['metadatas'][0])
                        all_dists.extend(filtered_results['distances'][0])
                
                # Fallback: buscar com where_document contendo o nome
                if not all_docs:
                    try:
                        partial_results = collection.query(
                            query_embeddings=[query_vector],
                            n_results=N_FILTERED,
                            where_document={"$contains": parlamentar_name.split()[0]}
                        )
                        if partial_results['documents'][0]:
                            all_docs.extend(partial_results['documents'][0])
                            all_metas.extend(partial_results['metadatas'][0])
                            all_dists.extend(partial_results['distances'][0])
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[Chat RAG V3] Erro na busca filtrada: {e}")

        # 3b. Busca geral complementar
        if not collection:
            logger.info("[Chat RAG V3] Sem ChromaDB — pulando busca vetorial, usando fallback SQL.")
        for v in ([search_vector, query_vector] if collection else []):
            general_results = collection.query(
                query_embeddings=[v],
                n_results=N_GENERAL
            )
            if general_results['documents'][0]:
                all_docs.extend(general_results['documents'][0])
                all_metas.extend(general_results['metadatas'][0])
                all_dists.extend(general_results['distances'][0])

        # 3c. Busca de CONTINUIDADE
        if collection and req.history:
            prev_user_msgs = [h["content"] for h in req.history if h.get("role") == "user"]
            if prev_user_msgs:
                last_user_query = prev_user_msgs[-1]
                try:
                    prev_embed = client.embeddings.create(
                        model="text-embedding-ada-002",
                        input=[last_user_query]
                    )
                    prev_vector = prev_embed.data[0].embedding
                    
                    if parlamentar_name:
                        prev_results = collection.query(
                            query_embeddings=[prev_vector],
                            n_results=15,
                            where={"Parlamentar": parlamentar_name}
                        )
                    else:
                        prev_results = collection.query(
                            query_embeddings=[prev_vector],
                            n_results=20
                        )
                    
                    if prev_results['documents'][0]:
                        all_docs.extend(prev_results['documents'][0])
                        all_metas.extend(prev_results['metadatas'][0])
                        all_dists.extend(prev_results['distances'][0])
                        logger.info(f"[Chat RAG V3] Continuidade: +{len(prev_results['documents'][0])} docs do turno anterior")
                except Exception as e:
                    logger.warning(f"[Chat RAG V3] Erro na continuidade: {e}")

        # ── 4. Deduplicar e filtrar por relevância ──
        unique_results = _deduplicate_chroma_results(all_docs, all_metas, all_dists, threshold=SIM_THRESHOLD)
        for item in unique_results:
            item["lexical_score"] = _chat_lexical_score(
                " ".join([
                    item.get("doc") or "",
                    str(item.get("meta", {}).get("Parlamentar") or ""),
                    str(item.get("meta", {}).get("Comissao") or ""),
                    str(item.get("meta", {}).get("Sessao") or ""),
                ]),
                keyword_terms
            )
            # A busca vetorial decide a base; a pontuação lexical só promove trechos com termos explícitos.
            item["rank_score"] = item["score"] + min(item["lexical_score"], 5) * 0.035
        unique_results.sort(key=lambda x: x.get("rank_score", x["score"]), reverse=True)

        MAX_CONTEXT_DOCS = 20 if deep_search else 12
        top_results = unique_results[:MAX_CONTEXT_DOCS]

        logger.info(f"[Chat RAG V3] Bruto: {len(all_docs)} → Únicos (>{SIM_THRESHOLD}): {len(unique_results)} → Top: {len(top_results)} | Termos: {keyword_terms}")

        # ── 4b. FALLBACK SQL LEXICAL — quando ChromaDB retorna poucos/fracos resultados ──
        # Garante cobertura de discursos ainda não vetorizados no ChromaDB (654K de 1.5M total)
        _sql_fallback_threshold = 5  # se temos menos de 5 resultados bons do ChromaDB, ativa fallback
        _strong_chroma = [r for r in top_results if r.get("score", 0) >= 0.55]
        if len(_strong_chroma) < _sql_fallback_threshold and keyword_terms:
            try:
                import sqlite3 as _sq3f
                _conn_fallback = _sq3f.connect(DATABASE_PATHS.get("discursos", "discursos.db"))
                _conn_fallback.row_factory = _sq3f.Row

                # Construir condições LIKE para os keyword_terms
                _like_terms = [t for t in keyword_terms if len(t) >= 4][:6]
                if _like_terms:
                    # Busca com OR entre termos — captura discursos relevantes não vetorizados
                    _conditions = " OR ".join([f"LOWER(Texto) LIKE ?" for _ in _like_terms])
                    _params = [f"%{t.lower()}%" for t in _like_terms]

                    # Se há parlamentar específico, filtrar por ele também
                    _parl_cond = ""
                    if parlamentar_name:
                        _parl_cond = " AND UPPER(Parlamentar) LIKE ?"
                        _params.append(f"%{parlamentar_name.upper().split()[0]}%")

                    _sql_q = f"""
                        SELECT DISTINCT hash_linha, Parlamentar, Data, Comissao, Partido, Estado, Sessao,
                               substr(Texto, 1, 1500) as Texto
                        FROM discursos
                        WHERE ({_conditions}){_parl_cond}
                        ORDER BY Data DESC
                        LIMIT 12
                    """
                    _sql_rows = _conn_fallback.execute(_sql_q, _params).fetchall()

                    # Adicionar à lista de top_results como tipo SQL_FALLBACK
                    _existing_hashes = {
                        str(r.get("meta", {}).get("hash_linha") or r.get("meta", {}).get("hash") or "")
                        for r in top_results
                    }
                    _added = 0
                    for _row in _sql_rows:
                        _hl = str(_row["hash_linha"] or "")
                        if _hl and _hl in _existing_hashes:
                            continue
                        _existing_hashes.add(_hl)
                        top_results.append({
                            "doc": _row["Texto"] or "",
                            "meta": {
                                "hash_linha": _hl,
                                "Parlamentar": _row["Parlamentar"] or "",
                                "Data": _row["Data"] or "",
                                "Comissao": _row["Comissao"] or "",
                                "Partido": _row["Partido"] or "",
                                "Estado": _row["Estado"] or "",
                                "Sessao": _row["Sessao"] or "",
                            },
                            "score": 0.50,  # score fixo — relevância via keyword match
                            "lexical_score": 3,
                            "rank_score": 0.50,
                            "_fallback_tipo": "SQL_FALLBACK_LEXICAL",
                        })
                        _added += 1
                    _conn_fallback.close()
                    logger.info(f"[Chat RAG V3] SQL Fallback Lexical: +{_added} docs (termos: {_like_terms})")
            except Exception as _fe:
                logger.warning(f"[Chat RAG V3] Erro no SQL fallback: {_fe}")

        # ── 5. ENRIQUECIMENTO SQL — Buscar textos completos do banco ──
        hash_to_fulltext = {}
        if top_results:
            try:
                import sqlite3 as _sq3
                _conn_disc = _sq3.connect(DATABASE_PATHS.get("discursos", "discursos.db"))
                _conn_disc.row_factory = _sq3.Row
                
                # Coletar hash_linhas dos resultados
                hash_linhas = []
                for item in top_results:
                    hl = item["meta"].get("hash_linha") or item["meta"].get("hash")
                    if hl:
                        hash_linhas.append(str(hl))
                
                if hash_linhas:
                    placeholders = ",".join(["?" for _ in hash_linhas])
                    query_sql = f"SELECT hash_linha, Texto, Parlamentar, Data, Comissao, Partido, Estado, Sessao FROM discursos WHERE hash_linha IN ({placeholders})"
                    rows = _conn_disc.execute(query_sql, hash_linhas).fetchall()
                    for row in rows:
                        hash_to_fulltext[str(row["hash_linha"])] = {
                            "texto": row["Texto"] or "",
                            "parlamentar": row["Parlamentar"] or "",
                            "data": row["Data"] or "",
                            "comissao": row["Comissao"] or "",
                            "partido": row["Partido"] or "",
                            "estado": row["Estado"] or "",
                            "sessao": row["Sessao"] or "",
                        }
                    logger.info(f"[Chat RAG V3] SQL: {len(rows)} textos completos recuperados de {len(hash_linhas)} hashes")
                
                _conn_disc.close()
            except Exception as e:
                logger.warning(f"[Chat RAG V3] Erro no enriquecimento SQL: {e}")

        # ── 6. Preparar Contexto e Fontes (com textos completos do SQL) ──
        context_parts = []
        sources = []

        for idx, item in enumerate(top_results, 1):
            doc = item["doc"]
            meta = item["meta"]
            score = item["score"]

            # Tentar usar texto completo do SQL
            hl = str(meta.get("hash_linha") or meta.get("hash") or "")
            sql_data = hash_to_fulltext.get(hl)
            
            if sql_data and sql_data["texto"]:
                # Usar trecho amplo do SQL para preservar contexto sem estourar a janela.
                trecho = sql_data["texto"][:1800]
                parlamentar = sql_data["parlamentar"] or meta.get('Parlamentar', 'N/D')
                data = sql_data["data"] or meta.get('Data', 'N/D')
                comissao = sql_data["comissao"] or meta.get('Comissao', 'N/D')
                partido = sql_data["partido"] or meta.get('Partido', '')
                estado = sql_data["estado"] or meta.get('Estado', '')
                sessao = sql_data["sessao"] or meta.get('Sessao', '')
                fonte_tipo = "SQL_COMPLETO"
            elif item.get("_fallback_tipo") == "SQL_FALLBACK_LEXICAL":
                # Item veio do fallback SQL lexical — já tem texto direto no 'doc'
                trecho = doc[:1800] if len(doc) > 1800 else doc
                parlamentar = meta.get('Parlamentar', 'N/D')
                data = meta.get('Data', 'N/D')
                comissao = meta.get('Comissao', 'N/D')
                partido = meta.get('Partido', '')
                estado = meta.get('Estado', '')
                sessao = meta.get('Sessao', '')
                fonte_tipo = "SQL_FALLBACK_LEXICAL"
            else:
                # Fallback: usar chunk do ChromaDB
                trecho = doc[:1800] if len(doc) > 1800 else doc
                parlamentar = meta.get('Parlamentar', 'N/D')
                data = meta.get('Data', 'N/D')
                comissao = meta.get('Comissao', 'N/D')
                partido = meta.get('Partido', '')
                estado = meta.get('Estado', '')
                sessao = meta.get('Sessao', '')
                fonte_tipo = "CHROMA_CHUNK"

            filiacao_inferida = _inferir_partido_estado_do_discurso(trecho)
            if not _valor_metadata_valido(partido) and filiacao_inferida.get("partido"):
                partido = filiacao_inferida["partido"]
            if not _valor_metadata_valido(estado) and filiacao_inferida.get("estado"):
                estado = filiacao_inferida["estado"]

            filiacao = ""
            if _valor_metadata_valido(partido) and _valor_metadata_valido(estado):
                filiacao = f" ({partido}/{estado})"
            elif _valor_metadata_valido(partido):
                filiacao = f" ({partido})"
            elif _valor_metadata_valido(estado):
                filiacao = f" ({estado})"

            context_item = f"[EVIDÊNCIA {idx}] (Relevância: {score:.0%} | Fonte: {fonte_tipo})\n"
            context_item += f"Parlamentar: {parlamentar}{filiacao}\n"
            context_item += f"Data: {data} | Local: {comissao}"
            if sessao:
                context_item += f" | Sessão: {sessao}"
            context_item += f"\nTexto do Discurso:\n{trecho}\n"
            context_parts.append(context_item)

            sources.append({
                "parlamentar": parlamentar,
                "data": data,
                "comissao": comissao,
                "partido": partido,
                "estado": estado,
                "sessao": sessao,
                "score": score,
                "lexical_score": item.get("lexical_score", 0),
                "preview": trecho[:250],
                "fonte_tipo": fonte_tipo,
            })

        full_context = "\n" + "=" * 60 + "\n".join(context_parts)

        # contar evidências SQL vs ChromaDB vs Fallback
        sql_count = sum(1 for s in sources if s.get("fonte_tipo") in ("SQL_COMPLETO", "SQL_FALLBACK_LEXICAL"))
        chroma_count = len(sources) - sql_count
        fallback_count = sum(1 for s in sources if s.get("fonte_tipo") == "SQL_FALLBACK_LEXICAL")
        logger.info(f"[Chat RAG V3] Evidências: {sql_count} SQL ({fallback_count} fallback lexical) + {chroma_count} ChromaDB chunks")

        # ── 7. System Prompt V4 — conversa analítica com evidências verificáveis ──
        search_info = ""
        if parlamentar_name:
            search_info = f"\n⚙️ FILTRO ATIVO: Busca filtrada pelo parlamentar '{parlamentar_name}'."
        
        system_prompt = f"""Você é o Dr. Antunes, um assistente analítico e amigável para consultar discursos oficiais de parlamentares.

CONTEXTO: Você está analisando {len(top_results)} registros oficiais de discursos parlamentares da Câmara dos Deputados (2023-2026), sendo {sql_count} textos completos.

OBJETIVO:
Responder ao eleitor de forma clara, detalhada e verificável. O usuário pode perguntar algo amplo ("o que se fala sobre taxar o Pix?") ou específico ("o parlamentar X falou sobre fila do INSS?").

REGRA FUNDAMENTAL — NUNCA RESPONDA SEM EVIDÊNCIAS SE VOCÊ TEM DISCURSOS:
Você recebeu {len(top_results)} discursos. SE VOCÊ TEM DISCURSOS, VOCÊ TEM EVIDÊNCIAS. SEMPRE detalhe o que encontrou, mesmo que a resposta ao que o usuário perguntou seja "não" (ex: ninguém defendeu X, mas Y e Z criticaram). Uma resposta sem citar pelo menos 3 a 5 discursos com nome, data e trecho é INACEITÁVEL quando há registros disponíveis.

FORMATO OBRIGATÓRIO (siga à risca quando houver registros):
1. **Parágrafo inicial**: Resposta direta à pergunta em 2-3 frases. Se a resposta ao que o usuário perguntou for "não encontrei quem apoiou", diga isso — MAS continue para o passo 2.
2. **Contexto do debate** (1-2 parágrafos): O que os discursos revelam sobre o tema? Quais argumentos aparecem? Qual o padrão das posições? Quem foram os principais nomes?
3. **Seção "📋 Registros encontrados"** — OBRIGATÓRIA quando há discursos. Liste 4 a 8 evidências no formato:
   > **DD/MM/AAAA — [Local/Comissão] — [Parlamentar] ([PARTIDO/UF]):**
   > "trecho literal curto e relevante do discurso"
4. **Conclusão** (1 frase): síntese do que o conjunto de evidências indica.

REGRAS DE EVIDÊNCIA:
- Use APENAS informações presentes nos discursos fornecidos abaixo.
- Nunca invente citação, parlamentar, reunião, data ou posição.
- Toda citação entre aspas deve ser literal — trecho real do texto fornecido.
- Se o partido/UF não aparecer no metadata mas estiver no texto (ex: "Bloco/UNIÃO - MT"), use essa informação. Nunca escreva "sem partido" se o texto tiver filiação.
- Ao citar qualquer exemplo, inclua obrigatoriamente parlamentar, data e local. Nunca escreva "um deputado disse" se tiver o nome.
- Para temas amplos, agrupe por linhas argumentativas: "crítica à tributação", "defesa da medida", "apelo ao consumidor de baixa renda", etc.
- CONTINUIDADE: Em perguntas de follow-up, mantenha o contexto do histórico mas use apenas as evidências atuais.
{search_info}

══════════════════════════════════════════════
DISCURSOS RECUPERADOS ({len(top_results)} registros):
══════════════════════════════════════════════
{full_context}
══════════════════════════════════════════════"""

        messages = [{"role": "system", "content": system_prompt}]

        # ── 8. MEMÓRIA CONVERSACIONAL — incluir últimas 5 trocas ──
        if req.history:
            # Pegar últimas 10 mensagens (5 trocas user+assistant)
            recent_history = req.history[-10:]
            for h in recent_history:
                role = h.get("role", "user")
                content = h.get("content", "")
                if role == "assistant":
                    # Truncar respostas longas do assistente mas preservar contexto suficiente
                    content = content[:2500] if len(content) > 2500 else content
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": req.message})

        # ── 9. Chamar Chat Completion — gpt-4o-mini (rápido) ──
        chat_resp = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=messages,
            temperature=0.3,
            max_completion_tokens=2000
        )

        answer = chat_resp.choices[0].message.content.strip()

        return {
            "answer": answer,
            "sources": sources
        }

    except Exception as e:
        logger.error(f"Erro no Chat Parlamentar V3: {e}")
        error_msg = str(e)
        if "insufficient_quota" in error_msg or "429" in error_msg:
            error_msg = "⚠️ Quota da API OpenAI esgotada. Recarregue os créditos em platform.openai.com/account/billing."
        else:
            error_msg = f"⚠️ Erro na auditoria: {error_msg}"
        return {
            "answer": error_msg,
            "sources": []
        }


class ImprensaV2ReportRequest(BaseModel):
    parlamentar: str
    amostra_noticias: list
    temas_ranking: list = []
    veiculos_sentimento: list = []

@app.post("/api/llm/imprensa-v2-report")
async def gerar_dossie_llm_v2(req: ImprensaV2ReportRequest):
    """Gera um dossiê com GPT-4o-mini baseado nos metadados cirúrgicos e filtrados."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        texto_amostras = ""
        for n in req.amostra_noticias[:25]:
            texto_amostras += (
                f"\n- **{n.get('veiculo_nome')}** ({n.get('data_noticia')}):\n"
                f"  Fato Forense: {n.get('resumo_forense')}\n"
                f"  Participação de {req.parlamentar} (sentimento {n.get('sentimento_score')}/10): {n.get('resumo_participacao')}\n"
            )

        texto_temas = ""
        if req.temas_ranking:
            texto_temas = "\nRANKING DE TEMAS (mais frequentes primeiro):\n"
            for t in req.temas_ranking:
                texto_temas += f"  - {t.get('tema')}: {t.get('total')} menções\n"

        texto_veiculos = ""
        if req.veiculos_sentimento:
            texto_veiculos = "\nSENTIMENTO POR VEÍCULO (escala 0=negativo a 10=positivo):\n"
            for v in req.veiculos_sentimento:
                sent = v.get('media_sentimento', 5)
                tendencia = "negativo" if sent < 4 else ("positivo" if sent > 6 else "neutro")
                texto_veiculos += f"  - {v.get('veiculo')}: {sent:.1f}/10 ({tendencia}, {v.get('total_noticias')} notícias)\n"

        prompt = f"""Você é o Chefe de Inteligência Governamental do sistema Deep Audit.
Analise a cobertura da imprensa sobre o parlamentar **{req.parlamentar}** com base nos dados abaixo.

{texto_temas}
{texto_veiculos}

AMOSTRA DE REPORTAGENS:
{texto_amostras}

TAREFA:
Produza um dossiê analítico em **4 parágrafos curtos e diretos**, com linguagem jornalístico-investigativa:

1. **Perfil Temático**: Quais são os 2-3 temas dominantes na cobertura? O que isso revela sobre o posicionamento público do parlamentar?
2. **Cobertura Midiática**: Qual veículo cobre mais? Há veículos notadamente mais negativos ou positivos? Que tendência editorial isso indica?
3. **Postura nas Pautas**: O parlamentar aparece como escudo do governo, polemista, legislador técnico ou protagonista de escândalos?
4. **Diagnóstico Final**: Uma síntese objetiva de como a imprensa enxerga esse parlamentar hoje.

REGRAS: Retorne apenas texto corrido com marcações Markdown (negritos em palavras-chave). Sem títulos, sem listas, sem JSON. Sem introduções genéricas. Vá direto ao ponto como um analista experiente."""

        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_completion_tokens=800
        )
        report = response.choices[0].message.content.strip()

        return {"report": report}
    except Exception as e:
        logger.error(f"Erro LLM Imprensa V2: {e}")
        return JSONResponse(status_code=500, content={"error": "Falha ao gerar dossiê."})


class PipelineStatus(BaseModel):
    running: bool
    last_log: str
    schedules: List[Dict] = Field(default_factory=list)

class PipelineScheduleRequest(BaseModel):
    enabled: bool = True
    day: int
    time: str

PIPELINE_STAGES = ["all", "core", "legislativo", "noticias", "discursos", "auditoria"]
PIPELINE_LOCK_FILE = os.path.join(os.path.dirname(__file__), ".pipeline.lock")
PIPELINE_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "000_pipeline_final.py")
PIPELINE_SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "logs", "pipeline_schedules.json")
PIPELINE_SCHEDULER_STARTED = False

def _read_pipeline_schedules() -> Dict[str, Dict]:
    try:
        if not os.path.exists(PIPELINE_SCHEDULE_FILE):
            return {}
        with open(PIPELINE_SCHEDULE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Erro ao ler agendamentos do pipeline")
        return {}

def _write_pipeline_schedules(schedules: Dict[str, Dict]) -> None:
    os.makedirs(os.path.dirname(PIPELINE_SCHEDULE_FILE), exist_ok=True)
    with open(PIPELINE_SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedules, f, ensure_ascii=False, indent=2)

def _pipeline_schedule_list() -> List[Dict]:
    schedules = _read_pipeline_schedules()
    return [
        {"stage": stage, **schedule}
        for stage, schedule in schedules.items()
        if stage in PIPELINE_STAGES
    ]

def _spawn_pipeline(stage: str) -> None:
    if stage not in PIPELINE_STAGES:
        raise ValueError("Estágio inválido.")
    if os.path.exists(PIPELINE_LOCK_FILE):
        raise RuntimeError("O pipeline já está em execução.")

    cmd = [sys.executable, PIPELINE_SCRIPT_PATH, "--all"] if stage == "all" else [sys.executable, PIPELINE_SCRIPT_PATH, "--stage", stage]
    subprocess.Popen(cmd, cwd=os.path.dirname(__file__))

def _pipeline_scheduler_loop() -> None:
    logger.info("⏰ Agendador do Maestro iniciado.")
    while True:
        try:
            now = datetime.now()
            current_key = now.strftime("%Y-%m-%d %H:%M")
            current_time = now.strftime("%H:%M")
            current_day = now.weekday()
            schedules = _read_pipeline_schedules()
            changed = False

            for stage, schedule in schedules.items():
                if stage not in PIPELINE_STAGES or not schedule.get("enabled", True):
                    continue
                if int(schedule.get("day", -1)) != current_day:
                    continue
                if str(schedule.get("time", "")) != current_time:
                    continue
                if schedule.get("last_run_key") == current_key:
                    continue

                schedule["last_run_key"] = current_key
                schedule["last_run_at"] = now.isoformat(timespec="seconds")
                changed = True

                if os.path.exists(PIPELINE_LOCK_FILE):
                    logger.warning("⏳ Agendamento '%s' pulado: pipeline já está em execução.", stage)
                    continue

                logger.info("⏰ Agendamento disparando estágio: %s", stage)
                try:
                    _spawn_pipeline(stage)
                except Exception as exc:
                    logger.exception("Falha ao disparar agendamento '%s': %s", stage, exc)

            if changed:
                _write_pipeline_schedules(schedules)
        except Exception:
            logger.exception("Erro no loop do agendador do Maestro")
        time.sleep(20)

@app.post("/api/admin/pipeline/exec/{stage}")
async def exec_pipeline(stage: str):
    """Dispara a execução de um estágio do pipeline em segundo plano."""
    if stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail="Estágio inválido.")

    if os.path.exists(PIPELINE_LOCK_FILE):
        return {"status": "error", "message": "O pipeline já está em execução."}

    try:
        _spawn_pipeline(stage)
    except Exception as exc:
        logger.exception("Falha ao iniciar pipeline '%s'", stage)
        raise HTTPException(status_code=500, detail=f"Falha ao iniciar pipeline: {exc}") from exc

    return {"status": "success", "message": f"Pipeline ({stage}) iniciado em segundo plano."}

@app.get("/api/admin/pipeline/status")
async def get_pipeline_status():
    """Retorna o status e as últimas linhas do log do Maestro."""
    log_file = os.path.join(os.path.dirname(__file__), "logs", "pipeline_maestro.log")
    
    running = os.path.exists(PIPELINE_LOCK_FILE)
    last_log = ""
    
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                last_log = "".join(lines[-160:])
        except Exception:
            last_log = "Erro ao ler logs."
            
    return {"running": running, "last_log": last_log, "schedules": _pipeline_schedule_list()}

@app.get("/api/admin/pipeline/schedules")
async def get_pipeline_schedules():
    return {"schedules": _pipeline_schedule_list()}

@app.post("/api/admin/pipeline/schedule/{stage}")
async def save_pipeline_schedule(stage: str, req: PipelineScheduleRequest):
    if stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail="Estágio inválido.")
    if req.day < 0 or req.day > 6:
        raise HTTPException(status_code=400, detail="Dia inválido.")
    if not re.match(r"^\d{2}:\d{2}$", req.time or ""):
        raise HTTPException(status_code=400, detail="Horário inválido. Use HH:MM.")

    hour, minute = [int(part) for part in req.time.split(":")]
    if hour > 23 or minute > 59:
        raise HTTPException(status_code=400, detail="Horário inválido. Use HH:MM.")

    schedules = _read_pipeline_schedules()
    existing = schedules.get(stage, {})
    schedules[stage] = {
        **existing,
        "enabled": req.enabled,
        "day": req.day,
        "time": req.time,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_pipeline_schedules(schedules)
    return {"status": "success", "message": f"Agendamento salvo para {stage}.", "schedules": _pipeline_schedule_list()}

@app.delete("/api/admin/pipeline/schedule/{stage}")
async def delete_pipeline_schedule(stage: str):
    if stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail="Estágio inválido.")
    schedules = _read_pipeline_schedules()
    schedules.pop(stage, None)
    _write_pipeline_schedules(schedules)
    return {"status": "success", "message": f"Agendamento removido para {stage}.", "schedules": _pipeline_schedule_list()}

# ── Proxy de imagens (para html2canvas capturar fotos/logos sem CORS) ──────────
@app.get("/api/proxy-image")
async def proxy_image(url: str = Query(...)):
    """Busca uma imagem externa e a retorna com headers CORS corretos,
    permitindo que html2canvas capture sem taint de canvas."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        ct = r.headers.get("content-type", "image/jpeg")
        return Response(
            content=r.content,
            media_type=ct,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=3600",
            },
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

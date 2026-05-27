# -*- coding: utf-8 -*-
import sqlite3
import requests
import os
import json
import time
import datetime
from openai import OpenAI
from dotenv import load_dotenv
from ddgs import DDGS
from datetime import datetime, timedelta

# --- CONSTANTES GLOBAIS ---
DB_NAME = "tabelao.db"
API_CAMARA_VOTACOES = "https://dadosabertos.camara.leg.br/api/v2/votacoes"
API_CAMARA_VOTACAO_DETALHE = "https://dadosabertos.camara.leg.br/api/v2/votacoes/{id}"
API_CAMARA_VOTOS_DETALHE = "https://dadosabertos.camara.leg.br/api/v2/votacoes/{id}/votos"
API_CAMARA_ORIENTACOES = "https://dadosabertos.camara.leg.br/api/v2/votacoes/{id}/orientacoes"
API_CAMARA_PROPOSICAO_TEMAS = "https://dadosabertos.camara.leg.br/api/v2/proposicoes/{id}/temas"
OPENAI_MODEL = "gpt-4o-mini"

# Carrega a chave da API do .env
load_dotenv()
try:
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("OPENAI_API_KEY não encontrada no .env")
    client_openai = OpenAI(api_key=openai_key)
    print("✅ Cliente OpenAI inicializado com sucesso.")
except Exception as e:
    print(f"Erro ao inicializar cliente OpenAI: {e}")
    exit()

# ==============================================================================
# 1. FUNÇÕES DE BANCO DE DADOS
# (Esta função não mudou)
# ==============================================================================

def criar_banco_e_tabelas():
    """
    Garante que as tabelas existam sem apagar dados anteriores.
    Usa as mesmas tabelas do pipeline principal: votacoes_unificadas,
    votacoes_analise_enrichment e votos_parlamentares_analise.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    print(f"Preparando banco '{DB_NAME}'...")

    # tabela principal de votações (pipeline unificado)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS votacoes_unificadas (
            id_votacao TEXT PRIMARY KEY NOT NULL,
            data_registro TEXT,
            sigla_orgao TEXT,
            proposicao TEXT,
            descricao TEXT,
            cobertura_midia INTEGER DEFAULT 0,
            resumo_midia TEXT,
            posicao_midia TEXT,
            links_noticias TEXT,
            tipo_votacao TEXT,
            tem_votos_nominais INTEGER DEFAULT 0,
            updated_at TEXT
        )
        """
    )

    # tabela de enrichment (tema_macro, pauta_governo, resumo_leigo)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS votacoes_analise_enrichment (
            id_votacao TEXT PRIMARY KEY NOT NULL,
            tema_macro TEXT,
            resumo_leigo TEXT,
            pauta_governo TEXT,
            local_votacao TEXT,
            analise_ia_json TEXT,
            atualizado_em TEXT
        )
        """
    )

    # tabela de votos individuais por parlamentar
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS votos_parlamentares_analise (
            id_votacao TEXT NOT NULL,
            nome_deputado TEXT,
            partido TEXT,
            uf TEXT,
            voto TEXT,
            comissao TEXT,
            data_registro TEXT,
            PRIMARY KEY (id_votacao, nome_deputado)
        )
        """
    )

    conn.commit()
    print("Tabelas verificadas/criadas com sucesso.")
    return conn

# ==============================================================================
# 2. FUNÇÕES DE COLETA (API DA CÂMARA)
# (Estas funções não mudaram)
# ==============================================================================

def _coletar_intervalo(data_inicio, data_fim, depth=0):
    """Busca votações dentro de um intervalo. Se der timeout, divide o período."""
    indent = "  " * depth
    print(f"{indent}- Janela {data_inicio.date()} a {data_fim.date()}")
    pagina = 1
    tentativas_falhas = 0
    resultados = []

    while True:
        params = {
            'dataInicio': data_inicio.strftime("%Y-%m-%d"),
            'dataFim': data_fim.strftime("%Y-%m-%d"),
            'ordem': 'ASC',
            'ordenarPor': 'dataHoraRegistro',
            'pagina': pagina,
            'itens': 100
        }
        try:
            response = requests.get(API_CAMARA_VOTACOES, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()
            votacoes_pagina = data.get('dados', [])
            if not votacoes_pagina:
                break

            for votacao in votacoes_pagina:
                resultados.append({
                    'id': votacao.get('id'),
                    'dataHoraRegistro': votacao.get('dataHoraRegistro'),
                    'descricao': votacao.get('descricao'),
                    'tipoVotacao': votacao.get('tipoVotacao'),
                    'descricaoTipoVotacao': votacao.get('descricaoTipoVotacao'),
                    'siglaOrgao': votacao.get('siglaOrgao')
                })

            links = {link['rel']: link['href'] for link in data.get('links', [])}
            if 'next' not in links:
                break

            pagina += 1
            tentativas_falhas = 0
        except requests.RequestException as e:
            tentativas_falhas += 1
            print(f"{indent}  ⚠️  Erro página {pagina} (tentativa {tentativas_falhas}): {e}")
            if tentativas_falhas >= 3:
                delta = (data_fim - data_inicio).days
                if delta <= 2:
                    print(f"{indent}  ⚠️  Intervalo muito pequeno; abortando janela.")
                    return resultados
                meio = data_inicio + timedelta(days=delta // 2)
                resultados += _coletar_intervalo(data_inicio, meio, depth + 1)
                resultados += _coletar_intervalo(meio + timedelta(days=1), data_fim, depth + 1)
                return resultados
            time.sleep(3 * tentativas_falhas)
            continue

    return resultados

def buscar_lista_votacoes_api(data_inicio, data_fim):
    print(f"Buscando lista de votações da API desde {data_inicio}...")
    inicio_global = datetime.strptime(data_inicio, "%Y-%m-%d")
    if isinstance(data_fim, str):
        fim_global = datetime.strptime(data_fim, "%Y-%m-%d")
    else:
        fim_global = data_fim
    resultados = []

    janela_inicio = inicio_global
    while janela_inicio <= fim_global:
        proximo_mes = (janela_inicio + timedelta(days=32)).replace(day=1)
        janela_fim = proximo_mes - timedelta(days=1)
        if janela_fim > fim_global:
            janela_fim = fim_global
        resultados += _coletar_intervalo(janela_inicio, janela_fim)
        janela_inicio = proximo_mes

    print(f"\nColeta concluída. Total de votações encontradas: {len(resultados)}")
    return resultados

def buscar_detalhes_votacao_api(id_votacao):
    """
    Busca os detalhes de UMA votação específica.
    Retorna também informações sobre o tipo de votação.
    """
    url = API_CAMARA_VOTACAO_DETALHE.format(id=id_votacao)
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json().get('dados', {})
        
        detalhes = {
            "id_votacao": id_votacao,
            "data_votacao": data.get('data'),
            "descricao": data.get('descricao', 'N/A'),
            "nome_projeto": "Votação genérica",
            "numero_pl": None,
            "ementa": data.get('descricao'),
            "query_busca": data.get('descricao'),
            "tipo_votacao": data.get('tipoVotacao', 'N/A'),
            "sigla_orgao": data.get('siglaOrgao', 'N/A'),
            "objeto_votacao": data.get('objeto', data.get('descricao', 'N/A')),
            "id_proposicao": None,
        }

        if data.get('proposicaoObjeto'):
            prop = data['proposicaoObjeto']
            detalhes['id_proposicao'] = prop.get('id')
            detalhes['nome_projeto'] = f"{prop.get('siglaTipo', '')} {prop.get('numero', '')}/{prop.get('ano', '')}"
            detalhes['numero_pl'] = f"{prop.get('siglaTipo', '')} {prop.get('numero', '')}/{prop.get('ano', '')}"
            detalhes['ementa'] = prop.get('ementa', detalhes['descricao'])
            detalhes['query_busca'] = f"{detalhes['nome_projeto']} {detalhes['ementa'][:100]}"
            detalhes['objeto_votacao'] = prop.get('ementa', detalhes['objeto_votacao'])
        elif data.get('objetosPossiveis') and isinstance(data['objetosPossiveis'], list):
            obj = data['objetosPossiveis'][0] if data['objetosPossiveis'] else {}
            if isinstance(obj, dict) and obj.get('id'):
                detalhes['id_proposicao'] = obj['id']
        elif data.get('descricao'):
            detalhes['nome_projeto'] = data['descricao']
            detalhes['query_busca'] = data['descricao']
            detalhes['objeto_votacao'] = data['descricao']

        return detalhes
        
    except requests.RequestException as e:
        print(f"Erro ao buscar detalhes da votação {id_votacao}: {e}")
        return None

def buscar_votos_parlamentares_api(id_votacao):
    """
    Busca a lista de votos (Sim, Não, Abs) de TODOS os deputados
    para UMA votação específica.
    """
    url = API_CAMARA_VOTOS_DETALHE.format(id=id_votacao)
    votos_lista = []
    try:
        response = requests.get(url, timeout=60) 
        response.raise_for_status()
        response_data = response.json()
        
        # Debug: verificar estrutura completa da resposta
        print(f"   [DEBUG] Status da resposta: {response.status_code}")
        print(f"   [DEBUG] Chaves no JSON: {list(response_data.keys())}")
        
        # Verificar se há paginação
        if 'links' in response_data:
            links = {link['rel']: link['href'] for link in response_data.get('links', [])}
            print(f"   [DEBUG] Links disponíveis: {list(links.keys())}")
        
        data = response_data.get('dados', [])
        
        # Se não houver dados na primeira página, verificar se há mais páginas
        if not data and 'links' in response_data:
            links = {link['rel']: link['href'] for link in response_data.get('links', [])}
            if 'next' in links:
                print(f"   [DEBUG] Tentando próxima página...")
                # Tentar buscar próxima página (implementação básica)
                try:
                    next_response = requests.get(links['next'], timeout=60)
                    next_response.raise_for_status()
                    next_data = next_response.json().get('dados', [])
                    if next_data:
                        data = next_data
                        print(f"   [DEBUG] Próxima página retornou {len(data)} registros")
                except:
                    pass
        
        # Debug detalhado
        if not data:
            print(f"   [DEBUG] API retornou lista de votos vazia []. (Votação simbólica ou sem votos nominais)")
            print(f"   [DEBUG] Resposta completa (primeiros 500 chars): {str(response_data)[:500]}")
        else:
            print(f"   [DEBUG] API retornou {len(data)} registros de votos. Filtrando...")
            # Debug: mostrar estrutura do primeiro voto
            if len(data) > 0:
                primeiro_voto = data[0]
                print(f"   [DEBUG] Estrutura do primeiro voto: {list(primeiro_voto.keys())}")
                # Verificar se tem 'parlamentar' ou 'deputado_'
                parlamentar_info = primeiro_voto.get('parlamentar') or primeiro_voto.get('deputado_', {})
                nome_parl = parlamentar_info.get('nome', 'N/A') if parlamentar_info else 'N/A'
                print(f"   [DEBUG] Primeiro voto (amostra): tipoVoto={primeiro_voto.get('tipoVoto')}, parlamentar={nome_parl}")

        for voto_info in data:
            # Verificar se tipoVoto existe e não é '-'
            tipo_voto = voto_info.get('tipoVoto', '-')
            if tipo_voto == '-' or not tipo_voto:
                continue  # Ignora quem não votou
            
            # A API pode retornar 'parlamentar' ou 'deputado_' (com underscore)
            parlamentar = voto_info.get('parlamentar') or voto_info.get('deputado_', {})
            if not parlamentar:
                print(f"   [DEBUG] Voto sem informações de parlamentar/deputado: {list(voto_info.keys())}")
                continue
            
            id_parlamentar = parlamentar.get('id')
            nome_parlamentar = parlamentar.get('nome')
            partido = parlamentar.get('siglaPartido') or parlamentar.get('siglaPartidoAnterior')
            uf = parlamentar.get('siglaUf')
            
            if not id_parlamentar or not nome_parlamentar:
                print(f"   [DEBUG] Voto com parlamentar incompleto: id={id_parlamentar}, nome={nome_parlamentar}")
                continue
            
            votos_lista.append({
                "id_parlamentar": str(id_parlamentar),
                "nome_parlamentar": nome_parlamentar,
                "voto": tipo_voto,
                "partido": partido,
                "uf": uf
            })
        
        if votos_lista:
            print(f"   [DEBUG] Após filtragem: {len(votos_lista)} votos válidos extraídos")
        else:
            print(f"   [DEBUG] Nenhum voto válido após filtragem (todos eram '-' ou sem parlamentar)")
            
        return votos_lista
        
    except requests.RequestException as e:
        print(f"   [ERRO] Erro ao buscar votos parlamentares para {id_votacao}: {e}")
        import traceback
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"   [ERRO] Erro inesperado ao processar votos para {id_votacao}: {e}")
        import traceback
        traceback.print_exc()
        return None

# ==============================================================================
# 3. FUNÇÕES DE ANÁLISE (DUCKDUCKGO E GEMINI)
# ==============================================================================

def buscar_orientacoes_api(id_votacao):
    """
    Busca a orientação oficial dos partidos/governo para uma votação.
    Retorna 'Sim', 'Não', 'Indiferente' ou None se não encontrado.
    """
    url = API_CAMARA_ORIENTACOES.format(id=id_votacao)
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        items = response.json().get('dados', [])
        for item in items:
            sigla = (item.get('siglaPartidoBloco') or '').strip()
            if 'Governo' in sigla:
                voto = (item.get('orientacaoVoto') or '').strip()
                if voto == 'Sim':
                    return 'Sim'
                elif voto in ('Não', 'Nao', 'Obstrução'):
                    return 'Não'
                elif voto == 'Liberado':
                    return 'Indiferente'
        return None
    except Exception as e:
        print(f"   [WARN] Não foi possível buscar orientações para {id_votacao}: {e}")
        return None

def buscar_tema_proposicao_api(id_proposicao):
    """
    Busca os temas oficiais da Câmara para uma proposição.
    Retorna string com temas separados por vírgula, ou None.
    Ex: "Saúde, Assistência Social"
    """
    if not id_proposicao:
        return None
    url = API_CAMARA_PROPOSICAO_TEMAS.format(id=id_proposicao)
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        temas = response.json().get('dados', [])
        if temas:
            # API retorna campo 'tema' (não 'nome'), ordenado por relevância
            temas_sorted = sorted(temas, key=lambda t: t.get('relevancia', 0), reverse=True)
            nomes = [t.get('tema', '').strip() for t in temas_sorted if t.get('tema')]
            return ", ".join(nomes[:3]) if nomes else None  # máximo 3 temas
        return None
    except Exception as e:
        print(f"   [WARN] Não foi possível buscar temas para proposição {id_proposicao}: {e}")
        return None

def buscar_noticias_ddg(query):
    """
    Usa o DuckDuckGo (ddgs) para buscar notícias sobre o projeto de lei.
    Retorna uma lista de dicionários com título, resumo e URL.
    """
    print(f"   Buscando notícias (DDG) para: '{query[:50]}...'")
    resultados = []
    if not query:
        return resultados
    try:
        with DDGS() as ddgs:
            items = ddgs.text(query, region='br-pt', max_results=5)
            if items:
                for res in items:
                    resultados.append({
                        'title': res.get('title'),
                        'body': res.get('body'),
                        'url': res.get('href')
                    })
        return resultados
    except Exception as e:
        print(f"   Erro ao buscar no DuckDuckGo: {e}")
        return resultados

def analisar_com_llm(detalhes, noticias):
    """
    Envia os detalhes do projeto e as notícias para o Gemini
    e pede um resumo estruturado em JSON.
    """
    print("   Enviando para análise do OpenAI...")

    contexto_noticias = []
    for idx, item in enumerate(noticias or [], start=1):
        contexto_noticias.append(
            f"{idx}. Título: {item.get('title') or 'N/A'}\n"
            f"   Fonte: {item.get('url') or 'N/A'}\n"
            f"   Resumo: {item.get('body') or 'N/A'}"
        )
    bloco_noticias = "\n".join(contexto_noticias) if contexto_noticias else "Nenhuma notícia externa relevante encontrada."

    prompt = f"""Você é um analista político especializado em votações da Câmara dos Deputados do Brasil.
Analise a votação abaixo e produza APENAS um JSON válido, sem texto adicional.

## DADOS DA VOTAÇÃO
- ID: {detalhes.get('id_votacao')}
- Data: {detalhes.get('data_votacao')}
- Órgão: {detalhes.get('sigla_orgao')}
- Tipo: {detalhes.get('tipo_votacao')}
- Descrição: {detalhes.get('descricao')}
- Objeto/ementa: {detalhes.get('ementa')}

## NOTÍCIAS ENCONTRADAS
{bloco_noticias}

Retorne APENAS este JSON (sem markdown, sem explicações):
{{
  "tema": "Categoria temática em poucas palavras (ex: Saúde, Segurança Pública, Economia, Previdência, Educação, Meio Ambiente, etc.)",
  "cobertura_na_midia": true,
  "resumo_discussao": "Resumo objetivo em 2-3 frases do que foi debatido e sua relevância para a sociedade brasileira",
  "foi_polemico": true,
  "motivo_polemica": "Explique a controvérsia ou 'N/A' se não houve",
  "fontes_citadas": ["URL da fonte 1"]
}}

Regras:
- Retorne JSON válido sem markdown.
- "fontes_citadas": apenas URLs das notícias fornecidas. Lista vazia se não houver.
- "cobertura_na_midia": false se não há notícias relevantes.
- "foi_polemico": false e "motivo_polemica": "N/A" se não foi controverso.
"""

    for tentativa in range(5):
        try:
            response = client_openai.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            analise_json = response.choices[0].message.content.strip()
            print("   Análise do OpenAI recebida.")
            return json.loads(analise_json)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower() or "503" in msg:
                espera = 15 * (tentativa + 1)
                print(f"   OpenAI rate limit. Aguardando {espera}s (tentativa {tentativa+1}/5)...")
                time.sleep(espera)
            else:
                print(f"   Erro na chamada do OpenAI: {e}")
                return None
    print("   Falha após 5 tentativas no OpenAI. Pulando.")
    return None

# ==============================================================================
# 4. FUNÇÕES DE ORQUESTRAÇÃO E SALVAMENTO
# ==============================================================================

def salvar_votacao_no_banco(conn, detalhes, analise_llm, pauta_governo=None, tema_oficial=None):
    """ Salva em votacoes_unificadas + votacoes_analise_enrichment.
        pauta_governo vem da API orientacoes; tema_oficial da API /proposicoes/{id}/temas. """
    cursor = conn.cursor()
    try:
        proposicao = detalhes.get('nome_projeto') or detalhes.get('descricao', '')
        if detalhes.get('numero_pl') and detalhes['numero_pl'] != proposicao:
            proposicao = f"{proposicao} {detalhes['numero_pl']}".strip()

        # Tabela principal
        cursor.execute(
            """
            INSERT OR IGNORE INTO votacoes_unificadas (
                id_votacao, data_registro, sigla_orgao, tipo_votacao, descricao,
                proposicao, cobertura_midia, resumo_midia, tem_votos_nominais, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
            """,
            (
                detalhes['id_votacao'],
                detalhes['data_votacao'],
                detalhes['sigla_orgao'],
                detalhes['tipo_votacao'],
                detalhes['descricao'],
                proposicao,
                1 if analise_llm.get('cobertura_na_midia', False) else 0,
                analise_llm.get('resumo_discussao', ''),
            )
        )

        # pauta_governo: API orientacoes > 'Indiferente'
        pauta_final = pauta_governo if pauta_governo else 'Indiferente'
        # tema: API /proposicoes/{id}/temas > Gemini > 'Outros'
        tema_final = tema_oficial or analise_llm.get('tema') or 'Outros'

        # Tabela de enrichment
        analise_json = json.dumps(analise_llm, ensure_ascii=False)
        cursor.execute(
            """
            INSERT OR REPLACE INTO votacoes_analise_enrichment (
                id_votacao, tema_macro, resumo_leigo, pauta_governo,
                local_votacao, analise_ia_json, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                detalhes['id_votacao'],
                tema_final,
                analise_llm.get('resumo_discussao', ''),
                pauta_final,
                detalhes.get('sigla_orgao', ''),
                analise_json,
            )
        )

        conn.commit()
        print(f"   tema: {tema_final} | pauta_governo: {pauta_final}")
    except Exception as e:
        print(f"   Erro ao salvar votação {detalhes['id_votacao']} no DB: {e}")

def salvar_votos_parlamentares_no_banco(conn, id_votacao, votos_lista):
    """ Salva a lista de votos em votos_parlamentares_analise """
    cursor = conn.cursor()
    try:
        agora = datetime.now().isoformat()
        dados_para_inserir = [
            (
                id_votacao,
                voto['nome_parlamentar'],
                voto.get('partido'),
                voto.get('uf'),
                voto['voto'],
                'PLEN',  # maioria das votações nominais é plenário
                agora
            )
            for voto in votos_lista
        ]

        if not dados_para_inserir:
            print("   Nenhum voto nominal filtrado para salvar.")
            return

        cursor.executemany(
            """
            INSERT OR IGNORE INTO votos_parlamentares_analise (
                id_votacao, nome_deputado, partido, uf, voto, comissao, data_registro
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            dados_para_inserir
        )
        conn.commit()
        print(f"   +++ SUCESSO: {len(dados_para_inserir)} votos nominais de parlamentares salvos! +++")
    except Exception as e:
        print(f"   Erro ao salvar votos parlamentares para {id_votacao}: {e}")

# ==============================================================================
# FUNÇÃO PRINCIPAL (MAIN)
# (Esta função não mudou)
# ==============================================================================

def main():
    print("========================================")
    print("  COLETOR DE VOTAÇÕES DA CÂMARA (v1.0)")
    print("========================================")

    data_inicio_env = os.getenv("DATA_INICIO_COLETA")
    data_fim_env = os.getenv("DATA_FIM_COLETA")
    if data_fim_env:
        data_fim_global = datetime.strptime(data_fim_env, "%Y-%m-%d")
    else:
        data_fim_global = datetime.utcnow()
    if data_inicio_env:
        data_inicio_coleta = datetime.strptime(data_inicio_env, "%Y-%m-%d")
    else:
        data_inicio_coleta = data_fim_global - timedelta(days=30)

    print(f"Período configurado: {data_inicio_coleta.date()} até {data_fim_global.date()}")

    conn = criar_banco_e_tabelas()
    cursor = conn.cursor()

    votacoes_api = buscar_lista_votacoes_api(data_inicio_coleta.strftime("%Y-%m-%d"), data_fim_global.strftime("%Y-%m-%d"))
    if not votacoes_api:
        print("Nenhuma votação nominal encontrada na API. Encerrando.")
        conn.close()
        return
        
    total_api = len(votacoes_api)
    print(f"Total de {total_api} votações nominais encontradas na API.")

    # 2. Busca IDs que JÁ ESTÃO no banco (votacoes_unificadas + votos_parlamentares_analise)
    print("Verificando votações já processadas no banco de dados...")
    cursor.execute("SELECT id_votacao FROM votacoes_unificadas")
    ids_no_banco = {row[0] for row in cursor.fetchall()}
    try:
        cursor.execute("SELECT DISTINCT id_votacao FROM votos_parlamentares_analise")
        ids_com_votos = {row[0] for row in cursor.fetchall()}
    except Exception:
        ids_com_votos = set()
    ids_ja_processados = ids_no_banco | ids_com_votos
    print(f"{len(ids_ja_processados)} votações já existem no banco ({len(ids_no_banco)} unificadas, {len(ids_com_votos)} com votos).")

    # 3. Calcula a diferença
    votacoes_para_processar = [v for v in votacoes_api if v.get('id') not in ids_ja_processados]

    total_para_processar = len(votacoes_para_processar)
    if total_para_processar == 0:
        print("\nO banco de dados já está 100% atualizado. Nada a fazer.")
        conn.close()
        return

    print(f"\nIniciando processamento de {total_para_processar} NOVAS votações...")

    # FILTRAGEM
    print("\n" + "="*40)
    print("FILTRANDO VOTAÇÕES NOMINAIS COM VOTOS...")
    print("="*40)

    votacoes_nominais = []
    votacoes_sem_votos = 0
    votacoes_falhas_detalhes = 0
    votacoes_falhas_votos = 0

    for i, votacao in enumerate(votacoes_para_processar):
        id_votacao = votacao.get('id')
        if (i + 1) % 50 == 0:
            print(
                f"Verificando votações... {i+1}/{total_para_processar} "
                f"(Nominais {len(votacoes_nominais)}, sem votos {votacoes_sem_votos}, "
                f"falhas {votacoes_falhas_detalhes + votacoes_falhas_votos})"
            )

        # Pular se já tem votos salvos
        if id_votacao in ids_com_votos:
            continue

        detalhes = buscar_detalhes_votacao_api(id_votacao)
        if not detalhes:
            votacoes_falhas_detalhes += 1
            continue

        votos_lista = buscar_votos_parlamentares_api(id_votacao)
        if votos_lista is None:
            votacoes_falhas_votos += 1
            continue
        if len(votos_lista) == 0:
            votacoes_sem_votos += 1
            continue

        votacoes_nominais.append((id_votacao, detalhes, votos_lista))

    print(f"\n✅ Filtragem concluída:")
    print(f"   - Votações nominais com votos: {len(votacoes_nominais)}")
    print(f"   - Votações com API retornando vazio: {votacoes_sem_votos}")
    print(f"   - Falhas ao obter detalhes: {votacoes_falhas_detalhes}")
    print(f"   - Falhas ao obter votos: {votacoes_falhas_votos}")
    print(
        f"   - Total avaliado: "
        f"{len(votacoes_nominais) + votacoes_sem_votos + votacoes_falhas_detalhes + votacoes_falhas_votos}"
    )

    if not votacoes_nominais:
        print("\n⚠️ Nenhuma votação nominal com votos retornados pela API.")
        conn.close()
        return

    # PROCESSAMENTO
    print(f"\n{'='*40}")
    print(f"PROCESSANDO {len(votacoes_nominais)} VOTAÇÕES NOMINAIS...")
    print(f"{'='*40}\n")

    for i, (id_votacao, detalhes, votos_lista) in enumerate(votacoes_nominais):
        print("\n" + "="*40)
        print(f"Processando Votação Nominal {i+1} de {len(votacoes_nominais)} (ID: {id_votacao})")
        print(f"   ✅ Já confirmado: {len(votos_lista)} votos nominais")

        # ETAPA C: Dados oficiais da Câmara (orientação do governo + tema da proposição)
        pauta_governo = buscar_orientacoes_api(id_votacao)
        print(f"   pauta_governo (API Câmara): {pauta_governo or 'não disponível'}")

        tema_oficial = buscar_tema_proposicao_api(detalhes.get('id_proposicao'))
        print(f"   tema_oficial (API Câmara): {tema_oficial or 'não disponível — usará Gemini'}")

        # ETAPA D: Busca notícias (DuckDuckGo)
        noticias = buscar_noticias_ddg(detalhes.get('query_busca'))

        # ETAPA E: Análise com Gemini (resumo, polêmica, tema se não veio da API)
        analise_llm = analisar_com_llm(detalhes, noticias)
        if not analise_llm:
            print("   Falha na análise do Gemini. Pulando.")
            continue

        # ETAPA F: Salva a Votação analisada (Tabela 1)
        salvar_votacao_no_banco(conn, detalhes, analise_llm,
                                pauta_governo=pauta_governo,
                                tema_oficial=tema_oficial)

        # ETAPA G: Salva os votos (Tabela 2)
        salvar_votos_parlamentares_no_banco(conn, id_votacao, votos_lista)

        print(f"   ✅ Votação {id_votacao} concluída e salva com {len(votos_lista)} votos nominais.")
        time.sleep(1)

    print("\n" + "="*40)
    print("Processamento concluído!")
    print(f"Banco de dados '{DB_NAME}' está atualizado.")
    conn.close()

if __name__ == "__main__":
    main()
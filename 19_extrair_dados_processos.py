#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para extrair dados detalhados dos processos STF que já estão no banco
mas ainda não têm dados extraídos. Agora com extração de conteúdo textual
e análise via LLM para gerar resumos e metadados estruturados.
"""

import sqlite3
import pandas as pd
import time
from tqdm import tqdm
import sys
import os
import json
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Importar funções do script principal
from importlib import import_module
import importlib.util

# Adicionar o diretório atual ao path para importar
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Importar funções do 18_processo.py
spec = importlib.util.spec_from_file_location("processo_module", "18_processo.py")
processo_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(processo_module)

DB_PATH = "/Users/aislangreca/Library/Mobile Documents/com~apple~CloudDocs/Projetos_dados/acompanhamento_camara/dash2/tabelao.db"

def get_db_connection():
    """Retorna conexão com o banco de dados."""
    return sqlite3.connect(DB_PATH)

def extrair_conteudo_textual(soup, html_content):
    """
    Extrai conteúdo textual relevante da página do processo.
    Busca por movimentações, documentos, partes envolvidas, etc.
    """
    conteudo = {
        'texto_principal': '',
        'movimentacoes': [],
        'documentos': [],
        'partes_envolvidas': [],
        'decisoes': [],
        'texto_completo': ''
    }
    
    try:
        # Extrair texto principal (remover scripts, styles, etc.)
        for script in soup(["script", "style", "nav", "header", "footer"]):
            script.decompose()
        
        # Buscar seções principais
        texto_principal = soup.get_text(separator='\n', strip=True)
        conteudo['texto_completo'] = texto_principal[:10000]  # Limitar a 10k caracteres
        
        # Buscar movimentações (tabelas com datas e descrições)
        tabelas = soup.find_all('table')
        for tabela in tabelas:
            linhas = tabela.find_all('tr')
            for linha in linhas:
                celulas = linha.find_all(['td', 'th'])
                if len(celulas) >= 2:
                    texto_linha = ' | '.join([c.get_text(strip=True) for c in celulas])
                    if any(palavra in texto_linha.lower() for palavra in ['data', 'moviment', 'decis', 'julg', 'senten']):
                        conteudo['movimentacoes'].append(texto_linha[:500])
        
        # Buscar documentos (links para PDFs ou documentos)
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            texto = link.get_text(strip=True)
            if any(ext in href.lower() for ext in ['.pdf', 'documento', 'doc', 'anexo']):
                conteudo['documentos'].append({
                    'texto': texto[:200],
                    'link': href[:500]
                })
        
        # Buscar partes envolvidas (geralmente em listas ou tabelas)
        divs_partes = soup.find_all(['div', 'ul', 'ol'], class_=re.compile(r'parte|envolvido|requerente|requerido', re.I))
        for div in divs_partes:
            texto = div.get_text(strip=True)
            if len(texto) > 10 and len(texto) < 500:
                conteudo['partes_envolvidas'].append(texto)
        
        # Buscar decisões (textos que mencionam decisões, sentenças, etc.)
        textos_decisoes = soup.find_all(string=re.compile(r'decisão|sentença|julgamento|acórdão', re.I))
        for texto in textos_decisoes:
            parent = texto.parent
            if parent:
                contexto = parent.get_text(strip=True)
                if len(contexto) > 50 and len(contexto) < 1000:
                    conteudo['decisoes'].append(contexto[:500])
        
        # Limitar quantidade de itens
        conteudo['movimentacoes'] = conteudo['movimentacoes'][:20]
        conteudo['documentos'] = conteudo['documentos'][:10]
        conteudo['partes_envolvidas'] = conteudo['partes_envolvidas'][:10]
        conteudo['decisoes'] = conteudo['decisoes'][:10]
        
    except Exception as e:
        if '--debug' in sys.argv:
            print(f"      ⚠️  Erro ao extrair conteúdo textual: {e}")
    
    return conteudo

def gerar_resumo_e_metadados_llm(conteudo_extraido, dados_basicos, usar_llm=True):
    """
    Usa LLM para gerar resumo e metadados estruturados do processo.
    """
    if not usar_llm:
        return {
            'resumo': None,
            'metadados': None,
            'temas_principais': None,
            'gravidade': None,
            'tipo_processo': None
        }
    
    try:
        from openai import OpenAI
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            if '--debug' in sys.argv:
                print("      ⚠️  OPENAI_API_KEY não configurada")
            return {
                'resumo': None,
                'metadados': None,
                'temas_principais': None,
                'gravidade': None,
                'tipo_processo': None,
                'analise_qualitativa': None
            }
        
        if '--debug' in sys.argv:
            print(f"      🔑 API Key encontrada (tamanho: {len(api_key)})")
        
        client = OpenAI(api_key=api_key)
        
        if '--debug' in sys.argv:
            print(f"      📝 Preparando contexto para LLM...")
            print(f"         - Texto completo: {len(conteudo_extraido.get('texto_completo', ''))} chars")
            print(f"         - Movimentações: {len(conteudo_extraido.get('movimentacoes', []))}")
            print(f"         - Partes: {len(conteudo_extraido.get('partes_envolvidas', []))}")
        
        # Preparar contexto para o LLM
        contexto = f"""
DADOS BÁSICOS DO PROCESSO:
- Classe: {dados_basicos.get('classe', 'N/A')}
- Assunto: {dados_basicos.get('assunto', 'N/A')}
- Relator: {dados_basicos.get('relator', 'N/A')}
- Situação: {dados_basicos.get('situacao', 'N/A')}
- Origem: {dados_basicos.get('origem', 'N/A')}

CONTEÚDO EXTRAÍDO:
Texto Principal (primeiros 2000 caracteres):
{conteudo_extraido['texto_completo'][:2000]}

Movimentações Recentes:
{chr(10).join(conteudo_extraido['movimentacoes'][:5])}

Partes Envolvidas:
{chr(10).join(conteudo_extraido['partes_envolvidas'][:5])}

Decisões/Despachos:
{chr(10).join(conteudo_extraido['decisoes'][:5])}
"""
        
        prompt = f"""Você é um especialista em análise de processos judiciais do STF. Analise o processo abaixo e gere:

1. RESUMO EXECUTIVO (2-3 parágrafos): Resumo claro e objetivo do que se trata o processo, principais fatos e situação atual.

2. METADADOS ESTRUTURADOS (em formato JSON válido, SEM comentários):
{{
    "temas_principais": ["tema1", "tema2", "tema3"],
    "gravidade_denuncia": "baixa|media|alta|muito_alta",
    "indice_problema": 0-10,
    "estado_denuncia": "em_tramitacao|julgado|arquivado|suspenso|parado|aguardando_julgamento|outro",
    "processo_parado": true|false,
    "tempo_parado_meses": número ou null,
    "ultima_movimentacao_meses_atras": número ou null,
    "tipo_processo": "criminal|civil|eleitoral|administrativo|constitucional|outro",
    "natureza": "acao|recurso|medida_cautelar|inquerito|outro",
    "envolvimento_parlamentar": "autor|reus|testemunha|terceiro_interessado|outro",
    "relevancia_publica": "baixa|media|alta|muito_alta",
    "risco_penal": "nenhum|baixo|medio|alto|muito_alto",
    "probabilidade_condenacao": "muito_baixa|baixa|media|alta|muito_alta|indefinida",
    "prazo_estimado": "curto_prazo|medio_prazo|longo_prazo|indefinido",
    "palavras_chave": ["palavra1", "palavra2", "palavra3"]
}}

IMPORTANTE: 
- O JSON deve ser válido e bem formatado
- Use apenas números para "indice_problema", "tempo_parado_meses", "ultima_movimentacao_meses_atras"
- Use true/false (boolean) para "processo_parado"
- Use null quando a informação não estiver disponível
- Analise as movimentações para determinar se o processo está parado e há quanto tempo
- O "indice_problema" deve refletir a gravidade e complexidade (0=nada grave, 10=muito grave)
- O "estado_denuncia" deve ser baseado na situação atual do processo

3. ANÁLISE QUALITATIVA (1 parágrafo): Análise sobre a relevância, complexidade e possíveis desdobramentos.

IMPORTANTE:
- Seja objetivo e preciso
- Baseie-se apenas nas informações fornecidas
- Use terminologia jurídica adequada
- O JSON deve ser válido e bem formatado
- Se alguma informação não estiver disponível, use "N/A"

CONTEXTO DO PROCESSO:
{contexto}

RESPOSTA (formato):
RESUMO:
[seu resumo aqui]

METADADOS:
{{"temas_principais": [...], "gravidade": "...", ...}}

ANÁLISE:
[sua análise aqui]
"""
        
        if '--debug' in sys.argv:
            print(f"      🚀 Enviando requisição para OpenAI...")
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um especialista em análise de processos judiciais do STF. Seja preciso, objetivo e use terminologia jurídica adequada."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.3
        )
        
        resposta = response.choices[0].message.content
        
        if '--debug' in sys.argv:
            print(f"      ✅ Resposta recebida do LLM ({len(resposta)} caracteres)")
            print(f"         Primeiros 200 chars: {resposta[:200]}...")
        
        # Extrair resumo, metadados e análise
        resumo = None
        metadados = None
        analise = None
        
        # Tentar extrair resumo (aceitar diferentes formatos)
        resumo_markers = ["RESUMO:", "RESUMO EXECUTIVO:", "**RESUMO EXECUTIVO:**", "## RESUMO", "# RESUMO"]
        for marker in resumo_markers:
            if marker in resposta.upper() or marker.replace("**", "").replace("#", "").upper() in resposta.upper():
                # Encontrar o marcador (case insensitive)
                resposta_lower = resposta.lower()
                marker_lower = marker.lower().replace("**", "").replace("#", "")
                idx = resposta_lower.find(marker_lower)
                if idx >= 0:
                    # Pegar texto após o marcador
                    texto_apos = resposta[idx + len(marker):].strip()
                    # Remover markdown se houver
                    texto_apos = re.sub(r'^\*\*', '', texto_apos)
                    texto_apos = re.sub(r'\*\*$', '', texto_apos)
                    # Parar no próximo marcador (METADADOS, ANÁLISE, etc.)
                    for next_marker in ["METADADOS:", "ANÁLISE:", "## METADADOS", "## ANÁLISE"]:
                        if next_marker.upper() in texto_apos.upper():
                            texto_apos = texto_apos.split(next_marker, 1)[0].strip()
                            break
                    resumo = texto_apos
                    break
        
        # Tentar extrair metadados JSON (aceitar diferentes formatos)
        metadados_markers = ["METADADOS:", "## METADADOS", "# METADADOS", "**METADADOS:**", "METADADOS ESTRUTURADOS:"]
        json_texto = None
        
        for marker in metadados_markers:
            if marker.upper() in resposta.upper() or marker.replace("**", "").replace("#", "").upper() in resposta.upper():
                resposta_lower = resposta.lower()
                marker_lower = marker.lower().replace("**", "").replace("#", "")
                idx = resposta_lower.find(marker_lower)
                if idx >= 0:
                    json_texto = resposta[idx + len(marker):].strip()
                    # Parar no próximo marcador (ANÁLISE, etc.)
                    for next_marker in ["ANÁLISE:", "## ANÁLISE", "# ANÁLISE", "ANÁLISE QUALITATIVA:"]:
                        if next_marker.upper() in json_texto.upper():
                            json_texto = json_texto.split(next_marker, 1)[0].strip()
                            break
                    break
        
        # Se não encontrou marcador, tentar encontrar JSON diretamente na resposta
        if not json_texto:
            # Procurar por padrões JSON na resposta inteira
            json_matches = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', resposta, re.DOTALL)
            if json_matches:
                json_texto = json_matches[0]  # Pegar o primeiro JSON encontrado
        
        # Tentar extrair JSON
        if json_texto:
            # Limpar o texto
            json_texto = re.sub(r'```json\s*', '', json_texto)
            json_texto = re.sub(r'```\s*', '', json_texto)
            json_texto = json_texto.strip()
            
            # Remover comentários JSON (// comentário)
            json_texto = re.sub(r'//.*?$', '', json_texto, flags=re.MULTILINE)
            
            # Tentar parse direto
            try:
                metadados = json.loads(json_texto)
            except json.JSONDecodeError:
                # Tentar encontrar JSON válido no texto (pode ter texto antes/depois)
                # Procurar por { ... } que seja JSON válido
                matches = re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', json_texto, re.DOTALL)
                for match in matches:
                    try:
                        metadados = json.loads(match.group(0))
                        break
                    except json.JSONDecodeError:
                        continue
                
                # Se ainda não funcionou, tentar corrigir JSON comum
                if not metadados:
                    try:
                        # Remover trailing commas
                        json_texto = re.sub(r',\s*}', '}', json_texto)
                        json_texto = re.sub(r',\s*]', ']', json_texto)
                        # Tentar novamente
                        metadados = json.loads(json_texto)
                    except:
                        pass
        
        # Tentar extrair análise (aceitar diferentes formatos)
        analise_markers = ["ANÁLISE:", "## ANÁLISE", "# ANÁLISE", "**ANÁLISE:**", "ANÁLISE QUALITATIVA:"]
        for marker in analise_markers:
            if marker.upper() in resposta.upper() or marker.replace("**", "").replace("#", "").upper() in resposta.upper():
                resposta_lower = resposta.lower()
                marker_lower = marker.lower().replace("**", "").replace("#", "")
                idx = resposta_lower.find(marker_lower)
                if idx >= 0:
                    analise = resposta[idx + len(marker):].strip()
                    # Remover markdown se houver
                    analise = re.sub(r'^\*\*', '', analise)
                    analise = re.sub(r'\*\*$', '', analise)
                    break
        
        if '--debug' in sys.argv:
            print(f"      📊 Extração: Resumo={'SIM' if resumo else 'NÃO'}, Metadados={'SIM' if metadados else 'NÃO'}, Análise={'SIM' if analise else 'NÃO'}")
            if resumo:
                print(f"         Resumo (primeiros 150 chars): {resumo[:150]}...")
            if metadados:
                print(f"         Metadados extraídos: gravidade={metadados.get('gravidade_denuncia')}, indice={metadados.get('indice_problema')}, estado={metadados.get('estado_denuncia')}, parado={metadados.get('processo_parado')}")
        
        # Extrair campos individuais dos metadados
        temas_principais = None
        gravidade_denuncia = None
        indice_problema = None
        estado_denuncia = None
        processo_parado = None
        tempo_parado_meses = None
        ultima_movimentacao_meses_atras = None
        tipo_processo = None
        relevancia_publica = None
        risco_penal = None
        probabilidade_condenacao = None
        
        if metadados:
            temas_principais = ', '.join(metadados.get('temas_principais', [])) if isinstance(metadados.get('temas_principais'), list) else None
            gravidade_denuncia = metadados.get('gravidade_denuncia') or metadados.get('gravidade')
            indice_problema = metadados.get('indice_problema')
            estado_denuncia = metadados.get('estado_denuncia') or metadados.get('status_atual')
            processo_parado = metadados.get('processo_parado')
            tempo_parado_meses = metadados.get('tempo_parado_meses')
            ultima_movimentacao_meses_atras = metadados.get('ultima_movimentacao_meses_atras')
            tipo_processo = metadados.get('tipo_processo')
            relevancia_publica = metadados.get('relevancia_publica')
            risco_penal = metadados.get('risco_penal')
            probabilidade_condenacao = metadados.get('probabilidade_condenacao')
        
        return {
            'resumo': resumo,
            'metadados': json.dumps(metadados, ensure_ascii=False) if metadados else None,
            'temas_principais': temas_principais,
            'gravidade_denuncia': gravidade_denuncia,
            'indice_problema': indice_problema,
            'estado_denuncia': estado_denuncia,
            'processo_parado': processo_parado,
            'tempo_parado_meses': tempo_parado_meses,
            'ultima_movimentacao_meses_atras': ultima_movimentacao_meses_atras,
            'tipo_processo': tipo_processo,
            'relevancia_publica': relevancia_publica,
            'risco_penal': risco_penal,
            'probabilidade_condenacao': probabilidade_condenacao,
            'analise_qualitativa': analise
        }
        
    except Exception as e:
        if '--debug' in sys.argv:
            import traceback
            print(f"      ❌ Erro ao gerar resumo/metadados com LLM: {e}")
            print(f"         Traceback: {traceback.format_exc()}")
        return {
            'resumo': None,
            'metadados': None,
            'temas_principais': None,
            'gravidade': None,
            'tipo_processo': None,
            'analise_qualitativa': None
        }

def atualizar_banco_com_colunas_llm():
    """Adiciona colunas para dados do LLM se não existirem."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Verificar colunas existentes
        colunas_existentes = [row[1] for row in cursor.execute("PRAGMA table_info(processos_stf)").fetchall()]
        
        novas_colunas = {
            'resumo_llm': 'TEXT',
            'metadados_llm': 'TEXT',
            'temas_principais': 'TEXT',
            'gravidade_denuncia': 'TEXT',
            'indice_problema': 'INTEGER',
            'estado_denuncia': 'TEXT',
            'processo_parado': 'INTEGER',  # 0 ou 1 (boolean)
            'tempo_parado_meses': 'INTEGER',
            'ultima_movimentacao_meses_atras': 'INTEGER',
            'tipo_processo': 'TEXT',
            'relevancia_publica': 'TEXT',
            'risco_penal': 'TEXT',
            'probabilidade_condenacao': 'TEXT',
            'analise_qualitativa': 'TEXT',
            'conteudo_textual': 'TEXT'  # JSON com conteúdo extraído
        }
        
        for coluna, tipo in novas_colunas.items():
            if coluna not in colunas_existentes:
                try:
                    cursor.execute(f"ALTER TABLE processos_stf ADD COLUMN {coluna} {tipo}")
                    print(f"✅ Coluna {coluna} adicionada")
                except sqlite3.OperationalError:
                    pass  # Coluna já existe
        
        conn.commit()
    finally:
        conn.close()

def main():
    print("=" * 80)
    print("📥 EXTRAÇÃO DE DADOS DETALHADOS DOS PROCESSOS STF (COM LLM)")
    print("=" * 80)
    print("\n💡 Este script extrai dados detalhados dos processos que já estão")
    print("   no banco, incluindo conteúdo textual e análise via LLM.")
    print("\n📋 Modos de operação:")
    print("   - Padrão: Processa apenas processos sem dados extraídos")
    print("   - --reprocessar-llm: Reprocessa processos sem dados do LLM")
    print("   - --atualizar-todos: Atualiza TODOS os processos (verifica mudanças)")
    print("   - --sem-llm: Apenas extração básica, sem LLM\n")
    
    # Verificar se deve usar LLM
    usar_llm = '--sem-llm' not in sys.argv
    if usar_llm:
        print("🤖 LLM habilitado: Resumos e metadados serão gerados")
    else:
        print("⚠️  LLM desabilitado: Apenas extração de dados básicos")
    
    # Atualizar banco com novas colunas
    print("\n📊 Atualizando estrutura do banco de dados...")
    atualizar_banco_com_colunas_llm()
    
    conn = get_db_connection()
    try:
        # Buscar processos sem dados extraídos ou sem dados do LLM
        # Modo --atualizar-todos: processa todos os processos para atualizar dados
        if '--atualizar-todos' in sys.argv:
            query = """
                SELECT id, nome_deputado, incidente, link_processo, cpf,
                       classe, assunto, relator, situacao, origem, data_extracao
                FROM processos_stf
                ORDER BY nome_deputado, incidente
            """
            print("🔄 Modo atualizar todos: Processando todos os processos para atualizar dados")
        elif '--reprocessar-llm' in sys.argv:
            query = """
                SELECT id, nome_deputado, incidente, link_processo, cpf,
                       classe, assunto, relator, situacao, origem, data_extracao
                FROM processos_stf
                WHERE resumo_llm IS NULL OR resumo_llm = ''
                ORDER BY nome_deputado, incidente
            """
            print("🔄 Modo reprocessar: Processando processos sem dados do LLM")
        else:
            query = """
                SELECT id, nome_deputado, incidente, link_processo, cpf,
                       classe, assunto, relator, situacao, origem, data_extracao
                FROM processos_stf
                WHERE data_extracao IS NULL
                ORDER BY nome_deputado, incidente
            """
        
        # Limitar quantidade se flag --limit estiver presente
        limit = None
        if '--limit' in sys.argv:
            try:
                idx = sys.argv.index('--limit')
                limit = int(sys.argv[idx + 1])
                query += f" LIMIT {limit}"
                print(f"🔢 Modo teste: Processando apenas {limit} processo(s)")
            except (ValueError, IndexError):
                pass
        
        df_processos = pd.read_sql_query(query, conn)
        
        if df_processos.empty:
            print("✅ Todos os processos já têm dados extraídos!")
            return
        
        print(f"📊 Encontrados {len(df_processos)} processos para processar\n")
        
        # Verificar se deve usar Playwright
        usar_playwright = '--requests' not in sys.argv
        
        if usar_playwright:
            try:
                from playwright.sync_api import sync_playwright
                print("🔧 Usando Playwright para extração\n")
            except ImportError:
                print("⚠️ Playwright não disponível, usando requests\n")
                usar_playwright = False
        else:
            print("🔧 Usando requests para extração\n")
        
        # Processar cada processo
        sucesso = 0
        erro = 0
        sucesso_llm = 0
        
        for idx, row in tqdm(df_processos.iterrows(), total=len(df_processos), desc="Extraindo dados"):
            processo_id = row['id']
            nome_deputado = row['nome_deputado']
            incidente = row['incidente']
            link_processo = row['link_processo']
            
            try:
                # Verificar dados existentes para comparar
                cursor_check = conn.cursor()
                cursor_check.execute("""
                    SELECT classe, assunto, relator, situacao, data_extracao, resumo_llm
                    FROM processos_stf
                    WHERE id = ?
                """, (processo_id,))
                dados_existentes = cursor_check.fetchone()
                
                # Extrair dados básicos do processo
                dados_extraidos = processo_module.extrair_dados_processo(link_processo, usar_playwright)
                dados_extraidos['data_extracao'] = time.strftime('%Y-%m-%d %H:%M:%S')
                
                # Verificar se houve mudanças nos dados básicos
                houve_mudanca_dados = False
                if dados_existentes:
                    dados_antigos = {
                        'classe': dados_existentes[0],
                        'assunto': dados_existentes[1],
                        'relator': dados_existentes[2],
                        'situacao': dados_existentes[3]
                    }
                    houve_mudanca_dados = (
                        dados_extraidos.get('classe') != dados_antigos.get('classe') or
                        dados_extraidos.get('assunto') != dados_antigos.get('assunto') or
                        dados_extraidos.get('relator') != dados_antigos.get('relator') or
                        dados_extraidos.get('situacao') != dados_antigos.get('situacao')
                    )
                    
                    if houve_mudanca_dados and '--debug' in sys.argv:
                        print(f"      🔄 Mudanças detectadas nos dados básicos do processo {incidente}")
                
                # Se não há dados do LLM ou houve mudanças, reprocessar LLM
                tem_llm = dados_existentes and dados_existentes[5] and dados_existentes[5].strip()
                deve_reprocessar_llm = not tem_llm or houve_mudanca_dados or '--atualizar-todos' in sys.argv
                
                # Extrair conteúdo textual adicional (apenas se necessário para LLM)
                conteudo_textual = None
                if deve_reprocessar_llm and usar_llm:
                    if usar_playwright:
                        from playwright.sync_api import sync_playwright
                    try:
                        with sync_playwright() as p:
                            browser = p.chromium.launch(headless=True)
                            context = browser.new_context(
                                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                            )
                            page = context.new_page()
                            try:
                                # Tentar com networkidle, se falhar tenta domcontentloaded
                                try:
                                    page.goto(link_processo, wait_until='networkidle', timeout=30000)
                                except:
                                    page.goto(link_processo, wait_until='domcontentloaded', timeout=30000)
                                
                                page.wait_for_timeout(2000)
                                html_content = page.content()
                                soup = BeautifulSoup(html_content, 'html.parser')
                                conteudo_textual = extrair_conteudo_textual(soup, html_content)
                            finally:
                                context.close()
                                browser.close()
                    except Exception as e:
                        if '--debug' in sys.argv:
                            print(f"      ⚠️  Erro ao extrair conteúdo textual (Playwright): {e}")
                        # Tentar com requests como fallback
                        import requests
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        }
                        try:
                            response = requests.get(link_processo, headers=headers, timeout=15, verify=False)
                            if response.status_code == 200:
                                soup = BeautifulSoup(response.content, 'html.parser')
                                conteudo_textual = extrair_conteudo_textual(soup, response.text)
                        except:
                            pass
                    else:
                        import requests
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        }
                        response = requests.get(link_processo, headers=headers, timeout=20, verify=False)
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.content, 'html.parser')
                            conteudo_textual = extrair_conteudo_textual(soup, response.text)
                
                # Gerar resumo e metadados com LLM (apenas se necessário)
                dados_llm = {}
                if usar_llm and deve_reprocessar_llm:
                    if conteudo_textual:
                        if '--debug' in sys.argv:
                            print(f"      🤖 Chamando LLM para gerar resumo e metadados...")
                        dados_llm = gerar_resumo_e_metadados_llm(
                            conteudo_textual,
                            dados_extraidos,
                            usar_llm=True
                        )
                        if dados_llm.get('resumo'):
                            sucesso_llm += 1
                            if '--debug' in sys.argv:
                                print(f"      ✅ Resumo LLM gerado com sucesso")
                        else:
                            if '--debug' in sys.argv:
                                print(f"      ⚠️  LLM não retornou resumo")
                    else:
                        if '--debug' in sys.argv:
                            print(f"      ⚠️  Conteúdo textual não disponível para LLM")
                
                # Atualizar no banco
                cursor = conn.cursor()
                
                # Preparar dados para atualização
                conteudo_json = json.dumps(conteudo_textual, ensure_ascii=False) if conteudo_textual else None
                
                # Converter processo_parado para 0/1
                processo_parado_int = 1 if dados_llm.get('processo_parado') else 0 if dados_llm.get('processo_parado') is False else None
                
                if '--debug' in sys.argv:
                    if deve_reprocessar_llm:
                        print(f"      💾 Salvando no banco: gravidade={dados_llm.get('gravidade_denuncia')}, indice={dados_llm.get('indice_problema')}, estado={dados_llm.get('estado_denuncia')}, parado={processo_parado_int}")
                    else:
                        print(f"      💾 Atualizando apenas dados básicos (sem reprocessar LLM)")
                
                # Se deve reprocessar LLM ou houve mudanças, atualizar tudo
                if deve_reprocessar_llm:
                    cursor.execute("""
                        UPDATE processos_stf 
                        SET classe = ?, assunto = ?, relator = ?, data_distribuicao = ?, 
                            situacao = ?, origem = ?, dados_processo = ?, data_extracao = ?,
                            resumo_llm = ?, metadados_llm = ?, temas_principais = ?,
                            gravidade_denuncia = ?, indice_problema = ?, estado_denuncia = ?,
                            processo_parado = ?, tempo_parado_meses = ?, ultima_movimentacao_meses_atras = ?,
                            tipo_processo = ?, relevancia_publica = ?, risco_penal = ?,
                            probabilidade_condenacao = ?, analise_qualitativa = ?,
                            conteudo_textual = ?
                        WHERE id = ?
                    """, (
                        dados_extraidos.get('classe'),
                        dados_extraidos.get('assunto'),
                        dados_extraidos.get('relator'),
                        dados_extraidos.get('data_distribuicao'),
                        dados_extraidos.get('situacao'),
                        dados_extraidos.get('origem'),
                        dados_extraidos.get('dados_processo'),
                        dados_extraidos.get('data_extracao'),
                        dados_llm.get('resumo'),
                        dados_llm.get('metadados'),
                        dados_llm.get('temas_principais'),
                        dados_llm.get('gravidade_denuncia'),
                        dados_llm.get('indice_problema'),
                        dados_llm.get('estado_denuncia'),
                        processo_parado_int,
                        dados_llm.get('tempo_parado_meses'),
                        dados_llm.get('ultima_movimentacao_meses_atras'),
                        dados_llm.get('tipo_processo'),
                        dados_llm.get('relevancia_publica'),
                        dados_llm.get('risco_penal'),
                        dados_llm.get('probabilidade_condenacao'),
                        dados_llm.get('analise_qualitativa'),
                        conteudo_json,
                        processo_id
                    ))
                else:
                    # Apenas atualizar dados básicos (sem reprocessar LLM)
                    cursor.execute("""
                        UPDATE processos_stf 
                        SET classe = ?, assunto = ?, relator = ?, data_distribuicao = ?, 
                            situacao = ?, origem = ?, dados_processo = ?, data_extracao = ?
                        WHERE id = ?
                    """, (
                        dados_extraidos.get('classe'),
                        dados_extraidos.get('assunto'),
                        dados_extraidos.get('relator'),
                        dados_extraidos.get('data_distribuicao'),
                        dados_extraidos.get('situacao'),
                        dados_extraidos.get('origem'),
                        dados_extraidos.get('dados_processo'),
                        dados_extraidos.get('data_extracao'),
                        processo_id
                    ))
                conn.commit()
                sucesso += 1
                
                # Delay entre requisições
                time.sleep(2 if usar_llm else 1)
                
            except Exception as e:
                erro += 1
                if '--debug' in sys.argv:
                    print(f"\n⚠️ Erro ao extrair dados do processo {incidente} ({nome_deputado}): {e}")
                continue
        
        print("\n" + "=" * 80)
        print("📊 RESUMO")
        print("=" * 80)
        print(f"✅ Processos processados com sucesso: {sucesso}")
        if usar_llm:
            print(f"🤖 Processos com análise LLM: {sucesso_llm}")
        print(f"⚠️ Processos com erro: {erro}")
        print(f"📊 Total processado: {sucesso + erro}")
        print("=" * 80)
        
    finally:
        conn.close()

if __name__ == "__main__":
    main()

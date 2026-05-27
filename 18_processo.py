#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para buscar processos dos deputados no STF usando CPF como referência.
Baseado em analise_STF_processo_senadores.ipynb
"""

import sqlite3
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
from tqdm import tqdm
import re
from datetime import datetime
import sys
import urllib3
import unicodedata

# Desabilitar avisos de SSL não verificado
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def normalizar_nome(nome):
    """Remove acentos e normaliza o nome para busca."""
    # Remove acentos
    nome_sem_acento = ''.join(
        c for c in unicodedata.normalize('NFD', nome)
        if unicodedata.category(c) != 'Mn'
    )
    return nome_sem_acento.upper().strip()



# Configurações
DB_PATH = "/Users/aislangreca/Library/Mobile Documents/com~apple~CloudDocs/Projetos_dados/acompanhamento_camara/dash2/tabelao.db"
DELAY_ENTRE_REQUISICOES = 2  # Delay entre requisições para evitar bloqueio
TIMEOUT = 30

# URL base do portal STF
STF_BASE_URL = "https://portal.stf.jus.br/processos/"

def get_db_connection():
    """Retorna conexão com o banco de dados."""
    return sqlite3.connect(DB_PATH)

def get_deputados_cpf():
    """Busca CPFs únicos dos deputados no banco de dados."""
    conn = get_db_connection()
    try:
        query = """
            SELECT DISTINCT 
                id,
                nome,
                nomeCivil,
                cpf,
                sgUF as estado,
                sgPartido as partido
            FROM tabelao
            WHERE cpf IS NOT NULL 
                AND cpf != ''
                AND cpf != '0'
                AND ultimoStatus_idLegislatura = 57
            ORDER BY nome
        """
        df = pd.read_sql_query(query, conn)
        # Limpar CPF (remover pontos, traços, espaços)
        df['cpf_limpo'] = df['cpf'].astype(str).str.replace(r'\D', '', regex=True)
        # Filtrar apenas CPFs válidos (11 dígitos)
        df = df[df['cpf_limpo'].str.len() == 11]
        # Usar nomeCivil (nome completo) se disponível, senão usar nome (nome eleitoral)
        df['nome_completo'] = df['nomeCivil'].fillna(df['nome'])
        df['nome_completo'] = df['nome_completo'].str.strip()
        return df
    finally:
        conn.close()

def buscar_processos_stf_por_nome(nome, cpf, usar_playwright=False):
    """
    Busca processos no STF usando nome completo do parlamentar.
    Tenta com acento e sem acento.
    Usa apenas a URL correta: listarPartes.asp
    """
    processos = []
    cpf_limpo = re.sub(r'\D', '', str(cpf))
    
    if len(cpf_limpo) != 11:
        return processos
    
    nome_limpo = str(nome).strip()
    if not nome_limpo:
        return processos
    
    # Importar urllib.parse para encoding correto
    from urllib.parse import quote
    
    # Gerar duas variações: com acento e sem acento
    nome_com_acento = nome_limpo
    nome_sem_acento = normalizar_nome(nome_limpo)
    
    # Lista de nomes para tentar (remover duplicatas se forem iguais)
    nomes_para_tentar = []
    if nome_com_acento != nome_sem_acento:
        nomes_para_tentar = [nome_com_acento, nome_sem_acento]
    else:
        nomes_para_tentar = [nome_com_acento]
    
    # Tentar cada variação do nome
    for nome_variacao in nomes_para_tentar:
        if processos:
            break  # Se já encontrou, parar
        
        # URL CORRETA: listarPartes.asp com termo codificado
        nome_codificado = quote(nome_variacao, safe='')
        url_busca = f"https://portal.stf.jus.br/processos/listarPartes.asp?processosEmTramitacao=sim&tipoPesquisa=PARTE&termo={nome_codificado}"
        
        if '--debug' in sys.argv:
            tipo_nome = "com acento" if nome_variacao == nome_com_acento else "sem acento"
            print(f"      🔍 Tentando nome {tipo_nome}: '{nome_variacao}'")
    
        if usar_playwright:
            # Método Playwright
            try:
                from playwright.sync_api import sync_playwright
                
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
                        viewport={'width': 1920, 'height': 1080}
                    )
                    page = context.new_page()
                    
                    try:
                        if '--debug' in sys.argv:
                            print(f"      🔗 URL: {url_busca[:100]}...")
                        page.goto(url_busca, wait_until='networkidle', timeout=30000)
                        page.wait_for_timeout(3000)
                        
                        # Aguardar por elementos de processo (se existirem)
                        try:
                            page.wait_for_selector("a[href*='incidente='], table, .processo, .resultado", timeout=5000)
                        except:
                            pass
                        
                        # Obter HTML da página
                        html_content = page.content()
                        soup = BeautifulSoup(html_content, 'html.parser')
                        
                        # Procurar links de processos
                        links_processos = []
                        
                        # Buscar via Playwright
                        links_playwright = page.query_selector_all("a[href*='incidente='], a[href*='detalhe.asp'], a[href*='detalheProcesso.asp']")
                        for link in links_playwright:
                            href = link.get_attribute('href')
                            if href:
                                links_processos.append({'href': href, 'text': link.inner_text().strip()})
                        
                        # Buscar via BeautifulSoup
                        links_soup = soup.find_all('a', href=re.compile(r'incidente=|detalhe\.asp|detalheProcesso\.asp', re.I))
                        for link in links_soup:
                            href = link.get('href', '')
                            if href:
                                links_processos.append({'href': href, 'text': link.get_text(strip=True)})
                        
                        # Buscar em tabelas e divs
                        tabelas = soup.find_all('table')
                        for tabela in tabelas:
                            links_tabela = tabela.find_all('a', href=re.compile(r'incidente=|detalhe\.asp|detalheProcesso\.asp', re.I))
                            for link in links_tabela:
                                href = link.get('href', '')
                                if href:
                                    links_processos.append({'href': href, 'text': link.get_text(strip=True)})
                        
                        divs = soup.find_all('div', class_=re.compile(r'processo|resultado|item', re.I))
                        for div in divs:
                            links_div = div.find_all('a', href=re.compile(r'incidente=|detalhe\.asp|detalheProcesso\.asp', re.I))
                            for link in links_div:
                                href = link.get('href', '')
                                if href:
                                    links_processos.append({'href': href, 'text': link.get_text(strip=True)})
                        
                        # Remover duplicatas
                        links_unicos = {}
                        for link_info in links_processos:
                            href = link_info['href']
                            if 'incidente=' in href:
                                links_unicos[href] = link_info
                        
                        # Processar links encontrados
                        incidentes_vistos = set()
                        for href, link_info in links_unicos.items():
                            incidente_match = re.search(r'incidente=(\d+)', href)
                            if incidente_match:
                                incidente = incidente_match.group(1)
                                
                                if incidente in incidentes_vistos:
                                    continue
                                incidentes_vistos.add(incidente)
                                
                                # Construir URL completa
                                if href.startswith('http'):
                                    url_completa = href
                                elif href.startswith('/'):
                                    url_completa = f"https://portal.stf.jus.br{href}"
                                else:
                                    url_completa = f"https://portal.stf.jus.br/processos/{href}"
                                
                                identificacao = link_info.get('text', '').strip() or f"Processo {incidente}"
                                
                                processos.append({
                                    'cpf': cpf_limpo,
                                    'incidente': incidente,
                                    'identificacao': identificacao,
                                    'link_processo': url_completa,
                                    'data_busca': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                })
                        
                        # Debug: salvar HTML se flag estiver ativa
                        if not processos and '--debug' in sys.argv:
                            with open(f'debug_stf_playwright_{nome_variacao[:10].replace(" ", "_")}.html', 'w', encoding='utf-8') as f:
                                f.write(html_content)
                            print(f"   📄 HTML salvo em debug_stf_playwright_{nome_variacao[:10].replace(' ', '_')}.html")
                        
                    finally:
                        context.close()
                        browser.close()
                        time.sleep(DELAY_ENTRE_REQUISICOES)
                        
            except ImportError:
                print("⚠️ Playwright não disponível. Instale com: pip install playwright && playwright install chromium")
            except Exception as e:
                if '--debug' in sys.argv:
                    print(f"      ⚠️  Erro ao buscar processos (Playwright) para {nome_variacao}: {str(e)[:100]}")
                continue
        else:
            # Método requests
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Referer': 'https://portal.stf.jus.br/processos/',
                }
                
                if '--debug' in sys.argv:
                    print(f"      🔗 URL: {url_busca[:100]}...")
                
                response = requests.get(url_busca, headers=headers, timeout=TIMEOUT, verify=False)
                
                if response.status_code == 200:
                    response.encoding = response.apparent_encoding or 'utf-8'
                    soup = BeautifulSoup(response.content, 'html.parser', from_encoding=response.encoding)
                    
                    # Buscar links de processos
                    links_processos = []
                    
                    links_diretos = soup.find_all('a', href=re.compile(r'incidente=|detalhe\.asp|detalheProcesso\.asp', re.I))
                    links_processos.extend(links_diretos)
                    
                    tabelas = soup.find_all('table')
                    for tabela in tabelas:
                        links_tabela = tabela.find_all('a', href=re.compile(r'incidente=|detalhe\.asp|detalheProcesso\.asp|processos', re.I))
                        links_processos.extend(links_tabela)
                    
                    divs = soup.find_all('div', class_=re.compile(r'processo|resultado|item', re.I))
                    for div in divs:
                        links_div = div.find_all('a', href=re.compile(r'incidente=|detalhe\.asp|detalheProcesso\.asp', re.I))
                        links_processos.extend(links_div)
                    
                    todos_links = soup.find_all('a', href=True)
                    for link in todos_links:
                        href = link.get('href', '')
                        if re.search(r'incidente=\d{6,}', href, re.I):
                            links_processos.append(link)
                    
                    # Remover duplicatas
                    links_processos = list(dict.fromkeys(links_processos))
                    
                    # Processar links encontrados
                    incidentes_vistos = set()
                    for link in links_processos:
                        href = link.get('href', '')
                        
                        incidente_match = re.search(r'incidente=(\d+)', href)
                        if incidente_match:
                            incidente = incidente_match.group(1)
                            
                            if incidente in incidentes_vistos:
                                continue
                            incidentes_vistos.add(incidente)
                            
                            if href.startswith('http'):
                                url_completa = href
                            elif href.startswith('/'):
                                url_completa = f"https://portal.stf.jus.br{href}"
                            else:
                                url_completa = f"https://portal.stf.jus.br/processos/{href}"
                            
                            identificacao = link.get_text(strip=True)
                            if not identificacao:
                                parent = link.parent
                                if parent:
                                    identificacao = parent.get_text(strip=True)
                            
                            processos.append({
                                'cpf': cpf_limpo,
                                'incidente': incidente,
                                'identificacao': identificacao or f"Processo {incidente}",
                                'link_processo': url_completa,
                                'data_busca': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            })
                    
                    # Debug: salvar HTML se flag estiver ativa
                    if not processos and '--debug' in sys.argv:
                        with open(f'debug_stf_{cpf_limpo[:5]}.html', 'w', encoding='utf-8') as f:
                            f.write(response.text)
                        print(f"   📄 HTML salvo em debug_stf_{cpf_limpo[:5]}.html")
                
                # Se encontrou processos, parar de tentar outras variações
                if processos:
                    break
                
                time.sleep(DELAY_ENTRE_REQUISICOES)
                
            except Exception as e:
                if '--debug' in sys.argv:
                    print(f"      ⚠️  Erro ao buscar processos (requests) para {nome_variacao}: {str(e)[:100]}")
                continue
    
    # Validar processos encontrados pelo CPF (se flag estiver ativa)
    if processos and '--validar-cpf' in sys.argv:
        processos_validados = []
        for processo in processos:
            print(f"      🔍 Validando processo {processo['incidente']} pelo CPF...")
            cpf_valido = validar_processo_por_cpf(processo['link_processo'], cpf_limpo, usar_playwright)
            if cpf_valido:
                processos_validados.append(processo)
            else:
                print(f"      ⚠️  Processo {processo['incidente']} não confere com CPF")
        processos = processos_validados
    
    return processos

def extrair_dados_processo(url_processo, usar_playwright=False):
    """
    Extrai dados detalhados do processo acessando o link.
    Retorna um dicionário com os dados extraídos.
    """
    dados = {
        'classe': None,
        'assunto': None,
        'relator': None,
        'data_distribuicao': None,
        'situacao': None,
        'origem': None,
        'dados_processo': None
    }
    
    try:
        if usar_playwright:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                
                try:
                    page.goto(url_processo, wait_until='networkidle', timeout=20000)
                    page.wait_for_timeout(3000)
                    
                    html_content = page.content()
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # Extrair dados da página
                    dados = extrair_dados_html(soup, html_content)
                    
                finally:
                    context.close()
                    browser.close()
        else:
            # Usar requests
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            response = requests.get(url_processo, headers=headers, timeout=20, verify=False)
            
            if response.status_code == 200:
                response.encoding = response.apparent_encoding or 'utf-8'
                soup = BeautifulSoup(response.content, 'html.parser', from_encoding=response.encoding)
                dados = extrair_dados_html(soup, response.text)
        
    except Exception as e:
        if '--debug' in sys.argv:
            print(f"      ⚠️  Erro ao extrair dados do processo: {e}")
    
    return dados

def extrair_dados_html(soup, html_content):
    """
    Extrai dados do processo do HTML parseado.
    Tenta diferentes estratégias para encontrar os campos.
    """
    dados = {
        'classe': None,
        'assunto': None,
        'relator': None,
        'data_distribuicao': None,
        'situacao': None,
        'origem': None,
        'dados_processo': None
    }
    
    # Estratégia 1: Buscar em tabelas
    tabelas = soup.find_all('table')
    for tabela in tabelas:
        linhas = tabela.find_all('tr')
        for linha in linhas:
            celulas = linha.find_all(['td', 'th'])
            if len(celulas) >= 2:
                label = celulas[0].get_text(strip=True).lower()
                valor = celulas[1].get_text(strip=True)
                
                if 'classe' in label or 'tipo' in label:
                    dados['classe'] = valor
                elif 'assunto' in label:
                    dados['assunto'] = valor
                elif 'relator' in label:
                    dados['relator'] = valor
                elif 'distribui' in label or 'data' in label and 'distrib' in label:
                    dados['data_distribuicao'] = valor
                elif 'situa' in label or 'status' in label:
                    dados['situacao'] = valor
                elif 'origem' in label:
                    dados['origem'] = valor
    
    # Estratégia 2: Buscar por labels/strong/bold
    labels = soup.find_all(['label', 'strong', 'b', 'span'], string=re.compile(r'classe|assunto|relator|distribui|situa|origem', re.I))
    for label in labels:
        texto_label = label.get_text(strip=True).lower()
        # Tentar pegar o próximo elemento ou o próximo texto
        proximo = label.find_next_sibling()
        if proximo:
            valor = proximo.get_text(strip=True)
            if 'classe' in texto_label:
                dados['classe'] = valor
            elif 'assunto' in texto_label:
                dados['assunto'] = valor
            elif 'relator' in texto_label:
                dados['relator'] = valor
            elif 'distribui' in texto_label:
                dados['data_distribuicao'] = valor
            elif 'situa' in texto_label:
                dados['situacao'] = valor
            elif 'origem' in texto_label:
                dados['origem'] = valor
    
    # Estratégia 3: Buscar por divs com classes específicas
    divs = soup.find_all('div', class_=re.compile(r'classe|assunto|relator|distribui|situa|origem|dados|info', re.I))
    for div in divs:
        texto = div.get_text(strip=True)
        if ':' in texto:
            partes = texto.split(':', 1)
            if len(partes) == 2:
                label = partes[0].strip().lower()
                valor = partes[1].strip()
                
                if 'classe' in label:
                    dados['classe'] = valor
                elif 'assunto' in label:
                    dados['assunto'] = valor
                elif 'relator' in label:
                    dados['relator'] = valor
                elif 'distribui' in label:
                    dados['data_distribuicao'] = valor
                elif 'situa' in label:
                    dados['situacao'] = valor
                elif 'origem' in label:
                    dados['origem'] = valor
    
    # Salvar HTML completo como fallback (limitado a 5000 caracteres)
    dados['dados_processo'] = html_content[:5000] if len(html_content) > 5000 else html_content
    
    return dados

def validar_processo_por_cpf(url_processo, cpf_esperado, usar_playwright=False):
    """
    Valida se um processo pertence ao CPF informado.
    Acessa a página do processo e verifica o CPF.
    """
    try:
        if usar_playwright:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                
                try:
                    page.goto(url_processo, wait_until='networkidle', timeout=20000)
                    page.wait_for_timeout(2000)
                    
                    # Buscar CPF na página
                    html_content = page.content()
                    cpf_encontrado = re.search(r'\b\d{11}\b', html_content)
                    
                    if cpf_encontrado:
                        cpf_pagina = cpf_encontrado.group(0)
                        return cpf_pagina == cpf_esperado
                    
                finally:
                    context.close()
                    browser.close()
        else:
            # Usar requests
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            response = requests.get(url_processo, headers=headers, timeout=15, verify=False)
            
            if response.status_code == 200:
                # Buscar CPF no conteúdo
                cpf_encontrado = re.search(r'\b\d{11}\b', response.text)
                if cpf_encontrado:
                    cpf_pagina = cpf_encontrado.group(0)
                    return cpf_pagina == cpf_esperado
        
        # Se não encontrou CPF, assumir que é válido (pode não estar na página)
        return True
        
    except Exception as e:
        # Em caso de erro, assumir válido para não perder processos
        if '--debug' in sys.argv:
            print(f"      ⚠️  Erro ao validar CPF: {e}")
        return True

def criar_tabela_processos_stf():
    """Cria a tabela para armazenar processos do STF se não existir."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processos_stf (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_deputado INTEGER,
                nome_deputado TEXT,
                cpf TEXT,
                estado TEXT,
                partido TEXT,
                incidente TEXT,
                identificacao TEXT,
                link_processo TEXT,
                data_busca TEXT,
                data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
                -- Dados extraídos do processo
                classe TEXT,
                assunto TEXT,
                relator TEXT,
                data_distribuicao TEXT,
                situacao TEXT,
                origem TEXT,
                dados_processo TEXT,
                data_extracao TEXT,
                FOREIGN KEY (id_deputado) REFERENCES tabelao(id)
            )
        """)
        
        # Adicionar novas colunas se não existirem (para tabelas já criadas)
        colunas_existentes = [row[1] for row in cursor.execute("PRAGMA table_info(processos_stf)").fetchall()]
        novas_colunas = {
            'classe': 'TEXT',
            'assunto': 'TEXT',
            'relator': 'TEXT',
            'data_distribuicao': 'TEXT',
            'situacao': 'TEXT',
            'origem': 'TEXT',
            'dados_processo': 'TEXT',
            'data_extracao': 'TEXT'
        }
        
        for coluna, tipo in novas_colunas.items():
            if coluna not in colunas_existentes:
                try:
                    cursor.execute(f"ALTER TABLE processos_stf ADD COLUMN {coluna} {tipo}")
                except sqlite3.OperationalError:
                    pass  # Coluna já existe
        
        # Criar índices
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_processos_stf_cpf ON processos_stf(cpf)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_processos_stf_id_deputado ON processos_stf(id_deputado)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_processos_stf_incidente ON processos_stf(incidente)")
        
        conn.commit()
        print("✅ Tabela processos_stf criada/verificada com sucesso")
    finally:
        conn.close()

def salvar_processos(processos, id_deputado, nome_deputado, estado, partido, extrair_detalhes=True, usar_playwright=False):
    """
    Salva processos no banco de dados.
    Se extrair_detalhes=True, acessa cada link para extrair dados adicionais.
    """
    if not processos:
        return
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        for processo in processos:
            try:
                # Verificar se o processo já existe
                cursor.execute("""
                    SELECT id, classe, assunto, relator, situacao, data_extracao
                    FROM processos_stf
                    WHERE incidente = ? AND cpf = ?
                """, (processo['incidente'], processo['cpf']))
                processo_existente = cursor.fetchone()
                
                # Extrair dados do processo se necessário
                if extrair_detalhes:
                    # Extrair dados do processo
                    if '--debug' in sys.argv:
                        if processo_existente:
                            print(f"      🔄 Atualizando dados do processo {processo['incidente']}...")
                        else:
                            print(f"      📥 Extraindo dados do processo {processo['incidente']}...")
                    dados_extraidos = extrair_dados_processo(processo['link_processo'], usar_playwright)
                    dados_extraidos['data_extracao'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                else:
                    dados_extraidos = {
                        'classe': None, 'assunto': None, 'relator': None,
                        'data_distribuicao': None, 'situacao': None, 'origem': None,
                        'dados_processo': None, 'data_extracao': None
                    }
                
                if processo_existente:
                    # Processo já existe - atualizar apenas se houver mudanças
                    processo_id = processo_existente[0]
                    dados_antigos = {
                        'classe': processo_existente[1],
                        'assunto': processo_existente[2],
                        'relator': processo_existente[3],
                        'situacao': processo_existente[4],
                        'data_extracao': processo_existente[5]
                    }
                    
                    # Verificar se houve mudanças nos dados principais
                    houve_mudanca = (
                        dados_extraidos.get('classe') != dados_antigos.get('classe') or
                        dados_extraidos.get('assunto') != dados_antigos.get('assunto') or
                        dados_extraidos.get('relator') != dados_antigos.get('relator') or
                        dados_extraidos.get('situacao') != dados_antigos.get('situacao')
                    )
                    
                    if houve_mudanca or extrair_detalhes:
                        # Atualizar processo existente
                        cursor.execute("""
                            UPDATE processos_stf 
                            SET identificacao = ?, link_processo = ?, data_busca = ?,
                                classe = ?, assunto = ?, relator = ?, data_distribuicao = ?, 
                                situacao = ?, origem = ?, dados_processo = ?, data_extracao = ?
                            WHERE id = ?
                        """, (
                            processo['identificacao'],
                            processo['link_processo'],
                            processo['data_busca'],
                            dados_extraidos['classe'],
                            dados_extraidos['assunto'],
                            dados_extraidos['relator'],
                            dados_extraidos['data_distribuicao'],
                            dados_extraidos['situacao'],
                            dados_extraidos['origem'],
                            dados_extraidos['dados_processo'],
                            dados_extraidos['data_extracao'],
                            processo_id
                        ))
                        if '--debug' in sys.argv and houve_mudanca:
                            print(f"      ✅ Processo {processo['incidente']} atualizado (houve mudanças)")
                    else:
                        # Apenas atualizar data_busca
                        cursor.execute("""
                            UPDATE processos_stf 
                            SET data_busca = ?
                            WHERE id = ?
                        """, (processo['data_busca'], processo_id))
                else:
                    # Inserir novo processo
                    cursor.execute("""
                        INSERT INTO processos_stf 
                        (id_deputado, nome_deputado, cpf, estado, partido, 
                         incidente, identificacao, link_processo, data_busca,
                         classe, assunto, relator, data_distribuicao, 
                         situacao, origem, dados_processo, data_extracao)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        id_deputado,
                        nome_deputado,
                        processo['cpf'],
                        estado,
                        partido,
                        processo['incidente'],
                        processo['identificacao'],
                        processo['link_processo'],
                        processo['data_busca'],
                        dados_extraidos['classe'],
                        dados_extraidos['assunto'],
                        dados_extraidos['relator'],
                        dados_extraidos['data_distribuicao'],
                        dados_extraidos['situacao'],
                        dados_extraidos['origem'],
                        dados_extraidos['dados_processo'],
                        dados_extraidos['data_extracao']
                    ))
                
                # Delay entre extrações para não sobrecarregar o servidor
                if extrair_detalhes:
                    time.sleep(1)
                    
            except sqlite3.IntegrityError:
                # Processo já existe (pode acontecer em caso de race condition)
                # Tentar atualizar
                if '--debug' in sys.argv:
                    print(f"      ⚠️  Conflito de integridade no processo {processo['incidente']}, tentando atualizar...")
                try:
                    cursor.execute("""
                        UPDATE processos_stf 
                        SET data_busca = ?, link_processo = ?
                        WHERE incidente = ? AND cpf = ?
                    """, (processo['data_busca'], processo['link_processo'], 
                          processo['incidente'], processo['cpf']))
                except:
                    pass
        
        conn.commit()
    finally:
        conn.close()

def main():
    """Função principal."""
    print("=" * 80)
    print("🔍 BUSCA DE PROCESSOS DOS DEPUTADOS NO STF")
    print("=" * 80)
    print("\n💡 Dicas:")
    print("   - Por padrão, usa Playwright e busca por NOME do parlamentar")
    print("   - Por padrão, extrai dados detalhados de cada processo (classe, assunto, relator, etc.)")
    print("   - Use --requests para forçar uso de requests (mais rápido, mas pode não funcionar)")
    print("   - Use --sem-detalhes para não extrair dados detalhados dos processos (mais rápido)")
    print("   - Use --debug para salvar HTML das páginas para análise")
    print("   - Use --validar-cpf para validar cada processo pelo CPF (mais lento, mas mais preciso)")
    print("   Exemplo: python 18_processo.py --debug --validar-cpf\n")
    
    # Criar tabela se não existir
    criar_tabela_processos_stf()
    
    # Buscar deputados com CPF
    print("\n📊 Buscando deputados com CPF no banco de dados...")
    df_deputados = get_deputados_cpf()
    
    if df_deputados.empty:
        print("⚠️ Nenhum deputado com CPF encontrado no banco de dados.")
        return
    
    print(f"✅ Encontrados {len(df_deputados)} deputados com CPF válido")
    
    # Buscar todos os processos já existentes no banco (para verificar rapidamente)
    conn = get_db_connection()
    try:
        df_processos_existentes = pd.read_sql_query("""
            SELECT DISTINCT cpf, incidente FROM processos_stf
        """, conn)
        # Criar set de tuplas (cpf, incidente) para busca rápida O(1)
        processos_existentes = set(zip(df_processos_existentes['cpf'].astype(str), df_processos_existentes['incidente'].astype(str)))
    finally:
        conn.close()
    
    print(f"📋 Verificando TODOS os {len(df_deputados)} deputados para processos novos...")
    print(f"📊 Processos já no banco: {len(processos_existentes)}\n")
    
    total_processos = 0
    processos_novos = 0
    processos_existentes_skip = 0
    
    # Processar TODOS os deputados
    for idx, row in tqdm(df_deputados.iterrows(), total=len(df_deputados), desc="Buscando processos"):
        id_deputado = row['id']
        nome_eleitoral = row['nome']
        nome_completo = row.get('nome_completo', row['nome'])  # Usar nome completo se disponível
        cpf = row['cpf_limpo']
        estado = row['estado']
        partido = row['partido']
        
        print(f"\n🔍 Buscando processos para: {nome_eleitoral} (CPF: {cpf[:3]}***{cpf[-2:]})")
        print(f"   📝 Nome eleitoral: '{nome_eleitoral}'")
        print(f"   📝 Nome completo: '{nome_completo}'")
        print(f"   🔍 Buscando por NOME COMPLETO: '{nome_completo}'")
        
        # Buscar processos por NOME COMPLETO (não por CPF, não por nome eleitoral)
        # Usar Playwright por padrão já que a página requer JavaScript
        usar_playwright_flag = len(sys.argv) > 1 and '--playwright' in sys.argv
        usar_requests_flag = len(sys.argv) > 1 and '--requests' in sys.argv
        
        # Se --requests foi passado explicitamente, usar requests. Senão, usar Playwright
        usar_playwright_para_busca = False
        if usar_requests_flag:
            print(f"   🔧 Usando método: requests")
            processos = buscar_processos_stf_por_nome(nome_completo, cpf, usar_playwright=False)
        else:
            # Tentar Playwright primeiro (mais eficaz para páginas com JavaScript)
            try:
                from playwright.sync_api import sync_playwright
                print(f"   🔧 Usando método: Playwright")
                usar_playwright_para_busca = True
                processos = buscar_processos_stf_por_nome(nome_completo, cpf, usar_playwright=True)
            except ImportError:
                # Se Playwright não estiver disponível, tentar requests
                print(f"   ⚠️  Playwright não disponível, usando requests...")
                processos = buscar_processos_stf_por_nome(nome_completo, cpf, usar_playwright=False)
        
        # Verificar se deve extrair detalhes (por padrão sim, mas pode ser desabilitado com --sem-detalhes)
        extrair_detalhes = '--sem-detalhes' not in sys.argv
        
        if processos:
            # Filtrar apenas processos novos (que não estão no banco)
            processos_novos_lista = []
            for processo in processos:
                chave = (processo['cpf'], processo['incidente'])
                if chave not in processos_existentes:
                    processos_novos_lista.append(processo)
                    processos_existentes.add(chave)  # Adicionar ao set para próximas verificações
                else:
                    processos_existentes_skip += 1
            
            if processos_novos_lista:
                print(f"   ✅ Encontrados {len(processos)} processo(s) - {len(processos_novos_lista)} novo(s), {len(processos) - len(processos_novos_lista)} já existente(s)")
                salvar_processos(processos_novos_lista, id_deputado, nome_eleitoral, estado, partido, 
                               extrair_detalhes=extrair_detalhes, usar_playwright=usar_playwright_para_busca)
                processos_novos += len(processos_novos_lista)
                total_processos += len(processos_novos_lista)
            else:
                print(f"   ⏭️  Encontrados {len(processos)} processo(s) - todos já existem no banco, pulando...")
        else:
            print(f"   ⚠️  Nenhum processo encontrado")
        
        # Delay entre requisições
        time.sleep(DELAY_ENTRE_REQUISICOES)
    
    # Resumo final
    print("\n" + "=" * 80)
    print("📊 RESUMO")
    print("=" * 80)
    print(f"✅ Deputados verificados: {len(df_deputados)}")
    print(f"✅ Processos novos encontrados e salvos: {processos_novos}")
    print(f"⏭️  Processos já existentes (pulados): {processos_existentes_skip}")
    print(f"📊 Total de processos no banco: {len(processos_existentes) + processos_novos}")
    
    # Estatísticas finais
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM processos_stf")
        total_banco = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT id_deputado) FROM processos_stf")
        deputados_com_processos = cursor.fetchone()[0]
        
        print(f"✅ Total de processos no banco: {total_banco}")
        print(f"✅ Deputados com processos: {deputados_com_processos}")
    finally:
        conn.close()
    
    print("\n" + "=" * 80)
    print("✅ Processo concluído!")
    print("=" * 80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Processo interrompido pelo usuário.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Erro fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)













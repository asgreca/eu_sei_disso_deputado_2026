#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para coletar dados de emendas parlamentares do Portal da Transparência
e armazenar em 3 tabelas no banco de dados tabelao.db:
1. emendas - Dados principais das emendas
2. documentos_emendas - Documentos relacionados às emendas
3. convenios_emendas - Convênios relacionados às emendas

Para cada CNPJ encontrado nos documentos, busca dados do fornecedor e coordenadas.
Baseado no notebook emendas.ipynb
"""

import os
import sys
import time
import re
import asyncio
import pandas as pd
import sqlite3
import httpx
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from tqdm import tqdm
from dotenv import load_dotenv
from geopy.geocoders import ArcGIS
from geopy.extra.rate_limiter import RateLimiter
from io import StringIO
import numpy as np
import unicodedata

# Carregar variáveis de ambiente
load_dotenv()

# -------------------------------------------------------------------
# CONFIGURAÇÕES: Altere estas variáveis
# -------------------------------------------------------------------

API_KEY = os.getenv("TRANSPARENCIA")
if not API_KEY or API_KEY == "SUA_CHAVE_API_AQUI":
    raise ValueError("Variável TRANSPARENCIA não encontrada no .env. Configure a chave da API do Portal da Transparência.")
# -------------------------------------------------------------------
# INÍCIO DAS CONFIGURAÇÕES
# -------------------------------------------------------------------


# 2. Anos para pesquisar
ANOS_PESQUISA = [2023, 2024, 2025, 2026]
START_FROM_DEPUTADO = 230  # Retomar a partir deste índice (1-based). 0 = começo.


# 3. URL dos deputados
DEPUTADOS_URL = "https://dadosabertos.camara.leg.br/arquivos/deputados/csv/deputados.csv"

# 4. Nome do arquivo de saída (backup)
NOME_ARQUIVO_SAIDA = "emendas_consolidado_append.csv"

# 5. Configuração do Banco de Dados
DB_NAME = "tabelao.db"
TABLE_NAME = "emenda"
TABLE_BASE = "emendas_base"
TABLE_DOCUMENTOS = "emendas_documentos"
TABLE_CONVENIOS = "emendas_convenios"

DB_PATH = DB_NAME

# API Pública (Passo 1)
API_PUBLICA_URL = "https://api.portaldatransparencia.gov.br/api-de-dados/emendas"
API_PUBLICA_HEADERS = {"chave-api-dados": API_KEY}

# Endereços de Scraping (Passo 2)
HTML_DETALHE_URL = "https://portaldatransparencia.gov.br/emendas/detalhe"

# URL dos deputados
DEPUTADOS_URL = "https://dadosabertos.camara.leg.br/arquivos/deputados/csv/deputados.csv"

# Banco de dados
DB_PATH = "tabelao.db"

# Configurações de geocoding
geolocator = ArcGIS(user_agent="emendas_app/1.0")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=0.5, max_retries=2, error_wait_seconds=5.0, swallow_exceptions=True)
BATCH_SIZE = 50

# =============================================================================
# FUNÇÕES DO NOTEBOOK (MANTIDAS IGUAIS)
# =============================================================================

async def passo_1_buscar_codigos_emenda(client, nome_autor, ano):
    """
    Passo 1: Usa a API pública para buscar os códigos de emenda.
    """

    pagina = 1
    lista_codigos = []
    print(f"--- PASSO 1: Buscando códigos de '{nome_autor}' para {ano} ---")

    while True:
        params = {"nomeAutor": nome_autor, "ano": ano, "pagina": pagina}
        try:
            response = await client.get(API_PUBLICA_URL, params=params)
            response.raise_for_status()
            dados_pagina = response.json()

            if not dados_pagina:
                if pagina == 1:
                    print(f"Nenhuma emenda encontrada para '{nome_autor}' em {ano}.")
                else:
                    print("Fim da busca por códigos.")
                break
            
            print(f"Coletando códigos da página {pagina}...")
            for item in dados_pagina:
                if 'codigoEmenda' in item:
                    lista_codigos.append(item['codigoEmenda'])
            
            pagina += 1
            await asyncio.sleep(0.5)
            
        except httpx.HTTPStatusError as err:
            if err.response.status_code == 401:
                print("\nErro 401: Chave da API inválida.", file=sys.stderr)
            else:
                print(f"\nErro HTTP no Passo 1 (API Pública): {err}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"\nErro inesperado no Passo 1: {e}", file=sys.stderr)
            return []

    return lista_codigos

def _get_value_by_label(soup, label):
    """Função auxiliar (síncrona) para o scraping com BeautifulSoup."""
    try:
        label_tag = soup.find('strong', string=lambda t: t and label.lower() in t.lower().strip())
        if label_tag:
            value_tag = label_tag.find_next_sibling('span')
            if value_tag:
                return value_tag.text.strip()
    except Exception:
        pass
    return 'N/A'

async def passo_2_raspar_com_playwright(page, codigo_emenda):
    """
    Passo 2: Usa o Playwright para carregar a página, clicar em TUDO,
    e raspar o HTML final.
    """

    print(f"  > P2: Navegando para a emenda {codigo_emenda}...")
    url_html = f"{HTML_DETALHE_URL}?codigoEmenda={codigo_emenda}"

    base_info = {}  # Informações do topo da página
    documentos_encontrados = []  # Tabela 1
    convenios_encontrados = []  # Tabela 2

    try:
        await page.goto(url_html, wait_until='domcontentloaded', timeout=20000)
        await page.wait_for_timeout(1000)

        # --- ETAPA 1: Clicar no Cookie ---
        print("     ...procurando e clicando no banner de cookies...")
        try:
            await page.locator('text="Aceitar todos"').click(timeout=5000)
            print("     ...banner de cookies aceito.")
            await page.wait_for_timeout(1000)  # Espera 1s pro banner sumir
        except PlaywrightTimeoutError:
            print("     ...banner de cookies não encontrado (provavelmente já aceito).")

        # --- ETAPA 2: Clicar na aba "Documentos" ---
        print("     ...clicando na aba 'DOCUMENTOS RELACIONADOS'...")
        documentos_clicked = False
        tabela_docs_encontrada = False
        
        try:
            # Aguardar a página carregar completamente
            await page.wait_for_load_state('networkidle', timeout=10000)
            await page.wait_for_timeout(2000)
            
            # Tentar clicar usando JavaScript primeiro (mais confiável)
            try:
                await page.evaluate("""
                    () => {
                        const elemento = document.querySelector('#dados-detalhados-titulo-documentos-relacionados');
                        if (elemento) {
                            elemento.click();
                            return true;
                        }
                        return false;
                    }
                """)
                documentos_clicked = True
                print("     ✅ Clicou na aba Documentos (JavaScript)")
            except:
                # Tentar com Playwright locator
                try:
                    elemento = page.locator("#dados-detalhados-titulo-documentos-relacionados")
                    if await elemento.count() > 0:
                        await elemento.scroll_into_view_if_needed()
                        await page.wait_for_timeout(500)
                        await elemento.click(timeout=5000)
                        documentos_clicked = True
                        print("     ✅ Clicou na aba Documentos (Playwright)")
                except:
                    # Tentar por texto
                    try:
                        await page.locator('text="DOCUMENTOS RELACIONADOS"').click(timeout=5000)
                        documentos_clicked = True
                        print("     ✅ Clicou na aba Documentos (Texto)")
                    except:
                        pass
            
            if documentos_clicked:
                await page.wait_for_timeout(1000)
                try:
                    await page.wait_for_selector("#documentos-relacionados tbody tr", timeout=10000)
                    await page.wait_for_timeout(500)
                except PlaywrightTimeoutError:
                    pass
                try:
                    await page.wait_for_selector("#documentos-relacionados_info", timeout=5000)
                    tabela_docs_encontrada = True
                    print("     ✅ Tabela 'Documentos' encontrada e carregada")
                except:
                    try:
                        await page.wait_for_selector("#documentos-relacionados", timeout=5000)
                        await page.wait_for_timeout(500)
                        tabela_docs_encontrada = True
                        print("     ✅ Tabela 'Documentos' encontrada")
                    except:
                        print("     ⚠️  Tabela 'Documentos' não encontrada (pode não ter docs)")
                if tabela_docs_encontrada:
                    try:
                        linhas_preview = await page.eval_on_selector_all(
                            "#documentos-relacionados tbody tr",
                            "els => els.map(e => e.innerText)"
                        )
                        linhas_validas = [l for l in linhas_preview if l and 'Nenhum documento' not in l]
                        print(f"     ℹ️  {len(linhas_validas)} linhas detectadas na tabela de documentos (antes do parsing)")
                    except Exception:
                        pass
            else:
                print("     ⚠️  Não foi possível clicar na aba Documentos")
        except Exception as e:
            print(f"     ⚠️  Erro ao clicar/esperar por Documentos: {e}")

        # --- ETAPA 3: Clicar na aba "Convênios" ---
        print("     ...clicando na aba 'CONVÊNIOS'...")
        convenios_clicked = False
        tabela_conv_encontrada = False
        
        try:
            await page.wait_for_timeout(1000)
            
            # Tentar clicar usando JavaScript primeiro (mais confiável)
            try:
                await page.evaluate("""
                    () => {
                        const elemento = document.querySelector('#dados-detalhados-titulo-convenios');
                        if (elemento) {
                            elemento.click();
                            return true;
                        }
                        return false;
                    }
                """)
                convenios_clicked = True
                print("     ✅ Clicou na aba Convênios (JavaScript)")
            except:
                # Tentar com Playwright locator
                try:
                    elemento = page.locator("#dados-detalhados-titulo-convenios")
                    if await elemento.count() > 0:
                        await elemento.scroll_into_view_if_needed()
                        await page.wait_for_timeout(500)
                        await elemento.click(timeout=5000)
                        convenios_clicked = True
                        print("     ✅ Clicou na aba Convênios (Playwright)")
                except:
                    # Tentar por texto
                    try:
                        await page.locator('text="CONVÊNIOS"').click(timeout=5000)
                        convenios_clicked = True
                        print("     ✅ Clicou na aba Convênios (Texto)")
                    except:
                        pass
            
            if convenios_clicked:
                await page.wait_for_timeout(1000)
                try:
                    await page.wait_for_selector("#convenios-relacionados tbody tr", timeout=10000)
                    await page.wait_for_timeout(500)
                except PlaywrightTimeoutError:
                    pass
                try:
                    await page.wait_for_selector("#convenios-relacionados_info", timeout=5000)
                    tabela_conv_encontrada = True
                    print("     ✅ Tabela 'Convênios' encontrada e carregada")
                except:
                    try:
                        await page.wait_for_selector("#convenios-relacionados", timeout=5000)
                        await page.wait_for_timeout(500)
                        tabela_conv_encontrada = True
                        print("     ✅ Tabela 'Convênios' encontrada")
                    except:
                        print("     ⚠️  Tabela 'Convênios' não encontrada (pode não ter convênios)")
                if tabela_conv_encontrada:
                    try:
                        linhas_conv_preview = await page.eval_on_selector_all(
                            "#convenios-relacionados tbody tr",
                            "els => els.map(e => e.innerText)"
                        )
                        linhas_conv_validas = [l for l in linhas_conv_preview if l and 'Nenhum convênio' not in l]
                        print(f"     ℹ️  {len(linhas_conv_validas)} linhas detectadas na tabela de convênios (antes do parsing)")
                    except Exception:
                        pass
            else:
                print("     ⚠️  Não foi possível clicar na aba Convênios")
        except Exception as e:
            print(f"     ⚠️  Erro ao clicar/esperar por Convênios: {e}")

        # --- ETAPA 4: Raspar TUDO ---
        print("     ...raspando o HTML final...")
        html_final = await page.content()
        soup = BeautifulSoup(html_final, 'lxml')

        # Dicionário com os dados principais da emenda
        base_info = {
            "Código Emenda": codigo_emenda,
            "Autor/Emenda": _get_value_by_label(soup, "Autor/Emenda"),
            "Tipo de Emenda": _get_value_by_label(soup, "Tipo de Emenda"),
            "Localidade Emenda": _get_value_by_label(soup, "Localidade da Emenda"),
            "Ano Emenda": _get_value_by_label(soup, "Ano da Emenda"),
            "Valor Empenhado": _get_value_by_label(soup, "Valor da Emenda (Empenhado)"),
            "Valor Liquidado": _get_value_by_label(soup, "Valor da Emenda (Liquidado)"),
            "Valor Pago": _get_value_by_label(soup, "Valor da Emenda (Pago)"),
            "Valor RP Inscritos": _get_value_by_label(soup, "Valor Restos a Pagar Inscritos"),
            "Valor RP Cancelados": _get_value_by_label(soup, "Valor Restos a Pagar Cancelados"),
            "Valor RP Pagos": _get_value_by_label(soup, "Valor Restos a Pagar Pagos"),
            "Função": _get_value_by_label(soup, "Área de Atuação (Função)"),
            "Subfunção": _get_value_by_label(soup, "Subfunção"),
            "Programa": _get_value_by_label(soup, "Programa"),
            "Ação": _get_value_by_label(soup, "Ação"),
            "Plano Orçamentário": _get_value_by_label(soup, "Plano Orçamentário - PO")
        }

    except Exception as e:
        print(f"\nErro inesperado no Passo 2 (Playwright) para {codigo_emenda}: {e}", file=sys.stderr)
        return []  # Retorna vazio se a página inteira falhar

    # --- Raspar a TABELA 1: Documentos ---
    try:
        tabela_doc = soup.find('table', id='documentos-relacionados')
        if tabela_doc:
            tbody = tabela_doc.find('tbody')
            if tbody:
                linhas_doc = tbody.find_all('tr')
                if linhas_doc and not linhas_doc[0].find('td', class_='dataTables_empty'):
                    for linha in linhas_doc:
                        colunas = linha.find_all('td')
                        if len(colunas) == 5:
                            link_tag = colunas[2].find('a')
                            doc_link = "N/A"
                            if link_tag and link_tag.has_attr('href'):
                                if link_tag['href'].startswith('http'):
                                    doc_link = link_tag['href']
                                else:
                                    doc_link = "https://portaldatransparencia.gov.br" + link_tag['href']

                            documentos_encontrados.append({
                                "Doc Data": colunas[0].text.strip(),
                                "Doc Fase": colunas[1].text.strip(),
                                "Doc Número": colunas[2].text.strip(),
                                "Doc Link": doc_link,
                                "Doc Favorecido Nome": colunas[3].text.strip(),
                                "Doc Valor": colunas[4].text.strip()
                            })
    except Exception as e:
        print(f"\nErro inesperado ao raspar a tabela de Documentos: {e}", file=sys.stderr)

    # --- Raspar a TABELA 2: Convênios ---
    try:
        tabela_conv = soup.find('table', id='convenios-relacionados')
        if tabela_conv:
            tbody = tabela_conv.find('tbody')
            if tbody:
                linhas_conv = tbody.find_all('tr')
                if linhas_conv and not linhas_conv[0].find('td', class_='dataTables_empty'):
                    for linha in linhas_conv:
                        colunas = linha.find_all('td')
                        if len(colunas) == 5:
                            convenios_encontrados.append({
                                "Conv Número": colunas[0].text.strip(),
                                "Conv Objeto": colunas[1].text.strip(),
                                "Conv Situação": colunas[2].text.strip(),
                                "Conv Vigência": colunas[3].text.strip(),
                                "Conv Valor": colunas[4].text.strip()
                            })
    except Exception as e:
        print(f"\nErro inesperado ao raspar a tabela de Convênios: {e}", file=sys.stderr)

    # --- Combinação dos Dados (EXATAMENTE COMO NO NOTEBOOK) ---
    linhas_dataframe = []
    # Se não achou NADA, salva só a info base
    if not documentos_encontrados and not convenios_encontrados:
        print("  > Concluído. Nenhuma tabela de Documento ou Convênio encontrada.")
        linhas_dataframe.append(base_info)

    # Se achou Documentos, salva eles
    if documentos_encontrados:
        print(f"  > Sucesso! Encontrados {len(documentos_encontrados)} documentos.")
        for doc in documentos_encontrados:
            linha_completa = base_info.copy()
            linha_completa.update(doc)
            linhas_dataframe.append(linha_completa)

    # Se achou Convênios, salva eles
    if convenios_encontrados:
        print(f"  > Sucesso! Encontrados {len(convenios_encontrados)} convênios.")
        for conv in convenios_encontrados:
            linha_completa = base_info.copy()
            linha_completa.update(conv)
            linhas_dataframe.append(linha_completa)

    return linhas_dataframe

# =============================================================================
# FUNÇÕES AUXILIARES PARA CNPJ E GEOCODING (DO 00_tabelao.py)
# =============================================================================

def limpar_cep(cep):
    """Limpa CEP removendo caracteres não numéricos"""
    if cep is None or str(cep).lower() == "nan":
        return None
    s = str(cep).strip()
    s = re.sub(r"\D", "", s)
    return s if len(s) == 8 else None

def consultar_cep(cep):
    """Consulta CEP na API ViaCEP"""
    if not cep or len(cep) != 8:
        return None
    url = f"https://viacep.com.br/ws/{cep}/json/"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("erro"):
            return None
        return {
            "logradouro": data.get("logradouro", ""),
            "localidade": data.get("localidade", ""),
            "uf": data.get("uf", "")
        }
    except requests.exceptions.RequestException:
        return None

def processar_geocoding(row, geocode_func):
    """Processa geocoding para um CNPJ"""
    cnpj = row.get('cnpj')
    cep_original = row.get('CEP')

    latitude, longitude = None, None
    endereco_completo = "N/A"
    query_location = "CEP inválido"
    cep8 = limpar_cep(cep_original)

    if cep8:
        endereco_info = consultar_cep(cep8)
        if endereco_info and endereco_info.get('localidade'):
            endereco_completo = f"{endereco_info['logradouro']}, {endereco_info['localidade']}, {endereco_info['uf']}"
            query_location = f"{endereco_completo}, Brazil"
        else:
            query_location = f"{cep8[:5]}-{cep8[5:]}, Brazil"

        if query_location.strip().startswith(','):
            query_location = query_location.strip()[1:].strip()

        try:
            location = geocode_func(query_location, timeout=10)
            if location:
                latitude = location.latitude
                longitude = location.longitude
        except Exception as e:
            pass

    return {
        'cnpj': cnpj, 'CEP': cep8, 'endereco_completo': endereco_completo,
        'latitude': latitude, 'longitude': longitude
    }

def consultar_cnpj_receitaws(cnpj):
    """Consulta CNPJ na BrasilAPI"""
    cnpj_limpo = cnpj.replace('.', '').replace('-', '').replace('/', '').strip()
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    try:
        response = requests.get(url, timeout=15, headers={"Accept": "application/json"})
        if response.status_code == 200:
            data = response.json()
            # Mapear sócios do formato BrasilAPI
            qsa = [
                {
                    'nome': s.get('nome_socio') or s.get('nome'),
                    'qual': s.get('qualificacao_socio') or s.get('qualificacao'),
                    'cpf': s.get('cnpj_cpf_do_socio') or s.get('cpf_cnpj_socio'),
                }
                for s in (data.get('qsa') or [])
            ]
            return {
                'cnpj': cnpj_limpo,
                'Nome': data.get('razao_social'),
                'Logradouro': data.get('logradouro'),
                'Número': data.get('numero'),
                'Complemento': data.get('complemento'),
                'Bairro': data.get('bairro'),
                'Cidade': data.get('municipio'),
                'Estado': data.get('uf'),
                'CEP': data.get('cep'),
                'qsa': qsa,
                'Erro': None
            }
        return {'cnpj': cnpj_limpo, 'Erro': f"Status {response.status_code}"}
    except Exception as e:
        return {'cnpj': cnpj_limpo, 'Erro': str(e)}

# =============================================================================
# FUNÇÕES DE BANCO DE DADOS
# =============================================================================

def inicializar_tabelas(conn):
    """Cria as tabelas se não existirem"""
    cursor = conn.cursor()

    # Tabela de emendas (usando nomes das colunas do notebook)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emendas (
            codigo_emenda TEXT PRIMARY KEY,
            autor_emenda TEXT,
            tipo_emenda TEXT,
            localidade_emenda TEXT,
            ano_emenda TEXT,
            valor_empenhado TEXT,
            valor_liquidado TEXT,
            valor_pago TEXT,
            valor_rp_inscritos TEXT,
            valor_rp_cancelados TEXT,
            valor_rp_pagos TEXT,
            funcao TEXT,
            subfuncao TEXT,
            programa TEXT,
            acao TEXT,
            plano_orcamentario TEXT
        )
    """)

    # Tabela de documentos (usando nomes das colunas do notebook)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documentos_emendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_emenda TEXT,
            doc_data TEXT,
            doc_fase TEXT,
            doc_numero TEXT,
            doc_link TEXT,
            cnpj TEXT,
            fornecedor TEXT,
            doc_valor TEXT,
            FOREIGN KEY (codigo_emenda) REFERENCES emendas(codigo_emenda)
        )
    """)

    # Tabela de convênios (usando nomes das colunas do notebook)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS convenios_emendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_emenda TEXT,
            conv_numero TEXT,
            conv_objeto TEXT,
            conv_situacao TEXT,
            conv_vigencia TEXT,
            conv_valor TEXT,
            FOREIGN KEY (codigo_emenda) REFERENCES emendas(codigo_emenda)
        )
    """)

    conn.commit()

def processar_dataframe_completo(df_completo):
    """
    Processa o DataFrame completo (como no notebook) e separa em 3 tabelas.
    """
    if df_completo.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    df_completo = df_completo.copy()
    df_completo = df_completo.map(lambda v: v.strip() if isinstance(v, str) else v)
    df_completo.replace({
        "N/A": pd.NA,
        "NA": pd.NA,
        "n/a": pd.NA,
        "": pd.NA,
        "--": pd.NA
    }, inplace=True)

    # Colunas de "Fato" (as informações base da emenda)
    colunas_base = [
        'Código Emenda', 'Autor/Emenda', 'Tipo de Emenda',
        'Localidade Emenda', 'Ano Emenda', 'Valor Empenhado',
        'Valor Liquidado', 'Valor Pago', 'Valor RP Inscritos',
        'Valor RP Cancelados', 'Valor RP Pagos', 'Função',
        'Subfunção', 'Programa', 'Ação', 'Plano Orçamentário'
    ]

    # Colunas da tabela de Documentos (incluindo a chave)
    colunas_documentos = [
        'Código Emenda', 'Doc Data', 'Doc Fase', 'Doc Número',
        'Doc Link', 'Doc Favorecido Nome', 'Doc Valor'
    ]

    # Colunas da tabela de Convênios (incluindo a chave)
    colunas_convenios = [
        'Código Emenda', 'Conv Número', 'Conv Objeto',
        'Conv Situação', 'Conv Vigência', 'Conv Valor'
    ]

    # 1. DataFrame de DADOS GERAIS DA EMENDA
    df_base_emendas = df_completo[[c for c in colunas_base if c in df_completo.columns]].drop_duplicates().reset_index(drop=True)
    if 'Código Emenda' in df_base_emendas.columns:
        df_base_emendas = df_base_emendas[df_base_emendas['Código Emenda'].notna()].reset_index(drop=True)

    if 'Doc Número' in df_completo.columns:
        df_documentos_raw = df_completo[
            df_completo['Doc Número'].notna()
        ][[c for c in colunas_documentos if c in df_completo.columns]].reset_index(drop=True)
        if 'Código Emenda' in df_documentos_raw.columns:
            df_documentos_raw = df_documentos_raw[df_documentos_raw['Código Emenda'].notna()].reset_index(drop=True)
    else:
        df_documentos_raw = pd.DataFrame(columns=colunas_documentos)

    if 'Conv Número' in df_completo.columns:
        df_convenios = df_completo[
            df_completo['Conv Número'].notna()
        ][[c for c in colunas_convenios if c in df_completo.columns]].reset_index(drop=True)
        if 'Código Emenda' in df_convenios.columns:
            df_convenios = df_convenios[df_convenios['Código Emenda'].notna()].reset_index(drop=True)
    else:
        df_convenios = pd.DataFrame(columns=colunas_convenios)

    # 4. Processar documentos: extrair CNPJ e Fornecedor
    if not df_documentos_raw.empty:
        # Dividir a coluna 'Doc Favorecido Nome'
        split_data = df_documentos_raw['Doc Favorecido Nome'].fillna('N/A - N/A').str.split(' - ', n=1, expand=True)
        df_documentos_raw['CNPJ_temp'] = split_data[0]
        df_documentos_raw['Fornecedor'] = split_data[1]
        # Limpar CNPJ
        df_documentos_raw['CNPJ'] = df_documentos_raw['CNPJ_temp'].str.replace(r'[./-]', '', regex=True)
        df_documentos_raw.loc[df_documentos_raw['CNPJ'] == 'NA', ['CNPJ', 'Fornecedor']] = np.nan
        # Remover colunas temporárias e reordenar
        df_documentos = df_documentos_raw.drop(columns=['Doc Favorecido Nome', 'CNPJ_temp'])
        colunas_finais = ['Código Emenda', 'Doc Data', 'Doc Fase', 'Doc Número', 'Doc Link', 'CNPJ', 'Fornecedor', 'Doc Valor']
        colunas_existentes = [col for col in colunas_finais if col in df_documentos.columns]
        df_documentos = df_documentos[colunas_existentes]
    else:
        df_documentos = pd.DataFrame()

    # Renomear colunas para o banco de dados (sem espaços e acentos)
    df_emendas_db = aplicar_normalizacao_colunas(df_base_emendas.copy())

    df_documentos_db = aplicar_normalizacao_colunas(df_documentos.copy())
    df_convenios_db = aplicar_normalizacao_colunas(df_convenios.copy())

    return df_emendas_db, df_documentos_db, df_convenios_db

def limpar_dados_vazios(conn):
    """Remove linhas vazias/inválidas das tabelas"""
    cursor = conn.cursor()
    
    # Limpar emendas com código vazio
    try:
        cursor.execute("DELETE FROM emendas WHERE codigo_emenda IS NULL OR codigo_emenda = ''")
        emendas_removidas = cursor.rowcount
        if emendas_removidas > 0:
            print(f"  🗑️  Removidas {emendas_removidas} emendas vazias")
    except:
        pass
    
    # Limpar documentos sem código de emenda
    try:
        cursor.execute("DELETE FROM documentos_emendas WHERE codigo_emenda IS NULL OR codigo_emenda = ''")
        docs_removidos = cursor.rowcount
        if docs_removidos > 0:
            print(f"  🗑️  Removidos {docs_removidos} documentos vazios")
    except:
        pass
    
    # Limpar convênios sem código de emenda
    try:
        cursor.execute("DELETE FROM convenios_emendas WHERE codigo_emenda IS NULL OR codigo_emenda = ''")
        conv_removidos = cursor.rowcount
        if conv_removidos > 0:
            print(f"  🗑️  Removidos {conv_removidos} convênios vazios")
    except:
        pass
    
    conn.commit()

def verificar_progresso(conn):
    """Verifica quais códigos de emenda já existem na tabela bruta 'emenda'."""
    try:
        df = pd.read_sql_query(
            """
            SELECT DISTINCT "Código Emenda" AS codigo
            FROM emenda
            WHERE "Código Emenda" IS NOT NULL
              AND TRIM("Código Emenda") <> ''
            """,
            conn
        )
        codigos = set(df['codigo'].astype(str))
        print(f"   ✅ {len(codigos)} códigos já presentes na tabela emenda")
        return codigos
    except Exception as e:
        print(f"   ⚠️  Não foi possível ler os códigos existentes: {e}")
        return set()

def salvar_em_banco(conn, df_emendas, df_documentos, df_convenios):
    """Salva os DataFrames no banco de dados (apenas novos registros)"""
    # Limpar dados vazios antes de salvar
    limpar_dados_vazios(conn)
    
    # Salvar emendas (verificando duplicatas)
    if not df_emendas.empty:
        # Remover linhas vazias do DataFrame
        df_emendas = df_emendas[df_emendas['codigo_emenda'].notna() & (df_emendas['codigo_emenda'] != '')]
        
        if not df_emendas.empty:
            cursor = conn.cursor()
            cursor.execute("SELECT codigo_emenda FROM emendas WHERE codigo_emenda IS NOT NULL")
            emendas_existentes = set(row[0] for row in cursor.fetchall())
            df_emendas_novas = df_emendas[~df_emendas['codigo_emenda'].isin(emendas_existentes)]

            if not df_emendas_novas.empty:
                df_emendas_novas.to_sql('emendas', conn, if_exists='append', index=False)
                print(f"  💾 {len(df_emendas_novas)} novas emendas salvas.")
            else:
                print(f"  ⏭️  {len(df_emendas)} emendas já existem no banco (puladas)")

    # Salvar documentos (apenas se tiver código de emenda)
    if not df_documentos.empty:
        df_documentos = df_documentos[df_documentos['codigo_emenda'].notna() & (df_documentos['codigo_emenda'] != '')]
        if not df_documentos.empty:
            df_documentos.to_sql('documentos_emendas', conn, if_exists='append', index=False)
            print(f"  💾 {len(df_documentos)} documentos salvos.")

    # Salvar convênios (apenas se tiver código de emenda)
    if not df_convenios.empty:
        df_convenios = df_convenios[df_convenios['codigo_emenda'].notna() & (df_convenios['codigo_emenda'] != '')]
        if not df_convenios.empty:
            df_convenios.to_sql('convenios_emendas', conn, if_exists='append', index=False)
            print(f"  💾 {len(df_convenios)} convênios salvos.")

    conn.commit()

def processar_cnpjs_documentos(conn):
    """Processa CNPJs dos documentos: busca dados e coordenadas"""
    print("\n" + "="*80)
    print("📊 PROCESSANDO CNPJs DOS DOCUMENTOS")
    print("="*80)

    # Buscar CNPJs únicos dos documentos
    query = """
        SELECT DISTINCT cnpj, fornecedor
        FROM documentos_emendas
        WHERE cnpj IS NOT NULL AND cnpj != '' AND cnpj != 'N/A'
    """
    df_cnpjs = pd.read_sql_query(query, conn)

    if df_cnpjs.empty:
        print("  ⚠️ Nenhum CNPJ encontrado nos documentos.")
        return

    print(f"  📋 {len(df_cnpjs)} CNPJs únicos encontrados nos documentos.")

    # Verificar quais CNPJs já estão na tabela lista_cnpj_geral
    try:
        query_existentes = "SELECT DISTINCT cnpj FROM lista_cnpj_geral"
        df_existentes = pd.read_sql_query(query_existentes, conn)
        cnpjs_existentes = set(df_existentes['cnpj'].astype(str).str.replace(r'\D', '', regex=True))
    except:
        cnpjs_existentes = set()

    # Filtrar CNPJs que precisam ser consultados
    df_cnpjs['cnpj_limpo'] = df_cnpjs['cnpj'].astype(str).str.replace(r'\D', '', regex=True)
    df_novos = df_cnpjs[~df_cnpjs['cnpj_limpo'].isin(cnpjs_existentes)]

    if df_novos.empty:
        print("  ✅ Todos os CNPJs já estão na base de dados.")
    else:
        print(f"  🔄 {len(df_novos)} CNPJs novos para consultar na ReceitaWS...")

        # Consultar CNPJs na ReceitaWS
        for idx, row in tqdm(df_novos.iterrows(), total=len(df_novos), desc="Consultando CNPJs"):
            cnpj_limpo = row['cnpj_limpo']
            dados_empresa = consultar_cnpj_receitaws(cnpj_limpo)

            if dados_empresa.get('Erro') is None:
                # Preparar dados base
                base_empresa = dados_empresa.copy()
                qsa = base_empresa.pop('qsa', []) # Remove QSA para não dar erro no insert se a coluna não existir
                
                # Adicionar campos de sócio vazios na base
                base_empresa['Nome_Socio'] = None
                base_empresa['Qualificação_Socio'] = None
                base_empresa['CPF/CNPJ_Socio'] = None

                # Salvar empresa principal
                df_empresa = pd.DataFrame([base_empresa])
                df_empresa.to_sql('lista_cnpj_geral', conn, if_exists='append', index=False)
                
                # Salvar sócios (QSA)
                for socio in qsa:
                    socio_data = base_empresa.copy()
                    socio_data.update({
                        'Nome_Socio': socio.get('nome'),
                        'Qualificação_Socio': socio.get('qual'),
                        'CPF/CNPJ_Socio': socio.get('cpf', socio.get('cnpj'))
                    })
                    pd.DataFrame([socio_data]).to_sql('lista_cnpj_geral', conn, if_exists='append', index=False)

                conn.commit()
                time.sleep(1)  # BrasilAPI nao tem rate limit rigido
            else:
                print(f"    ⚠️ Erro ao consultar CNPJ {cnpj_limpo}: {dados_empresa.get('Erro')}")

    # Buscar coordenadas para CNPJs sem coordenadas
    print(f"\n  🗺️ Buscando coordenadas para CNPJs sem coordenadas...")

    # Buscar CNPJs dos documentos
    query_docs_cnpj = """
        SELECT DISTINCT REPLACE(REPLACE(REPLACE(cnpj, '.', ''), '/', ''), '-', '') as cnpj_limpo
        FROM documentos_emendas
        WHERE cnpj IS NOT NULL AND cnpj != '' AND cnpj != 'N/A'
    """

    try:
        df_docs_cnpj = pd.read_sql_query(query_docs_cnpj, conn)
        if df_docs_cnpj.empty:
            print("    ✅ Nenhum CNPJ nos documentos para processar.")
            return

        cnpjs_docs = set(df_docs_cnpj['cnpj_limpo'].astype(str))

        # Buscar CNPJs que já têm coordenadas
        query_com_coord = "SELECT DISTINCT cnpj FROM coordenadas_empresas WHERE cnpj IS NOT NULL"
        try:
            df_com_coord = pd.read_sql_query(query_com_coord, conn)
            cnpjs_com_coord = set(df_com_coord['cnpj'].astype(str).str.replace(r'\D', '', regex=True))
        except:
            cnpjs_com_coord = set()

        # Buscar todos os CNPJs relevantes em partes
        df_sem_coord_list = []
        cnpjs_docs_lista = list(cnpjs_docs)
        for i in range(0, len(cnpjs_docs_lista), 100):
            cnpjs_lote = cnpjs_docs_lista[i:i+100]
            query_lote = """
                SELECT DISTINCT lg.cnpj, lg.CEP
                FROM lista_cnpj_geral lg
                WHERE REPLACE(REPLACE(REPLACE(lg.cnpj, '.', ''), '/', ''), '-', '') IN ({})
            """.format(','.join([f"'{cnpj}'" for cnpj in cnpjs_lote]))
            try:
                df_lote = pd.read_sql_query(query_lote, conn)
                if not df_lote.empty:
                    df_lote['cnpj_limpo'] = df_lote['cnpj'].astype(str).str.replace(r'\D', '', regex=True)
                    df_lote_filtrado = df_lote[~df_lote['cnpj_limpo'].isin(cnpjs_com_coord)]
                    if not df_lote_filtrado.empty:
                        df_sem_coord_list.append(df_lote_filtrado)
            except Exception as e:
                print(f"    ⚠️ Erro ao buscar lote {i}: {e}")

        if df_sem_coord_list:
            df_sem_coord = pd.concat(df_sem_coord_list, ignore_index=True).drop_duplicates(subset=['cnpj'])
        else:
            df_sem_coord = pd.DataFrame()

        if not df_sem_coord.empty:
            print(f"    📍 {len(df_sem_coord)} CNPJs precisam de coordenadas.")

            # Processar geocoding em lotes
            resultados_coord = []
            for idx, row in tqdm(df_sem_coord.iterrows(), total=len(df_sem_coord), desc="Geocodificando"):
                resultado = processar_geocoding(row, geocode)
                if resultado.get('latitude'):
                    resultados_coord.append(resultado)

                if len(resultados_coord) >= BATCH_SIZE:
                    df_coord = pd.DataFrame(resultados_coord)
                    df_coord.to_sql('coordenadas_empresas', conn, if_exists='append', index=False)
                    conn.commit()
                    resultados_coord.clear()

            # Salvar último lote
            if resultados_coord:
                df_coord = pd.DataFrame(resultados_coord)
                df_coord.to_sql('coordenadas_empresas', conn, if_exists='append', index=False)
                conn.commit()
                print(f"    ✅ {len(resultados_coord)} coordenadas salvas.")
        else:
            print("    ✅ Todos os CNPJs já têm coordenadas.")
    except Exception as e:
        print(f"    ⚠️ Erro ao processar coordenadas: {e}")

def normalizar_nome_coluna(col: str) -> str:
    col = col.replace('/', '_').replace(' ', '_').lower()
    col = ''.join(ch for ch in unicodedata.normalize('NFKD', col) if not unicodedata.combining(ch))
    col = col.replace('_de_', '_')
    return col


def aplicar_normalizacao_colunas(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df.columns = [normalizar_nome_coluna(col) for col in df.columns]
    return df

# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

async def main():
    """Função principal"""
    print("="*80)
    print("🚀 INICIANDO COLETA DE DADOS DE EMENDAS PARLAMENTARES")
    print("="*80)

    # 1. Buscar lista de deputados do tabelao.db
    print("\n📥 Buscando nomes dos deputados no banco tabelao.db...")
    try:
        conn_temp = sqlite3.connect(DB_PATH, timeout=30)
        query_nomes = "SELECT DISTINCT UPPER(nome) as nome FROM tabelao WHERE nome IS NOT NULL AND nome != '' ORDER BY nome"
        df_nomes = pd.read_sql_query(query_nomes, conn_temp)
        conn_temp.close()
        
        nomes_deputados = df_nomes['nome'].dropna().unique().tolist()
        nomes_deputados = [nome for nome in nomes_deputados if nome and str(nome) != 'nan' and len(str(nome).strip()) > 0]
        
        print(f"✅ {len(nomes_deputados)} deputados únicos encontrados no tabelao.db")
        print(f"   Primeiros 5: {', '.join(nomes_deputados[:5])}...")
    except Exception as e:
        print(f"❌ Erro ao buscar nomes do tabelao.db: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    # 2. Conectar ao banco de dados
    print(f"\n💾 Conectando ao banco de dados: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    inicializar_tabelas(conn)
    
    # Limpar dados vazios existentes
    print("\n🧹 Limpando dados vazios do banco...")
    limpar_dados_vazios(conn)
    
    # Verificar progresso atual
    print("\n📊 Verificando progresso atual...")
    codigos_processados = verificar_progresso(conn)
    print(f"   ✅ {len(codigos_processados)} emendas já processadas encontradas no banco")

    # 3. Inicializar Playwright e httpx
    try:
        async with async_playwright() as p, httpx.AsyncClient(headers=API_PUBLICA_HEADERS, timeout=30.0) as client:
            browser = await p.chromium.launch(headless=True)  # headless=True para rodar em background
            page = await browser.new_page()

            # Lista completa final (como no notebook)
            lista_completa_final = []

            # 4. Processar cada deputado e cada ano
            total_deputados = len(nomes_deputados)
            if START_FROM_DEPUTADO > 1:
                print(f"\n⏩ Pulando os primeiros {START_FROM_DEPUTADO - 1} deputados (retomando do {START_FROM_DEPUTADO}º)...")
                nomes_deputados = nomes_deputados[START_FROM_DEPUTADO - 1:]
            print(f"\n📊 Processando {len(nomes_deputados)} deputados para os anos {ANOS_PESQUISA}...\n")

            for idx, nome_deputado in enumerate(tqdm(nomes_deputados, desc="Processando deputados", unit="deputado", ncols=100, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} ({percentage:3.0f}%) - {desc}'), START_FROM_DEPUTADO):
                print(f"\n{'='*80}")
                print(f"Deputado {idx}/{total_deputados} ({idx*100/total_deputados:.1f}%): {nome_deputado}")
                print(f"{'='*80}")

                # Para cada ano, buscar emendas
                emendas_por_ano = {}
                for ano in ANOS_PESQUISA:
                    print(f"\n📅 [{ano}] Buscando emendas...")
                    
                    # Passo 1: Buscar códigos de emenda
                    codigos_emenda = await passo_1_buscar_codigos_emenda(client, nome_deputado, ano)
                    
                    # Filtrar emendas já processadas
                    codigos_ja_processados = 0
                    if codigos_emenda:
                        codigos_novos = [c for c in codigos_emenda if c not in codigos_processados]
                        codigos_ja_processados = len(codigos_emenda) - len(codigos_novos)
                        codigos_emenda = codigos_novos
                        
                        if codigos_ja_processados > 0:
                            print(f"   ⏭️  {codigos_ja_processados} emendas já processadas (puladas)")
                    
                    emendas_por_ano[ano] = len(codigos_emenda) if codigos_emenda else 0

                    if not codigos_emenda:
                        if codigos_ja_processados > 0:
                            print(f"   ✅ Todas as emendas de {ano} já foram processadas")
                        else:
                            print(f"   ⚠️  Nenhuma emenda encontrada para {ano}")
                        continue

                    print(f"   ✅ {len(codigos_emenda)} novas emendas para processar em {ano}")

                    # Passo 2: Para cada código, raspar detalhes
                    total_emendas = len(codigos_emenda)
                    documentos_total = 0
                    convenios_total = 0
                    
                    for i, codigo in enumerate(codigos_emenda):
                        # Verificar novamente se já foi processada (dupla verificação)
                        cursor_temp = conn.cursor()
                        cursor_temp.execute("SELECT COUNT(*) FROM emendas WHERE codigo_emenda = ?", (codigo,))
                        if cursor_temp.fetchone()[0] > 0:
                            print(f"\n   [{ano}] Emenda {i+1}/{total_emendas} (Código: {codigo}) - ⏭️  Já processada (pulando)")
                            continue
                        
                        print(f"\n   [{ano}] Emenda {i+1}/{total_emendas} (Código: {codigo})")

                        linhas_da_emenda = await passo_2_raspar_com_playwright(page, codigo)

                        if linhas_da_emenda:
                            # Contar documentos e convênios
                            for linha in linhas_da_emenda:
                                if 'Doc Número' in linha and pd.notna(linha.get('Doc Número')) and linha.get('Doc Número') != '':
                                    documentos_total += 1
                                if 'Conv Número' in linha and pd.notna(linha.get('Conv Número')) and linha.get('Conv Número') != '':
                                    convenios_total += 1
                            lista_completa_final.extend(linhas_da_emenda)
                            # Adicionar código às processadas para evitar reprocessamento
                            codigos_processados.add(codigo)

                        await asyncio.sleep(0.5)
                    
                    print(f"   ✅ [{ano}] Concluído: {len(codigos_emenda)} emendas, {documentos_total} documentos, {convenios_total} convênios")
                
                # Resumo do deputado
                total_emendas_dep = sum(emendas_por_ano.values())
                print(f"\n{'='*80}")
                print(f"📊 RESUMO - {nome_deputado}:")
                for ano, count in emendas_por_ano.items():
                    print(f"   {ano}: {count} emendas")
                print(f"   TOTAL: {total_emendas_dep} emendas encontradas")
                print(f"{'='*80}")

                # Salvar em lotes (a cada 10 deputados ou ao final)
                if idx % 10 == 0 or idx == total_deputados:
                    if lista_completa_final:
                        df_completo = pd.DataFrame(lista_completa_final)
                        df_emendas, df_documentos, df_convenios = processar_dataframe_completo(df_completo)
                        salvar_em_banco(conn, df_emendas, df_documentos, df_convenios)
                        lista_completa_final.clear()
                        print(f"  ✅ Lote de deputados salvo.")

            print("Busca concluída para todos os deputados e anos. Fechando o navegador.")
            await browser.close()

            try:
                processar_cnpjs_documentos(conn)
            except Exception as e:
                import traceback
                print("\n⚠️  Falha ao processar CNPJs dos documentos:", e)
                traceback.print_exc()

            try:
                conn.close()
            except Exception as e:
                print("⚠️  Erro ao fechar conexão com o banco:", e)

    except Exception as e:
        import traceback
        print("\n❌ Erro crítico ao iniciar o Playwright ou HTTPX:", e)
        traceback.print_exc()
        raise

# =============================================================================
# EXECUÇÃO DIRETA
# =============================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Execução interrompida pelo usuário.")
    except Exception as err:
        import traceback
        print("\n❌ Erro não tratado durante a execução:", err)
        traceback.print_exc()
        sys.exit(1)




def main():
    # Verifica se o pandas está instalado
    try:
        import pandas as pd
    except ImportError:
        print("Erro: A biblioteca 'pandas' é necessária para este script.", file=sys.stderr)
        print("Instale usando: pip install pandas", file=sys.stderr)
        sys.exit(1)
        
    listar_autores_limitado(API_KEY, ANO_PESQUISA, PAGINAS_PARA_BUSCAR)
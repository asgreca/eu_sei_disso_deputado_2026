#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SCRAPER DE CONTEÚDO (MARCOS TEMPORAIS & TEXTOS):
Lê os links do banco de dados seguro e salva os textos em Markdown.
"""

import sqlite3
import requests
from bs4 import BeautifulSoup
import os
import time
from tqdm import tqdm
import concurrent.futures

# --- CONFIGURAÇÕES DE CAMINHOS ---

# 1. Caminho SEGURO do banco de dados (fora do iCloud)
PASTA_SEGURA = "/Users/aislangreca/Banco_de_dados_eu_sei_disso_deputado"
NOME_BANCO = "discursos_links.db"
DB_PATH = os.path.join(PASTA_SEGURA, NOME_BANCO)

# 2. Pasta onde os arquivos Markdown serão salvos 
# (Criará uma pasta onde você rodar este script)
OUTPUT_DIR = "discursos_markdown"

MAX_WORKERS = 10

# Cabeçalhos para simular navegador real
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

class ScraperDiscursosFinal:
    def __init__(self):
        print(f"📂 Lendo banco de dados de: {DB_PATH}")
        
        # Verifica se o banco existe antes de começar
        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(f"O banco de dados não foi encontrado em: {DB_PATH}")

        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        
        # Cria as pastas de saída
        os.makedirs(os.path.join(OUTPUT_DIR, "plenario"), exist_ok=True)
        os.makedirs(os.path.join(OUTPUT_DIR, "comissao"), exist_ok=True)
        
    def extrair_texto_discurso(self, soup: BeautifulSoup) -> str:
        """Extrai o conteúdo principal do discurso."""
        divs_principal = soup.find_all('div', class_='principalStyle')
        if divs_principal:
            for div in divs_principal:
                texto = div.get_text(strip=True)
                if len(texto) > 100:
                    return texto
        
        paragrafos_principal = soup.find_all('p', class_='principalStyle')
        if paragrafos_principal:
            textos = []
            for p in paragrafos_principal:
                texto_p = p.get_text(strip=True)
                if texto_p and len(texto_p) > 30:
                    textos.append(texto_p)
            
            if textos:
                resultado = '\n\n'.join(textos)
                if len(resultado) > 100:
                    return resultado
        
        divs_texto = soup.find_all('div')
        for div in divs_texto:
            texto = div.get_text(strip=True)
            if len(texto) > 200 and ('SR.' in texto or 'SRA.' in texto or 'PRESIDENTE' in texto):
                return texto
        
        paragrafos = soup.find_all('p')
        if paragrafos:
            textos = []
            for p in paragrafos:
                texto_p = p.get_text(strip=True)
                if texto_p and len(texto_p) > 50:
                    textos.append(texto_p)
            
            if textos:
                resultado = '\n\n'.join(textos)
                if len(resultado) > 100:
                    return resultado
        
        texto_completo = soup.get_text()
        if len(texto_completo) > 200:
            return texto_completo
        
        return "Conteúdo não encontrado"
    
    def processar_link(self, link_data):
        """Processa um link individual com gravação atômica."""
        link_id, url, origem, deputado = link_data

        url_limpa = url.replace('\n', '').replace('\r', '').replace('\t', '').strip()
        
        deputado_limpo = deputado if deputado else 'desconhecido'
        deputado_limpo = "".join(c for c in deputado_limpo if c.isalnum() or c in (' ', '_')).rstrip()
        deputado_limpo = deputado_limpo.replace(' ', '_')
        filename = f"{link_id}_{deputado_limpo}.md"
        
        if origem == 'plenario':
            filepath = os.path.join(OUTPUT_DIR, "plenario", filename)
        else:
            filepath = os.path.join(OUTPUT_DIR, "comissao", filename)
        
        # Define um nome de arquivo temporário
        temp_filepath = filepath + ".tmp"

        if os.path.exists(filepath):
            return (True, link_id, f"Arquivo já existia para o ID {link_id}.")
        
        try:
            # 1. FAZER A REQUISIÇÃO
            response = self.session.get(url_limpa, timeout=15)
            response.raise_for_status()
            
            if len(response.content) < 100:
                return (False, link_id, f"Conteúdo muito pequeno para o link ID {link_id}.")
            
            # 2. EXTRAIR O TEXTO
            soup = BeautifulSoup(response.content, 'html.parser')
            texto = self.extrair_texto_discurso(soup)

            # 3. ESCREVER EM ARQUIVO TEMPORÁRIO
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                f.write(f"# Discurso ID: {link_id}\n")
                f.write(f"## Deputado(a): {deputado if deputado else 'N/A'}\n")
                f.write(f"## Origem: {origem}\n")
                f.write(f"**URL:** {url_limpa}\n\n")
                f.write("---\n\n")
                f.write(texto)
            
            # 4. SE TUDO DEU CERTO, RENOMEAR O ARQUIVO (Gravação Atômica)
            os.rename(temp_filepath, filepath)
            
            return (True, link_id, f"Link ID {link_id} processado.")
            
        except Exception as e:
            # 5. SE ERRO, LIMPAR TEMP
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except OSError:
                    pass

            if isinstance(e, requests.exceptions.HTTPError):
                msg = f"Erro HTTP {e.response.status_code} para o link ID {link_id}"
            elif isinstance(e, requests.exceptions.RequestException):
                msg = f"Erro de conexão para o link ID {link_id}: {e}"
            else:
                msg = f"Erro inesperado para o link ID {link_id}: {e}"
            
            return (False, link_id, msg)

    def executar(self):
        """Executa o processamento de todos os links em lote."""
        conn = None
        try:
            # Conecta no banco da pasta segura
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Verificar se a coluna 'processado' existe
            cursor.execute("PRAGMA table_info(links_discursos)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'processado' not in columns:
                print("Adicionando coluna 'processado' à tabela links_discursos...")
                cursor.execute("ALTER TABLE links_discursos ADD COLUMN processado INTEGER DEFAULT 0")
                conn.commit()
                print("✅ Coluna 'processado' adicionada com sucesso.")
            
            # Pega apenas os não processados
            query = "SELECT id, url, origem, deputado FROM links_discursos WHERE processado = 0 ORDER BY id"
            cursor.execute(query)
            links = cursor.fetchall()
            
            if not links:
                print("✅ Todos os links do banco já foram processados! Nada a fazer.")
                return
            
            print(f"🚀 Iniciando download de {len(links)} discursos com {MAX_WORKERS} threads...")
            
            sucessos = 0
            falhas = 0
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_link = {executor.submit(self.processar_link, link): link for link in links}
                
                # Barra de progresso
                for future in tqdm(concurrent.futures.as_completed(future_to_link), total=len(links), desc="Baixando", unit="discursos"):
                    try:
                        success, link_id, message = future.result()
                        
                        if success:
                            sucessos += 1
                            # Marca como processado no banco imediatamente (ou em lotes pequenos seria melhor, mas assim é seguro)
                            cursor.execute("UPDATE links_discursos SET processado = 1 WHERE id = ?", (link_id,))
                            # Commit a cada sucesso para salvar progresso em tempo real
                            conn.commit() 
                        else:
                            falhas += 1
                            # print(f"❌ {message}") # Descomente se quiser ver erros na tela

                    except Exception as exc:
                        link_info = future_to_link[future]
                        print(f"❌ Erro crítico na thread do ID {link_info[0]}: {exc}")
                        falhas += 1
            
            print(f"\n🏁 Processamento Concluído!")
            print(f"✅ Sucessos: {sucessos}")
            print(f"❌ Falhas: {falhas}")
            print(f"📁 Arquivos salvos na pasta: {os.path.abspath(OUTPUT_DIR)}")
            
        except sqlite3.OperationalError as e:
            print(f"❌ Erro ao acessar o banco de dados. Verifique se o caminho está correto: {e}")
        except Exception as e:
            print(f"❌ Erro geral no executor: {e}")
        finally:
            if conn:
                conn.close()

if __name__ == "__main__":
    scraper = ScraperDiscursosFinal()
    scraper.executar()
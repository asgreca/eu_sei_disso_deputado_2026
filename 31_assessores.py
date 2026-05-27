"""
31_assessores.py — Mapeamento de Secretários Parlamentares via Playwright

Coleta nomes, lotação, salário e data de admissão de assessores de gabinete
da Câmara dos Deputados via scraping com Playwright.

Fonte: https://www.camara.leg.br/transparencia/recursos-humanos/funcionarios
"""

import sqlite3
import pandas as pd
import time
import re
import unicodedata
from tqdm import tqdm
from playwright.sync_api import sync_playwright

# Configurações
DB_NAME = "tabelao.db"
# URL com filtros PRÉ-APLICADOS: Secretário Parlamentar + Gabinetes dos Deputados + Em exercício
BASE_URL = "https://www.camara.leg.br/transparencia/recursos-humanos/funcionarios?areaDeAtuacao=Gabinetes%20dos%20Deputados&categoriaFuncional=Secret%C3%A1rio%20Parlamentar&situacao=Em%20exerc%C3%ADcio"

def normalizar_nome(nome):
    if not nome: return ""
    return "".join(c for c in unicodedata.normalize('NFKD', str(nome)) if not unicodedata.combining(c)).upper().strip()

def setup_db():
    conn = sqlite3.connect(DB_NAME, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gabinetes_assessores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ponto TEXT,
        nome_assessor TEXT,
        lotacao TEXT,
        cargo TEXT,
        situacao TEXT,
        salario_liquido REAL,
        data_admissao TEXT,
        link_remuneracao TEXT,
        nome_deputado_referencia TEXT,
        UNIQUE(ponto, nome_assessor)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auditoria_conflitos_gabinete (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_deputado TEXT,
        nome_assessor TEXT,
        cnpj_empresa TEXT,
        nome_empresa TEXT,
        valor_emenda REAL,
        codigo_emenda TEXT,
        data_auditoria TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    return conn

def execute_with_retry(conn, query, params=None, retries=5, delay=2):
    for i in range(retries):
        try:
            if params:
                conn.execute(query, params)
            else:
                conn.execute(query)
            conn.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                print(f"⚠️ Banco travado (tentativa {i+1}/{retries}). Aguardando {delay}s...")
                time.sleep(delay)
            else:
                raise e
    return False

def extrair_nome_deputado(lotacao):
    """Extrai o nome do deputado da lotação (ex: 'Gabinete Coronel Assis' -> 'CORONEL ASSIS')"""
    if not lotacao: return "N/A"
    lotacao_upper = normalizar_nome(lotacao)
    # Remove prefixo 'GABINETE' ou 'GABINETE DO DEPUTADO' etc
    lotacao_upper = re.sub(r'^GABINETE\s+(D[OEA]+\s+)?(DEPUTAD[OA]\s+)?', '', lotacao_upper)
    return lotacao_upper.strip() if lotacao_upper.strip() else "N/A"

def coletar_assessores(conn):
    """Coleta assessores com detalhamento de salário e admissão via Playwright"""
    print("🚀 Iniciando coleta de Secretários Parlamentares (Gabinetes dos Deputados)...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        
        print(f"🌐 Acessando portal filtrado...")
        page.goto(BASE_URL, timeout=60000)
        page.wait_for_load_state('networkidle')
        time.sleep(3)
        
        # Verificar se a tabela carregou (seletor real: tbody tr)
        page.wait_for_selector('tbody tr', timeout=30000)
        print("✅ Tabela de resultados carregada.")

        total_inseridos = 0
        pagina = 1
        
        while True:
            print(f"\n📄 Processando página {pagina}...")
            page.wait_for_selector('tbody tr', timeout=20000)
            
            rows = page.locator('tbody tr').all()
            print(f"  Encontradas {len(rows)} linhas na tabela.")
            
            if len(rows) == 0:
                print("  ⚠️ Nenhuma linha encontrada. Fim.")
                break
            
            # Para cada linha: extrair dados básicos e link de remuneração
            tarefas = []
            for row in rows:
                try:
                    cells = row.locator('td').all()
                    if len(cells) < 4: continue
                    
                    nome = cells[0].inner_text().strip()
                    # O link do nome abre um modal com a lotação real
                    nome_link = cells[0].locator('a').first
                    modal_target = nome_link.get_attribute('data-target') if nome_link else None
                    
                    # Link de remuneração (última célula)
                    rem_link_el = cells[3].locator('a').first
                    rem_url = rem_link_el.get_attribute('href') if rem_link_el else None
                    
                    tarefas.append({
                        'nome': nome,
                        'modal_target': modal_target,
                        'rem_url': rem_url,
                    })
                except Exception as e:
                    continue
            
            # Processar cada assessor: abrir modal para lotação, depois página de remuneração
            for task in tarefas:
                nome = task['nome']
                
                # Verificar se já existe no banco
                exists = conn.execute(
                    "SELECT id FROM gabinetes_assessores WHERE nome_assessor = ?", (nome,)
                ).fetchone()
                if exists:
                    continue
                
                lotacao = "Gabinetes dos Deputados"
                
                # 1. Abrir modal para pegar lotação real
                if task['modal_target']:
                    try:
                        # Clicar no nome para abrir o modal
                        page.locator(f'a[data-target="{task["modal_target"]}"]').click()
                        time.sleep(1)
                        
                        # Ler conteúdo do modal
                        modal = page.locator(task['modal_target'])
                        if modal.is_visible():
                            modal_text = modal.inner_text()
                            # Procurar "Unidade: Gabinete ..."
                            m = re.search(r'Unidade:\s*(.+)', modal_text)
                            if m:
                                lotacao = m.group(1).strip()
                            
                            # Fechar modal
                            close_btn = modal.locator('button.close, [data-dismiss="modal"]').first
                            if close_btn.is_visible():
                                close_btn.click()
                                time.sleep(0.5)
                    except Exception as e:
                        # Se modal falhar, seguir com lotação genérica
                        try:
                            page.keyboard.press('Escape')
                            time.sleep(0.3)
                        except: pass
                
                # 2. Abrir página de remuneração para salário e data de admissão
                salario = 0.0
                admissao = ""
                ponto = nome  # fallback
                
                if task['rem_url']:
                    try:
                        detail = context.new_page()
                        detail.goto(task['rem_url'], timeout=30000)
                        detail.wait_for_load_state('networkidle')
                        time.sleep(1)
                        
                        body_text = detail.inner_text('body')
                        
                        # Extrair data de admissão
                        m_adm = re.search(r'Data de exercício:\s*(\d{2}/\d{2}/\d{4})', body_text)
                        if m_adm:
                            admissao = m_adm.group(1)
                        
                        # Extrair salário (item 5 - Remuneração após Descontos Obrigatórios)
                        m_sal = re.search(r'Remuneração após Descontos Obrigatórios\s+([\d.,]+)', body_text)
                        if m_sal:
                            sal_str = m_sal.group(1).replace('.', '').replace(',', '.')
                            try:
                                salario = float(sal_str)
                            except: pass
                        
                        # Ponto/matrícula da URL
                        ponto_match = re.search(r'/remuneracao/(.+?)$', task['rem_url'])
                        if ponto_match:
                            ponto = ponto_match.group(1)
                        
                        detail.close()
                    except Exception as e:
                        print(f"    ⚠️ Erro na página de remuneração de {nome}: {e}")
                        try: detail.close()
                        except: pass
                
                nome_dep = extrair_nome_deputado(lotacao)
                
                execute_with_retry(conn, """
                INSERT OR IGNORE INTO gabinetes_assessores 
                (ponto, nome_assessor, lotacao, cargo, situacao, salario_liquido, data_admissao, link_remuneracao, nome_deputado_referencia)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (ponto, nome, lotacao, 'Secretário Parlamentar', 'Em exercício', 
                      salario, admissao, task['rem_url'] or '', nome_dep))
                
                total_inseridos += 1
                if total_inseridos % 5 == 0 or total_inseridos <= 3:
                    print(f"    ✅ [{total_inseridos}] {nome} | Gab: {lotacao} | R$ {salario:.2f} | Adm: {admissao}")
            
            # Próxima página
            try:
                next_btn = page.locator('a:has-text("Próxim")').first
                if next_btn.is_visible():
                    next_btn.click()
                    page.wait_for_load_state('networkidle')
                    time.sleep(2)
                    pagina += 1
                else:
                    print("  📌 Última página. Finalizando.")
                    break
            except:
                print("  📌 Sem mais páginas. Finalizando.")
                break
        
        browser.close()
    
    total_banco = conn.execute("SELECT COUNT(*) FROM gabinetes_assessores").fetchone()[0]
    print(f"\n✅ Coleta concluída! {total_inseridos} novos assessores. Total no banco: {total_banco}")

def auditoria_cruzada(conn):
    """Cruza assessores com empresas e emendas"""
    print("\n🔍 Iniciando auditoria de conflitos (Assessor -> Empresa -> Emenda)...")
    
    try:
        df_vinculos = pd.read_sql_query("""
            SELECT DISTINCT a.nome_assessor, a.nome_deputado_referencia, s.cnpj, s.Nome as nome_empresa
            FROM gabinetes_assessores a
            JOIN lista_cnpj_geral s ON UPPER(a.nome_assessor) = UPPER(s.Nome_Socio)
        """, conn)
        print(f"🏢 Encontrados {len(df_vinculos)} vínculos de assessores com empresas.")
    except Exception as e:
        print(f"⚠️ Erro: {e}")
        return

    if df_vinculos.empty:
        print("ℹ️ Nenhum vínculo encontrado.")
        return

    try:
        df_emendas = pd.read_sql_query("""
            SELECT d.cnpj, d.doc_valor, d.codigo_emenda, e.autor_emenda
            FROM documentos_emendas d
            JOIN emendas e ON d.codigo_emenda = e.codigo_emenda
        """, conn)
        df_emendas['cnpj_limpo'] = df_emendas['cnpj'].astype(str).str.replace(r'\D', '', regex=True)
    except:
        print("⚠️ Tabela de emendas não encontrada.")
        return

    total_conflitos = 0
    for _, vinculo in tqdm(df_vinculos.iterrows(), total=len(df_vinculos), desc="Auditando"):
        cnpj = str(vinculo['cnpj']).replace('.','').replace('-','').replace('/','')
        dep = normalizar_nome(vinculo['nome_deputado_referencia'])
        
        for _, em in df_emendas[df_emendas['cnpj_limpo'] == cnpj].iterrows():
            autor = normalizar_nome(em['autor_emenda'])
            if dep in autor or autor in dep:
                try:
                    execute_with_retry(conn, """
                    INSERT INTO auditoria_conflitos_gabinete 
                    (nome_deputado, nome_assessor, cnpj_empresa, nome_empresa, valor_emenda, codigo_emenda)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (vinculo['nome_deputado_referencia'], vinculo['nome_assessor'], 
                          vinculo['cnpj'], vinculo['nome_empresa'],
                          float(str(em['doc_valor']).replace('.','').replace(',','.')), 
                          em['codigo_emenda']))
                    total_conflitos += 1
                except: pass
                    
    conn.commit()
    print(f"✨ Auditoria concluída! {total_conflitos} conflitos identificados.")

def main():
    conn = setup_db()
    coletar_assessores(conn)
    auditoria_cruzada(conn)
    conn.close()

if __name__ == "__main__":
    main()

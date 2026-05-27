import sqlite3
import pandas as pd
import unicodedata
from tqdm import tqdm
import datetime

DB_NAME = "tabelao.db"

def normalize(s):
    if not s: return ''
    # Remove accents, convert to uppercase, and strip whitespace
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s)) if not unicodedata.combining(c)).upper().strip()

def setup_table(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS cruzamento_emendas_sociedades")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cruzamento_emendas_sociedades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parlamentar_autor TEXT,
        cnpj_recebedor TEXT,
        nome_recebedor TEXT,
        valor_emenda REAL,
        ano_emenda TEXT,
        codigo_emenda TEXT,
        tipo_vinculo TEXT, -- 'POLITICO', 'ASSESSOR'
        socio_vinc_parlamentar TEXT, -- Nome do Sócio que casou
        vinculo_com_quem TEXT, -- Nome do Político ou Assessor que casou
        data_cruzamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()

def run_cross_reference():
    print(f"🚀 Iniciando Cruzamento Forense de Emendas às {datetime.datetime.now()}")
    conn = sqlite3.connect(DB_NAME)
    setup_table(conn)
    
    # 1. Carregar Políticos (Deputados)
    print("📋 Carregando lista de políticos...")
    df_deputados = pd.read_sql_query("SELECT DISTINCT nomeCivil, nome FROM tabelao", conn)
    politicos = {}
    for _, row in df_deputados.iterrows():
        n1 = normalize(row['nomeCivil'])
        if n1: politicos[n1] = row['nomeCivil']
        n2 = normalize(row['nome'])
        if n2: politicos[n2] = row['nome'] # Nome parlamentar
        
    # 2. Carregar Assessores
    print("📋 Carregando lista de assessores...")
    df_assessores = pd.read_sql_query("SELECT DISTINCT nome_assessor, nome_deputado_referencia FROM gabinetes_assessores", conn)
    assessores = {}
    assessor_to_deputy = {}
    for _, row in df_assessores.iterrows():
        n = normalize(row['nome_assessor'])
        if n:
            assessores[n] = row['nome_assessor']
            assessor_to_deputy[n] = row['nome_deputado_referencia']

    # 3. Carregar Doadores
    print("📋 Carregando lista de doadores (apenas para eleitos)...")
    df_doadores = pd.read_sql_query("SELECT DISTINCT socio, parlamentar, valor_doado_campanha FROM cruzamento_doacoes", conn)
    doadores = {}
    for _, row in df_doadores.iterrows():
        n_socio = normalize(row['socio'])
        n_parl = normalize(row['parlamentar'])
        
        # Só incluir se o destinatário da doação for um político eleito (presente no tabelao)
        if n_parl in politicos:
            if n_socio not in doadores: doadores[n_socio] = []
            doadores[n_socio].append({
                'parlamentar': row['parlamentar'],
                'valor': row['valor_doado_campanha']
            })

    # 4. Carregar Sócios de empresas que receberam emendas
    print("🔍 Buscando sócios de empresas recebedoras de emendas...")
    
    # Precisamos carregar as Tabelas e cruzar no Pandas para garantir limpeza dos CNPJs
    df_docs = pd.read_sql_query("SELECT cnpj, fornecedor as nome_recebedor, doc_valor as valor, codigo_emenda FROM documentos_emendas", conn)
    df_emendas_ref = pd.read_sql_query("SELECT codigo_emenda, autor_emenda FROM emendas", conn)
    df_qsa = pd.read_sql_query("SELECT cnpj, Nome_Socio, Nome as Nome_Empresa FROM lista_cnpj_geral WHERE Nome_Socio IS NOT NULL AND Nome_Socio != ''", conn)
    
    # Normalizar CNPJs para cruzamento
    df_docs['cnpj_clean'] = df_docs['cnpj'].astype(str).str.replace(r'\D', '', regex=True).str.zfill(14)
    df_qsa['cnpj_clean'] = df_qsa['cnpj'].astype(str).str.replace(r'\D', '', regex=True).str.zfill(14)
    
    # Merge Documentos com Autor da Emenda
    df_docs = pd.merge(df_docs, df_emendas_ref, on='codigo_emenda', how='left')
    
    # Central: Cruzar Documentos com Quadro de Sócios (QSA)
    df_partners = pd.merge(df_docs, df_qsa, on='cnpj_clean', how='inner')
    
    print(f"📊 Analisando {len(df_partners)} relações empresa-sócio...")
    
    # Limpar tabela anterior para novo cruzamento
    conn.execute("DELETE FROM cruzamento_emendas_sociedades")
    conn.commit()
    
    matches = []
    
    for _, row in tqdm(df_partners.iterrows(), total=len(df_partners), desc="Fazendo o Match"):
        socio_original = row['Nome_Socio']
        socio_norm = normalize(socio_original)
        
        if not socio_norm: continue
        
        # 4.1 Verificar Político/Assessor (Reciprocidade Direta)
        autor_raw = row['autor_emenda']
        if not isinstance(autor_raw, str): continue # Pula se o autor for nulo ou inválido
        
        n_autor_clean = normalize(autor_raw.split('/')[0])
        
        if socio_norm in politicos:
            # Sócio é o próprio político
            if socio_norm == n_autor_clean:
                matches.append((
                    row['autor_emenda'], row['cnpj_clean'], row['nome_recebedor'], row['valor'],
                    'N/A', row['codigo_emenda'], 'POLITICO', socio_original, politicos[socio_norm]
                ))
        
        if socio_norm in assessores:
            # Só mostrar se for assessor do MESMO autor da emenda
            deputado_vinc = assessor_to_deputy[socio_norm]
            if normalize(deputado_vinc) == n_autor_clean:
                vinc = f"{assessores[socio_norm]} (Assessor de {deputado_vinc})"
                matches.append((
                    row['autor_emenda'], row['cnpj_clean'], row['nome_recebedor'], row['valor'],
                    'N/A', row['codigo_emenda'], 'ASSESSOR', socio_original, vinc
                ))

        # 4.2 Verificar Doador de Campanha (Reciprocidade Direta)
        if socio_norm in doadores:
            for d in doadores[socio_norm]:
                if normalize(d['parlamentar']) == n_autor_clean:
                    vinc = f"Doador de {d['parlamentar']} (R$ {d['valor']:,.2f})"
                    matches.append((
                        row['autor_emenda'], row['cnpj_clean'], row['nome_recebedor'], row['valor'],
                        'N/A', row['codigo_emenda'], 'DOADOR', socio_original, vinc
                    ))

    if matches:
        print(f"🎯 Encontrados {len(matches)} potenciais conflitos!")
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO cruzamento_emendas_sociedades 
            (parlamentar_autor, cnpj_recebedor, nome_recebedor, valor_emenda, ano_emenda, codigo_emenda, tipo_vinculo, socio_vinc_parlamentar, vinculo_com_quem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, matches)
        conn.commit()
    else:
        print("ℹ️ Nenhum conflito direto detectado nesta rodada.")
        
    conn.close()
    print(f"✅ Cruzamento finalizado às {datetime.datetime.now()}")

if __name__ == "__main__":
    run_cross_reference()

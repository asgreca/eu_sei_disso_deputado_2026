import sqlite3
import pandas as pd
import requests
import time
import os
import glob
import re
import json
from tqdm import tqdm
from geopy.geocoders import ArcGIS
from geopy.extra.rate_limiter import RateLimiter
import unicodedata

# Configurações
DB_NAME = "tabelao.db"
RECEITA_DELAY = 21 # 20s + margem de segurança para free tier
GEO_DELAY = 0.5
BATCH_SIZE = 20

def normalizar_nome(nome):
    if not nome: return ""
    return "".join(c for c in unicodedata.normalize('NFKD', str(nome)) if not unicodedata.combining(c)).upper().strip()

def setup_db():
    conn = sqlite3.connect(DB_NAME, timeout=120) # Aumentar timeout para 120s
    conn.execute("PRAGMA journal_mode=WAL")      # Habilitar modo WAL para concorrência
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=120000")   # 120 segundos de espera interna do SQLite
    cursor = conn.cursor()
    
    # Tabela de Auditoria Triangular (Conflito Indireto)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auditoria_triangular_profunda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deputado_autor TEXT,
        municipio_cnpj TEXT,
        municipio_nome TEXT,
        contrato_id TEXT,
        valor_contrato REAL,
        empresa_cnpj TEXT,
        empresa_nome TEXT,
        socio_vinculado TEXT,
        tipo_vinculo TEXT, -- 'Direto', 'Nivel 2', 'Nivel 3'
        data_auditoria TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    return conn

def execute_with_retry(conn, query, params=None, retries=10, delay=5):
    """Executa uma query com retentativa em caso de 'database is locked'"""
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

def coletar_cnpjs_faltantes(conn):
    print("🔍 Escaneando CNPJs em emendas e contratos...")
    
    # CNPJs já conhecidos COM DADOS — exclui os sem nome (falha anterior) para re-tentar
    try:
        conhecidos_df = pd.read_sql_query(
            "SELECT DISTINCT cnpj FROM lista_cnpj_geral WHERE Nome IS NOT NULL AND Nome != ''", conn
        )
        conhecidos = set(
            conhecidos_df['cnpj'].astype(str).str.replace(r'\D', '', regex=True)
            .str.zfill(14).dropna()
        )
        print(f"✅ {len(conhecidos)} CNPJs já processados com sucesso (serão pulados)")
    except Exception as e:
        print(f"ℹ️  Nenhum cache encontrado na tabela 'lista_cnpj_geral'. Começando do zero. ({e})")
        conhecidos = set()

    # CNPJs em Documentos de Emendas
    try:
        emendas = pd.read_sql_query("SELECT DISTINCT cnpj FROM documentos_emendas", conn)
        cnpjs_emendas = set(
            emendas['cnpj'].astype(str).str.replace(r'\D', '', regex=True)
            .str.zfill(14).dropna()
        )
    except:
        cnpjs_emendas = set()

    # CNPJs em Contratos Locais
    cnpjs_contratos = set()
    arquivos = glob.glob("contratos_*.csv")
    for arq in arquivos:
        try:
            df = pd.read_csv(arq, sep=';', encoding='latin-1', usecols=lambda x: 'CNPJ' in x.upper())
            for col in df.columns:
                cnpjs_contratos.update(
                    df[col].astype(str).str.replace(r'\D', '', regex=True)
                    .str.zfill(14).dropna()
                )
        except: pass

    faltantes = (cnpjs_emendas | cnpjs_contratos) - conhecidos
    print(f"📊 Total de CNPJs únicos encontrados: {len(cnpjs_emendas | cnpjs_contratos)}")
    print(f"🆕 CNPJs novos para investigar: {len(faltantes)}")
    return list(faltantes)

def crawler_receita(cnpj, conn):
    url = f"https://www.receitaws.com.br/v1/cnpj/{cnpj}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'OK':
                base = {
                    'cnpj': str(cnpj),
                    'Nome': data.get('nome'),
                    'Logradouro': data.get('logradouro'),
                    'Bairro': data.get('bairro'),
                    'Cidade': data.get('municipio'),
                    'Estado': data.get('uf'),
                    'CEP': data.get('cep'),
                }
                
                # Salvar Empresa e Sócios (QSA) com retry
                qsa = data.get('qsa', [])
                try:
                    if not qsa:
                        pd.DataFrame([base]).to_sql('lista_cnpj_geral', conn, if_exists='append', index=False)
                    else:
                        rows = []
                        for socio in qsa:
                            row = base.copy()
                            row.update({
                                'Nome_Socio': socio.get('nome'),
                                'Qualificação_Socio': socio.get('qual'),
                                'CPF/CNPJ_Socio': socio.get('cpf', socio.get('cnpj'))
                            })
                            rows.append(row)
                        pd.DataFrame(rows).to_sql('lista_cnpj_geral', conn, if_exists='append', index=False)
                    conn.commit()
                except sqlite3.OperationalError:
                    print(f"⚠️ Banco travado ao salvar CNPJ {cnpj}. Tentando novamente no próximo ciclo...")
                    return False, None
                
                return True, base.get('cep')
        elif response.status_code == 429:
            print("⏳ Limite de API atingido. Aguardando...")
            time.sleep(60)
    except Exception as e:
        if "locked" in str(e).lower():
            print(f"⚠️ Banco travado no CNPJ {cnpj}")
        else:
            print(f"❌ Erro no CNPJ {cnpj}: {e}")
    return False, None

def geocodificar(cnpj, cep, conn):
    if not cep: return
    geolocator = ArcGIS(user_agent="tcc_auditor_v1")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=GEO_DELAY)
    
    try:
        location = geocode(f"{cep}, Brazil")
        if location:
            pd.DataFrame([{
                'cnpj': cnpj,
                'latitude': location.latitude,
                'longitude': location.longitude,
                'endereco_completo': location.address
            }]).to_sql('coordenadas_empresas', conn, if_exists='append', index=False)
            conn.commit()
    except: pass

def auditoria_triangular(conn):
    print("\n🕸️ Iniciando Auditoria Triangular de Nível 3...")
    
    # 1. Mapa de Influência (Deputado -> Municípios que receberam emendas dele)
    query_influencia = """
        SELECT e.autor_emenda, d.cnpj as cnpj_municipio, d.fornecedor as nome_municipio
        FROM emendas e
        JOIN documentos_emendas d ON e.codigo_emenda = d.codigo_emenda
        WHERE d.fornecedor LIKE '%PREFEITURA%' OR d.fornecedor LIKE '%MUNICIPIO%'
           OR d.fornecedor LIKE '%FUNDO MUNICIPAL%'
    """
    df_influ = pd.read_sql_query(query_influencia, conn)
    df_influ['autor_norm'] = df_influ['autor_emenda'].apply(normalizar_nome)
    
    # 2. Teia Corporativa (3 Níveis)
    print("🔗 Mapeando teia corporativa (3 níveis)...")
    # Simplificado para performance: Parlamentar -> Sócio -> Empresa do Sócio -> Co-Sócio -> Empresa do Co-Sócio
    parlamentares = set(pd.read_sql_query("SELECT DISTINCT nomeCivil FROM tabelao", conn)['nomeCivil'].apply(normalizar_nome))
    df_qsa = pd.read_sql_query("SELECT cnpj, Nome, Nome_Socio FROM lista_cnpj_geral", conn)
    df_qsa['Socio_Norm'] = df_qsa['Nome_Socio'].apply(normalizar_nome)
    
    # Nível 1: Empresa do Parlamentar
    empresas_n1 = df_qsa[df_qsa['Socio_Norm'].isin(parlamentares)]
    
    # Nível 2: Empresas de Co-Sócios do parlamentar
    cnpjs_n1 = set(empresas_n1['cnpj'])
    socios_n1 = set(df_qsa[df_qsa['cnpj'].isin(cnpjs_n1)]['Socio_Norm'])
    empresas_n2 = df_qsa[df_qsa['Socio_Norm'].isin(socios_n1)]
    
    # Nível 3: Empresas de Parceiros (Sócios dos sócios)
    cnpjs_n2 = set(empresas_n2['cnpj'])
    socios_n2 = set(df_qsa[df_qsa['cnpj'].isin(cnpjs_n2)]['Socio_Norm'])
    empresas_n3 = df_qsa[df_qsa['Socio_Norm'].isin(socios_n2)]
    
    teia = {
        'Direto': set(empresas_n1['cnpj']),
        'Nivel 2': set(empresas_n2['cnpj']) - set(empresas_n1['cnpj']),
        'Nivel 3': set(empresas_n3['cnpj']) - (set(empresas_n1['cnpj']) | set(empresas_n2['cnpj']))
    }

    # 3. Cruzamento Final com Contratos dos Municípios Influenciados
    arquivos_contratos = glob.glob("contratos_*.csv")
    for arq in arquivos_contratos:
        print(f"📄 Cruzando com {arq}...")
        df_c = pd.read_csv(arq, sep=';', encoding='latin-1')
        df_c.columns = [c.upper() for c in df_c.columns]
        
        # Colunas dinâmicas (Portal da Transparência muda nomes às vezes)
        col_cnpj_org = next((c for c in df_c.columns if 'ÓRGÃO' in c and 'CNPJ' in c), None)
        col_cnpj_forn = next((c for c in df_c.columns if 'CONTRATADO' in c and 'CNPJ' in c), None)
        
        if not col_cnpj_org or not col_cnpj_forn: continue
        
        for _, row in tqdm(df_c.iterrows(), total=len(df_c), desc="Auditando Triangulações"):
            cnpj_org = str(row[col_cnpj_org]).replace(r'\D', '', regex=True)
            cnpj_forn = str(row[col_cnpj_forn]).replace(r'\D', '', regex=True)
            
            # Existe empresa da teia ganhando contrato de órgão influenciado?
            match_influ = df_influ[df_influ['cnpj_municipio'].str.contains(cnpj_org, na=False)]
            
            if not match_influ.empty:
                for nivel, cnpjs_teia in teia.items():
                    if cnpj_forn in cnpjs_teia:
                        # Achamos um Triângulo!
                        for _, influ in match_influ.iterrows():
                            execute_with_retry(conn, """
                            INSERT INTO auditoria_triangular_profunda 
                            (deputado_autor, municipio_cnpj, municipio_nome, contrato_id, valor_contrato, empresa_cnpj, empresa_nome, socio_vinculado, tipo_vinculo)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                influ['autor_emenda'], influ['cnpj_municipio'], influ['nome_municipio'],
                                row.get('NÚMERO CONTRATO', 'N/A'), row.get('VALOR INICIAL', 0.0),
                                cnpj_forn, row.get('NOME CONTRATADO', 'N/A'), "Teia Corporativa", nivel
                            ))
        conn.commit()

def geocodificar_pendentes(conn):
    """Geocodifica CNPJs que já têm CEP na lista_cnpj_geral mas ainda não têm coordenadas."""
    com_coords = pd.read_sql_query(
        "SELECT DISTINCT cnpj FROM coordenadas_empresas WHERE latitude IS NOT NULL", conn
    )
    com_coords_set = set(com_coords['cnpj'].astype(str).str.replace(r'\D','',regex=True).str.zfill(14))

    pendentes = pd.read_sql_query(
        "SELECT cnpj, CEP FROM lista_cnpj_geral WHERE CEP IS NOT NULL AND CEP != '' AND Nome IS NOT NULL AND Nome != ''", conn
    )
    pendentes['cnpj_limpo'] = pendentes['cnpj'].astype(str).str.replace(r'\D','',regex=True).str.zfill(14)
    pendentes = pendentes[~pendentes['cnpj_limpo'].isin(com_coords_set)].drop_duplicates('cnpj_limpo')

    print(f"📍 {len(pendentes)} CNPJs com CEP mas sem coordenadas — geocodificando...")
    for _, row in tqdm(pendentes.iterrows(), total=len(pendentes), desc="Geocodificando"):
        geocodificar(row['cnpj_limpo'], row['CEP'], conn)

def main():
    conn = setup_db()

    # 1. Coleta e Crawler (Para quem não tem API paga, isto leva tempo)
    faltantes = coletar_cnpjs_faltantes(conn)
    if faltantes:
        print(f"📢 Começando o Crawler de {len(faltantes)} CNPJs. Isso levará tempo (21s por CNPJ)...")
        for cnpj in tqdm(faltantes, desc="Crawler ReceitaWS"):
            sucesso, cep = crawler_receita(cnpj, conn)
            if sucesso:
                geocodificar(cnpj, cep, conn)
            time.sleep(RECEITA_DELAY)

    # 2. Geocodificar pendentes (têm CEP mas sem lat/long)
    geocodificar_pendentes(conn)

    # 3. Auditoria de Triangulação
    auditoria_triangular(conn)
    
    conn.close()

if __name__ == "__main__":
    main()

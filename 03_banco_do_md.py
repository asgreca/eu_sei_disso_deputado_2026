import os
import re
import sqlite3
import pandas as pd
import hashlib
import requests
import io
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from tqdm import tqdm
from unicodedata import normalize
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- CONFIGURAÇÃO DOS CAMINHOS ---
PATH_PLENARIO = "./discursos_markdown/plenario"
PATH_COMISSAO = "./discursos_markdown/comissao"
DB_NAME = "discursos.db"

# --- FUNÇÃO AUXILIAR DE LOG ---
def log_status(mensagem):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] 📢 {mensagem}", flush=True)

# --- FUNÇÕES DE ENRIQUECIMENTO (DEPUTADOS) ---
def fetch_single_deputy_data(deputy_info):
    nome, uri = deputy_info
    headers = {'Accept': 'application/json'}
    try:
        response = requests.get(uri, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()['dados']
        status = data['ultimoStatus']
        nome_normalizado = normalize('NFKD', status['nome']).encode('ASCII', 'ignore').decode('ASCII').upper()
        return nome_normalizado, {'partido': status['siglaPartido'], 'estado': status['siglaUf']}
    except (requests.RequestException, KeyError, IndexError):
        return None

def fetch_deputies_data():
    log_status("Iniciando download da lista de deputados (CSV)...")
    try:
        url_deputados_csv = 'http://dadosabertos.camara.leg.br/arquivos/deputados/csv/deputados.csv'
        response_csv = requests.get(url_deputados_csv, timeout=30)
        response_csv.raise_for_status()
        csv_content = response_csv.content.decode('utf-8')
        df = pd.read_csv(io.StringIO(csv_content), delimiter=';')
        df_atual = df[df['idLegislaturaFinal'] == 57].copy()
        
        deputies_to_fetch = list(zip(df_atual['nome'], df_atual['uri']))
        log_status(f"Encontrados {len(deputies_to_fetch)} deputados. Coletando API...")
        
        deputies_map = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_deputy = {executor.submit(fetch_single_deputy_data, dep): dep for dep in deputies_to_fetch}
            for future in tqdm(as_completed(future_to_deputy), total=len(deputies_to_fetch), desc="API Deputados"):
                result = future.result()
                if result:
                    nome, data = result
                    deputies_map[nome] = data
        return deputies_map
    except Exception as e:
        log_status(f"❌ Erro lista deputados: {e}")
        return {}

def enrich_deputy_data(df, deputies_map):
    if not deputies_map: return df
    def get_info(row):
        parlamentar_norm = normalize('NFKD', str(row['Parlamentar'])).encode('ASCII', 'ignore').decode('ASCII').upper()
        deputy_info = deputies_map.get(parlamentar_norm)
        if deputy_info:
            row['Partido'] = deputy_info['partido']
            row['Estado'] = deputy_info['estado']
        return row
    # tqdm removido daqui para não poluir o log nos loops
    df = df.apply(get_info, axis=1)
    return df

# --- FUNÇÕES DE ENRIQUECIMENTO (COMISSÃO) ---
def fetch_single_commission_data(session_id):
    if not session_id or not str(session_id).isdigit():
        return session_id, "ID Inválido"
    url = f"https://dadosabertos.camara.leg.br/api/v2/eventos/{session_id}"
    headers = {'Accept': 'application/json'}
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 404: return session_id, "Comissão não encontrada"
            response.raise_for_status()
            data = response.json()['dados']
            orgaos = list(dict.fromkeys(orgao['nome'] for orgao in data.get('orgaos', []) if orgao.get('nome')))
            return session_id, ", ".join(orgaos) if orgaos else "Sem nome"
        except requests.RequestException:
            if attempt < 2: time.sleep(1)
            continue
    return session_id, "Erro API"

def enrich_with_commission_names(df):
    ids = df[df['Origem'] == 'Comissao']['Sessao'].unique()
    if len(ids) == 0:
        df['Comissao'] = 'Plenário'
        return df
        
    cache = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id = {executor.submit(fetch_single_commission_data, sid): sid for sid in ids}
        for future in as_completed(future_to_id): # tqdm removido para limpeza
            sid, name = future.result()
            cache[sid] = name
            
    df['Comissao'] = df['Sessao'].map(cache)
    df.loc[df['Origem'] == 'Plenario', 'Comissao'] = 'Plenário'
    df['Comissao'].fillna("-", inplace=True)
    return df

# --- UTILITÁRIOS ---
def calculate_file_hash(filepath):
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def calculate_row_hash(row):
    row_string = "".join(str(x) for x in row)
    return hashlib.sha256(row_string.encode('utf-8')).hexdigest()

def get_info_from_url(url_string):
    try:
        parsed = urlparse(url_string)
        qp = parse_qs(parsed.query)
        sessao = next((qp[k][0] for k in ['nuSessao', 'reuniao'] if k in qp), None)
        data = qp.get('Data', [None])[0]
        return sessao, data
    except: return None, None

def setup_database():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS discursos (
        ID INTEGER, Sessao TEXT, Parlamentar TEXT, Estado TEXT, Partido TEXT, 
        Origem TEXT, Comissao TEXT, Data TEXT, Texto TEXT, hash_linha TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS meta_processamento (
        filename TEXT PRIMARY KEY, file_hash TEXT, 
        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def get_processed_files():
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query("SELECT filename FROM meta_processamento", conn)
        # Retorna um SET (conjunto) para busca ultra-rápida O(1)
        return set(df['filename'].values)
    except: return set()
    finally: conn.close()

# --- PARSERS ---
def parse_plenario_file(filepath):
    try:
        with open(file9path, 'r', encoding='utf-8') as f: content = f.read()
        header, body = re.split(r'\n---\n', content, maxsplit=1)
        discurso_id = re.search(r'# Discurso ID: (\d+)', header).group(1)
        parlamentar = re.search(r'## Deputado\(a\): (.+)', header).group(1).replace('+', ' ').strip().upper()
        origem = re.search(r'## Origem: (.+)', header).group(1).strip().capitalize()
        url = re.search(r'\*\*URL:\*\* (.+)', header).group(1).strip()
        sessao, data = get_info_from_url(url)
        clean_body = re.sub(r'DISCURSO NA ÍNTEGRA.*?\n', '', body, flags=re.IGNORECASE).strip()
        clean_body = re.sub(r'^PRONUNCIAMENTO DO DEPUTADO.*?\n', '', clean_body, flags=re.IGNORECASE).strip()
        parts = re.split(r'(?:Senhor Presidente|Senhora Presidenta),', clean_body, maxsplit=1, flags=re.IGNORECASE)
        texto = parts[1].strip() if len(parts) > 1 else clean_body
        return [{'ID': int(discurso_id), 'Sessao': sessao, 'Parlamentar': parlamentar, 'Estado': None, 'Partido': None, 'Origem': origem, 'Data': data, 'Texto': texto}]
    except: return []

def parse_comissao_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f: content = f.read()
        header, body = re.split(r'\n---\n', content, maxsplit=1)
        discurso_id = re.search(r'# Discurso ID: (\d+)', header).group(1)
        origem = re.search(r'## Origem: (.+)', header).group(1).strip().capitalize()
        url = re.search(r'\*\*URL:\*\* (.+)', header).group(1).strip()
        sessao, data = get_info_from_url(url)
        records = []
        body = re.sub(r'\n(A SRA\.|O SR\.)', r'%%TURNO%%\1', body)
        for turno in body.split('%%TURNO%%'):
            turno = turno.strip()
            if not turno or ' - ' not in turno: continue
            info, texto = turno.rsplit(' - ', 1)
            parlamentar, partido, estado = None, None, None
            if "PRESIDENTE" in info.upper() or "PRESIDENTA" in info.upper():
                m = re.search(r'\((.*?)\.', info, re.DOTALL)
                if m: parlamentar = m.group(1).replace('\n', ' ').strip()
            else:
                m = re.search(r'^(?:A SRA\.|O SR\.)\s*([^()]+)', info)
                if m: parlamentar = m.group(1).strip()
            m_pe = re.search(r'([A-Z\d/]+)\s*-\s*([A-Z]{2})\s*\)', info)
            if m_pe: partido, estado = m_pe.groups()
            if parlamentar:
                records.append({'ID': int(discurso_id), 'Sessao': sessao, 'Parlamentar': parlamentar.upper(), 'Estado': estado, 'Partido': partido, 'Origem': origem, 'Data': data, 'Texto': texto.strip()})
        return records
    except: return []

# --- MAIN OTIMIZADA ---
def main():
    log_status("🚀 Iniciando Modo Turbo (Ignorando arquivos já processados)...")
    setup_database()
    deputies_map = fetch_deputies_data()
    
    # 1. Pega apenas os nomes dos arquivos que JÁ EXISTEM no banco
    log_status("Carregando lista de arquivos já processados do banco...")
    processed_filenames = get_processed_files()
    log_status(f"Já temos {len(processed_filenames)} arquivos no banco de dados.")

    # 2. Varredura Rápida (os.scandir)
    log_status("Escaneando diretórios (sem ler conteúdo)...")
    files_to_process = []
    
    for path, origin_type in [(PATH_PLENARIO, "Plenário"), (PATH_COMISSAO, "Comissão")]:
        if not os.path.exists(path): continue
        # scandir é muito mais rápido que listdir
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.endswith('.md'):
                    # AQUI ESTÁ A MÁGICA: Se o nome existe no banco, pula.
                    if entry.name in processed_filenames:
                        continue
                    # Se não existe, adiciona na lista para processar
                    files_to_process.append((entry.path, origin_type, entry.name))

    total_novos = len(files_to_process)
    log_status(f"📦 Arquivos NOVOS encontrados: {total_novos}")
    
    if total_novos == 0:
        log_status("✅ Nenhum arquivo novo. Banco atualizado.")
        return

    # 3. Processamento em LOTES (Batch) para não travar memória
    BATCH_SIZE = 1000
    conn = sqlite3.connect(DB_NAME, timeout=30)
    cursor = conn.cursor()

    try:
        for i in range(0, total_novos, BATCH_SIZE):
            batch = files_to_process[i : i + BATCH_SIZE]
            current_batch_num = (i // BATCH_SIZE) + 1
            total_batches = (total_novos // BATCH_SIZE) + 1
            
            log_status(f"⚙️ Processando Lote {current_batch_num}/{total_batches} ({len(batch)} arquivos)...")
            
            batch_records = []
            batch_meta = []
            
            # Agora sim lemos o conteúdo, mas só dos novos
            for filepath, origin, fname in tqdm(batch, desc=f"Lote {current_batch_num}"):
                fhash = calculate_file_hash(filepath) # Hash calculado agora
                recs = parse_plenario_file(filepath) if origin == "Plenário" else parse_comissao_file(filepath)
                if recs:
                    batch_records.extend(recs)
                    batch_meta.append({'filename': fname, 'file_hash': fhash})
            
            if not batch_records: continue

            # Cria DataFrame do lote
            df = pd.DataFrame(batch_records)
            
            # Limpeza rápida
            df['Parlamentar'] = df['Parlamentar'].astype(str).str.replace(r'^(DEPUTADO|DEPUTADA)\s+', '', regex=True).str.replace('\n', ' ').str.strip()
            df['Texto'] = df['Texto'].astype(str).str.replace('\n', ' ').str.strip()
            
            # Enriquecimento
            df = enrich_with_commission_names(df)
            df = enrich_deputy_data(df, deputies_map)
            
            # Formatação Final
            cols = ['ID', 'Sessao', 'Parlamentar', 'Estado', 'Partido', 'Origem', 'Comissao', 'Data', 'Texto']
            df = df[cols]
            df['hash_linha'] = df.apply(calculate_row_hash, axis=1)

            # Salva Lote no Banco
            df.to_sql('temp_discursos', conn, if_exists='replace', index=False)
            cursor.execute('''INSERT OR REPLACE INTO discursos 
                              (ID, Sessao, Parlamentar, Estado, Partido, Origem, Comissao, Data, Texto, hash_linha) 
                              SELECT ID, Sessao, Parlamentar, Estado, Partido, Origem, Comissao, Data, Texto, hash_linha 
                              FROM temp_discursos''')
            cursor.execute('DROP TABLE temp_discursos')

            # Salva Meta
            if batch_meta:
                meta_df = pd.DataFrame(batch_meta)
                meta_df.to_sql('temp_meta', conn, if_exists='replace', index=False)
                cursor.execute('INSERT OR REPLACE INTO meta_processamento (filename, file_hash) SELECT filename, file_hash FROM temp_meta')
                cursor.execute('DROP TABLE temp_meta')
            
            conn.commit()
            log_status(f"✅ Lote {current_batch_num} salvo com sucesso.")

        final_count = cursor.execute("SELECT COUNT(*) FROM discursos").fetchone()[0]
        log_status(f"🏁 FIM! Total de registros no banco: {final_count}")

    except Exception as e:
        log_status(f"❌ ERRO FATAL: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
import sqlite3
import pandas as pd
import requests
import zipfile
import io
import os
import unicodedata
import glob
from tqdm import tqdm

# Configurações
DB_NAME = "tabelao.db"
TSE_ZIP_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2022.zip"
DOWNLOAD_DIR = "downloads_tse"
LIMIT_SAMPLE = None # Mude para um número para rodar uma amostra (ex: 100)

def normalizar_nome(nome):
    if not nome:
        return ""
    # Remover acentos e colocar em maiúsculo
    nfkd_form = unicodedata.normalize('NFKD', str(nome))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).upper().strip()

def setup_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Tabela de cruzamento final (Doações) - Recriar se necessário para garantir sq_receita
    cursor.execute("DROP TABLE IF EXISTS cruzamento_doacoes")
    cursor.execute("""
    CREATE TABLE cruzamento_doacoes (
        sq_receita TEXT,
        cnpj TEXT,
        socio TEXT,
        parlamentar TEXT,
        valor_doado_campanha REAL,
        data_doacao TEXT,
        tp_receita TEXT,
        PRIMARY KEY (sq_receita, cnpj)
    )
    """)

    # Nova Tabela: Cruzamento Doadores x Contratos Públicos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cruzamento_doacoes_contratos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parlamentar TEXT,
        doador_socio TEXT,
        cnpj_empresa TEXT,
        nome_empresa TEXT,
        valor_contrato REAL,
        objeto_contrato TEXT,
        data_inicio TEXT,
        data_cruzamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Tabela de controle de processamento por CNPJ
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS controle_processamento_doacoes (
        cnpj TEXT PRIMARY KEY,
        status TEXT,
        data_processamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    return conn

def get_mapeamento_socios(conn):
    print("📋 Carregando mapeamento de sócios...")
    query = "SELECT cnpj, Nome_Socio FROM lista_cnpj_geral WHERE Nome_Socio IS NOT NULL AND Nome_Socio != ''"
    df = pd.read_sql_query(query, conn)
    df['Nome_Socio_Norm'] = df['Nome_Socio'].apply(normalizar_nome)
    
    # Criar um dicionário de busca rápida: {Nome_Normalizado: [Cnpj1, Cnpj2, ...]}
    mapeamento = {}
    for _, row in df.iterrows():
        nome = row['Nome_Socio_Norm']
        cnpj = str(row['cnpj'])
        if nome not in mapeamento:
            mapeamento[nome] = []
        if cnpj not in mapeamento[nome]:
            mapeamento[nome].append(cnpj)
            
    return mapeamento

def get_parlamentares_ativos(conn):
    print("📋 Carregando lista de parlamentares (nomeCivil e nome)...")
    query = "SELECT DISTINCT nomeCivil, nome, sgUF, sgPartido FROM tabelao"
    df = pd.read_sql_query(query, conn)
    mapeamento = {}
    for _, row in df.iterrows():
        uf = str(row['sgUF']).upper()
        partido = str(row['sgPartido']).upper()
        n1 = normalizar_nome(row['nomeCivil'])
        if n1: mapeamento[n1] = (uf, partido)
        n2 = normalizar_nome(row['nome'])
        if n2: mapeamento[n2] = (uf, partido)
    return mapeamento

def baixar_e_processar_tse(mapeamento_socios, parlamentares_ativos, conn, amostra=None):
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        
    local_zip = os.path.join(DOWNLOAD_DIR, "tse_2022_receitas.zip")
    
    if os.path.exists(local_zip):
        print(f"📦 Usando arquivo local: {local_zip}")
    else:
        print(f"🌐 Baixando dados do TSE: {TSE_ZIP_URL}")
        response = requests.get(TSE_ZIP_URL, stream=True)
        total_size = int(response.headers.get('content-length', 0))
        
        with open(local_zip, 'wb') as f_out:
            with tqdm(total=total_size, unit='B', unit_scale=True, desc="Download ZIP") as pbar:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f_out.write(chunk)
                        pbar.update(len(chunk))
    
    # Tabela de controle de arquivos (Para não reprocessar o mesmo CSV)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS controle_arquivos_tse (
        nome_arquivo TEXT PRIMARY KEY,
        data_processamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    
    print("📦 Extraindo e analisando arquivos do ZIP...")
    with zipfile.ZipFile(local_zip) as z:
        file_list = z.namelist()
        # Filtro: Apenas receitas de candidatos (exclui doador originário e despesas)
        # O arquivo _BRASIL.csv costuma ser o consolidado, mas vamos processar todos os estaduais 
        # para garantir cobertura caso o BRASIL esteja incompleto ou vice-versa, 
        # usando INSERT OR IGNORE no banco para evitar duplicatas.
        receitas_files = [f for f in file_list if "receitas_candidatos_2022" in f 
                          and f.endswith(".csv") 
                          and "doador_originario" not in f]
        
        print(f"found {len(receitas_files)} arquivos de receitas para processar.")
        
        for target_file in tqdm(receitas_files, desc="Arquivos TSE"):
            # Checkpoint do arquivo
            res = conn.execute("SELECT 1 FROM controle_arquivos_tse WHERE nome_arquivo = ?", (target_file,)).fetchone()
            if res:
                # print(f"   ⏩ {target_file} já processado. Pulando.")
                continue
                
            with z.open(target_file) as f:
                # Usar colunas cruciais para o match
                usecols = ['NM_DOADOR', 'NM_CANDIDATO', 'VR_RECEITA', 'DT_RECEITA', 'DS_RECEITA', 'SQ_RECEITA', 'SG_UF', 'SG_PARTIDO', 'DS_CARGO']
                chunks = pd.read_csv(f, sep=';', encoding='latin-1', chunksize=100000, usecols=usecols)
                
                total_encontrado_no_arquivo = 0
                for chunk in chunks:
                    # Normalizar doadores e candidatos do chunk
                    chunk['NM_DOADOR_NORM'] = chunk['NM_DOADOR'].apply(normalizar_nome)
                    chunk['NM_CANDIDATO_NORM'] = chunk['NM_CANDIDATO'].apply(normalizar_nome)
                    
                    # 1. Primeiro filtro rápido: Doadores que são sócios
                    matches_socios = chunk[chunk['NM_DOADOR_NORM'].isin(mapeamento_socios.keys())]
                    
                    if not matches_socios.empty:
                        # 2. Segundo filtro: Candidatos que são nossos parlamentares (VALIDAÇÃO POR NOME + UF + CARGO)
                        def is_real_match(row_data):
                            nome = row_data['NM_CANDIDATO_NORM']
                            uf = str(row_data['SG_UF']).upper().strip()
                            cargo = str(row_data['DS_CARGO']).upper()
                            
                            # Filtro de cargo: Focar em cargos federais
                            if "FEDERAL" not in cargo and "SENADOR" not in cargo:
                                return False
                                
                            if nome in parlamentares_ativos:
                                p_uf, p_partido = parlamentares_ativos[nome]
                                return uf == p_uf
                            return False
                            
                        matches_finais = matches_socios[matches_socios.apply(is_real_match, axis=1)]
                        
                        if not matches_finais.empty:
                            print(f"   🎯 Match Final Encontrado! ({len(matches_finais)} registros)")
                            for _, row in matches_finais.iterrows():
                                socio_norm = row['NM_DOADOR_NORM']
                                cnpjs_vivos = mapeamento_socios[socio_norm]
                                
                                for cnpj in cnpjs_vivos:
                                    try:
                                        conn.execute("""
                                        INSERT OR IGNORE INTO cruzamento_doacoes 
                                        (sq_receita, cnpj, socio, parlamentar, valor_doado_campanha, data_doacao, tp_receita)
                                        VALUES (?, ?, ?, ?, ?, ?, ?)
                                        """, (
                                            str(row['SQ_RECEITA']),
                                            cnpj, 
                                            row['NM_DOADOR'], 
                                            row['NM_CANDIDATO'], 
                                            float(str(row['VR_RECEITA']).replace(',', '.')), 
                                            row['DT_RECEITA'],
                                            row['DS_RECEITA']
                                        ))
                                    except Exception:
                                        pass
                                    
                            conn.commit()
                            total_encontrado_no_arquivo += len(matches_finais)
                            
                            if amostra and total_encontrado_no_arquivo >= amostra:
                                break
                
                # Marcar arquivo como concluído
                conn.execute("INSERT INTO controle_arquivos_tse (nome_arquivo) VALUES (?)", (target_file,))
                conn.commit()
                
                if amostra and total_encontrado_no_arquivo >= amostra:
                    print(f"✅ Amostra atingida no arquivo {target_file}.")
                    break

def main():
    conn = setup_db()
    
    # 1. Obter mapeamento de sócios (Filtro inicial)
    mapeamento = get_mapeamento_socios(conn)
    print(f"👥 Total de sócios mapeados para monitoramento: {len(mapeamento)}")
    
    # 2. Obter lista de parlamentares ativos
    parlamentares = get_parlamentares_ativos(conn)
    print(f"🏛️ Total de parlamentares ativos monitorados: {len(parlamentares)}")
    
    # 3. Processar TSE
    # Se quiser testar uma amostra, mude para um número, ex: 10
    baixar_e_processar_tse(mapeamento, parlamentares, conn, amostra=LIMIT_SAMPLE)
    
    res = conn.execute("SELECT COUNT(*) FROM cruzamento_doacoes").fetchone()[0]
    print(f"✨ Processamento de doações concluído! Cruzamentos salvos: {res}")
    
    # 4. Cruzamento com Contratos (Opcional - Requer CSVs do Portal da Transparência)
    arquivos_contratos = glob.glob("contratos_*.csv")
    if arquivos_contratos:
        print(f"🔍 Iniciando cruzamento extra com {len(arquivos_contratos)} arquivos de Contratos Públicos...")
        for arquivo in arquivos_contratos:
            print(f"   📄 Processando: {arquivo}")
            processar_contratos(conn, arquivo)
    else:
        print("💡 Dica: Rode com arquivos 'contratos_2023.csv', etc., do Portal da Transparência.")
    
    conn.close()

def processar_contratos(conn, emendas_file):
    """Cruza os doadores já identificados com a base de contratos do governo."""
    try:
        df_contratos = pd.read_csv(emendas_file, sep=';', encoding='latin-1')
        df_contratos.columns = [c.upper() for c in df_contratos.columns]
        
        # Carrega doadores identificados
        doadores = pd.read_sql_query("SELECT DISTINCT socio, cnpj, parlamentar FROM cruzamento_doacoes", conn)
        
        # Filtra contratos cujos CNPJs estão na nossa lista de doadores/empresas
        lista_cnpjs = set(doadores['cnpj'].astype(str).tolist())
        
        col_cnpj = next((c for c in df_contratos.columns if 'CONTRATADO' in c and 'CNPJ' in c), None)
        col_valor = next((c for c in df_contratos.columns if 'VALOR' in c and 'INICIAL' in c), None)
        
        if not col_cnpj:
            print("❌ Coluna de CNPJ não encontrada no CSV de contratos.")
            return

        for _, row in df_contratos.iterrows():
            cnpj_limpo = str(row[col_cnpj]).replace('.', '').replace('-', '').replace('/', '').strip()
            if cnpj_limpo in lista_cnpjs:
                info_doador = doadores[doadores['cnpj'] == cnpj_limpo].iloc[0]
                conn.execute("""
                INSERT INTO cruzamento_doacoes_contratos 
                (parlamentar, doador_socio, cnpj_empresa, nome_empresa, valor_contrato, objeto_contrato, data_inicio)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    info_doador['parlamentar'], info_doador['socio'], cnpj_limpo,
                    row.get('NOME CONTRATADO', 'N/A'), str(row[col_valor]).replace(',', '.'),
                    row.get('OBJETO', 'N/A'), row.get('DATA INÍCIO VIGÊNCIA', 'N/A')
                ))
        conn.commit()
        print("✨ Cruzamento Doação x Contratos concluído com sucesso!")
    except Exception as e:
        print(f"❌ Erro no processamento de contratos: {e}")

if __name__ == "__main__":
    main()

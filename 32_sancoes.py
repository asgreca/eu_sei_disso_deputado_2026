#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
32_sancoes.py — Auditoria de Sanções (CEIS/CEPIM)
Integra as bases de empresas inidôneas (CEIS) e ONGs impedidas (CEPIM) — dados
abertos publicados pela própria Controladoria-Geral da União (CGU) no Portal da
Transparência — com o Tabelão. Identifica se empresas/ONGs contrataram com o
governo ou receberam emendas parlamentares ENQUANTO estavam punidas.

Fonte oficial (dados abertos, formato aberto, sem necessidade de chave de API):
  https://portaldatransparencia.gov.br/download-de-dados/ceis
  https://portaldatransparencia.gov.br/download-de-dados/cepim

O script baixa automaticamente o extrato completo mais recente já publicado
(a CGU atualiza esses extratos diariamente, mas com alguns dias de defasagem
até a publicação — por isso tentamos alguns dias para trás). Se a rede estiver
indisponível, reaproveita o CSV mais recente já baixado anteriormente na pasta
do projeto (padrão de nome `AAAAMMDD_CEIS.csv` / `AAAAMMDD_CEPIM.csv`, igual ao
publicado pela CGU).
"""

import sqlite3
import pandas as pd
import os
import glob
import io
import zipfile
import logging
import requests
from tqdm import tqdm
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações
DB_NAME = "tabelao.db"
BASE_DOWNLOAD_URL = "https://portaldatransparencia.gov.br/download-de-dados"
MAX_DIAS_TENTATIVA = 15  # publicação do extrato tem alguns dias de defasagem


def _csv_local_mais_recente(sufixo):
    """Reaproveita o CSV `AAAAMMDD_<sufixo>.csv` mais recente já presente no projeto."""
    candidatos = sorted(glob.glob(f"[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_{sufixo}.csv"), reverse=True)
    return candidatos[0] if candidatos else None


def baixar_extrato_cgu(dataset, sufixo_arquivo):
    """
    Baixa o extrato completo (CEIS ou CEPIM) publicado pela CGU no Portal da
    Transparência, em formato aberto (ZIP contendo um CSV ';'-delimitado,
    encoding ISO-8859-1 — o mesmo formato que a CGU disponibiliza para download
    manual). Tenta os últimos `MAX_DIAS_TENTATIVA` dias até achar uma data
    já publicada. Retorna o caminho do CSV local (baixado ou reaproveitado).
    """
    hoje = datetime.now()
    for i in range(MAX_DIAS_TENTATIVA):
        data_ref = hoje - timedelta(days=i)
        aaaammdd = data_ref.strftime("%Y%m%d")
        nome_csv = f"{aaaammdd}_{sufixo_arquivo}.csv"

        if os.path.exists(nome_csv):
            return nome_csv

        url = f"{BASE_DOWNLOAD_URL}/{dataset}/{aaaammdd}"
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200 or len(resp.content) < 1000:
                continue
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                membro = next((n for n in zf.namelist() if n.lower().endswith('.csv')), None)
                if not membro:
                    continue
                zf.extract(membro, ".")
                if membro != nome_csv:
                    os.replace(membro, nome_csv)
            print(f"✅ Extrato {dataset.upper()} de {aaaammdd} baixado do Portal da Transparência (CGU).")
            return nome_csv
        except (requests.RequestException, zipfile.BadZipFile) as e:
            logger.debug(f"Falha ao baixar {dataset} para {aaaammdd}: {e}")
            continue

    # Rede indisponível ou nenhum extrato recente publicado: reaproveita o mais recente já em disco
    fallback = _csv_local_mais_recente(sufixo_arquivo)
    if fallback:
        print(f"⚠️  Não foi possível baixar um extrato novo de {dataset.upper()}. Reaproveitando '{fallback}' já existente.")
        return fallback

    raise RuntimeError(
        f"Não foi possível obter o extrato {dataset.upper()} da CGU (nem via download automático, nem localmente). "
        f"Baixe manualmente em {BASE_DOWNLOAD_URL}/{dataset} e salve como AAAAMMDD_{sufixo_arquivo}.csv na raiz do projeto."
    )

def setup_db():
    conn = sqlite3.connect(DB_NAME, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()
    
    # Tabela de Sanções CEIS (Empresas)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lista_ceis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cnpj TEXT,
        nome_sancionado TEXT,
        tipo_pessoa TEXT,
        categoria_sancao TEXT,
        data_inicio DATE,
        data_fim DATE,
        orgao_sancionador TEXT,
        uf_orgao TEXT,
        UNIQUE(cnpj, data_inicio, categoria_sancao)
    )
    """)
    
    # Tabela de Sanções CEPIM (ONGs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lista_cepim (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cnpj TEXT,
        nome_entidade TEXT,
        motivo TEXT,
        UNIQUE(cnpj)
    )
    """)

    # Tabela de Auditoria de Sanções
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auditoria_sancoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT, -- 'CEIS' ou 'CEPIM'
        cnpj TEXT,
        nome_entidade TEXT,
        id_vinculo TEXT, -- ID da emenda ou nome do contrato
        data_evento DATE, -- Data da emenda/contrato
        sancao_inicio DATE,
        sancao_fim DATE,
        conflito_historico INTEGER, -- 1 se a data_evento está no intervalo da sanção
        detalhes TEXT
    )
    """)
    conn.commit()
    return conn

def limpar_cnpj(val):
    if not val or pd.isna(val): return ""
    return ''.join(filter(str.isdigit, str(val))).zfill(14)

def converter_data(val):
    if not val or pd.isna(val) or val == "": return None
    try:
        return datetime.strptime(str(val), "%d/%m/%Y").strftime("%Y-%m-%d")
    except:
        return None

def ingest_ceis(conn, ceis_file):
    print(f"📦 Ingerindo {ceis_file}...")
    try:
        # CEIS usa ponto e vírgula e encoding Latin-1/ISO-8859-1
        df = pd.read_csv(ceis_file, sep=';', encoding='iso-8859-1', dtype=str)
        
        # Normalizar nomes de colunas (remover acentos e caracteres especiais mangled)
        # Ex: "DATA INCIO SANO" -> "DATA INICIO SANCAO"
        def normalizar_coluna(c):
            c = ''.join(i for i in c if ord(i) < 128) # Manter apenas ASCII
            return c.upper().strip().replace('  ', ' ')
        
        df.columns = [normalizar_coluna(col) for col in df.columns]
        
        # Mapeamento dinâmico baseado em palavras-chave
        col_cnpj = next((c for c in df.columns if 'CPF' in c and 'CNPJ' in c), None)
        col_nome = next((c for c in df.columns if 'NOME' in c and 'SANCIONADO' in c), None)
        col_cat = next((c for c in df.columns if 'CATEGORIA' in c and 'SANCAO' in c), None)
        col_ini = next((c for c in df.columns if 'DATA' in c and 'INCIO' in c), None) # "INCIO" por causa do ASCII
        col_fim = next((c for c in df.columns if 'DATA' in c and 'FINAL' in c), None)
        col_org = next((c for c in df.columns if 'RG O' in c and 'SANCIONADOR' in c or 'ORGAO SANCIONADOR' in c), None)

        if not col_cnpj or not col_ini:
            print(f"  ❌ Colunas críticas não encontradas. Colunas lidas: {df.columns}")
            return

        df['cnpj_limpo'] = df[col_cnpj].apply(limpar_cnpj)
        df['dt_ini'] = df[col_ini].apply(converter_data)
        df['dt_fim'] = df[col_fim].apply(converter_data) if col_fim else None
        
        count = 0
        for _, row in tqdm(df.iterrows(), total=len(df), desc="Lendo CEIS"):
            if not row['cnpj_limpo']: continue
            try:
                conn.execute("""
                INSERT OR IGNORE INTO lista_ceis (cnpj, nome_sancionado, tipo_pessoa, categoria_sancao, data_inicio, data_fim, orgao_sancionador)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (row['cnpj_limpo'], row[col_nome] if col_nome else "", row.get('TIPO DE PESSOA', ''), 
                      row[col_cat] if col_cat else "", row['dt_ini'], row['dt_fim'], 
                      row[col_org] if col_org else ""))
                count += 1
            except: pass
            
        conn.commit()
        print(f"✅ {count} registros de sanções (CEIS) inseridos.")
    except Exception as e:
        print(f"❌ Erro ao ler CEIS: {e}")

def ingest_cepim(conn, cepim_file):
    print(f"📦 Ingerindo {cepim_file}...")
    try:
        df = pd.read_csv(cepim_file, sep=';', encoding='iso-8859-1', dtype=str)
        df['cnpj_limpo'] = df['CNPJ ENTIDADE'].apply(limpar_cnpj)
        
        count = 0
        for _, row in tqdm(df.iterrows(), total=len(df), desc="Lendo CEPIM"):
            if not row['cnpj_limpo']: continue
            try:
                conn.execute("""
                INSERT OR IGNORE INTO lista_cepim (cnpj, nome_entidade, motivo)
                VALUES (?, ?, ?)
                """, (row['cnpj_limpo'], row['NOME ENTIDADE'], row['MOTIVO DO IMPEDIMENTO']))
                count += 1
            except: pass
            
        conn.commit()
        print(f"✅ {count} registros de ONGs impedidas (CEPIM) inseridos.")
    except Exception as e:
        print(f"❌ Erro ao ler CEPIM: {e}")

def cruzamento_historico(conn):
    print("\n🕵️‍♂️ Iniciando Cruzamento Histórico (Sancionados vs Emendas/Contratos)...")

    # Reprocessa do zero a cada execução: evita duplicar alertas quando o script
    # roda de novo após um extrato CEIS/CEPIM mais recente ser baixado.
    conn.execute("DELETE FROM auditoria_sancoes")
    conn.commit()

    # 1. Cruzar CEIS com Emendas
    print("  🔍 Verificando Emendas enviadas para empresas no CEIS...")
    query_emendas = """
    SELECT d.cnpj, d.codigo_emenda, d.doc_data, c.nome_sancionado, c.data_inicio, c.data_fim, c.categoria_sancao
    FROM documentos_emendas d
    JOIN lista_ceis c ON REPLACE(REPLACE(REPLACE(d.cnpj, '.', ''), '-', ''), '/', '') = c.cnpj
    """
    try:
        df_audit = pd.read_sql_query(query_emendas, conn)
        total_emendas = 0
        for _, row in tqdm(df_audit.iterrows(), total=len(df_audit), desc="Auditando Emendas"):
            # Lógica de conflito histórico
            is_conflito = 0
            dt_evento = converter_data(row['doc_data']) # Garantir formato YYYY-MM-DD
            dt_ini = row['data_inicio']
            dt_fim = row['data_fim']
            
            if dt_ini and dt_evento:
                if dt_evento >= dt_ini:
                    if not dt_fim or dt_evento <= dt_fim:
                        is_conflito = 1
            
            if is_conflito:
                conn.execute("""
                INSERT INTO auditoria_sancoes (tipo, cnpj, nome_entidade, id_vinculo, data_evento, sancao_inicio, sancao_fim, conflito_historico, detalhes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ('CEIS/EMENDA', row['cnpj'], row['nome_sancionado'], row['codigo_emenda'], 
                      dt_evento, dt_ini, dt_fim, 1, f"Categoria: {row['categoria_sancao']}"))
                total_emendas += 1
            
        conn.commit()
        print(f"  ✨ Encontrados {total_emendas} conflitos históricos em emendas.")
    except Exception as e:
        print(f"  ⚠️ Erro no cruzamento de emendas: {e}")

    # 2. Cruzar CEPIM com Emendas
    print("  🔍 Verificando Emendas enviadas para ONGs no CEPIM...")
    query_cepim = """
    SELECT d.cnpj, d.codigo_emenda, d.doc_data, c.nome_entidade, c.motivo
    FROM documentos_emendas d
    JOIN lista_cepim c ON REPLACE(REPLACE(REPLACE(d.cnpj, '.', ''), '-', ''), '/', '') = c.cnpj
    """
    try:
        df_cepim = pd.read_sql_query(query_cepim, conn)
        total_cepim = 0
        for _, row in tqdm(df_cepim.iterrows(), total=len(df_cepim), desc="Auditando CEPIM"):
            dt_evento = converter_data(row['doc_data'])
            conn.execute("""
            INSERT INTO auditoria_sancoes (tipo, cnpj, nome_entidade, id_vinculo, data_evento, conflito_historico, detalhes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ('CEPIM/EMENDA', row['cnpj'], row['nome_entidade'], row['codigo_emenda'], 
                  dt_evento, 1, f"Motivo: {row['motivo']}"))
            total_cepim += 1
        conn.commit()
        print(f"  ✨ {total_cepim} emendas para ONGs impedidas identificadas.")
    except Exception as e:
        print(f"  ⚠️ Erro no cruzamento de CEPIM: {e}")

    # 3. Cruzar CEIS com Contratos da Transparência (CSV)
    print("\n  🔍 Verificando Contratos Públicos com empresas no CEIS...")
    arquivos_contratos = glob.glob("contratos_*.csv")
    total_contratos = 0
    
    # Carregar CNPJs punidos para busca rápida
    df_ceis = pd.read_sql_query("SELECT cnpj, nome_sancionado, data_inicio, data_fim FROM lista_ceis", conn)
    ceis_dict = df_ceis.groupby('cnpj').apply(lambda x: x.to_dict('records')).to_dict()

    for arq in tqdm(arquivos_contratos, desc="Processando Contratos"):
        try:
            df_c = pd.read_csv(arq, sep=';', encoding='iso-8859-1', dtype=str)
            
            # Identificar colunas dinamicamente (para evitar problemas de encoding)
            col_cnpj = None
            col_data = None
            col_num = None
            
            for col in df_c.columns:
                c_norm = col.lower().replace(' ', '')
                if 'cdigo' in c_norm and 'contratado' in c_norm: col_cnpj = col
                if 'data' in c_norm and 'assinatura' in c_norm: col_data = col
                if 'nmero' in c_norm and 'contrato' in c_norm: col_num = col
            
            if not col_cnpj or not col_data:
                # Se falhar, tentar buscar apenas por 'contratado' ou 'cnpj'
                for col in df_c.columns:
                    c_norm = col.lower()
                    if not col_cnpj and ('contratado' in c_norm or 'cnpj' in c_norm): col_cnpj = col
                    if not col_data and ('data' in c_norm and ('assinatura' in c_norm or 'celebracao' in c_norm)): col_data = col

            if not col_cnpj or not col_data:
                print(f"  ⚠️ Colunas não identificadas em {arq}. Pulando.")
                continue

            # Limpar CNPJs
            df_c['cnpj_limpo'] = df_c[col_cnpj].apply(limpar_cnpj)
            
            for _, cont in df_c.iterrows():
                cnpj = cont['cnpj_limpo']
                if cnpj in ceis_dict:
                    dt_ass = converter_data(cont[col_data])
                    for sancao in ceis_dict[cnpj]:
                        is_conflito = 0
                        s_ini = sancao['data_inicio']
                        s_fim = sancao['data_fim']
                        
                        if s_ini and dt_ass:
                            if dt_ass >= s_ini:
                                if not s_fim or dt_ass <= s_fim:
                                    is_conflito = 1
                        
                        if is_conflito:
                            conn.execute("""
                            INSERT INTO auditoria_sancoes (tipo, cnpj, nome_entidade, id_vinculo, data_evento, sancao_inicio, sancao_fim, conflito_historico, detalhes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, ('CEIS/CONTRATO', cnpj, sancao['nome_sancionado'], cont.get(col_num or 'N/A'), 
                                  dt_ass, s_ini, s_fim, 1, f"Contrato em {arq}"))
                            total_contratos += 1
        except Exception as e:
            print(f"  ⚠️ Erro no arquivo {arq}: {e}")
            
    conn.commit()
    print(f"  ✨ Encontrados {total_contratos} conflitos históricos em contratos públicos.")

def main():
    import sys
    refresh = "--refresh" in sys.argv

    conn = setup_db()
    ceis_count = conn.execute("SELECT COUNT(*) FROM lista_ceis").fetchone()[0]

    # Ingestão só roda se as tabelas estiverem vazias (poupar tempo) ou se
    # --refresh for passado explicitamente (baixa o extrato mais recente da CGU).
    if ceis_count == 0 or refresh:
        if refresh:
            conn.execute("DELETE FROM lista_ceis")
            conn.execute("DELETE FROM lista_cepim")
            conn.commit()
        ceis_file = baixar_extrato_cgu("ceis", "CEIS")
        cepim_file = baixar_extrato_cgu("cepim", "CEPIM")
        ingest_ceis(conn, ceis_file)
        ingest_cepim(conn, cepim_file)

    cruzamento_historico(conn)
    conn.close()
    print("\n✅ Auditoria de Sanções concluída! Verifique a tabela 'auditoria_sancoes'.")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
32_sancoes.py — Auditoria de Sanções (CEIS/CEPIM)
Integra as bases de empresas inidôneas e ONGs impedidas com o Tabelão.
Identifica se empresas contrataram com o governo ENQUANTO estavam punidas.
"""

import sqlite3
import pandas as pd
import os
import glob
from tqdm import tqdm
from datetime import datetime

# Configurações
DB_NAME = "tabelao.db"
CEIS_FILE = "20260403_CEIS.csv"
CEPIM_FILE = "20260401_CEPIM.csv"

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

def ingest_ceis(conn):
    print(f"📦 Ingerindo {CEIS_FILE}...")
    try:
        # CEIS usa ponto e vírgula e encoding Latin-1/ISO-8859-1
        df = pd.read_csv(CEIS_FILE, sep=';', encoding='iso-8859-1', dtype=str)
        
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

def ingest_cepim(conn):
    print(f"📦 Ingerindo {CEPIM_FILE}...")
    try:
        df = pd.read_csv(CEPIM_FILE, sep=';', encoding='iso-8859-1', dtype=str)
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
    conn = setup_db()
    # Ingestão apenas se as tabelas estiverem vazias para poupar tempo
    ceis_count = conn.execute("SELECT COUNT(*) FROM lista_ceis").fetchone()[0]
    if ceis_count == 0:
        ingest_ceis(conn)
        ingest_cepim(conn)
    
    cruzamento_historico(conn)
    conn.close()
    print("\n✅ Auditoria de Sanções concluída! Verifique a tabela 'auditoria_sancoes'.")

if __name__ == "__main__":
    main()

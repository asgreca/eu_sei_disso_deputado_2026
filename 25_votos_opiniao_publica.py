import sqlite3
import json
import time
from datetime import datetime

# Configuração
DB_PATH = "tabelao.db"

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Nova tabela unificada
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS votacoes_unificadas (
        id_votacao TEXT PRIMARY KEY,
        data_registro TEXT,
        sigla_orgao TEXT,
        proposicao TEXT,
        descricao TEXT,
        
        -- Dados de Mídia (do script 22)
        cobertura_midia INTEGER DEFAULT 0, -- 0 ou 1
        resumo_midia TEXT,
        posicao_midia TEXT,
        links_noticias TEXT,

        -- Dados de Voto (do script 24)
        tipo_votacao TEXT, -- 'Nominal' ou 'Simbólica'
        tem_votos_nominais INTEGER DEFAULT 0, -- 0 ou 1
        
        updated_at TEXT
    )
    """)
    
    # Índices
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_unificadas_data ON votacoes_unificadas (data_registro)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_unificadas_midia ON votacoes_unificadas (cobertura_midia)")
    
    conn.commit()
    conn.close()

def merge_data():
    init_db()
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("🚀 Iniciando unificação de votações (Mídia + Votos)...")
    
    # 1. Carregar dados de Mídia (votacoes_destaque) - Script 22
    # Prioridade alta pois tem info de mídia
    print("📦 Carregando dados de votacoes_destaque (Mídia)...")
    cursor.execute("SELECT * FROM votacoes_destaque")
    destaque_rows = cursor.fetchall()
    destaque_map = {row['id_votacao']: dict(row) for row in destaque_rows}
    print(f"   - {len(destaque_map)} registros com análise de mídia.")
    
    # 2. Carregar Votações Simbólicas - Script 24
    print("📦 Carregando votacoes_simbolicas_geral...")
    try:
        cursor.execute("SELECT * FROM votacoes_simbolicas_geral")
        simbolicas_rows = cursor.fetchall()
        simbolicas_map = {row['id_votacao']: dict(row) for row in simbolicas_rows}
        print(f"   - {len(simbolicas_map)} registros simbólicos.")
    except sqlite3.OperationalError:
        print("   ⚠️  Tabela votacoes_simbolicas_geral não encontrada. Pule se ainda não rodou o script 24.")
        simbolicas_map = {}

    # 3. Carregar IDs Totais de Votos Nominais - Script 24
    # Para saber quais são nominais, basta ver se tem ID na tabela de votos ou pegar do script 24 se ele salvou metadados (ele salvou votos).
    # Vamos pegar distinct ids da tabela de votos totais.
    print("📦 Identificando votações com votos nominais (votos_parlamentares_totais)...")
    try:
        cursor.execute("SELECT DISTINCT id_votacao FROM votos_parlamentares_totais")
        nominais_ids = {row[0] for row in cursor.fetchall()}
        print(f"   - {len(nominais_ids)} votações com votos nominais.")
    except sqlite3.OperationalError:
        print("   ⚠️  Tabela votos_parlamentares_totais não encontrada.")
        nominais_ids = set()
        
    # Unir todos os IDs únicos
    all_ids = set(destaque_map.keys()) | set(simbolicas_map.keys()) | nominais_ids
    total_ids = len(all_ids)
    print(f"\n📋 Total de votações únicas identificadas: {total_ids}")
    
    count_saved = 0
    now = datetime.now().isoformat()
    
    for idx, vid in enumerate(all_ids):
        # Prioridades de Dados:
        # 1. Dados de Destaque (tem info rica de proposicao, resumo, mídia)
        # 2. Dados Simbólicos (tem metadados básicos)
        # 3. Se só tiver id nominal, precisamos buscar metadados onde? 
        #    O script 24 não salvou 'votacoes_nominais_metadata', só os votos.
        #    Mas se está em 'votacoes_destaque', ok.
        #    Se não está em destaque e é nominal, faltam dados de descrição/proposição se não buscarmos.
        #    Vamos assumir que se é nominal, ou está em destaque ou precisamos aceitar dados parciais.
        
        # Base data
        base = {}
        source = ""
        
        if vid in destaque_map:
            row = destaque_map[vid]
            base = {
                'id_votacao': vid,
                'data_registro': row.get('data'),
                'sigla_orgao': row.get('sigla_orgao'),
                'proposicao': row.get('proposicao'),
                'descricao': row.get('resumo_camara'), # ou row['proposicao']
                'cobertura_midia': row.get('cobertura_midia', 0),
                'resumo_midia': row.get('resumo_midia'),
                'posicao_midia': row.get('posicao_midia'),
                'links_noticias': row.get('links_noticias')
            }
            source = "Destaque"
        elif vid in simbolicas_map:
            row = simbolicas_map[vid]
            base = {
                'id_votacao': vid,
                'data_registro': row.get('data_registro'),
                'sigla_orgao': row.get('sigla_orgao'),
                'proposicao': row.get('proposicao'),
                'descricao': row.get('descricao'),
                'cobertura_midia': 0, # Default Não
                'resumo_midia': None,
                'posicao_midia': None,
                'links_noticias': None
            }
            source = "Simbólica"
        else:
            # Apenas Nominal sem metadata rico (pode acontecer se o script 22 não pegou mas o 24 pegou?)
            # O script 24 percorre TUDO. Então se é nominal e não está em Simbólica, 
            # e se não está em destaque (que filtra cobertura mídia), então é uma nominal sem mídia.
            # Mas faltam os metadados (proposicao, etc) pq o script 24 só salvou os VOTOS.
            # Ideal seria o script 24 ter salvo metadados das nominais também.
            # Mas vamos preencher com "Dados Nominais (Recuperar)" por enquanto ou NULL.
            base = {
                'id_votacao': vid,
                'data_registro': None, # Não temos fácil aqui, teríamos que consultar a API ou tabela votos (data_registro do voto serve de proxy)
                'sigla_orgao': None,
                'proposicao': "Votação Nominal (Verificar API)",
                'descricao': None,
                'cobertura_midia': 0,
                'resumo_midia': None,
                'posicao_midia': None,
                'links_noticias': None
            }
            source = "Nominal-Only"
            
            # Tentar recuperar algo da tabela de votos
            if vid in nominais_ids:
                try:
                    # Pegar 1 voto para extrair data e orgao
                    cursor.execute("SELECT data_registro, comissao FROM votos_parlamentares_totais WHERE id_votacao = ? LIMIT 1", (vid,))
                    vrow = cursor.fetchone()
                    if vrow:
                        base['data_registro'] = vrow['data_registro']
                        base['sigla_orgao'] = vrow['comissao']
                except:
                    pass

        # Determinar Tipo e Flag Nominal
        is_nominal = vid in nominais_ids
        base['tem_votos_nominais'] = 1 if is_nominal else 0
        
        if vid in simbolicas_map:
             base['tipo_votacao'] = 'Simbólica'
        elif is_nominal:
             base['tipo_votacao'] = 'Nominal'
        else:
             base['tipo_votacao'] = 'Desconhecido'
             
        # Insert or Replace
        cursor.execute("""
        INSERT OR REPLACE INTO votacoes_unificadas (
            id_votacao, data_registro, sigla_orgao, proposicao, descricao,
            cobertura_midia, resumo_midia, posicao_midia, links_noticias,
            tipo_votacao, tem_votos_nominais, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            base['id_votacao'],
            base['data_registro'],
            base['sigla_orgao'],
            base['proposicao'],
            base['descricao'],
            base['cobertura_midia'],
            base['resumo_midia'],
            base['posicao_midia'],
            base['links_noticias'],
            base['tipo_votacao'],
            base['tem_votos_nominais'],
            now
        ))
        count_saved += 1
        
        if idx % 100 == 0:
            print(f"   Processando... {idx}/{total_ids}", end="\r")
            
    print(f"\n✅ Unificação concluída! {count_saved} registros salvos em 'votacoes_unificadas'.")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    merge_data()

import sqlite3
import requests
import time
import os
import json
from datetime import datetime

# Configuração
DB_PATH = "tabelao.db"
API_CAMARA_VOTACOES = "https://dadosabertos.camara.leg.br/api/v2/votacoes"
API_CAMARA_VOTOS = "https://dadosabertos.camara.leg.br/api/v2/votacoes/{id}/votos"

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Tabela para Votos NOMINAIS (Quem votou o que)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS votos_parlamentares_totais (
        id_votacao TEXT,
        nome_deputado TEXT,
        partido TEXT,
        uf TEXT,
        voto TEXT,
        comissao TEXT,
        data_registro TEXT,
        PRIMARY KEY (id_votacao, nome_deputado)
    )
    """)
    
    # Índices para Nominais
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votos_totais_deputado ON votos_parlamentares_totais (nome_deputado)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votos_totais_votacao ON votos_parlamentares_totais (id_votacao)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votos_totais_comissao ON votos_parlamentares_totais (comissao)")
    
    # 2. Tabela para Votações SIMBÓLICAS (Sem votos individuais)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS votacoes_simbolicas_geral (
        id_votacao TEXT PRIMARY KEY,
        data_registro TEXT,
        sigla_orgao TEXT,
        proposicao TEXT,
        descricao TEXT,
        motivo TEXT,
        updated_at TEXT
    )
    """)
    
    # Índice para Simbólicas
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_simbolicas_orgao ON votacoes_simbolicas_geral (sigla_orgao)")
    
    conn.commit()
    conn.close()

def fetch_all_votings(start_date="2023-01-01"):
    """
    Busca todas as votações na API da Câmara a partir da data de início.
    Lida com paginação automaticamente.
    """
    votings = []
    page = 1
    params = {
        "dataInicio": start_date,
        "ordem": "ASC",
        "ordenarPor": "dataHoraRegistro",
        "itens": 200,  # Max items per page
        "pagina": page
    }
    
    print(f"🔄 Buscando lista de votações a partir de {start_date}...")
    
    while True:
        try:
            params["pagina"] = page
            response = requests.get(API_CAMARA_VOTACOES, params=params)
            
            if response.status_code != 200:
                print(f"   ⚠️ Erro na página {page}: {response.status_code}")
                break
                
            data = response.json()
            items = data.get('dados', [])
            
            if not items:
                print("   🏁 Fim da paginação.")
                break
            
            votings.extend(items)
            print(f"   📄 Página {page}: {len(items)} votações encontradas (Total acumulado: {len(votings)})")
            
            # Verificar se tem próxima página
            links = data.get('links', [])
            has_next = any(l['rel'] == 'next' for l in links)
            if not has_next:
                break
                
            page += 1
            time.sleep(0.3) # Leve delay para evitar bloqueio
            
        except Exception as e:
            print(f"   ❌ Erro de conexão na página {page}: {e}")
            time.sleep(5)
            break
            
    return votings

def process_votes():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Buscar TODAS as votações
    all_votings = fetch_all_votings("2023-01-01")
    total = len(all_votings)
    print(f"\n📋 Total de votações encontradas na API: {total}")
    print("🚀 Iniciando processamento e separação (Nominal vs Simbólica)...\n")
    
    nominal_count = 0
    symbolic_count = 0
    skips = 0
    
    # Prepara statements para evitar repetição de query string no loop
    # Mas sqlite em python não tem prepare explicito fácil de reutilizar fora da string, uso direto mesmo.

    for idx, voting in enumerate(all_votings):
        id_votacao = voting['id']
        sigla_orgao = voting.get('siglaOrgao', 'Desconhecido')
        proposicao = voting.get('proposicaoObjeto') or voting.get('descricao') or 'N/A'
        data_registro = voting.get('dataHoraRegistro')
        descricao = voting.get('descricao', '')
        
        # 2. Verificar se já processamos em ALGUMA das tabelas
        cursor.execute("SELECT 1 FROM votos_parlamentares_totais WHERE id_votacao = ? LIMIT 1", (id_votacao,))
        is_in_nominal = cursor.fetchone()
        
        cursor.execute("SELECT 1 FROM votacoes_simbolicas_geral WHERE id_votacao = ? LIMIT 1", (id_votacao,))
        is_in_symbolic = cursor.fetchone()
        
        if is_in_nominal or is_in_symbolic:
            skips += 1
            if idx % 50 == 0:
                print(f"[{idx+1}/{total}] ⏩ Processado ({skips} pulados)...", end="\r")
            continue
            
        print(f"[{idx+1}/{total}] 🔍 {id_votacao} ({sigla_orgao}): {proposicao[:50]}...", end="\r")
        
        try:
            # Busca os votos individuais
            url = API_CAMARA_VOTOS.format(id=id_votacao)
            response = requests.get(url)
            
            if response.status_code != 200:
                print(f"\n   ⚠️  Erro API Câmara {id_votacao}: {response.status_code}")
                continue
                
            data_votos = response.json().get('dados', [])
            now = datetime.now().isoformat()
            
            if not data_votos:
                # === CASO SIMBÓLICA (Lista Vazia) ===
                cursor.execute("""
                INSERT OR IGNORE INTO votacoes_simbolicas_geral
                (id_votacao, data_registro, sigla_orgao, proposicao, descricao, motivo, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (id_votacao, data_registro, sigla_orgao, proposicao, descricao, "Lista vazia na API", now))
                symbolic_count += 1
                # print(f"\n   ⚪️ Simbólica: {id_votacao}")
            else:
                # === CASO NOMINAL (Com Votos) ===
                votos_insert = []
                for voto in data_votos:
                    deputado = voto.get('deputado_')
                    if not deputado: continue
                    
                    votos_insert.append((
                        id_votacao,
                        deputado.get('nome'),
                        deputado.get('siglaPartido'),
                        deputado.get('siglaUf'),
                        voto.get('tipoVoto'),
                        sigla_orgao,
                        now
                    ))
                
                if votos_insert:
                    cursor.executemany("""
                    INSERT OR IGNORE INTO votos_parlamentares_totais 
                    (id_votacao, nome_deputado, partido, uf, voto, comissao, data_registro)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, votos_insert)
                    conn.commit()
                    nominal_count += 1
                    print(f"\n   ✅ Nominal: {id_votacao} ({len(votos_insert)} votos)")
                else:
                     # Caso raro: Lista não vazia mas sem dados de deputado válidos? Trata como simbólica ou erro?
                     # Vamos logar erro e não salvar.
                     print(f"\n   ⚠️  Lista com dados inválidos: {id_votacao}")
            
            conn.commit()
            
            # Rate limit
            time.sleep(0.3)
            
        except Exception as e:
            print(f"\n   ❌ Erro ao processar {id_votacao}: {e}")
            time.sleep(1)
            
    print("\n" + "="*40)
    print("🏁 Coleta e Separação Concluídas!")
    print(f"   - Total API:        {total}")
    print(f"   - Pulados (Já tem): {skips}")
    print(f"   - Novos Nominais:   {nominal_count}")
    print(f"   - Novos Simbólicos: {symbolic_count}")
    print("="*40)
    conn.close()

if __name__ == "__main__":
    process_votes()
